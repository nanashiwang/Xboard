//! Only built-in or publisher-signed origins may receive account credentials.
use crate::account::{http, Fault};
use base64::{engine::general_purpose::STANDARD, Engine};
use minisign_verify::{PublicKey, Signature};
use reqwest::{Client, Url};
use serde::{Deserialize, Serialize};
use std::{
    path::PathBuf,
    time::{Duration, Instant},
};

pub const PRIMARY: &str = "https://capybarago.uk";
pub const BACKUP: &str = "https://app.capybarahub.fyi";
pub const HUB: &str = "https://capybarahub.fyi";
const DISCOVERY: [&str; 2] = [
    "https://capybarahub.fyi/downloads/capybara-entrypoints.json",
    "https://capybarago.uk/downloads/capybara-entrypoints.json",
];

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Envelope {
    payload: String,
    signature: String,
}
#[derive(Clone, Deserialize)]
#[serde(deny_unknown_fields)]
struct Manifest {
    kind: String,
    sequence: u64,
    issued_at: u64,
    expires_at: u64,
    origins: Vec<String>,
}

fn valid_origin(value: &str) -> bool {
    Url::parse(value).is_ok_and(|url| {
        url.scheme() == "https"
            && url.port().is_none()
            && url.username().is_empty()
            && url.password().is_none()
            && url.query().is_none()
            && url.fragment().is_none()
            && url.path() == "/"
            && url.origin().ascii_serialization() == value
            && url.host_str().is_some_and(|host| {
                host.contains('.')
                    && !host.ends_with('.')
                    && host.parse::<std::net::IpAddr>().is_err()
            })
    })
}

fn verify(envelope: &Envelope, key: &str) -> Result<Manifest, String> {
    let decode = |value: &str| {
        STANDARD
            .decode(value)
            .map_err(|_| "无效入口签名".to_string())
    };
    let key = String::from_utf8(decode(key)?).map_err(|_| "无效入口公钥")?;
    let signature = String::from_utf8(decode(&envelope.signature)?).map_err(|_| "无效入口签名")?;
    let payload = decode(&envelope.payload)?;
    PublicKey::decode(&key)
        .and_then(|k| k.verify(&payload, &Signature::decode(&signature)?, false))
        .map_err(|_| "入口签名校验失败")?;
    let manifest: Manifest = serde_json::from_slice(&payload).map_err(|_| "入口清单格式错误")?;
    if manifest.kind != "capybara-service-origins-v1"
        || manifest.sequence == 0
        || manifest.origins.is_empty()
        || manifest.origins.len() > 4
        || manifest.origins.iter().any(|origin| !valid_origin(origin))
        || manifest.expires_at <= manifest.issued_at
        || manifest.expires_at - manifest.issued_at > 366 * 86400
    {
        return Err("入口清单不符合策略".into());
    }
    Ok(manifest)
}
fn pubkey() -> String {
    serde_json::from_str::<serde_json::Value>(include_str!("../tauri.conf.json")).unwrap()
        ["plugins"]["updater"]["pubkey"]
        .as_str()
        .unwrap()
        .into()
}
fn current(manifest: &Manifest, now: u64) -> bool {
    manifest.issued_at <= now.saturating_add(300) && now < manifest.expires_at
}

