use crate::account::Fault;
use serde::Serialize;
use tauri::{
    menu::{Menu, MenuItem, PredefinedMenuItem},
    tray::{MouseButton, TrayIconBuilder, TrayIconEvent},
    AppHandle, Manager, State,
};
use tauri_plugin_autostart::ManagerExt;
use tokio::sync::Mutex;

pub const AUTOSTART_ARG: &str = "--autostart";

pub struct DesktopState {
    tray_available: bool,
    autostart_lock: Mutex<()>,
}

#[derive(Serialize)]
pub struct DesktopView {
    autostart_enabled: bool,
    background_available: bool,
}

pub fn show_main(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    }
}

// A login launch must not raise an already running app; manual launches must.
fn should_show(args: impl Iterator<Item = String>, tray_available: bool) -> bool {
    !tray_available || !args.skip(1).any(|arg| arg == AUTOSTART_ARG)
}

pub fn activate(app: &AppHandle, args: impl Iterator<Item = String>) {
    let tray_available = app
        .try_state::<DesktopState>()
        .is_some_and(|state| state.tray_available);
    if should_show(args, tray_available) {
        show_main(app);
    }
}

pub fn close_window(window: &tauri::Window) {
    let app = window.app_handle();
    if app
        .try_state::<DesktopState>()
        .is_some_and(|state| state.tray_available)
    {
        let _ = window.hide();
    } else {
        // Without a tray, preserve the existing recover-proxy-and-exit path.
        app.exit(0);
    }
}

fn create_tray(app: &AppHandle) -> tauri::Result<()> {
    let open = MenuItem::with_id(app, "desktop_open", "打开卡皮巴拉", true, None::<&str>)?;
    let separator = PredefinedMenuItem::separator(app)?;
    let quit = MenuItem::with_id(app, "desktop_quit", "退出卡皮巴拉", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&open, &separator, &quit])?;
    let mut tray = TrayIconBuilder::with_id("capybara")
        .tooltip("卡皮巴拉 · 后台运行")
        .menu(&menu)
        .show_menu_on_left_click(true)
        .on_menu_event(|app, event| match event.id.as_ref() {
            "desktop_open" => show_main(app),
            "desktop_quit" => {
                if crate::updates::prevent_exit(app) {
                    show_main(app);
                } else {
                    app.exit(0);
                }
            }
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if matches!(
                event,
                TrayIconEvent::DoubleClick {
                    button: MouseButton::Left,
                    ..
                }
            ) {
                show_main(tray.app_handle());
            }
        });
    if let Some(icon) = app.default_window_icon() {
        tray = tray.icon(icon.clone());
    }
    tray.build(app)?;
    Ok(())
}

pub fn setup(app: &AppHandle) {
    app.manage(DesktopState {
        tray_available: create_tray(app).is_ok(),
        autostart_lock: Mutex::new(()),
    });
}

fn read_settings(app: &AppHandle, state: &DesktopState) -> Result<DesktopView, Fault> {
    Ok(DesktopView {
        autostart_enabled: app
            .autolaunch()
            .is_enabled()
            .map_err(|_| Fault::local("无法读取系统自启设置，请重试"))?,
        background_available: state.tray_available,
    })
}

#[tauri::command]
pub async fn desktop_settings(
    app: AppHandle,
    state: State<'_, DesktopState>,
) -> Result<DesktopView, Fault> {
    let _guard = state.autostart_lock.lock().await;
    read_settings(&app, &state)
}

#[tauri::command]
pub async fn set_autostart(
    app: AppHandle,
    state: State<'_, DesktopState>,
    enabled: bool,
) -> Result<DesktopView, Fault> {
    let _guard = state.autostart_lock.lock().await;
    let manager = app.autolaunch();
    if enabled {
        manager.enable()
    } else {
        manager.disable()
    }
    .map_err(|_| Fault::local("无法更改开机自启，请检查系统的登录项设置后重试"))?;
    let settings = read_settings(&app, &state)?;
    if settings.autostart_enabled != enabled {
        return Err(Fault::local("系统未应用自启设置，请检查登录项后重试"));
    }
    Ok(settings)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn login_launch_hides_only_with_tray_and_manual_relaunch_always_shows() {
        let args = |values: &[&str]| values.iter().map(|s| s.to_string()).collect::<Vec<_>>();
        assert!(!should_show(
            args(&["app", "--autostart"]).into_iter(),
            true
        ));
        assert!(should_show(args(&["app"]).into_iter(), true));
        assert!(should_show(
            args(&["app", "--autostart"]).into_iter(),
            false
        ));
        assert!(should_show(
            args(&["app", "--autostart=false"]).into_iter(),
            true
        ));
    }
}
