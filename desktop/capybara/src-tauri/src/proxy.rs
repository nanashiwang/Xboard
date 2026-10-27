use serde::{Deserialize, Serialize};
use std::path::Path;
#[cfg(not(target_os = "windows"))]
use std::process::Command;

#[derive(Clone, Serialize, Deserialize)]
pub struct Snapshot {
    pub port: u16,
    pub original: serde_json::Value,
}
fn journal(dir: &Path) -> std::path::PathBuf {
    dir.join("proxy-recovery.json")
}
pub fn enable(dir: &Path, port: u16) -> Result<(), String> {
    if journal(dir).exists() {
        recover(dir)?;
    }
    let snapshot = Snapshot {
        port,
        original: platform::capture()?,
    };
    crate::private_write(
        &journal(dir),
        &serde_json::to_vec(&snapshot).map_err(|_| "无法保存代理恢复记录")?,
    )?;
    if let Err(e) = platform::apply(&snapshot) {
        let restored = recover(dir);
        return Err(if restored.is_err() {
            format!("{e}；代理恢复未完成，请重启卡皮巴拉修复")
        } else {
            e
        });
    }
    Ok(())
}
pub fn recover(dir: &Path) -> Result<(), String> {
    let file = journal(dir);
    if !file.exists() {
        return Ok(());
    }
    let snapshot: Snapshot =
        serde_json::from_slice(&std::fs::read(&file).map_err(|_| "无法读取代理恢复记录")?)
            .map_err(|_| "代理恢复记录损坏")?;
    platform::restore(&snapshot)?;
    std::fs::remove_file(file).map_err(|_| "无法清除代理恢复记录".into())
}
#[cfg(any(target_os = "windows", test))]
fn windows_server(port: u16) -> String {
    // The mixed listener accepts HTTP CONNECT for HTTPS destinations. A single address
    // also works with native clients whose system matcher cannot parse Windows' map syntax.
    format!("127.0.0.1:{port}")
}
#[cfg(any(target_os = "windows", test))]
fn windows_owns_server(value: &str, port: u16) -> bool {
    value == windows_server(port)
        // A recovery journal can survive an upgrade from the old mapped representation.
        || value == format!("http=127.0.0.1:{port};https=127.0.0.1:{port};socks=127.0.0.1:{port}")
}
#[cfg(not(target_os = "windows"))]
fn run(program: &str, args: &[&str]) -> Result<String, String> {
    let output = Command::new(program)
        .args(args)
        .env("LC_ALL", "C")
        .output()
        .map_err(|_| format!("无法运行 {program}，请检查系统组件"))?;
    if !output.status.success() {
        return Err(format!("{program} 操作失败，请检查系统代理权限"));
    }
    let text = String::from_utf8_lossy(&output.stdout).trim().to_string();
    if text.starts_with("** Error") || text.contains("not a recognized network service") {
        return Err("系统代理设置失败，请检查网络服务".into());
    }
    Ok(text)
}