#[derive(Clone)]
pub struct Directory {
    path: PathBuf,
    envelope: Option<Envelope>,
    manifest: Option<Manifest>,
    checked: Option<Instant>,
    discovery_checked: Option<Instant>,
    #[cfg(test)]
    pub test_origins: Option<Vec<String>>,
}
impl Directory {
    pub fn new(dir: &std::path::Path) -> Self {
        let path = dir.join("service-entrypoints.json");
        let envelope: Option<Envelope> = std::fs::read(&path)
            .ok()
            .filter(|bytes| bytes.len() <= 16384)
            .and_then(|bytes| serde_json::from_slice(&bytes).ok());
        let manifest = envelope
            .as_ref()
            .and_then(|value| verify(value, &pubkey()).ok());
        Self {
            path,
            envelope,
            manifest,
            checked: None,
            discovery_checked: None,
            #[cfg(test)]
            test_origins: None,
        }
    }
    pub fn origins(&self) -> Vec<String> {
        #[cfg(test)]
        if let Some(origins) = &self.test_origins {
            return origins.clone();
        }
        let mut origins = self
            .manifest
            .as_ref()
            .filter(|m| current(m, crate::now()))
            .map(|m| m.origins.clone())
            .unwrap_or_default();
        for origin in [PRIMARY, BACKUP] {
            if !origins.iter().any(|item| item == origin) {
                origins.push(origin.into());
            }
        }
        origins
    }
    fn accept(&mut self, envelope: Envelope, now: u64, key: &str) -> Result<(), String> {
        static CACHE_WRITE: std::sync::Mutex<()> = std::sync::Mutex::new(());
        let _guard = CACHE_WRITE.lock().map_err(|_| "入口缓存正忙")?;
        // Browser authorization and background account sync can own different snapshots.
        if let Some((stored, manifest)) = std::fs::read(&self.path)
            .ok()
            .filter(|bytes| bytes.len() <= 16384)
            .and_then(|bytes| serde_json::from_slice::<Envelope>(&bytes).ok())
            .and_then(|stored| verify(&stored, key).ok().map(|manifest| (stored, manifest)))
        {
            if self
                .manifest
                .as_ref()
                .is_none_or(|old| manifest.sequence >= old.sequence)
            {
                self.envelope = Some(stored);
                self.manifest = Some(manifest);
            }
        }
        let manifest = verify(&envelope, key)?;
        if !current(&manifest, now)
            || self.manifest.as_ref().is_some_and(|old| {
                manifest.sequence < old.sequence
                    || (manifest.sequence == old.sequence
                        && self
                            .envelope
                            .as_ref()
                            .is_none_or(|old| old.payload != envelope.payload))
            })
        {
            return Err("入口清单已过期或发生回退".into());
        }
        crate::private_write(
            &self.path,
            &serde_json::to_vec(&envelope).map_err(|_| "无法保存入口")?,
        )?;
        self.envelope = Some(envelope);
        self.manifest = Some(manifest);
        Ok(())
    }
    async fn discover(&mut self, client: &Client) {
        #[cfg(test)]
        if self.test_origins.is_some() {
            return;
        }
        if self
            .discovery_checked
            .is_some_and(|at| at.elapsed() < Duration::from_secs(60))
        {
            return;
        }
        self.discovery_checked = Some(Instant::now());
        for url in DISCOVERY {
            let Ok(mut response) = client.get(url).timeout(Duration::from_secs(3)).send().await
            else {
                continue;
            };
            if !response.status().is_success() {
                continue;
            }
            let mut bytes = Vec::new();
            while let Ok(Some(chunk)) = response.chunk().await {
                bytes.extend_from_slice(&chunk);
                if bytes.len() > 16384 {
                    break;
                }
            }
            if bytes.len() > 16384 {
                continue;
            }
            if let Ok(envelope) = serde_json::from_slice(&bytes) {
                if self.accept(envelope, crate::now(), &pubkey()).is_ok() {
                    break;
                }
            }
        }
    }
    pub async fn select(&mut self, origin: &str, failed: bool) -> Result<String, Fault> {
        // Loopback servers are only injected by native tests, never read from configuration.
        #[cfg(test)]
        if self.test_origins.is_none() && origin.starts_with("http://127.0.0.1:") {
            return Ok(origin.into());
        }
        if !failed
            && self
                .checked
                .is_some_and(|at| at.elapsed() < Duration::from_secs(30))
            && self.origins().iter().any(|item| item == origin)
        {
            return Ok(origin.into());
        }
        self.checked = None;
        let client = http()?;
        self.discover(&client).await;
        let mut candidates = self.origins();
        if !failed && self.manifest.is_none() && candidates.iter().any(|item| item == origin) {
            candidates.retain(|item| item != origin);
            candidates.insert(0, origin.into());
        } else if failed {
            candidates.retain(|item| item != origin);
        }
        for candidate in candidates {
            if healthy(&client, &candidate).await {
                self.checked = Some(Instant::now());
                return Ok(candidate);
            }
        }
        Err(Fault {
            code: "NETWORK_UNAVAILABLE".into(),
            message: "主用和备用服务暂时无法连接，请稍后重试或打开导航页".into(),
        })
    }
}

async fn healthy(client: &Client, origin: &str) -> bool {
    let Ok(mut response) = client
        .get(format!("{origin}/api/v1/client/health"))
        .timeout(Duration::from_secs(3))
        .send()
        .await
    else {
        return false;
    };
    if !response.status().is_success() {
        return false;
    }
    let mut bytes = Vec::new();
    while let Ok(Some(chunk)) = response.chunk().await {
        if bytes.len() + chunk.len() > 1024 {
            return false;
        }
        bytes.extend_from_slice(&chunk);
    }
    let Ok(value) = serde_json::from_slice::<serde_json::Value>(&bytes) else {
        return false;
    };
    value == serde_json::json!({"service":"capybara-account", "protocol":1})
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn publisher_signatures_expiry_and_rollback_are_enforced() {
        let data: serde_json::Value =
            serde_json::from_str(include_str!("../test-data/entrypoints.json")).unwrap();
        let key = data["key"].as_str().unwrap();
        let envelope = |name: &str| serde_json::from_value::<Envelope>(data[name].clone()).unwrap();
        let dir = std::env::temp_dir().join(uuid::Uuid::new_v4().to_string());
        std::fs::create_dir(&dir).unwrap();
        let mut directory = Directory::new(&dir);
        directory.accept(envelope("valid"), 1500, key).unwrap();
        for name in ["rollback", "conflict", "wrongPurpose", "unsafe"] {
            assert!(
                directory.accept(envelope(name), 1500, key).is_err(),
                "{name}"
            );
        }
        assert!(directory.accept(envelope("valid"), 2001, key).is_err());
        assert!(directory.accept(envelope("valid"), 1, key).is_err());
        let mut tampered = envelope("valid");
        tampered.payload = STANDARD.encode(b"{}");
        assert!(directory.accept(tampered, 1500, key).is_err());
        assert_eq!(directory.manifest.unwrap().sequence, 5);
        std::fs::remove_dir_all(dir).unwrap();
    }
    #[test]
    fn origins_cannot_smuggle_paths_credentials_or_plaintext() {
        assert!(valid_origin(PRIMARY));
        assert!(valid_origin(BACKUP));
        for value in [
            "https://example.com/",
            "http://example.com",
            "https://example.com/api",
            "https://user@example.com",
            "https://example.com?next=evil",
            "https://127.0.0.1",
            "https://example.com:444",
            "https://example.com.",
        ] {
            assert!(!valid_origin(value), "{value}");
        }
    }
    #[test]
    fn unsigned_cached_origins_never_receive_credentials() {
        let dir = std::env::temp_dir().join(uuid::Uuid::new_v4().to_string());
        std::fs::create_dir(&dir).unwrap();
        std::fs::write(
            dir.join("service-entrypoints.json"),
            r#"{"payload":"e30=","signature":"invalid"}"#,
        )
        .unwrap();
        assert_eq!(Directory::new(&dir).origins(), vec![PRIMARY, BACKUP]);
        std::fs::remove_dir_all(dir).unwrap();
    }
}
