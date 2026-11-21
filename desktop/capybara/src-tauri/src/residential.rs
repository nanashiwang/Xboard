use crate::{account::Fault, engine::Engine, routing::RoutingSettings, AppState};
use serde_json::{json, Value};
use tauri::State;

fn endpoint(data: &Value, protocol: &str) -> Result<Value, Fault> {
    if !matches!(protocol, "SOCKS5" | "HTTP") || data["status"] != "active" {
        return Err(Fault::local("代理尚未就绪或已到期"));
    }
    let address = data["address"].as_str().unwrap_or("");
    let port = data["port"].as_u64().unwrap_or(0);
    if !matches!(address, "216.36.108.173" | "192.204.56.29") || !(20001..=20010).contains(&port) {
        return Err(Fault::local("代理地址不在受支持的固定端点中"));
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
    Ok(json!({
        "name": "Residential", "type": if protocol == "HTTP" { "http" } else { "socks5" },
        "server": address, "port": port, "username": data["credentials"]["username"],
        "password": data["credentials"]["password"], "udp": false
    }))
}

struct Configuration {
    content: String,
    relays: Vec<String>,
}

// Each choice is a complete path ending at the purchased endpoint. Subscription
// rules, user overrides and DIRECT must never become public egress choices here.
fn configuration(
    exit: Value,
    source: Option<&str>,
    preferred: Option<&str>,
) -> Result<Configuration, Fault> {
    let mut proxies = Vec::new();
    let mut choices = Vec::new();
    let mut relays = Vec::new();
    if let Some(source) = source {
        let subscription: Value =
            serde_yaml::from_str(source).map_err(|_| Fault::local("订阅配置格式无效"))?;
        let mut nodes: Vec<_> = subscription["proxies"]
            .as_array()
            .into_iter()
            .flatten()
            .filter(|p| {
                p["name"].as_str().is_some_and(|n| !n.is_empty())
                    && p["server"].is_string()
                    && p.get("dialer-proxy").is_none()
                    && matches!(
                        p["type"].as_str(),
                        Some(
                            "ss" | "vmess"
                                | "vless"
                                | "trojan"
                                | "hysteria"
                                | "hysteria2"
                                | "tuic"
                                | "anytls"
                                | "mieru"
                                | "socks5"
                                | "http"
                        )
                    )
            })
            .collect();
        nodes.sort_by_key(|p| p["name"].as_str() != preferred);
        for (i, node) in nodes.into_iter().take(3).enumerate() {
            let mut relay = node.clone();
            relays.push(relay["name"].as_str().unwrap().to_owned());
            relay["name"] = json!(format!("Relay-{i}"));
            let mut path = exit.clone();
            path["dialer-proxy"] = relay["name"].clone();
            path["name"] = json!(format!("Residential-{i}"));
            choices.push(path["name"].clone());
            proxies.push(path);
            proxies.push(relay);
        }
        if choices.is_empty() {
            return Err(Fault::local(
                "订阅里没有可用的中转线路，请更新普通线路后重试",
            ));
        }
    } else {
        choices.push(exit["name"].clone());
        proxies.push(exit);
    }
    Ok(Configuration {
        content: json!({
            "proxies": proxies, "proxy-groups": [{"name":"Proxy", "type":"select", "proxies":choices}],
            "rules":["MATCH,Proxy"]
        }).to_string(),
        relays,
    })
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
            .timeout(std::time::Duration::from_secs(6))
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

impl Configuration {
    async fn verify(&self, engine: &Engine, address: &str) -> Result<Option<String>, Fault> {
        if self.relays.is_empty() {
            check_exit(engine, address).await.map_err(|e| {
                Fault::local(&format!("{e}。当前套餐没有中转线路，直连家宽入口失败"))
            })?;
            return Ok(None);
        }
        let mut last_error = String::new();
        for (i, relay) in self.relays.iter().enumerate() {
            if i > 0 {
                engine.select("Proxy", &format!("Residential-{i}")).await?;
            }
            match check_exit(engine, address).await {
                Ok(()) => return Ok(Some(relay.clone())),
                Err(error) => last_error = error,
            }
        }
        Err(Fault::local(&format!(
            "{last_error}。已尝试 {} 条普通线路，请在首页选择其他线路后重试",
            self.relays.len()
        )))
    }
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
            let exit = endpoint(&data, protocol)?;
            let address = exit["server"].as_str().unwrap().to_owned();
            let expires = data["expires_at"]
                .as_u64()
                .filter(|v| *v > crate::now())
                .ok_or_else(|| Fault::local("代理已到期"))?;
            let source = match rt.account.config().await {
                Ok(content) => Some(content),
                Err(error) if error.code == "SUBSCRIPTION_UNAVAILABLE" => None,
                Err(error) => return Err(error),
            };
            let preferred = if let Some(name) = &rt.view.proxy_relay {
                Some(name.clone())
            } else {
                rt.nodes.lock().await.preferred_relay().await
            };
            let config = configuration(exit, source.as_deref(), preferred.as_deref())?;
            rt.shutdown().await?;
            let mut engine = Engine::start(
                &rt.dir,
                rt.binary.clone(),
                &config.content,
                &RoutingSettings::default(),
            )
            .await?;
            let activation = async {
                let relay = config.verify(&engine, &address).await?;
                if expires <= crate::now() {
                    return Err(Fault::local("代理已到期"));
                }
                crate::proxy::enable(&rt.dir, engine.port)?;
                Ok(relay)
            }
            .await;
            rt.view.proxy_relay = match activation {
                Ok(relay) => relay,
                Err(error) => {
                    engine.stop()?;
                    rt.view.connection_error = Some(error.message.clone());
                    return Err(error);
                }
            };
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
            let cfg: Value = endpoint(&data, protocol).unwrap();
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
    fn relay_choices_all_end_at_the_same_asset_and_prefer_the_selected_node() {
        let exit = json!({"name":"Residential","type":"http","server":"192.0.2.1","port":20001});
        let source = json!({"proxies": [
            {"name":"bypass", "type":"direct","server":"invalid"},
            {"name":"one","type":"ss","server":"one.test"},
            {"name":"two","type":"vmess","server":"two.test"},
            {"name":"three","type":"trojan","server":"three.test"},
            {"name":"Proxy","type":"http","server":"four.test"}
        ], "rules":["MATCH,DIRECT"]});
        let cfg = configuration(exit.clone(), Some(&source.to_string()), Some("Proxy")).unwrap();
        assert_eq!(cfg.relays, ["Proxy", "one", "two"]);
        let config: Value = serde_json::from_str(&cfg.content).unwrap();
        assert_eq!(config["rules"], json!(["MATCH,Proxy"]));
        let choices = config["proxy-groups"][0]["proxies"].as_array().unwrap();
        assert_eq!(choices.len(), 3);
        for (i, choice) in choices.iter().enumerate() {
            let path = &config["proxies"][2 * i];
            assert_eq!(choice, &path["name"]);
            assert_eq!(path["server"], exit["server"]);
            assert_eq!(path["port"], exit["port"]);
            assert_eq!(path["dialer-proxy"], config["proxies"][2 * i + 1]["name"]);
        }
        assert!(configuration(exit.clone(), Some("proxies: []"), None).is_err());
        let direct = configuration(exit, None, None).unwrap();
        assert!(direct.relays.is_empty());
        assert!(!direct.content.contains("dialer-proxy"));
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
            let source = json!({"proxies":[{"name":"first","type":"http","server":"127.0.0.1","port":listener.local_addr().unwrap().port()}]});
            let exit = json!({"name":"Residential","type":protocol,"server":"192.0.2.10","port":20001,"username":"user","password":"pass"});
            let cfg = configuration(exit, Some(&source.to_string()), None).unwrap();
            let (_core, controller) =
                crate::engine::integration::start_test_core(&cfg.content).await;
            let hops = tokio::spawn(async move {
                let mut stream = BufReader::new(listener.accept().await.unwrap().0);
                assert!(headers(&mut stream)
                    .await
                    .starts_with("CONNECT 192.0.2.10:20001 "));
                stream.write_all(b"HTTP/1.1 200 OK\r\n\r\n").await.unwrap();
                // The fixture now acts as the residential server inside the first tunnel.
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
        }
    }
}
