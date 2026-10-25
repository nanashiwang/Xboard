use crate::credentials::{access, Access};
use reqwest::{Client, Method, StatusCode};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{
    path::Path,
    time::{Duration, Instant},
};
use uuid::Uuid;

pub const ORIGIN: &str = "https://taige.us";
pub const VERSION: &str = env!("CARGO_PKG_VERSION");
pub const CORE_VERSION: &str = "1.19.33";
pub fn platform() -> &'static str {
    if cfg!(target_os = "windows") {
        "windows"
    } else if cfg!(target_os = "macos") {
        "macos"
    } else {
        "linux"
    }
}
pub fn architecture() -> &'static str {
    if cfg!(target_arch = "aarch64") {
        "arm64"
    } else {
        "x64"
    }
}
pub fn http() -> Result<Client, String> {
    Client::builder()
        .no_proxy()
        .redirect(reqwest::redirect::Policy::none())
        .connect_timeout(Duration::from_secs(8))
        .timeout(Duration::from_secs(20))
        .user_agent(format!("Capybara/{VERSION}"))
        .build()
        .map_err(|_| "无法初始化网络组件".into())
}

#[derive(Debug, Clone, Serialize)]
pub struct Fault {
    pub code: String,
    pub message: String,
}
impl Fault {
    pub fn local(message: &str) -> Self {
        Self {
            code: "LOCAL_ERROR".into(),
            message: message.into(),
        }
    }
}
impl From<String> for Fault {
    fn from(message: String) -> Self {
        Self::local(&message)
    }
}
impl From<&str> for Fault {
    fn from(message: &str) -> Self {
        Self::local(message)
    }
}
#[derive(Serialize, Deserialize)]
struct Saved {
    refresh_token: String,
    device_id: String,
}
#[derive(Deserialize)]
struct Tokens {
    access_token: String,
    refresh_token: String,
    expires_in: u64,
}

