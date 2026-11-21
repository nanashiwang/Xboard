use crate::{account::Fault, engine::Engine, routing::RoutingSettings, AppState};
use serde_json::{json, Value};
use tauri::State;

fn endpoint(data: &Value, protocol: &str) -> Result<(String, Value), Fault> {
    if !matches!(protocol, "SOCKS5" | "HTTP") || data["status"] != "active" {
        return Err(Fault::local("代理尚未就绪或已到期"));
    }
    let address = data["address"].as_str().unwrap_or("");
    let port = data["port"].as_u64().unwrap_or(0);
    let host = match address {
        "216.36.108.173" => "a",
        "192.204.56.29" => "b",
        _ => return Err(Fault::local("代理地址不在受支持的固定端点中")),
    };
    if !(20001..=20010).contains(&port) {
        return Err(Fault::local("代理端口不在受支持的固定端点中"));
    }
    for key in ["username", "password"] {
        let value = data["credentials"][key].as_str().unwrap_or("");
        if value.len() < 8
            || value.len() > 128
            || !value
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
        {
            return Err(Fault::local("代理认证信息无效"));
        }
    }
    Ok((
        format!("wss://node.lumavia.fyi/residential/v1/{host}/{port}"),
        json!({
            "name": "Residential", "type": if protocol == "HTTP" { "http" } else { "socks5" },
            "server": "127.0.0.1", "username": data["credentials"]["username"],
            "password": data["credentials"]["password"], "udp": false
        }),
    ))
}

fn configuration(mut exit: Value, bridge_port: u16) -> String {
    exit["port"] = json!(bridge_port);
    json!({"proxies":[exit], "proxy-groups":[{"name":"Proxy","type":"select","proxies":["Residential"]}],
           "rules":["MATCH,Proxy"]}).to_string()
}

pub async fn check_exit(control: &crate::engine::Controller, expected: &str) -> Result<(), String> {
    let client = control.probe_client()?;
    // Both requests use the candidate listener, including TLS verification.
    for url in [
        "https://api.ipify.org",
        "https://www.cloudflare.com/cdn-cgi/trace",
    ] {
        let Ok(response) = client
            .get(url)
            .timeout(std::time::Duration::from_secs(12))
            .send()
            .await
        else {
            continue;
        };
        if response.status() != reqwest::StatusCode::OK {
            continue;
        }
        if let Ok(body) = response.text().await {
            let value = if url.ends_with("/trace") {
                body.lines().find_map(|line| line.strip_prefix("ip="))
            } else {
                Some(body.trim())
            };
            if let Some(address) = value.and_then(|s| s.parse::<std::net::IpAddr>().ok()) {
                if address.to_string() == expected {
                    return control.check().await;
                }
                return Err("检测到的公网出口与已购家宽 IP 不一致".into());
            }
        }
    }
    Err("家宽出口检测超时或不可用".into())
}

