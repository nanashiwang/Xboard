use crate::{now, private_write, AppState, Fault};
use serde::{Deserialize, Serialize};
use std::{
    path::Path,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
    time::Duration,
};
use tauri::{Manager, State};
use tauri_plugin_updater::{Update, UpdaterExt};

const INTERVAL: u64 = 6 * 60 * 60;
const FEED: &str = "https://taige.us/downloads/capybara-latest.json";

#[derive(Clone, Default, Deserialize, Serialize)]
struct Schedule {
    last_checked: Option<u64>,
}
impl Schedule {
    fn due(&self, time: u64) -> bool {
        self.last_checked
            .is_none_or(|last| time < last || time - last >= INTERVAL)
    }
}
#[derive(Clone, Serialize)]
pub struct Release {
    version: String,
    notes: String,
}
#[derive(Clone, Serialize)]
pub struct UpdateView {
    phase: String,
    last_checked: Option<u64>,
    release: Option<Release>,
    prompt: bool,
    downloaded: u64,
    total: Option<u64>,
    error: Option<String>,
    manual_install: bool,
}
struct Data {
    view: UpdateView,
    schedule: Schedule,
    update: Option<Update>,
}
pub struct Monitor {
    data: Mutex<Data>,
    path: std::path::PathBuf,
    pub installing: Arc<AtomicBool>,
}
#[derive(Clone)]
pub struct UpdateState(pub Arc<Monitor>);
impl Monitor {
    fn new(dir: &Path, manual_install: bool, installing: Arc<AtomicBool>) -> Self {
        let path = dir.join("update-check.json");
        let schedule: Schedule = std::fs::read(&path)
            .ok()
            .and_then(|bytes| serde_json::from_slice(&bytes).ok())
            .unwrap_or_default();
        Self {
            path,
            installing,
            data: Mutex::new(Data {
                view: UpdateView {
                    phase: "idle".into(),
                    last_checked: schedule.last_checked,
                    release: None,
                    prompt: false,
                    downloaded: 0,
                    total: None,
                    error: None,
                    manual_install,
                },
                schedule,
                update: None,
            }),
        }
    }
    fn view(&self) -> UpdateView {
        self.data.lock().unwrap().view.clone()
    }
    fn begin_check(&self, time: u64, manual: bool) -> bool {
        let mut data = self.data.lock().unwrap();
        if data.view.phase == "checking"
            || self.installing.load(Ordering::SeqCst)
            || (!manual && !data.schedule.due(time))
        {
            return false;
        }
        data.schedule.last_checked = Some(time);
        // Keep the in-memory deadline even if storage is unavailable, avoiding a retry storm.
        let saved = private_write(&self.path, &serde_json::to_vec(&data.schedule).unwrap());
        data.view.phase = "checking".into();
        data.view.last_checked = Some(time);
        data.view.release = None;
        data.view.prompt = false;
        data.view.error = saved.err();
        data.update = None;
        true
    }
    fn fail(&self, message: &str) {
        let mut data = self.data.lock().unwrap();
        data.view.phase = "error".into();
        data.view.error = Some(message.into());
        self.installing.store(false, Ordering::SeqCst);
    }
}

fn trusted_asset(update: &Update) -> bool {
    let url = &update.download_url;
    url.scheme() == "https"
        && url.host_str() == Some("taige.us")
        && url.port().is_none()
        && url.username().is_empty()
        && url.password().is_none()
        && url
            .path()
            .starts_with(&format!("/downloads/Capybara_{}_", update.version))
}

