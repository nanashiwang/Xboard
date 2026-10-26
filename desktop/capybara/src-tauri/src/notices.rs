use crate::account::{self, Fault};
use reqwest::{Client, Url};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use tauri_plugin_opener::OpenerExt;

#[derive(Clone, Deserialize, Serialize)]
pub struct Notice {
    id: u64,
    title: String,
    content: String,
    level: String,
    image_url: Option<String>,
    published_at: Option<String>,
    #[serde(default)]
    fingerprint: String,
}
#[derive(Deserialize, Serialize)]
pub struct Page {
    items: Vec<Notice>,
    page: u32,
    page_size: u32,
    total: u32,
}
fn decode(bytes: &[u8], requested: u32) -> Result<Page, Fault> {
    #[derive(Deserialize)]
    struct Envelope {
        data: Page,
    }
    let mut page: Page = serde_json::from_slice::<Envelope>(bytes)
        .map_err(|_| Fault::local("系统通知数据异常，请稍后刷新"))?
        .data;
    if page.page != requested || page.page_size != 20 || page.items.len() > 20 {
        return Err(Fault::local("系统通知分页异常，请稍后刷新"));
    }
    let mut ids = std::collections::HashSet::new();
    for item in &mut page.items {
        if item.id == 0
            || !ids.insert(item.id)
            || item.content.len() > 256 * 1024
            || item.title.len() > 16 * 1024
        {
            return Err(Fault::local("系统通知内容异常，请稍后刷新"));
        }
        // Edits should become unread again, even when the notice ID stays the same.
        let content = serde_json::to_vec(&(
            &item.title,
            &item.content,
            &item.level,
            &item.image_url,
            &item.published_at,
        ))
        .map_err(|_| Fault::local("无法读取系统通知"))?;
        item.fingerprint = format!("{:x}", Sha256::digest(content));
    }
    Ok(page)
}
async fn fetch(client: &Client, origin: &str, page: u32) -> Result<Page, Fault> {
    if !(1..=50_000).contains(&page) {
        return Err(Fault::local("通知页码无效"));
    }
    let mut response = client
        .get(format!("{origin}/api/v1/notices"))
        .query(&[("page", page), ("page_size", 20)])
        .header("Accept", "application/json")
        .send()
        .await
        .map_err(|_| Fault::local("暂时无法同步系统通知，请检查网络后刷新"))?;
    if !response.status().is_success() {
        return Err(Fault::local("系统通知服务暂不可用，请稍后刷新"));
    }
    let mut body = Vec::new();
    while let Some(chunk) = response
        .chunk()
        .await
        .map_err(|_| Fault::local("系统通知未接收完整，请刷新重试"))?
    {
        if body.len() + chunk.len() > 4 * 1024 * 1024 {
            return Err(Fault::local("系统通知响应过大"));
        }
        body.extend_from_slice(&chunk);
    }
    decode(&body, page)
}
#[tauri::command]
pub async fn fetch_notices(page: u32) -> Result<Page, Fault> {
    // Public notices do not need credentials or the account/node runtime locks.
    fetch(&account::http()?, account::ORIGIN, page).await
}
fn notice_url(value: &str) -> Result<Url, Fault> {
    let url = Url::parse(value).map_err(|_| Fault::local("通知链接无效"))?;
    if value.len() > 4096
        || value.chars().any(|c| c.is_control() || c.is_whitespace())
        || !matches!(url.scheme(), "https" | "http")
        || url.host_str().is_none()
        || !url.username().is_empty()
        || url.password().is_some()
    {
        return Err(Fault::local("此通知链接不支持打开"));
    }
    Ok(url)
}
#[tauri::command]
pub fn open_notice_link(app: tauri::AppHandle, url: String) -> Result<(), Fault> {
    let url = notice_url(&url)?;
    app.opener()
        .open_url(url.as_str(), None::<&str>)
        .map_err(|_| Fault::local("无法打开浏览器，请稍后重试"))
}
#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    fn response(content: &str) -> Vec<u8> {
        serde_json::to_vec(&json!({"data":{"page":1,"page_size":20,"total":1,"items":[{
            "id":1,"title":"公告","content":content,"level":"info","image_url":null,"published_at":null
        }]}})).unwrap()
    }
    #[test]
    fn content_edits_invalidate_read_marks_and_malformed_pages_are_rejected() {
        let original = decode(&response("旧内容"), 1).unwrap();
        assert_eq!(
            original.items[0].fingerprint,
            decode(&response("旧内容"), 1).unwrap().items[0].fingerprint
        );
        assert_ne!(
            original.items[0].fingerprint,
            decode(&response("新内容"), 1).unwrap().items[0].fingerprint
        );
        assert!(decode(&response("内容"), 2).is_err());
        assert!(decode(b"{\"data\":null}", 1).is_err());
        assert!(decode(&response(&"x".repeat(256 * 1024 + 1)), 1).is_err());
    }
    #[test]
    fn notice_links_cannot_execute_local_files_or_scripts() {
        for value in [
            "javascript:alert(1)",
            "data:text/html,a",
            "file:///tmp/a",
            "tauri://localhost",
            "https://u:p@example.com",
            "https://example.com/\n",
        ] {
            assert!(notice_url(value).is_err(), "{value}");
        }
        assert!(notice_url("https://taige.us/#/plan").is_ok());
    }
    #[tokio::test]
    async fn notices_use_the_public_endpoint_without_account_credentials() {
        use std::io::{Read, Write};
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let server = std::thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            stream
                .set_read_timeout(Some(std::time::Duration::from_secs(5)))
                .unwrap();
            let mut bytes = [0; 4096];
            let n = stream.read(&mut bytes).unwrap();
            let request = String::from_utf8_lossy(&bytes[..n]).to_lowercase();
            assert!(request.starts_with("get /api/v1/notices?page=1&page_size=20 "));
            assert!(!request.contains("authorization:"));
            assert!(!request.contains("cookie:"));
            let body = response("公告正文");
            write!(stream,"HTTP/1.1 200 OK\r\nContent-Length: {}\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n",body.len()).unwrap();
            stream.write_all(&body).unwrap();
        });
        let page = fetch(&account::http().unwrap(), &format!("http://{address}"), 1)
            .await
            .unwrap();
        assert_eq!(page.items[0].content, "公告正文");
        server.join().unwrap();
    }
}
