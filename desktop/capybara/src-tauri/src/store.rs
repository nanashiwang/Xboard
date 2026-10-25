use crate::{account::Fault, AppState};
use serde_json::Value;
use tauri::{AppHandle, State};
use tauri_plugin_opener::OpenerExt;

fn order_path(payload: &Value) -> Result<String, Fault> {
    let trade = payload["trade_no"].as_str().unwrap_or("");
    if trade.is_empty()
        || trade.len() > 64
        || !trade
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_')
    {
        return Err(Fault::local("订单编号无效"));
    }
    Ok(format!("client/store/order?trade_no={trade}"))
}

fn payment_url(value: &str) -> Result<reqwest::Url, Fault> {
    let url = reqwest::Url::parse(value).map_err(|_| Fault::local("支付链接无效"))?;
    if value.len() > 4096
        || value.chars().any(|c| c.is_control() || c.is_whitespace())
        || !matches!(url.scheme(), "https" | "http")
        || url.host_str().is_none()
        || !url.username().is_empty()
        || url.password().is_some()
    {
        return Err(Fault::local("此支付链接无法打开，请在网站订单中心继续"));
    }
    Ok(url)
}

#[tauri::command]
pub async fn store_request(
    app: AppHandle,
    state: State<'_, AppState>,
    action: String,
    payload: Option<Value>,
) -> Result<Value, Fault> {
    let payload = payload.unwrap_or(Value::Null);
    let mut rt = state.0.lock().await;
    if action == "catalog" {
        return rt.account.public_get("client/plans").await;
    }
    if !rt.view.logged_in {
        return Err(Fault::local("请先登录账号"));
    }
    let mut result = match action.as_str() {
        "index" => rt.account.get("client/store").await?,
        "order" => rt.account.get(&order_path(&payload)?).await?,
        "save" | "checkout" | "cancel" => {
            rt.account
                .post(&format!("client/store/{action}"), &payload)
                .await?
        }
        _ => return Err(Fault::local("不支持的套餐操作")),
    };
    drop(rt);
    if action == "checkout" && result["kind"] == "url" {
        let url = payment_url(result["data"].as_str().unwrap_or(""))?;
        // Only a payment response from the fixed API origin may launch a payment URL.
        app.opener()
            .open_url(url.as_str(), None::<&str>)
            .map_err(|_| Fault::local("无法打开支付页面，请在网站订单中心继续"))?;
        result["data"] = Value::Null;
    }
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    #[test]
    fn payment_links_and_order_paths_cannot_execute_scripts_or_escape_endpoint() {
        for url in [
            "javascript:alert(1)",
            "file:///tmp/a",
            "https://user:pass@example.org",
            "https://example.org/\nfoo",
            "https://example.org/ foo",
        ] {
            assert!(payment_url(url).is_err(), "{url}");
        }
        assert!(payment_url("https://checkout.example.org/pay?id=1").is_ok());
        assert!(order_path(&json!({"trade_no":"12345"})).is_ok());
        for trade in ["", "1&user_id=2", "../auth", "a?x=1"] {
            assert!(order_path(&json!({"trade_no":trade})).is_err());
        }
    }
}