pub fn start(app: &tauri::AppHandle, dir: &Path, installing: Arc<AtomicBool>) {
    // DEB is managed by the system package installer, not replaced with an AppImage.
    #[cfg(target_os = "linux")]
    let manual = app.env().appimage.is_none();
    #[cfg(not(target_os = "linux"))]
    let manual = false;
    let monitor = Arc::new(Monitor::new(dir, manual, installing));
    app.manage(UpdateState(monitor.clone()));
    let app = app.clone();
    tauri::async_runtime::spawn(async move {
        let mut timer = tokio::time::interval(Duration::from_secs(60));
        timer.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
        loop {
            timer.tick().await;
            check(&app, &monitor, false).await;
        }
    });
}
async fn check(app: &tauri::AppHandle, monitor: &Monitor, manual: bool) {
    let time = now();
    if !monitor.begin_check(time, manual) {
        return;
    }
    let result = async {
        let updater = app
            .updater_builder()
            .no_proxy()
            .timeout(Duration::from_secs(25))
            .configure_client(|client| {
                client
                    .https_only(true)
                    .connect_timeout(Duration::from_secs(10))
            })
            // A new query also bypasses the static download directory's long cache lifetime.
            .endpoints(vec![format!("{FEED}?check={time}").parse()?])?
            .build()?;
        updater.check().await
    }
    .await;
    match result {
        Ok(update) if update.as_ref().is_none_or(trusted_asset) => {
            let mut data = monitor.data.lock().unwrap();
            data.view.release = update.as_ref().map(|u| Release {
                version: u.version.clone(),
                notes: u.body.clone().unwrap_or_default(),
            });
            data.view.prompt = update.is_some();
            data.view.phase = if update.is_some() {
                "available"
            } else {
                "current"
            }
            .into();
            data.update = update;
        }
        Ok(_) => monitor.fail("更新地址校验失败，请稍后重试或联系支持"),
        Err(_) => monitor.fail("暂时无法检查更新，请检查网络后重试"),
    }
}
#[tauri::command]
pub fn update_snapshot(state: State<'_, UpdateState>) -> UpdateView {
    state.0.view()
}
#[tauri::command]
pub async fn check_updates(
    app: tauri::AppHandle,
    state: State<'_, UpdateState>,
) -> Result<UpdateView, Fault> {
    check(&app, &state.0, true).await;
    Ok(state.0.view())
}
#[tauri::command]
pub fn show_update(state: State<'_, UpdateState>) -> UpdateView {
    let mut data = state.0.data.lock().unwrap();
    if data.update.is_some() && !state.0.installing.load(Ordering::SeqCst) {
        data.view.prompt = true;
    }
    data.view.clone()
}
#[tauri::command]
pub fn dismiss_update(state: State<'_, UpdateState>) -> UpdateView {
    let mut data = state.0.data.lock().unwrap();
    if !state.0.installing.load(Ordering::SeqCst) {
        data.view.prompt = false;
    }
    data.view.clone()
}
#[tauri::command]
pub async fn install_update(
    app: tauri::AppHandle,
    state: State<'_, UpdateState>,
    runtime: State<'_, AppState>,
) -> Result<UpdateView, Fault> {
    let monitor = state.0.clone();
    let (mut update, manual) = {
        let mut data = monitor.data.lock().unwrap();
        let update = data
            .update
            .clone()
            .ok_or_else(|| Fault::local("请先检查新版本"))?;
        if monitor.installing.swap(true, Ordering::SeqCst) {
            return Err(Fault::local("更新正在进行，请稍候"));
        }
        data.view.phase = "downloading".into();
        data.view.downloaded = 0;
        data.view.total = None;
        data.view.error = None;
        data.view.prompt = true;
        (update, data.view.manual_install)
    };
    if manual {
        use tauri_plugin_opener::OpenerExt;
        let result = app
            .opener()
            .open_url("https://taige.us/clients#linux", None::<&str>);
        monitor.installing.store(false, Ordering::SeqCst);
        if result.is_err() {
            monitor.fail("无法打开下载页，请访问 taige.us/clients 下载安装 DEB 更新");
        } else {
            let mut data = monitor.data.lock().unwrap();
            data.view.phase = "available".into();
            data.view.prompt = false;
        }
        return Ok(monitor.view());
    }
    // This command is only sent after an explicit confirmation in the update dialog.
    update.timeout = Some(Duration::from_secs(900));
    let downloaded = update
        .download(
            |chunk, total| {
                let mut data = monitor.data.lock().unwrap();
                data.view.downloaded += chunk as u64;
                data.view.total = total;
            },
            || {},
        )
        .await;
    let bytes = match downloaded {
        Ok(bytes) => bytes, // Tauri verifies the pinned publisher signature before returning.
        Err(_) => {
            monitor.fail("更新包下载或签名校验失败，未安装更新。请重试，或从官网下载。");
            return Ok(monitor.view());
        }
    };
    monitor.data.lock().unwrap().view.phase = "installing".into();
    // Keep connections gated until installation has completed; never exit with our proxy set.
    if runtime.0.lock().await.shutdown().await.is_err() {
        monitor.fail("系统代理恢复失败，已停止更新。请先断开连接后重试。");
        return Ok(monitor.view());
    }
    let installed = tauri::async_runtime::spawn_blocking(move || update.install(bytes)).await;
    match installed {
        Ok(Ok(())) => {
            monitor.data.lock().unwrap().view.phase = "restarting".into();
            app.request_restart();
        }
        _ => monitor.fail("安装未完成，系统代理已恢复。请重试或从官网下载新版安装包。"),
    }
    Ok(monitor.view())
}
pub fn prevent_exit(app: &tauri::AppHandle) -> bool {
    app.try_state::<UpdateState>().is_some_and(|state| {
        state.0.installing.load(Ordering::SeqCst) && state.0.view().phase != "restarting"
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    fn fixture() -> (std::path::PathBuf, Monitor) {
        let dir = std::env::temp_dir().join(format!("capybara-update-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir_all(&dir).unwrap();
        let monitor = Monitor::new(&dir, false, Arc::new(AtomicBool::new(false)));
        (dir, monitor)
    }
    #[test]
    fn six_hour_boundary_restart_sleep_and_clock_rollback() {
        let (dir, monitor) = fixture();
        assert!(monitor.begin_check(100_000, false));
        let restarted = Monitor::new(&dir, false, Arc::new(AtomicBool::new(false)));
        assert!(!restarted.begin_check(121_599, false));
        assert!(restarted.begin_check(121_600, false));
        assert!(Schedule {
            last_checked: Some(100_000)
        }
        .due(150_000));
        assert!(Schedule {
            last_checked: Some(100_000)
        }
        .due(99_999));
        std::fs::remove_dir_all(dir).unwrap();
    }
    #[test]
    fn failure_waits_six_hours_but_manual_retry_is_available() {
        let (dir, monitor) = fixture();
        assert!(monitor.begin_check(100_000, false));
        assert!(!monitor.begin_check(100_001, true)); // concurrent check
        monitor.fail("offline");
        assert!(!monitor.begin_check(100_001, false));
        assert!(monitor.begin_check(100_001, true));
        monitor.fail("offline");
        monitor.installing.store(true, Ordering::SeqCst);
        assert!(!monitor.begin_check(200_000, true));
        std::fs::remove_dir_all(dir).unwrap();
    }
    #[test]
    fn corrupted_schedule_recovers_without_blocking_updates() {
        let (dir, _) = fixture();
        std::fs::write(dir.join("update-check.json"), b"invalid").unwrap();
        let monitor = Monitor::new(&dir, false, Arc::new(AtomicBool::new(false)));
        assert!(monitor.begin_check(100_000, false));
        assert!(!monitor.installing.load(Ordering::SeqCst));
        std::fs::remove_dir_all(dir).unwrap();
    }
}