#[cfg(target_os = "macos")]
mod platform {
    use super::*;
    #[derive(Clone, Serialize, Deserialize)]
    struct Item {
        service: String,
        kind: String,
        host: String,
        port: u16,
    }
    fn field<'a>(text: &'a str, key: &str) -> &'a str {
        text.lines()
            .find_map(|s| s.strip_prefix(key))
            .unwrap_or("")
            .trim()
    }
    fn get(service: &str, kind: &str) -> Result<String, String> {
        run("/usr/sbin/networksetup", &[&format!("-get{kind}"), service])
    }
    pub fn capture() -> Result<serde_json::Value, String> {
        let services = run("/usr/sbin/networksetup", &["-listallnetworkservices"])?;
        let mut items = vec![];
        for service in services
            .lines()
            .skip(1)
            .filter(|s| !s.starts_with('*') && !s.is_empty())
        {
            if field(&get(service, "autoproxyurl")?, "Enabled:") == "Yes"
                || get(service, "proxyautodiscovery")?.contains("On")
            {
                return Err("请先关闭系统自动代理或其他代理客户端，再连接卡皮巴拉".into());
            }
            for kind in ["webproxy", "securewebproxy", "socksfirewallproxy"] {
                let raw = get(service, kind)?;
                if field(&raw, "Enabled:") == "Yes"
                    || field(&raw, "Authenticated Proxy Enabled:") == "1"
                {
                    return Err(
                        "检测到已有代理配置，请先关闭其他代理客户端；认证代理请使用系统设置切换"
                            .into(),
                    );
                }
                items.push(Item {
                    service: service.into(),
                    kind: kind.into(),
                    host: field(&raw, "Server:").into(),
                    port: field(&raw, "Port:").parse().unwrap_or(0),
                });
            }
        }
        if items.is_empty() {
            return Err("没有可用的网络服务".into());
        }
        serde_json::to_value(items).map_err(|_| "无法保存网络状态".into())
    }
    fn items(s: &Snapshot) -> Result<Vec<Item>, String> {
        serde_json::from_value(s.original.clone()).map_err(|_| "网络恢复记录无效".into())
    }
    pub fn apply(s: &Snapshot) -> Result<(), String> {
        for item in items(s)? {
            run(
                "/usr/sbin/networksetup",
                &[
                    &format!("-set{}", item.kind),
                    &item.service,
                    "127.0.0.1",
                    &s.port.to_string(),
                ],
            )?;
            run(
                "/usr/sbin/networksetup",
                &[&format!("-set{}state", item.kind), &item.service, "on"],
            )?;
            let raw = get(&item.service, &item.kind)?;
            if field(&raw, "Enabled:") != "Yes"
                || field(&raw, "Server:") != "127.0.0.1"
                || field(&raw, "Port:") != s.port.to_string()
            {
                return Err("系统没有应用代理设置，请检查权限".into());
            }
        }
        Ok(())
    }
    pub fn restore(s: &Snapshot) -> Result<(), String> {
        let mut failed = false;
        for item in items(s)? {
            let result = (|| -> Result<(), String> {
                let raw = get(&item.service, &item.kind)?;
                if field(&raw, "Server:") != "127.0.0.1"
                    || field(&raw, "Port:") != s.port.to_string()
                {
                    return Ok(());
                }
                run(
                    "/usr/sbin/networksetup",
                    &[&format!("-set{}state", item.kind), &item.service, "off"],
                )?;
                run(
                    "/usr/sbin/networksetup",
                    &[
                        &format!("-set{}", item.kind),
                        &item.service,
                        &item.host,
                        &item.port.to_string(),
                    ],
                )?;
                // networksetup's set operation may enable it again.
                run(
                    "/usr/sbin/networksetup",
                    &[&format!("-set{}state", item.kind), &item.service, "off"],
                )?;
                Ok(())
            })();
            if result.is_err() {
                failed = true
            }
        }
        if failed {
            Err("系统代理恢复失败，请在网络设置中关闭 127.0.0.1 代理后重试".into())
        } else {
            Ok(())
        }
    }
}

#[cfg(target_os = "linux")]
mod platform {
    use super::*;
    fn get(schema: &str, key: &str) -> Result<String, String> {
        run("gsettings", &["get", schema, key])
    }
    fn set(schema: &str, key: &str, value: &str) -> Result<(), String> {
        run("gsettings", &["set", schema, key, value])?;
        if get(schema, key)? != value {
            return Err("GNOME 代理设置未生效，请检查桌面会话".into());
        }
        Ok(())
    }
    pub fn capture() -> Result<serde_json::Value, String> {
        if get("org.gnome.system.proxy", "mode")? != "'none'" {
            return Err("请先关闭其他系统代理，再连接卡皮巴拉".into());
        }
        let mut values = serde_json::Map::new();
        for protocol in ["http", "https", "socks"] {
            let schema = format!("org.gnome.system.proxy.{protocol}");
            if protocol == "http" && get(&schema, "use-authentication")? == "true" {
                return Err("系统认证代理需要先在设置中关闭".into());
            }
            values.insert(
                protocol.into(),
                serde_json::json!({"host":get(&schema,"host")?,"port":get(&schema,"port")?}),
            );
        }
        values.insert(
            "use-same-proxy".into(),
            serde_json::json!(get("org.gnome.system.proxy", "use-same-proxy")?),
        );
        Ok(values.into())
    }
    pub fn apply(s: &Snapshot) -> Result<(), String> {
        for protocol in ["http", "https", "socks"] {
            let schema = format!("org.gnome.system.proxy.{protocol}");
            set(&schema, "host", "'127.0.0.1'")?;
            set(&schema, "port", &s.port.to_string())?;
        }
        set("org.gnome.system.proxy", "use-same-proxy", "true")?;
        set("org.gnome.system.proxy", "mode", "'manual'")
    }
    pub fn restore(s: &Snapshot) -> Result<(), String> {
        let mut owned = false;
        for protocol in ["http", "https", "socks"] {
            let schema = format!("org.gnome.system.proxy.{protocol}");
            if get(&schema, "host")? == "'127.0.0.1'" && get(&schema, "port")? == s.port.to_string()
            {
                owned = true;
            }
        }
        if !owned {
            return Ok(());
        }
        if get("org.gnome.system.proxy", "mode")? == "'manual'" {
            set("org.gnome.system.proxy", "mode", "'none'")?;
        }
        for protocol in ["http", "https", "socks"] {
            let schema = format!("org.gnome.system.proxy.{protocol}");
            if get(&schema, "host")? == "'127.0.0.1'" && get(&schema, "port")? == s.port.to_string()
            {
                set(
                    &schema,
                    "host",
                    s.original[protocol]["host"]
                        .as_str()
                        .ok_or("代理恢复记录无效")?,
                )?;
                set(
                    &schema,
                    "port",
                    s.original[protocol]["port"]
                        .as_str()
                        .ok_or("代理恢复记录无效")?,
                )?;
            }
        }
        set(
            "org.gnome.system.proxy",
            "use-same-proxy",
            s.original["use-same-proxy"]
                .as_str()
                .ok_or("代理恢复记录无效")?,
        )
    }
}