#[tauri::command]
pub async fn residential_request(
    state: State<'_, AppState>,
    action: String,
    payload: Option<Value>,
) -> Result<Value, Fault> {
    let payload = payload.unwrap_or(Value::Null);
    let mut rt = state.0.lock().await;
    if !rt.account.logged_in() {
        return Err(Fault::local("请先登录账号"));
    }
    let id = payload["id"].as_u64().filter(|id| *id > 0);
    match action.as_str() {
        "index" => rt.account.get("client/proxies").await,
        "detail" => {
            rt.account
                .get(&format!(
                    "client/proxies/detail?id={}",
                    id.ok_or_else(|| Fault::local("代理编号无效"))?
                ))
                .await
        }
        "save" | "update" => {
            rt.account
                .post(&format!("client/proxies/{action}"), &payload)
                .await
        }
        "disconnect" => {
            rt.shutdown().await?;
            Ok(Value::Null)
        }
        "connect" => {
            if rt.installing.load(std::sync::atomic::Ordering::SeqCst) {
                return Err(Fault::local("正在更新，请稍候"));
            }
            let id = id.ok_or_else(|| Fault::local("代理编号无效"))?;
            let protocol = payload["protocol"].as_str().unwrap_or("");
            let data = rt
                .account
                .get(&format!("client/proxies/detail?id={id}"))
                .await?;
            let (url, exit) = endpoint(&data, protocol)?;
            let address = data["address"].as_str().unwrap().to_owned();
            let expires = data["expires_at"]
                .as_u64()
                .filter(|v| *v > crate::now())
                .ok_or_else(|| Fault::local("代理已到期"))?;
            rt.shutdown().await?;
            let bridge = crate::residential_bridge::Bridge::start(url).await?;
            let config = configuration(exit, bridge.port);
            let mut engine = Engine::start(
                &rt.dir,
                rt.binary.clone(),
                &config,
                &RoutingSettings::default(),
            )
            .await?;
            let activation = async {
                check_exit(&engine, &address).await.map_err(|error| {
                    Fault::local(&format!("第一阶段到家宽出口未通过检测：{error}"))
                })?;
                if expires <= crate::now() {
                    return Err(Fault::local("代理已到期"));
                }
                crate::proxy::enable(&rt.dir, engine.port)?;
                Ok(())
            }
            .await;
            if let Err(error) = activation {
                engine.stop()?;
                rt.view.connection_error = Some(error.message.clone());
                return Err(error);
            }
            rt.proxy_bridge = Some(bridge);
            rt.view.proxy_relay = Some("第一阶段".into());
            rt.view.proxy_address = Some(address);
            rt.proxy_engine = Some(engine);
            rt.proxy_expires = expires;
            rt.proxy_revision = data["revision"].as_u64().unwrap_or(0);
            rt.view.proxy_id = Some(id);
            rt.view.connection = "connected".into();
            rt.view.connection_error = None;
            Ok(Value::Null)
        }
        _ => Err(Fault::local("不支持的代理操作")),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn config_uses_authenticated_fixed_endpoint_and_selected_protocol() {
        let mut data = json!({"status":"active","address":"216.36.108.173","port":20001,"credentials":{"username":"cp_12345678","password":"0123456789abcdef"}});
        for protocol in ["HTTP", "SOCKS5"] {
            let (url, cfg) = endpoint(&data, protocol).unwrap();
            assert_eq!(url, "wss://node.lumavia.fyi/residential/v1/a/20001");
            assert_eq!(cfg["server"], "127.0.0.1");
            assert_eq!(
                cfg["type"],
                if protocol == "HTTP" { "http" } else { "socks5" }
            );
            assert_eq!(cfg["udp"], false);
        }
        data["address"] = json!("127.0.0.1");
        assert!(endpoint(&data, "HTTP").is_err());
        data["address"] = json!("216.36.108.173");
        data["status"] = json!("expired");
        assert!(endpoint(&data, "SOCKS5").is_err());
    }
    #[test]
    fn only_inventory_ports_have_fixed_ingress_routes() {
        for (address, host) in [("216.36.108.173", "a"), ("192.204.56.29", "b")] {
            for port in 20000..=20011 {
                let data = json!({"status":"active","address":address,"port":port,
                    "credentials":{"username":"cp_12345678","password":"0123456789abcdef"}});
                let result = endpoint(&data, "HTTP");
                if (20001..=20010).contains(&port) {
                    assert_eq!(
                        result.unwrap().0,
                        format!("wss://node.lumavia.fyi/residential/v1/{host}/{port}")
                    );
                } else {
                    assert!(result.is_err());
                }
            }
        }
    }

    #[tokio::test]
    async fn bundled_core_dials_the_authenticated_exit_through_the_relay_for_both_protocols() {
        use tokio::io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader};
        use tokio::net::TcpListener;
        async fn headers(stream: &mut BufReader<tokio::net::TcpStream>) -> String {
            let mut headers = String::new();
            while !headers.ends_with("\r\n\r\n") {
                assert!(stream.read_line(&mut headers).await.unwrap() > 0);
            }
            headers
        }

        for protocol in ["http", "socks5"] {
            let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
            let stage1 = TcpListener::bind("127.0.0.1:0").await.unwrap();
            let bridge = crate::residential_bridge::Bridge::start(format!(
                "ws://{}/residential/v1/a/20001",
                stage1.local_addr().unwrap()
            ))
            .await
            .unwrap();
            let exit_addr = listener.local_addr().unwrap();
            let ingress = tokio::spawn(async move {
                // The first TLS/WebSocket handshake was reset before sending proxy bytes.
                drop(stage1.accept().await.unwrap().0);
                let tcp = stage1.accept().await.unwrap().0;
                let ws = tokio_tungstenite::accept_async(tcp).await.unwrap();
                let paid = tokio::net::TcpStream::connect(exit_addr).await.unwrap();
                crate::residential_bridge::forward(paid, ws).await;
            });
            let exit = json!({"name":"Residential","type":protocol,"server":"127.0.0.1","username":"user","password":"pass"});
            let (_core, controller) =
                crate::engine::integration::start_test_core(&configuration(exit, bridge.port))
                    .await;
            let hops = tokio::spawn(async move {
                let mut stream = BufReader::new(listener.accept().await.unwrap().0);
                if protocol == "http" {
                    let request = headers(&mut stream).await;
                    assert!(request.starts_with("CONNECT 203.0.113.20:80 "));
                    assert!(request
                        .to_ascii_lowercase()
                        .contains("proxy-authorization: basic dxnlcjpwyxnz"));
                    stream.write_all(b"HTTP/1.1 200 OK\r\n\r\n").await.unwrap();
                } else {
                    assert_eq!(stream.read_u8().await.unwrap(), 5);
                    let mut methods = vec![0; stream.read_u8().await.unwrap() as usize];
                    stream.read_exact(&mut methods).await.unwrap();
                    assert!(methods.contains(&2));
                    stream.write_all(&[5, 2]).await.unwrap();
                    let mut auth = [0; 11];
                    stream.read_exact(&mut auth).await.unwrap();
                    assert_eq!(&auth, b"\x01\x04user\x04pass");
                    stream.write_all(&[1, 0]).await.unwrap();
                    let mut dest = [0; 10];
                    stream.read_exact(&mut dest).await.unwrap();
                    assert_eq!(dest, [5, 1, 0, 1, 203, 0, 113, 20, 0, 80]);
                    stream
                        .write_all(&[5, 0, 0, 1, 127, 0, 0, 1, 0, 0])
                        .await
                        .unwrap();
                }
                assert!(headers(&mut stream).await.starts_with("GET /probe "));
                stream
                    .write_all(b"HTTP/1.1 204 No Content\r\nConnection: close\r\n\r\n")
                    .await
                    .unwrap();
            });
            let outcome = controller
                .probe_client()
                .unwrap()
                .get("http://203.0.113.20/probe")
                .send()
                .await;
            tokio::time::timeout(std::time::Duration::from_secs(3), hops)
                .await
                .unwrap()
                .unwrap();
            assert_eq!(outcome.unwrap().status(), 204);
            drop(bridge);
            ingress.await.unwrap();
        }
    }
}
