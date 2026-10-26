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
fn network_fault(error: reqwest::Error) -> Fault {
    // Never echo raw URLs, request bodies or server error text containing credentials.
    use std::error::Error;
    let mut source: Option<&(dyn Error + 'static)> = Some(&error);
    let mut denied = false;
    while let Some(cause) = source {
        denied |= cause
            .downcast_ref::<std::io::Error>()
            .is_some_and(|e| e.kind() == std::io::ErrorKind::PermissionDenied);
        source = cause.source();
    }
    let (code, message) = if denied {
        (
            "NETWORK_DENIED",
            "系统阻止了账户连接，请允许卡皮巴拉访问网络（NETWORK_DENIED）",
        )
    } else if error.is_timeout() {
        (
            "NETWORK_TIMEOUT",
            "连接 taige.us 超时，请检查网络后重试（NETWORK_TIMEOUT）",
        )
    } else if error.is_connect() {
        (
            "NETWORK_CONNECT",
            "无法连接 taige.us，请检查网络或防火墙设置（NETWORK_CONNECT）",
        )
    } else {
        (
            "NETWORK_REQUEST",
            "账户请求未完成，请重新发起登录（NETWORK_REQUEST）",
        )
    };
    Fault {
        code: code.into(),
        message: message.into(),
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
                message:
                    "登录记录暂时无法读取。点击“恢复登录”允许访问系统凭据库，或通过浏览器重新登录。"
                        .into(),
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
            "AUTH_BROWSER_EXPIRED" => "浏览器授权已过期，请重新登录",
            "AUTH_BROWSER_CANCELLED" => "已在浏览器取消授权，请重新登录",
            "AUTH_BROWSER_INVALID" => "授权请求无效，请重新登录",
            "AUTH_BROWSER_BUSY" => "授权服务繁忙，请稍后重试",
            "RATE_LIMITED" => "操作过于频繁，请稍后重试",
            "STORE_BUSY" => "订单正在处理，请稍后刷新",
            "STORE_PENDING_ORDER" => "请先支付或取消未完成订单",
            "STORE_PLAN_UNAVAILABLE" => "套餐暂不可购买，请刷新列表",
            "STORE_ORDER_REJECTED" => "下单未完成，请检查周期、优惠码或换购规则",
            "STORE_ORDER_CHANGED" => "订单状态已变化，请刷新",
            "STORE_PAYMENT_FAILED" => "支付请求未完成，请刷新订单后重试",
            "STORE_PAYMENT_UNSUPPORTED" => "此支付方式请在网站订单中心继续",
            "STORE_ORDER_NOT_FOUND" => "找不到订单，请刷新列表",
            "STORE_INVALID_INPUT" => "请选择有效套餐、周期和订单",
            "INVITE_BUSY" => "邀请码正在生成，请稍后刷新查看",
            "INVITE_LIMIT_REACHED" => "已达到可用邀请码数量上限，请使用已有邀请码",
            "INVITE_REGISTRATION_CLOSED" => "网站暂未开放注册，请稍后再邀请",
            "INVITE_INVALID_PAGE" => "页码无效，请刷新后重试",
            _ if status == StatusCode::NOT_FOUND => "服务正在准备中，请稍后重试或前往官网操作",
            _ if status == StatusCode::UNAUTHORIZED => "登录已失效，请重新登录",
            _ => "服务暂时不可用，请稍后重试",
        };
        Fault {
            code: code.into(),
            message: message.into(),
        }
    }
    pub async fn save_tokens(&mut self, value: Value, mode: Access) -> Result<(), Fault> {
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
    pub fn browser_session(&self) -> Result<BrowserSession, Fault> {
        self.entry()?;
        if self.logged_in() {
            return Err(Fault::local("请先退出当前账号"));
        }
        Ok(BrowserSession {
            registration: false,
            client: self.client.clone(),
            origin: self.origin.clone(),
            device_id: self.device_id.clone(),
            id: String::new(),
            secret: format!("{}{}", Uuid::new_v4().simple(), Uuid::new_v4().simple()),
            deadline: Instant::now() + Duration::from_secs(300),
        })
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
            .map_err(network_fault)?;
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
            .map_err(network_fault)?;
        if response.status() == StatusCode::UNAUTHORIZED {
            self.renew().await?;
            response = self
                .request(Method::GET, path)
                .bearer_auth(&self.access)
                .send()
                .await
                .map_err(network_fault)?;
        }
        Ok(response)
    }
    pub async fn get(&mut self, path: &str) -> Result<Value, Fault> {
        Self::decode(self.authorized(path).await?).await
    }
    pub async fn public_get(&self, path: &str) -> Result<Value, Fault> {
        Self::decode(
            self.request(Method::GET, path)
                .send()
                .await
                .map_err(network_fault)?,
        )
        .await
    }
    pub async fn post(&mut self, path: &str, body: &Value) -> Result<Value, Fault> {
        if self.access.is_empty() || Instant::now() >= self.expires {
            self.renew().await?;
        }
        // Mutations are never retried automatically, including ambiguous network failures.
        Self::decode(
            self.request(Method::POST, path)
                .bearer_auth(&self.access)
                .json(body)
                .send()
                .await
                .map_err(network_fault)?,
        )
        .await
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

#[derive(Clone)]
pub struct BrowserSession {
    pub registration: bool,
    client: Client,
    origin: String,
    device_id: String,
    id: String,
    secret: String,
    deadline: Instant,
}
impl BrowserSession {
    fn request(&self, action: &str) -> reqwest::RequestBuilder {
        self.client
            .post(format!("{}/api/v1/auth/browser/{action}", self.origin))
            .timeout(Duration::from_secs(12))
            .header("Accept", "application/json")
            .json(&json!({"request_id": self.id, "secret": self.secret}))
    }
    pub async fn start(&mut self) -> Result<(), Fault> {
        let response = self
            .request("start")
            .json(&json!({"secret": self.secret, "device": {
                "device_id": self.device_id, "name": format!("卡皮巴拉 · {}", platform()),
                "platform": platform(), "architecture": architecture(), "app_version": VERSION
            }}))
            .send()
            .await
            .map_err(network_fault)?;
        if response.status() == StatusCode::NOT_FOUND {
            return Err(Fault::local("账户服务尚未支持浏览器登录，请稍后再试"));
        }
        let value = Account::decode(response).await?;
        let id = value["request_id"].as_str().unwrap_or("");
        if id.len() != 26
            || !id
                .bytes()
                .all(|b| b"0123456789ABCDEFGHJKMNPQRSTVWXYZ".contains(&b))
        {
            return Err(Fault::local("授权响应不完整，请重新登录"));
        }
        self.id = id.into();
        self.deadline = Instant::now()
            + Duration::from_secs(value["expires_in"].as_u64().unwrap_or(0).min(300));
        Ok(())
    }
    pub fn url(&self) -> String {
        format!(
            "{}/desktop/login#request_id={}{}",
            self.origin,
            self.id,
            if self.registration {
                "&flow=register"
            } else {
                ""
            }
        )
    }
    pub fn remaining(&self) -> u64 {
        self.deadline
            .saturating_duration_since(Instant::now())
            .as_secs()
    }
    pub async fn poll(&self) -> Result<Option<Value>, Fault> {
        if self.remaining() == 0 {
            return Err(Fault::local("浏览器授权已过期，请重新登录"));
        }
        let response = self.request("poll").send().await.map_err(network_fault)?;
        let status = response.status();
        let value = match Account::decode(response).await {
            // The server guarantees this error only after a complete transaction rollback.
            Err(error)
                if status == StatusCode::SERVICE_UNAVAILABLE
                    && error.code == "AUTH_BROWSER_BUSY" =>
            {
                return Ok(None)
            }
            result => result?,
        };
        match value["phase"].as_str() {
            Some("pending") => Ok(None),
            Some("complete") if value["tokens"].is_object() => Ok(Some(value["tokens"].clone())),
            _ => Err(Fault::local("授权响应不完整，请重新登录")),
        }
    }
    pub async fn cancel(&self) {
        let _ = self.request("cancel").send().await;
    }
    pub async fn discard(&self, tokens: &Value) {
        if let Some(refresh) = tokens["refresh_token"].as_str() {
            let _ = self
                .client
                .post(format!("{}/api/v1/auth/logout", self.origin))
                .timeout(Duration::from_secs(12))
                .json(&json!({"refresh_token": refresh}))
                .send()
                .await;
        }
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
    async fn store_mutation_is_not_retried_on_server_failure() {
        let dir = std::env::temp_dir().join(format!("capybara-store-test-{}", Uuid::new_v4()));
        std::fs::create_dir_all(&dir).unwrap();
        let mut account = Account::new(&dir).unwrap();
        account.access = "test-access".into();
        account.expires = Instant::now() + Duration::from_secs(60);
        let (origin, server) = server(vec![(
            500,
            json!({"code":"SERVER_ERROR", "message":"secret"}),
        )]);
        account.origin = origin;
        assert!(!account
            .post("client/store/save", &json!({"plan_id":1}))
            .await
            .unwrap_err()
            .message
            .contains("secret"));
        assert_eq!(
            server.join().unwrap(),
            vec!["POST /api/v1/client/store/save HTTP/1.1"]
        );
        std::fs::remove_dir_all(dir).unwrap();
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

    #[tokio::test]
    async fn browser_waits_only_for_explicit_rolled_back_busy_response() {
        let dir = std::env::temp_dir().join(format!("capybara-busy-test-{}", Uuid::new_v4()));
        std::fs::create_dir_all(&dir).unwrap();
        let mut account = Account::new(&dir).unwrap();
        let (origin, server) = server(vec![
            (
                200,
                json!({"data":{"request_id":"01K8ABCDEFGHJKMNPQRSTVWXYZ", "expires_in":300}}),
            ),
            (503, json!({"code":"AUTH_BROWSER_BUSY"})),
            (503, json!({"code":"SERVICE_UNAVAILABLE"})),
            (500, json!({"code":"AUTH_BROWSER_BUSY"})),
        ]);
        account.origin = origin;
        let mut session = account.browser_session().unwrap();
        session.start().await.unwrap();
        assert!(session.poll().await.unwrap().is_none());
        assert_eq!(
            session.poll().await.unwrap_err().code,
            "SERVICE_UNAVAILABLE"
        );
        assert_eq!(session.poll().await.unwrap_err().code, "AUTH_BROWSER_BUSY");
        assert_eq!(server.join().unwrap().len(), 4);
        std::fs::remove_dir_all(dir).unwrap();
    }

    #[tokio::test]
    async fn browser_flow_keeps_secrets_native_and_saves_only_completed_authorization() {
        let dir = std::env::temp_dir().join(format!("capybara-browser-test-{}", Uuid::new_v4()));
        std::fs::create_dir_all(&dir).unwrap();
        let mut account = Account::new(&dir).unwrap();
        account.credential = Some(keyring::Entry::new_with_credential(Box::new(
            keyring::mock::MockCredential::default(),
        )));
        let (origin, server) = server(vec![
            (
                200,
                json!({"data":{"request_id":"01K8ABCDEFGHJKMNPQRSTVWXYZ", "expires_in":300}}),
            ),
            (200, json!({"data":{"phase":"pending"}})),
            (
                200,
                json!({"data":{"phase":"complete","tokens":{"access_token":"new-access","refresh_token":"new-refresh","expires_in":7200}}}),
            ),
        ]);
        account.origin = origin.clone();
        let mut session = account.browser_session().unwrap();
        let other = account.browser_session().unwrap();
        assert_eq!(session.secret.len(), 64);
        assert_ne!(session.secret, other.secret);
        session.start().await.unwrap();
        assert_eq!(
            session.url(),
            format!("{origin}/desktop/login#request_id=01K8ABCDEFGHJKMNPQRSTVWXYZ")
        );
        assert!(!session.url().contains(&session.secret));
        session.registration = true;
        assert_eq!(
            session.url(),
            format!("{origin}/desktop/login#request_id=01K8ABCDEFGHJKMNPQRSTVWXYZ&flow=register")
        );
        assert!(!session.url().contains(&session.secret));
        assert!(session.poll().await.unwrap().is_none());
        assert!(account.entry().unwrap().get_password().is_err());
        let tokens = session.poll().await.unwrap().unwrap();
        account
            .save_tokens(tokens, Access::UserInitiated)
            .await
            .unwrap();
        assert!(account.logged_in());
        assert!(account.browser_session().is_err());
        assert_eq!(server.join().unwrap().len(), 3);
        std::fs::remove_dir_all(dir).unwrap();
    }

    #[tokio::test]
    async fn browser_expiry_cancellation_and_late_tokens_do_not_log_in() {
        let (origin, server) = server(vec![
            (
                410,
                json!({"code":"AUTH_BROWSER_CANCELLED", "message":"private-value"}),
            ),
            (200, json!({"data":true})),
            (200, json!({"data":true})),
        ]);
        let mut session = BrowserSession {
            registration: false,
            client: http().unwrap(),
            origin,
            device_id: Uuid::new_v4().to_string(),
            id: "01K8ABCDEFGHJKMNPQRSTVWXYZ".into(),
            secret: "a".repeat(64),
            deadline: Instant::now(),
        };
        assert!(session.poll().await.unwrap_err().message.contains("过期"));
        session.deadline = Instant::now() + Duration::from_secs(60);
        let fault = session.poll().await.unwrap_err();
        assert_eq!(fault.code, "AUTH_BROWSER_CANCELLED");
        assert!(!fault.message.contains("private-value"));
        session.cancel().await;
        session
            .discard(&json!({"refresh_token":"late-refresh"}))
            .await;
        assert_eq!(
            server.join().unwrap(),
            vec![
                "POST /api/v1/auth/browser/poll HTTP/1.1",
                "POST /api/v1/auth/browser/cancel HTTP/1.1",
                "POST /api/v1/auth/logout HTTP/1.1",
            ]
        );
    }
}