#[cfg(target_os = "windows")]
mod platform {
    use super::*;
    use winreg::{enums::*, RegKey, RegValue};
    const KEY: &str = "Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings";
    const NAMES: [&str; 4] = ["ProxyEnable", "ProxyServer", "AutoConfigURL", "AutoDetect"];
    fn key() -> Result<RegKey, String> {
        RegKey::predef(HKEY_CURRENT_USER)
            .open_subkey_with_flags(KEY, KEY_READ | KEY_WRITE)
            .map_err(|_| "无法读取 Windows 代理设置".into())
    }
    fn notify() {
        unsafe {
            use windows_sys::Win32::Networking::WinInet::*;
            InternetSetOptionW(
                std::ptr::null_mut(),
                INTERNET_OPTION_SETTINGS_CHANGED,
                std::ptr::null(),
                0,
            );
            InternetSetOptionW(
                std::ptr::null_mut(),
                INTERNET_OPTION_REFRESH,
                std::ptr::null(),
                0,
            );
        }
    }
    pub fn capture() -> Result<serde_json::Value, String> {
        let k = key()?;
        capture_from(&k)
    }
    fn capture_from(k: &RegKey) -> Result<serde_json::Value, String> {
        if k.get_value::<u32, _>("ProxyEnable").unwrap_or(0) != 0
            || !k
                .get_value::<String, _>("AutoConfigURL")
                .unwrap_or_default()
                .is_empty()
        {
            return Err("请先关闭其他系统代理或自动代理，再连接卡皮巴拉".into());
        }
        let mut values = serde_json::Map::new();
        for name in NAMES {
            let v = k.get_raw_value(name).ok();
            values.insert(
                name.into(),
                v.map(|v| serde_json::json!({"bytes":v.bytes,"type":v.vtype as u32}))
                    .unwrap_or(serde_json::Value::Null),
            );
        }
        Ok(values.into())
    }
    pub fn apply(s: &Snapshot) -> Result<(), String> {
        let k = key()?;
        apply_to(&k, s)?;
        notify();
        Ok(())
    }
    fn apply_to(k: &RegKey, s: &Snapshot) -> Result<(), String> {
        k.set_value("ProxyServer", &windows_server(s.port))
            .map_err(|_| "无法设置代理地址")?;
        k.set_value("AutoDetect", &0u32)
            .map_err(|_| "无法关闭自动代理检测")?;
        k.set_value("ProxyEnable", &1u32)
            .map_err(|_| "无法启用系统代理")?;
        Ok(())
    }
    pub fn restore(s: &Snapshot) -> Result<(), String> {
        let k = key()?;
        if restore_to(&k, s)? {
            notify();
        }
        Ok(())
    }
    fn restore_to(k: &RegKey, s: &Snapshot) -> Result<bool, String> {
        if !windows_owns_server(
            &k.get_value::<String, _>("ProxyServer").unwrap_or_default(),
            s.port,
        ) {
            return Ok(false);
        }
        for name in NAMES {
            let v = &s.original[name];
            if v.is_null() {
                match k.delete_value(name) {
                    Ok(()) => {}
                    Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
                    Err(_) => return Err("无法恢复 Windows 代理".into()),
                }
            } else {
                let bytes: Vec<u8> =
                    serde_json::from_value(v["bytes"].clone()).map_err(|_| "代理恢复记录无效")?;
                let vtype = match v["type"].as_u64() {
                    Some(1) => REG_SZ,
                    Some(2) => REG_EXPAND_SZ,
                    Some(3) => REG_BINARY,
                    Some(4) => REG_DWORD,
                    _ => return Err("代理恢复记录类型不支持".into()),
                };
                k.set_raw_value(name, &RegValue { bytes, vtype })
                    .map_err(|_| "无法恢复 Windows 代理")?;
            }
        }
        Ok(true)
    }

