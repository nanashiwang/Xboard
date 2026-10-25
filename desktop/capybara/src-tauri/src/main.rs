#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
mod account;
mod credentials;
mod engine;
mod proxy;
mod updates;
use account::{Account, BrowserSession, Fault};
use engine::{Engine, Route};
use serde::Serialize;
use serde_json::Value;
use std::{
    io::Write,
    path::{Path, PathBuf},
    sync::Arc,
    time::{Duration, SystemTime, UNIX_EPOCH},
};
use tauri::{Manager, State};
use tokio::sync::Mutex;

pub fn private_write(path: &Path, content: &[u8]) -> Result<(), String> {
    let temporary = path.with_extension("tmp");
    let mut options = std::fs::OpenOptions::new();
    options.create(true).truncate(true).write(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options.open(&temporary).map_err(|_| "无法写入应用数据")?;
    file.write_all(content).map_err(|_| "应用数据写入失败")?;
    file.sync_all().map_err(|_| "应用数据保存失败")?;
    drop(file);
    // Windows rename cannot replace an existing file. The temp file remains private.
    #[cfg(windows)]
    if path.exists() {
        std::fs::remove_file(path).map_err(|_| "无法替换应用数据")?;
    }
    std::fs::rename(temporary, path).map_err(|_| "无法保存应用数据".into())
}
fn now() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}
#[derive(Clone, Serialize)]
struct BrowserView {
    phase: String,
    expires_at: Option<u64>,
    error: Option<String>,
}
#[derive(Clone, Serialize)]
struct View {
    logged_in: bool,
    session_needs_unlock: bool,
    browser_login: Option<BrowserView>,
    profile: Option<Value>,
    subscription: Option<Value>,
    synced_at: Option<u64>,
    sync_error: Option<String>,
    connection: String,
    connection_error: Option<String>,
    routes: Vec<Route>,
    version: String,
    platform: String,
}
impl Default for View {
    fn default() -> Self {
        Self {
            logged_in: false,
            session_needs_unlock: false,
            browser_login: None,
            profile: None,
            subscription: None,
            synced_at: None,
            sync_error: None,
            connection: "disconnected".into(),
            connection_error: None,
            routes: vec![],
            version: account::VERSION.into(),
            platform: account::platform().into(),
        }
    }
}
struct Runtime {
    account: Account,
    browser_attempt: Option<String>,
    browser_session: Option<BrowserSession>,
    engine: Option<Engine>,
    dir: PathBuf,
    binary: PathBuf,
    view: View,
    config_synced: Option<std::time::Instant>,
    app: tauri::AppHandle,
    installing: Arc<std::sync::atomic::AtomicBool>,
}
impl Runtime {
    async fn sync(&mut self) -> Result<(), Fault> {
        self.view.logged_in = self.account.logged_in();
        if !self.account.logged_in() {
            return Ok(());
        }
        let result = self.account.get("user/subscription").await;
        match result {
            Ok(subscription) => {
                let active = subscription["status"] == "active";
                let previous_active = self
                    .view
                    .subscription
                    .as_ref()
                    .is_some_and(|s| s["status"] == "active");
                if previous_active && !active {
                    use tauri_plugin_notification::NotificationExt;
                    let message = match subscription["status"].as_str() {
                        Some("traffic_exhausted") => {
                            "本期流量已用完，连接已暂停。打开卡皮巴拉查看重置时间或续费。"
                        }
                        Some("expired") => "套餐已到期，连接已暂停。续费后即可重新连接。",
                        _ => "套餐状态发生变化，请打开卡皮巴拉查看。",
                    };
                    let _ = self
                        .app
                        .notification()
                        .builder()
                        .title("卡皮巴拉 · 套餐提醒")
                        .body(message)
                        .show();
                }
                self.view.subscription = Some(subscription);
                self.view.synced_at = Some(now());
                self.view.sync_error = None;
                if !active && self.engine.is_some() {
                    self.disconnect()?;
                }
                if active
                    && self
                        .config_synced
                        .is_some_and(|t| t.elapsed() >= Duration::from_secs(3600))
                {
                    if let Some(engine) = self.engine.as_ref() {
                        // Keep status polling independent of hourly node refresh.
                        let result = match self.account.config().await {
                            Ok(content) => engine.reload(&content).await.map_err(Fault::from),
                            Err(error) => Err(error),
                        };
                        match result {
                            Ok(()) => {
                                self.config_synced = Some(std::time::Instant::now());
                                self.view.routes = engine.routes().await.unwrap_or_default();
                            }
                            Err(_) => {
                                self.view.connection_error = Some(
                                    "线路更新暂时失败，继续使用上次配置；稍后会自动重试".into(),
                                )
                            }
                        }
                    }
                }
                if self.view.profile.is_none() {
                    self.view.profile = self.account.get("user/profile").await.ok();
                }
                Ok(())
            }
            Err(e) => {
                self.view.logged_in = self.account.logged_in();
                self.view.sync_error = Some(e.message.clone());
                if !self.view.logged_in {
                    let _ = self.disconnect();
                    self.view.profile = None;
                    self.view.subscription = None;
                    self.view.synced_at = None;
                }
                Err(e)
            }
        }
    }
    fn disconnect(&mut self) -> Result<(), Fault> {
        let result = if let Some(mut engine) = self.engine.take() {
            engine.stop()
        } else {
            proxy::recover(&self.dir)
        };
        self.view.connection = "disconnected".into();
        self.view.routes.clear();
        self.view.connection_error = result.as_ref().err().cloned();
        result.map_err(Fault::from)
    }
    fn check_process(&mut self) {
        if self.engine.as_mut().is_some_and(|e| !e.alive()) {
            let _ = self.disconnect();
            self.view
                .connection_error
                .get_or_insert("连接组件已退出，系统代理已尝试恢复，请重新连接".into());
        }
    }
}
struct AppState(Arc<Mutex<Runtime>>);
#[tauri::command]
async fn snapshot(state: State<'_, AppState>) -> Result<View, Fault> {
    let mut rt = state.0.lock().await;
    rt.check_process();
    Ok(rt.view.clone())
}
// Network waits stay outside Runtime's lock so cancel and UI snapshots remain responsive.
async fn browser_login_job(
    state: Arc<Mutex<Runtime>>,
    attempt: String,
    mut session: BrowserSession,
) {
    let result = session.start().await;
    {
        let mut rt = state.lock().await;
        if rt.browser_attempt.as_deref() != Some(&attempt) {
            drop(rt);
            if result.is_ok() {
                session.cancel().await;
            }
            return;
        }
        if let Err(error) = result {
            rt.browser_attempt = None;
            rt.view.browser_login = Some(BrowserView {
                phase: "error".into(),
                expires_at: None,
                error: Some(error.message),
            });
            return;
        }
        rt.browser_session = Some(session.clone());
        use tauri_plugin_opener::OpenerExt;
        let error = rt
            .app
            .opener()
            .open_url(session.url(), None::<&str>)
            .err()
            .map(|_| "浏览器未能打开，请点击“重新打开浏览器”".into());
        rt.view.browser_login = Some(BrowserView {
            phase: "waiting".into(),
            expires_at: Some(now() + session.remaining()),
            error,
        });
    }
    loop {
        tokio::time::sleep(Duration::from_secs(3)).await;
        if state.lock().await.browser_attempt.as_deref() != Some(&attempt) {
            return;
        }
        let result = session.poll().await;
        let mut rt = state.lock().await;
        if rt.browser_attempt.as_deref() != Some(&attempt) {
            drop(rt);
            if let Ok(Some(tokens)) = result {
                session.discard(&tokens).await;
            }
            return;
        }
        match result {
            Ok(None) => continue,
            Ok(Some(tokens)) => {
                rt.browser_attempt = None;
                rt.browser_session = None;
                match rt
                    .account
                    .save_tokens(tokens, credentials::Access::UserInitiated)
                    .await
                {
                    Ok(()) => {
                        rt.view = View::default();
                        rt.view.logged_in = true;
                        let _ = rt.sync().await;
                        if let Some(window) = rt.app.get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                    }
                    Err(error) => {
                        rt.view.browser_login = Some(BrowserView {
                            phase: "error".into(),
                            expires_at: None,
                            error: Some(error.message),
                        });
                    }
                }
                return;
            }
            Err(error) => {
                rt.browser_attempt = None;
                rt.browser_session = None;
                rt.view.browser_login = Some(BrowserView {
                    phase: "error".into(),
                    expires_at: None,
                    error: Some(error.message),
                });
                drop(rt);
                // Do not retry an ambiguous exchange: the server may have already consumed it.
                session.cancel().await;
                return;
            }
        }
    }
}
#[tauri::command]
async fn begin_browser_login(state: State<'_, AppState>) -> Result<View, Fault> {
    let mut rt = state.0.lock().await;
    if rt.browser_attempt.is_some() {
        return Ok(rt.view.clone());
    }
    let session = rt.account.browser_session()?;
    let attempt = uuid::Uuid::new_v4().to_string();
    rt.browser_attempt = Some(attempt.clone());
    rt.view.browser_login = Some(BrowserView {
        phase: "starting".into(),
        expires_at: None,
        error: None,
    });
    tauri::async_runtime::spawn(browser_login_job(state.0.clone(), attempt, session));
    Ok(rt.view.clone())
}
#[tauri::command]
async fn cancel_browser_login(state: State<'_, AppState>) -> Result<View, Fault> {
    let mut rt = state.0.lock().await;
    rt.browser_attempt = None;
    rt.view.browser_login = None;
    if let Some(session) = rt.browser_session.take() {
        tauri::async_runtime::spawn(async move {
            session.cancel().await;
        });
    }
    Ok(rt.view.clone())
}
#[tauri::command]
async fn reopen_browser_login(state: State<'_, AppState>) -> Result<View, Fault> {
    use tauri_plugin_opener::OpenerExt;
    let mut rt = state.0.lock().await;
    let session = rt
        .browser_session
        .as_ref()
        .ok_or_else(|| Fault::local("请重新发起登录"))?;
    rt.app
        .opener()
        .open_url(session.url(), None::<&str>)
        .map_err(|_| Fault::local("无法打开浏览器，请检查默认浏览器设置"))?;
    if let Some(view) = rt.view.browser_login.as_mut() {
        view.error = None;
    }
    Ok(rt.view.clone())
}
#[tauri::command]
async fn restore_session(state: State<'_, AppState>) -> Result<View, Fault> {
    let mut rt = state.0.lock().await;
    if rt.browser_attempt.is_some() {
        return Err(Fault::local("请先完成或取消浏览器登录"));
    }
    match rt.account.resume(credentials::Access::UserInitiated) {
        Ok(saved) => {
            rt.view.session_needs_unlock = false;
            rt.view.sync_error = None;
            rt.view.logged_in = saved;
            let _ = rt.sync().await;
            Ok(rt.view.clone())
        }
        Err(e) => {
            rt.view.session_needs_unlock = e.code == "CREDENTIALS_LOCKED";
            rt.view.sync_error = Some(e.message.clone());
            Err(e)
        }
    }
}
#[tauri::command]
async fn refresh(state: State<'_, AppState>) -> Result<View, Fault> {
    let mut rt = state.0.lock().await;
    rt.sync().await?;
    Ok(rt.view.clone())
}
#[tauri::command]
async fn logout(state: State<'_, AppState>) -> Result<View, Fault> {
    let mut rt = state.0.lock().await;
    rt.disconnect()?;
    rt.account.logout().await?;
    rt.view = View::default();
    Ok(rt.view.clone())
}
#[tauri::command]
async fn connect(state: State<'_, AppState>) -> Result<View, Fault> {
    let mut rt = state.0.lock().await;
    if rt.installing.load(std::sync::atomic::Ordering::SeqCst) {
        return Err(Fault::local("正在更新，请稍候再连接"));
    }
    if rt.engine.is_some() {
        return Ok(rt.view.clone());
    }
    rt.sync().await?;
    if rt
        .view
        .subscription
        .as_ref()
        .is_none_or(|s| s["status"] != "active")
    {
        return Err(Fault::local("当前套餐不可用，请查看首页提示"));
    }
    let content = rt.account.config().await?;
    let engine = match Engine::start(&rt.dir, rt.binary.clone(), &content).await {
        Ok(e) => e,
        Err(e) => {
            rt.view.connection_error = Some(e.clone());
            return Err(e.into());
        }
    };
    rt.view.connection = "connected".into();
    rt.view.connection_error = engine.check().await.err();
    rt.view.routes = engine.routes().await.unwrap_or_default();
    rt.engine = Some(engine);
    rt.config_synced = Some(std::time::Instant::now());
    if rt.view.connection_error.is_some() {
        let _ = rt.sync().await;
    }
    Ok(rt.view.clone())
}
#[tauri::command]
async fn disconnect(state: State<'_, AppState>) -> Result<View, Fault> {
    let mut rt = state.0.lock().await;
    rt.disconnect()?;
    Ok(rt.view.clone())
}
#[tauri::command]
async fn select_route(
    state: State<'_, AppState>,
    group: String,
    name: String,
) -> Result<View, Fault> {
    let mut rt = state.0.lock().await;
    let engine = rt
        .engine
        .as_ref()
        .ok_or_else(|| Fault::local("请先连接，再切换线路"))?;
    engine.select(&group, &name).await?;
    let error = engine.check().await.err();
    let routes = engine.routes().await?;
    rt.view.connection_error = error;
    rt.view.routes = routes;
    if rt.view.connection_error.is_some() {
        let _ = rt.sync().await;
    }
    Ok(rt.view.clone())
}
#[tauri::command]
async fn check_connection(state: State<'_, AppState>) -> Result<View, Fault> {
    let mut rt = state.0.lock().await;
    rt.view.connection_error = rt
        .engine
        .as_ref()
        .ok_or_else(|| Fault::local("请先连接"))?
        .check()
        .await
        .err();
    let _ = rt.sync().await;
    Ok(rt.view.clone())
}
#[tauri::command]
fn open_link(app: tauri::AppHandle, target: String) -> Result<(), Fault> {
    use tauri_plugin_opener::OpenerExt;
    let url = match target.as_str() {
        "account" => "https://taige.us/#/dashboard",
        "support" => "https://taige.us/#/ticket",
        "register" => "https://taige.us/#/register",
        "releases" => "https://github.com/nanashiwang/Xboard/releases?q=capybara",
        _ => return Err(Fault::local("不支持的链接")),
    };
    app.opener()
        .open_url(url, None::<&str>)
        .map_err(|_| Fault::local("无法打开浏览器，请访问 taige.us"))
}
fn main() {
    if std::env::args().nth(1).as_deref() == Some("--capybara-engine") {
        std::process::exit(engine::worker_main())
    }
    let builder = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _, _| {
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.show();
                let _ = w.set_focus();
            }
        }))
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                window.app_handle().exit(0);
            }
        })
        .setup(|app| {
            let dir = app.path().app_data_dir()?;
            std::fs::create_dir_all(&dir)?;
            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                std::fs::set_permissions(&dir, std::fs::Permissions::from_mode(0o700))?;
            }
            let data_source = if cfg!(debug_assertions) {
                PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("resources/geoip.metadb")
            } else {
                app.path().resource_dir()?.join("geoip.metadb")
            };
            let data = std::fs::read(data_source)?;
            use sha2::{Digest, Sha256};
            if format!("{:x}", Sha256::digest(&data))
                != "646d077cc2b43a8abf1b853006f0ac29f03263a1656ba8c247aa621ebcf94c66"
            {
                return Err("地理规则数据校验失败，请重新安装完整客户端".into());
            }
            private_write(&dir.join("geoip.metadb"), &data).map_err(std::io::Error::other)?;
            let mut view = View {
                connection_error: proxy::recover(&dir).err(),
                ..View::default()
            };
            let mut account = Account::new(&dir).map_err(std::io::Error::other)?;
            match account.resume(credentials::Access::Background) {
                Ok(saved) => view.logged_in = saved,
                Err(e) => {
                    view.session_needs_unlock = e.code == "CREDENTIALS_LOCKED";
                    view.sync_error = Some(e.message);
                }
            }
            let binary = if cfg!(debug_assertions) {
                PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                    .join("binaries")
                    .join(format!(
                        "mihomo-{}{}",
                        host_target(),
                        if cfg!(windows) { ".exe" } else { "" }
                    ))
            } else {
                std::env::current_exe()?
                    .parent()
                    .ok_or("无法定位内核")?
                    .join(if cfg!(windows) {
                        "mihomo.exe"
                    } else {
                        "mihomo"
                    })
            };
            let installing = Arc::new(std::sync::atomic::AtomicBool::new(false));
            updates::start(app.handle(), &dir, installing.clone());
            let state = Arc::new(Mutex::new(Runtime {
                account,
                browser_attempt: None,
                browser_session: None,
                engine: None,
                dir,
                binary,
                view,
                config_synced: None,
                installing,
                app: app.handle().clone(),
            }));
            app.manage(AppState(state.clone()));
            tauri::async_runtime::spawn(async move {
                let mut ticks = tokio::time::interval(Duration::from_secs(30));
                ticks.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
                loop {
                    ticks.tick().await;
                    let mut rt = state.lock().await;
                    rt.check_process();
                    let _ = rt.sync().await;
                }
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            snapshot,
            begin_browser_login,
            cancel_browser_login,
            reopen_browser_login,
            restore_session,
            refresh,
            logout,
            connect,
            disconnect,
            select_route,
            check_connection,
            open_link,
            updates::update_snapshot,
            updates::check_updates,
            updates::dismiss_update,
            updates::install_update
        ]);
    let app = builder
        .build(tauri::generate_context!())
        .expect("卡皮巴拉初始化失败");
    let exiting = Arc::new(std::sync::atomic::AtomicU8::new(0));
    app.run(move |handle, event| {
        if let tauri::RunEvent::ExitRequested { api, .. } = event {
            if updates::prevent_exit(handle) {
                api.prevent_exit();
                return;
            }
            use std::sync::atomic::Ordering;
            if exiting.load(Ordering::SeqCst) == 2 {
                return;
            }
            api.prevent_exit();
            if exiting
                .compare_exchange(0, 1, Ordering::SeqCst, Ordering::SeqCst)
                .is_err()
            {
                return;
            }
            let state = handle.state::<AppState>().0.clone();
            let app = handle.clone();
            let flag = exiting.clone();
            tauri::async_runtime::spawn(async move {
                let mut rt = state.lock().await;
                if rt.disconnect().is_ok() {
                    flag.store(2, Ordering::SeqCst);
                    app.exit(0);
                } else {
                    flag.store(0, Ordering::SeqCst);
                    if let Some(window) = app.get_webview_window("main") {
                        let _ = window.show();
                        let _ = window.set_focus();
                    }
                }
            });
        }
    });
}
fn host_target() -> &'static str {
    if cfg!(target_os = "macos") {
        if cfg!(target_arch = "aarch64") {
            "aarch64-apple-darwin"
        } else {
            "x86_64-apple-darwin"
        }
    } else if cfg!(target_os = "windows") {
        if cfg!(target_arch = "aarch64") {
            "aarch64-pc-windows-msvc"
        } else {
            "x86_64-pc-windows-msvc"
        }
    } else if cfg!(target_arch = "aarch64") {
        "aarch64-unknown-linux-gnu"
    } else {
        "x86_64-unknown-linux-gnu"
    }
}
