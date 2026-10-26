use crate::{account::Fault, private_write};
use serde::{Deserialize, Serialize};
use std::{future::Future, path::Path};

pub const DEFAULT_INTERVAL_SECONDS: u64 = 3600;
const INTERVALS: [u64; 6] = [1800, 3600, 10800, 21600, 43200, 86400];

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Settings {
    interval_seconds: u64,
}

pub fn load_interval(dir: &Path) -> (u64, Option<String>) {
    let parsed = match std::fs::read(dir.join("subscription.json")) {
        Ok(content) => serde_json::from_slice::<Settings>(&content).ok(),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            return (DEFAULT_INTERVAL_SECONDS, None);
        }
        Err(_) => None,
    };
    match parsed {
        Some(value) if INTERVALS.contains(&value.interval_seconds) => {
            (value.interval_seconds, None)
        }
        _ => (
            DEFAULT_INTERVAL_SECONDS,
            Some("订阅更新设置无法读取，已恢复每小时更新，请重新保存设置".into()),
        ),
    }
}

pub fn save_interval(dir: &Path, seconds: u64) -> Result<(), Fault> {
    if !INTERVALS.contains(&seconds) {
        return Err(Fault::local("请选择有效的订阅更新周期"));
    }
    let content = serde_json::to_vec(&Settings {
        interval_seconds: seconds,
    })
    .map_err(|_| Fault::local("无法保存订阅更新设置"))?;
    private_write(&dir.join("subscription.json"), &content).map_err(Fault::from)
}

#[derive(Clone, Copy)]
pub struct RefreshRequest {
    pub forced: bool,
    pub engine_ready: bool,
    pub last_success: Option<u64>,
    pub interval_seconds: u64,
    pub now: u64,
}

impl RefreshRequest {
    pub fn due(self) -> bool {
        self.forced
            || !self.engine_ready
            || self.last_success.is_none_or(|previous| {
                // Wall time includes sleep. A backwards clock must not postpone refresh indefinitely.
                self.now < previous || self.now - previous >= self.interval_seconds
            })
    }
}

// The runtime uses this same path for manual and automatic refresh. A success
// timestamp is returned only after download validation and live application both succeed.
pub async fn refresh<D, DFut, A, AFut, C>(
    request: RefreshRequest,
    download: D,
    apply: A,
    completed_at: C,
) -> Result<Option<u64>, Fault>
where
    D: FnOnce() -> DFut,
    DFut: Future<Output = Result<String, Fault>>,
    A: FnOnce(String) -> AFut,
    AFut: Future<Output = Result<(), Fault>>,
    C: FnOnce() -> u64,
{
    if !request.due() {
        return Ok(None);
    }
    let content = download().await?;
    apply(content).await?;
    Ok(Some(completed_at()))
}

pub fn invalidates_session(error: &Fault) -> bool {
    matches!(
        error.code.as_str(),
        "AUTH_REQUIRED"
            | "AUTH_REFRESH_REUSED"
            | "AUTH_REFRESH_EXPIRED"
            | "AUTH_DEVICE_MISMATCH"
            | "AUTH_UNAUTHENTICATED"
            | "AUTH_TOKEN_EXPIRED"
            | "AUTH_TOKEN_INVALID"
            | "DEVICE_NOT_REGISTERED"
            | "DEVICE_REVOKED"
            | "ACCOUNT_BANNED"
    )
}