pub struct Account {
    client: Client,
    origin: String,
    credential: Option<keyring::Entry>,
    device_id: String,
    access: String,
    refresh: String,
    expires: Instant,
}
impl Account {
    pub fn new(dir: &Path) -> Result<Self, String> {
        let file = dir.join("device-id");
        let device_id = std::fs::read_to_string(&file)
            .ok()
            .filter(|s| Uuid::parse_str(s).is_ok())
            .unwrap_or_else(|| Uuid::new_v4().to_string());
        crate::private_write(&file, device_id.as_bytes())?;
        Ok(Self {
            client: http()?,
            origin: ORIGIN.into(),
            credential: keyring::Entry::new(
                "us.taige.capybara",
                &crate::credentials::account_name()?,
            )
            .ok(),
            device_id,
            access: String::new(),
            refresh: String::new(),
            expires: Instant::now(),
        })
    }
    fn entry(&self) -> Result<&keyring::Entry, Fault> {
        self.credential
            .as_ref()
            .ok_or_else(|| Fault::local("系统凭据库不可用，请解锁钥匙串或密钥环后重试"))
    }
    pub fn logged_in(&self) -> bool {
        !self.refresh.is_empty()
    }
    pub fn resume(&mut self, mode: Access) -> Result<bool, Fault> {
        if self.logged_in() {
            return Ok(true);
        }
        match access(mode, || self.entry_raw()?.get_password()) {
            Ok(raw) => {
                let saved: Saved = serde_json::from_str(&raw)
                    .map_err(|_| Fault::local("登录记录损坏，请重新登录"))?;
                if saved.device_id != self.device_id {
                    return Err(Fault::local("设备登录记录不匹配，请重新登录"));
                }
                self.refresh = saved.refresh_token;
                Ok(true)
            }
            Err(keyring::Error::NoEntry) => Ok(false),
            Err(_) => Err(Fault {
                code: "CREDENTIALS_LOCKED".into(),
                message: "登录记录暂时无法读取。点击“恢复登录”允许访问系统凭据库，或使用账号密码重新登录。".into(),
            }),
        }
    }
    fn entry_raw(&self) -> keyring::Result<&keyring::Entry> {
        self.credential
            .as_ref()
            .ok_or_else(|| keyring::Error::Invalid("credential".into(), "unavailable".into()))
    }
    fn request(&self, method: Method, path: &str) -> reqwest::RequestBuilder {
        self.client
            .request(method, format!("{}/api/v1/{path}", self.origin))
            .header("Accept", "application/json")
            .header("X-Device-ID", &self.device_id)
            .header("X-Client-Version", VERSION)
            .header("X-Core-Version", CORE_VERSION)
            .header("X-Platform", platform())
            .header("X-Architecture", architecture())
            .header("X-Request-ID", Uuid::new_v4().to_string())
    }
    async fn decode(response: reqwest::Response) -> Result<Value, Fault> {
        let status = response.status();
        if response.content_length().unwrap_or(0) > 4 * 1024 * 1024 {
            return Err(Fault::local("服务器响应过大"));
        }
        let body: Value = response
            .json()
            .await
            .map_err(|_| Fault::local("服务器响应异常，请稍后重试"))?;
        if !status.is_success() {
            return Err(Self::fault(status, &body));
        }
        body.get("data")
            .cloned()
            .ok_or_else(|| Fault::local("服务器响应缺少数据"))
    }
    fn fault(status: StatusCode, body: &Value) -> Fault {
        let code = body["code"].as_str().unwrap_or("SERVER_ERROR");
        let message = match code {
            "AUTH_INVALID_CREDENTIALS" => "邮箱或密码不正确",
            "ACCOUNT_BANNED" => "账号已停用，请联系客服",
            "AUTH_REFRESH_REUSED"
            | "AUTH_REFRESH_EXPIRED"
            | "AUTH_DEVICE_MISMATCH"
            | "AUTH_UNAUTHENTICATED" => "登录已失效，请重新登录",
            "DEVICE_LIMIT_REACHED" => "已达到设备数量上限，请在账户中心解绑旧设备",
            "SUBSCRIPTION_UNAVAILABLE" => "套餐当前不可用，请检查流量和到期时间",
            "RATE_LIMITED" => "操作过于频繁，请稍后重试",
            _ if status == StatusCode::UNAUTHORIZED => "登录已失效，请重新登录",
            _ => "服务暂时不可用，请稍后重试",
        };
        Fault {
            code: code.into(),
            message: message.into(),
        }
    }
    async fn save_tokens(&mut self, value: Value, mode: Access) -> Result<(), Fault> {
        let tokens: Tokens =
            serde_json::from_value(value).map_err(|_| Fault::local("登录响应不完整"))?;
        let saved = serde_json::to_string(&Saved {
            refresh_token: tokens.refresh_token.clone(),
            device_id: self.device_id.clone(),
        })
        .map_err(|_| Fault::local("无法保存登录"))?;
        if access(mode, || self.entry_raw()?.set_password(&saved)).is_err() {
            let _ = self
                .request(Method::POST, "auth/logout")
                .json(&json!({"refresh_token":tokens.refresh_token}))
                .send()
                .await;
            self.access.clear();
            self.refresh.clear();
            let _ = access(Access::Background, || self.entry_raw()?.delete_credential());
            return Err(Fault::local("无法安全保存登录，请解锁系统凭据库后重新登录"));
        }
        self.access = tokens.access_token;
        self.refresh = tokens.refresh_token;
        self.expires = Instant::now() + Duration::from_secs(tokens.expires_in.saturating_sub(30));
        Ok(())
    }
    pub async fn login(&mut self, email: String, password: String) -> Result<(), Fault> {
        self.entry()?;
        if self.logged_in() {
            return Err(Fault::local("请先退出当前账号"));
        }
        let response=self.request(Method::POST,"auth/login").json(&json!({"email":email.trim(),"password":password,"device":{"device_id":self.device_id,"name":format!("卡皮巴拉 · {}",platform()),"platform":platform(),"architecture":architecture(),"app_version":VERSION}})).send().await.map_err(|_|Fault::local("暂时无法连接账户服务，请检查网络后重试"))?;
        self.save_tokens(Self::decode(response).await?, Access::UserInitiated)
            .await
    }
    async fn renew(&mut self) -> Result<(), Fault> {
        if self.refresh.is_empty() {
            return Err(Fault {
                code: "AUTH_REQUIRED".into(),
                message: "请先登录账号".into(),
            });
        }
        let response = self
            .request(Method::POST, "auth/refresh")
            .json(&json!({"refresh_token":self.refresh,"device_id":self.device_id}))
            .send()
            .await
            .map_err(|_| Fault::local("无法同步账号，请检查网络后重试"))?;
        let status = response.status();
        let result = Self::decode(response).await;
        if status == StatusCode::UNAUTHORIZED || status == StatusCode::FORBIDDEN {
            self.clear(Access::Background)?;
        }
        self.save_tokens(result?, Access::Background).await
    }
    async fn authorized(&mut self, path: &str) -> Result<reqwest::Response, Fault> {
        if self.access.is_empty() || Instant::now() >= self.expires {
            self.renew().await?;
        }
        let mut response = self
            .request(Method::GET, path)
            .bearer_auth(&self.access)
            .send()
            .await
            .map_err(|_| Fault::local("账号同步失败，当前数据可能已过期"))?;
        if response.status() == StatusCode::UNAUTHORIZED {
            self.renew().await?;
            response = self
                .request(Method::GET, path)
                .bearer_auth(&self.access)
                .send()
                .await
                .map_err(|_| Fault::local("账号同步失败，请稍后重试"))?;
        }
        Ok(response)
    }
    pub async fn get(&mut self, path: &str) -> Result<Value, Fault> {
        Self::decode(self.authorized(path).await?).await
    }
    pub async fn config(&mut self) -> Result<String, Fault> {
        let response = self
            .authorized("client/config?format=mihomo&delivery=inline")
            .await?;
        if !response.status().is_success() {
            let _ = Self::decode(response).await?;
            return Err(Fault::local("配置下载失败"));
        }
        let etag = response
            .headers()
            .get("etag")
            .and_then(|h| h.to_str().ok())
            .unwrap_or("")
            .trim_matches('"')
            .to_owned();
        if response.content_length().unwrap_or(0) > 4 * 1024 * 1024 {
            return Err(Fault::local("配置过大"));
        }
        let content = response
            .text()
            .await
            .map_err(|_| Fault::local("配置下载中断"))?;
        use sha2::{Digest, Sha256};
        if content.len() > 4 * 1024 * 1024
            || etag != format!("{:x}", Sha256::digest(content.as_bytes()))
        {
            return Err(Fault::local("配置完整性校验失败，请重试"));
        }
        Ok(content)
    }
    fn clear(&mut self, mode: Access) -> Result<(), Fault> {
        self.access.clear();
        self.refresh.clear();
        match access(mode, || self.entry_raw()?.delete_credential()) {
            Ok(()) | Err(keyring::Error::NoEntry) => Ok(()),
            Err(_) => Err(Fault::local("无法清除系统登录记录，请解锁凭据库后重试")),
        }
    }
    pub async fn logout(&mut self) -> Result<(), Fault> {
        if !self.refresh.is_empty() {
            self.request(Method::POST, "auth/logout")
                .bearer_auth(&self.access)
                .json(&json!({"refresh_token":self.refresh}))
                .send()
                .await
                .map_err(|_| Fault::local("无法注销服务器登录，请联网后重试"))?
                .error_for_status()
                .map_err(|_| Fault::local("服务器注销失败，请稍后重试"))?;
        }
        self.clear(Access::UserInitiated)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{Read, Write};
    fn server(responses: Vec<(u16, Value)>) -> (String, std::thread::JoinHandle<Vec<String>>) {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let origin = format!("http://{}", listener.local_addr().unwrap());
        let handle = std::thread::spawn(move || {
            let mut paths = vec![];
            for (status, body) in responses {
                let (mut conn, _) = listener.accept().unwrap();
                conn.set_read_timeout(Some(Duration::from_secs(5))).unwrap();
                let mut request = vec![];
                let mut buf = [0; 4096];
                loop {
                    let n = conn.read(&mut buf).unwrap();
                    if n == 0 {
                        break;
                    }
                    request.extend_from_slice(&buf[..n]);
                    if let Some(end) = request.windows(4).position(|w| w == b"\r\n\r\n") {
                        let headers = String::from_utf8_lossy(&request[..end]).to_lowercase();
                        let length = headers
                            .lines()
                            .find_map(|s| {
                                s.strip_prefix("content-length:")
                                    .and_then(|s| s.trim().parse::<usize>().ok())
                            })
                            .unwrap_or(0);
                        if request.len() >= end + 4 + length {
                            break;
                        }
                    }
                }
                paths.push(
                    String::from_utf8_lossy(&request)
                        .lines()
                        .next()
                        .unwrap()
                        .to_owned(),
                );
                let body = body.to_string();
                write!(conn,"HTTP/1.1 {status} Test\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",body.len()).unwrap();
            }
            paths
        });
        (origin, handle)
    }
    #[tokio::test]
    async fn rotation_expiry_and_credential_failure_never_reuse_old_token() {
        let dir = std::env::temp_dir().join(format!("capybara-auth-test-{}", Uuid::new_v4()));
        std::fs::create_dir_all(&dir).unwrap();
        let mut a = Account::new(&dir).unwrap();
        a.credential = Some(keyring::Entry::new_with_credential(Box::new(
            keyring::mock::MockCredential::default(),
        )));
        a.save_tokens(
            json!({"access_token":"old-access","refresh_token":"old-refresh","expires_in":0}),
            Access::UserInitiated,
        )
        .await
        .unwrap();
        let (origin, server) = server(vec![
            (
                200,
                json!({"data":{"access_token":"new-access","refresh_token":"new-refresh","expires_in":7200}}),
            ),
            (200, json!({"data":{"status":"active"}})),
        ]);
        a.origin = origin;
        assert_eq!(
            a.get("user/subscription").await.unwrap()["status"],
            "active"
        );
        assert_eq!(a.refresh, "new-refresh");
        let saved: Saved =
            serde_json::from_str(&a.entry().unwrap().get_password().unwrap()).unwrap();
        assert_eq!(saved.refresh_token, "new-refresh");
        assert_eq!(
            server.join().unwrap(),
            vec![
                "POST /api/v1/auth/refresh HTTP/1.1",
                "GET /api/v1/user/subscription HTTP/1.1"
            ]
        );
        let (origin, server) = self::server(vec![(401, json!({"code":"AUTH_REFRESH_EXPIRED"}))]);
        a.origin = origin;
        a.expires = Instant::now();
        assert!(a.get("user/subscription").await.is_err());
        assert!(!a.logged_in());
        assert!(a.entry().unwrap().get_password().is_err());
        server.join().unwrap();
        let mock: &keyring::mock::MockCredential =
            a.entry().unwrap().get_credential().downcast_ref().unwrap();
        mock.set_error(keyring::Error::Invalid("storage".into(), "locked".into()));
        let (origin, server) = self::server(vec![(200, json!({"data":true}))]);
        a.origin = origin;
        assert!(a
            .save_tokens(
                json!({"access_token":"unpersisted","refresh_token":"rotated","expires_in":7200}),
                Access::Background
            )
            .await
            .is_err());
        assert!(!a.logged_in());
        assert!(a.access.is_empty());
        assert_eq!(
            server.join().unwrap(),
            vec!["POST /api/v1/auth/logout HTTP/1.1"]
        );
        std::fs::remove_dir_all(dir).unwrap();
    }
    #[test]
    fn resume_preserves_blocked_credentials_for_explicit_retry() {
        let dir = std::env::temp_dir().join(format!("capybara-resume-test-{}", Uuid::new_v4()));
        std::fs::create_dir_all(&dir).unwrap();
        let mut a = Account::new(&dir).unwrap();
        a.credential = Some(keyring::Entry::new_with_credential(Box::new(
            keyring::mock::MockCredential::default(),
        )));
        assert!(!a.resume(Access::Background).unwrap());
        let saved = json!({"refresh_token":"saved-refresh","device_id":a.device_id}).to_string();
        a.entry().unwrap().set_password(&saved).unwrap();
        let mock: &keyring::mock::MockCredential =
            a.entry().unwrap().get_credential().downcast_ref().unwrap();
        mock.set_error(keyring::Error::NoStorageAccess(Box::new(
            std::io::Error::new(std::io::ErrorKind::PermissionDenied, "locked"),
        )));
        assert_eq!(
            a.resume(Access::Background).unwrap_err().code,
            "CREDENTIALS_LOCKED"
        );
        assert!(!a.logged_in());
        assert_eq!(a.entry().unwrap().get_password().unwrap(), saved);
        assert!(a.resume(Access::UserInitiated).unwrap());
        assert_eq!(a.refresh, "saved-refresh");
        // A second restore must not roll an active session back to an old saved token.
        a.refresh = "rotated-in-memory".into();
        assert!(a.resume(Access::UserInitiated).unwrap());
        assert_eq!(a.refresh, "rotated-in-memory");
        a.refresh.clear();
        a.entry().unwrap().set_password("{invalid").unwrap();
        assert!(a.resume(Access::Background).is_err());
        assert!(!a.logged_in());
        a.entry()
            .unwrap()
            .set_password(
                &json!({"refresh_token":"wrong-device","device_id":"another"}).to_string(),
            )
            .unwrap();
        assert!(a.resume(Access::Background).is_err());
        assert!(!a.logged_in());
        a.entry().unwrap().set_password(&saved).unwrap();
        assert!(a.resume(Access::Background).unwrap());
        std::fs::remove_dir_all(dir).unwrap();
    }
    #[test]
    fn errors_never_echo_server_credentials() {
        let f = Account::fault(
            StatusCode::INTERNAL_SERVER_ERROR,
            &json!({"message":"secret-token","code":"SERVER_ERROR"}),
        );
        assert!(!f.message.contains("secret-token"));
    }
}
