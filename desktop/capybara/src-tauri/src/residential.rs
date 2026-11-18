use crate::{account::Fault, engine::Engine, routing::RoutingSettings, AppState};
use serde_json::{json, Value};
use tauri::State;

pub fn configuration(data: &Value, protocol: &str) -> Result<String, Fault> {
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
    Ok(json!({"proxies":[{"name":"Residential","type":if protocol=="HTTP"{"http"}else{"socks5"},"server":address,"port":port,"username":data["credentials"]["username"],"password":data["credentials"]["password"],"udp":false}],"proxy-groups":[{"name":"Proxy","type":"select","proxies":["Residential"]}],"rules":["MATCH,Proxy"]}).to_string())
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
            let content = configuration(&data, protocol)?;
            let expires = data["expires_at"]
                .as_u64()
                .filter(|v| *v > crate::now())
                .ok_or_else(|| Fault::local("代理已到期"))?;
            rt.shutdown().await?;
            let mut engine = Engine::start(
                &rt.dir,
                rt.binary.clone(),
                &content,
                &RoutingSettings::default(),
            )
            .await?;
            if let Err(e) = crate::proxy::enable(&rt.dir, engine.port) {
                let _ = engine.stop();
                return Err(e.into());
            }
            if let Err(e) = engine.check().await {
                let _ = engine.stop();
                let _ = crate::proxy::recover(&rt.dir);
                return Err(e.into());
            }
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
            let cfg: Value =
                serde_json::from_str(&configuration(&data, protocol).unwrap()).unwrap();
            assert_eq!(
                cfg["proxies"][0]["type"],
                if protocol == "HTTP" { "http" } else { "socks5" }
            );
            assert_eq!(cfg["proxies"][0]["udp"], false);
        }
        data["address"] = json!("127.0.0.1");
        assert!(configuration(&data, "HTTP").is_err());
        data["address"] = json!("216.36.108.173");
        data["status"] = json!("expired");
        assert!(configuration(&data, "SOCKS5").is_err());
    }
}