pub fn propagate_config_error(error: &Fault, forced: bool, logged_in: bool) -> bool {
    forced || !logged_in || invalidates_session(error) || error.code == "SUBSCRIPTION_UNAVAILABLE"
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::{Arc, Mutex};

    fn request(now: u64) -> RefreshRequest {
        RefreshRequest {
            forced: false,
            engine_ready: true,
            last_success: Some(1000),
            interval_seconds: DEFAULT_INTERVAL_SECONDS,
            now,
        }
    }

    async fn run(
        request: RefreshRequest,
        calls: Arc<Mutex<Vec<&'static str>>>,
        download_error: bool,
        apply_error: bool,
    ) -> Result<Option<u64>, Fault> {
        let downloaded = calls.clone();
        let applied = calls.clone();
        refresh(
            request,
            move || async move {
                downloaded.lock().unwrap().push("download");
                if download_error {
                    Err(Fault::local("download failed"))
                } else {
                    Ok("new source".into())
                }
            },
            move |content| async move {
                assert_eq!(content, "new source");
                applied.lock().unwrap().push("apply");
                if apply_error {
                    Err(Fault::local("application failed"))
                } else {
                    Ok(())
                }
            },
            || 5000,
        )
        .await
    }

    #[tokio::test]
    async fn manual_refresh_downloads_and_applies_before_interval_is_due() {
        let calls = Arc::new(Mutex::new(vec![]));
        assert_eq!(
            run(request(1100), calls.clone(), false, false)
                .await
                .unwrap(),
            None
        );
        assert!(calls.lock().unwrap().is_empty());
        let mut manual = request(1100);
        manual.forced = true;
        assert_eq!(
            run(manual, calls.clone(), false, false).await.unwrap(),
            Some(5000)
        );
        assert_eq!(*calls.lock().unwrap(), vec!["download", "apply"]);
    }

    #[tokio::test]
    async fn automatic_refresh_runs_once_for_due_wake_restart_and_clock_rollback() {
        for input in [
            request(4600),
            request(90_000),
            request(900),
            RefreshRequest {
                engine_ready: false,
                ..request(1100)
            },
            RefreshRequest {
                last_success: None,
                ..request(1100)
            },
            RefreshRequest {
                interval_seconds: 1800,
                ..request(2800)
            },
        ] {
            let calls = Arc::new(Mutex::new(vec![]));
            assert_eq!(
                run(input, calls.clone(), false, false).await.unwrap(),
                Some(5000)
            );
            assert_eq!(*calls.lock().unwrap(), vec!["download", "apply"]);
        }
    }

    #[tokio::test]
    async fn failed_download_or_application_never_produces_a_success_timestamp() {
        for (download_error, apply_error, expected) in [
            (true, false, vec!["download"]),
            (false, true, vec!["download", "apply"]),
        ] {
            let calls = Arc::new(Mutex::new(vec![]));
            let mut last_success = Some(1000);
            let result = run(request(4600), calls.clone(), download_error, apply_error).await;
            if let Ok(Some(updated)) = result.as_ref() {
                last_success = Some(*updated);
            }
            assert!(result.is_err());
            assert_eq!(last_success, Some(1000));
            assert_eq!(*calls.lock().unwrap(), expected);
        }
    }

    #[test]
    fn interval_is_private_validated_persisted_and_corruption_falls_back() {
        let dir = std::env::temp_dir().join(format!(
            "capybara-subscription-test-{}",
            uuid::Uuid::new_v4()
        ));
        std::fs::create_dir_all(&dir).unwrap();
        assert_eq!(load_interval(&dir), (3600, None));
        for interval in INTERVALS {
            save_interval(&dir, interval).unwrap();
            assert_eq!(load_interval(&dir), (interval, None));
        }
        assert!(save_interval(&dir, 0).is_err());
        assert_eq!(load_interval(&dir), (86400, None));
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            assert_eq!(
                std::fs::metadata(dir.join("subscription.json"))
                    .unwrap()
                    .permissions()
                    .mode()
                    & 0o777,
                0o600
            );
        }
        std::fs::write(dir.join("subscription.json"), br#"{"interval_seconds":1}"#).unwrap();
        let (interval, error) = load_interval(&dir);
        assert_eq!(interval, 3600);
        assert!(error.is_some());
        std::fs::write(dir.join("subscription.json"), b"invalid").unwrap();
        assert!(load_interval(&dir).1.is_some());
        std::fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn transient_network_failure_does_not_invalidate_login() {
        for code in [
            "NETWORK_TIMEOUT",
            "NETWORK_CONNECT",
            "CREDENTIALS_LOCKED",
            "LOCAL_ERROR",
        ] {
            let error = Fault {
                code: code.into(),
                message: String::new(),
            };
            assert!(!invalidates_session(&error));
            assert!(!propagate_config_error(&error, false, true));
            assert!(propagate_config_error(&error, true, true));
        }
        for code in [
            "AUTH_UNAUTHENTICATED",
            "AUTH_TOKEN_EXPIRED",
            "AUTH_TOKEN_INVALID",
            "AUTH_REFRESH_EXPIRED",
            "AUTH_REFRESH_REUSED",
            "AUTH_DEVICE_MISMATCH",
            "DEVICE_NOT_REGISTERED",
            "DEVICE_REVOKED",
            "ACCOUNT_BANNED",
        ] {
            let error = Fault {
                code: code.into(),
                message: String::new(),
            };
            assert!(invalidates_session(&error));
            assert!(propagate_config_error(&error, false, true));
        }
        let unavailable = Fault {
            code: "SUBSCRIPTION_UNAVAILABLE".into(),
            message: String::new(),
        };
        assert!(!invalidates_session(&unavailable));
        assert!(propagate_config_error(&unavailable, false, true));
    }
}