    #[cfg(test)]
    mod tests {
        use super::*;

        struct RegistryFixture {
            path: String,
            key: RegKey,
        }
        impl RegistryFixture {
            fn new() -> Self {
                let path = format!("Software\\CapybaraProxyTests-{}", uuid::Uuid::new_v4());
                let (key, _) = RegKey::predef(HKEY_CURRENT_USER)
                    .create_subkey(&path)
                    .unwrap();
                Self { path, key }
            }
        }
        impl Drop for RegistryFixture {
            fn drop(&mut self) {
                let _ = RegKey::predef(HKEY_CURRENT_USER).delete_subkey_all(&self.path);
            }
        }

        #[test]
        fn windows_registry_round_trip_restores_original_raw_values() {
            let fixture = RegistryFixture::new();
            let k = &fixture.key;
            k.set_value("ProxyEnable", &0u32).unwrap();
            k.set_value("AutoDetect", &1u32).unwrap();
            k.set_value("ProxyServer", &"old.proxy.example:8080")
                .unwrap();
            k.set_value("ProxyOverride", &"localhost;<local>").unwrap();
            let original = capture_from(k).unwrap();
            let snapshot = Snapshot {
                port: 32198,
                original: original.clone(),
            };
            apply_to(k, &snapshot).unwrap();
            assert_eq!(
                k.get_value::<String, _>("ProxyServer").unwrap(),
                "127.0.0.1:32198"
            );
            assert_eq!(k.get_value::<u32, _>("ProxyEnable").unwrap(), 1);
            assert_eq!(k.get_value::<u32, _>("AutoDetect").unwrap(), 0);
            assert!(restore_to(k, &snapshot).unwrap());
            assert_eq!(capture_from(k).unwrap(), original);
            assert_eq!(
                k.get_value::<String, _>("ProxyOverride").unwrap(),
                "localhost;<local>"
            );
            assert!(k.get_raw_value("AutoConfigURL").is_err());
        }

        #[test]
        fn windows_registry_recovers_legacy_journal_but_preserves_foreign_proxy() {
            let fixture = RegistryFixture::new();
            let k = &fixture.key;
            let original = capture_from(k).unwrap();
            let snapshot = Snapshot {
                port: 32198,
                original: original.clone(),
            };
            k.set_value(
                "ProxyServer",
                &"http=127.0.0.1:32198;https=127.0.0.1:32198;socks=127.0.0.1:32198",
            )
            .unwrap();
            k.set_value("ProxyEnable", &1u32).unwrap();
            assert!(restore_to(k, &snapshot).unwrap());
            assert_eq!(capture_from(k).unwrap(), original);
            apply_to(k, &snapshot).unwrap();
            k.set_value("ProxyServer", &"127.0.0.1:32199").unwrap();
            assert!(!restore_to(k, &snapshot).unwrap());
            assert_eq!(
                k.get_value::<String, _>("ProxyServer").unwrap(),
                "127.0.0.1:32199"
            );
            assert_eq!(k.get_value::<u32, _>("ProxyEnable").unwrap(), 1);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn windows_proxy_address_is_understood_by_native_http_matcher() {
        let server = windows_server(32198);
        let matcher = hyper_util::client::proxy::matcher::Matcher::builder()
            .http(server.clone())
            .https(server)
            .build();
        for target in [
            "http://example.com/",
            "https://chatgpt.com/backend-api/codex/responses",
        ] {
            let proxy = matcher
                .intercept(&target.parse().unwrap())
                .expect("system proxy must intercept both HTTP and HTTPS");
            assert_eq!(proxy.uri().to_string(), "http://127.0.0.1:32198/");
        }
    }

    #[test]
    fn windows_recovery_recognizes_only_owned_current_or_legacy_endpoints() {
        assert!(windows_owns_server("127.0.0.1:32198", 32198));
        assert!(windows_owns_server(
            "http=127.0.0.1:32198;https=127.0.0.1:32198;socks=127.0.0.1:32198",
            32198
        ));
        for foreign in [
            "127.0.0.1:32199",
            "127.0.0.1:321980",
            "192.0.2.1:32198",
            "http=127.0.0.1:32198;https=127.0.0.1:32199;socks=127.0.0.1:32198",
            "http=127.0.0.1:32198;https=127.0.0.1:32198;socks=127.0.0.1:32198;ftp=proxy.example:21",
            "",
        ] {
            assert!(
                !windows_owns_server(foreign, 32198),
                "must not overwrite a changed proxy: {foreign}"
            );
        }
    }
}
