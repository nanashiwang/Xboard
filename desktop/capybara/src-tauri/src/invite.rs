use crate::{account::Fault, AppState};
use serde_json::{json, Value};
use tauri::State;

fn read_path(action: &str, page: Option<u32>) -> Result<String, Fault> {
    match action {
        "index" => Ok("client/invite".into()),
        "details" => match page.unwrap_or(1) {
            page @ 1..=100_000 => Ok(format!("client/invite/details?page={page}")),
            _ => Err(Fault::local("页码无效，请刷新后重试")),
        },
        _ => Err(Fault::local("不支持的邀请操作")),
    }
}

#[tauri::command]
pub async fn invite_request(
    state: State<'_, AppState>,
    action: String,
    page: Option<u32>,
) -> Result<Value, Fault> {
    let mut rt = state.0.lock().await;
    if !rt.view.logged_in {
        return Err(Fault::local("请先登录账号"));
    }
    if action == "generate" {
        rt.account.post("client/invite/generate", &json!({})).await
    } else {
        rt.account.get(&read_path(&action, page)?).await
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn invitation_requests_are_bounded_to_fixed_read_endpoints() {
        assert_eq!(read_path("index", None).unwrap(), "client/invite");
        assert_eq!(
            read_path("details", Some(2)).unwrap(),
            "client/invite/details?page=2"
        );
        assert!(read_path("details", Some(0)).is_err());
        assert!(read_path("details", Some(100_001)).is_err());
        assert!(read_path("../user", None).is_err());
        assert!(read_path("generate", None).is_err());
    }
}
