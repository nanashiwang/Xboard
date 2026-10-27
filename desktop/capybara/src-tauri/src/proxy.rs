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
#[cfg(any(target_os = "windows", test))]
fn windows_loopback_override(original: &str) -> String {
    let mut value = original.to_owned();
    // <local> and IPv4 wildcards are not understood consistently by native clients.
    // Keep existing exceptions intact and include explicit IPv4/IPv6 loopback hosts.
    for host in ["localhost", "127.0.0.1", "::1", "[::1]"] {
        if !original
            .split(';')
            .any(|entry| entry.trim().eq_ignore_ascii_case(host))
        {
            if !value.is_empty() && !value.ends_with(';') {
                value.push(';');
            }
            value.push_str(host);
        }
    }
    value
}
#[cfg(any(target_os = "windows", test))]
fn windows_original_override(value: &serde_json::Value) -> Result<String, String> {
    if value.is_null() {
        return Ok(String::new());
    }
    let invalid = || "Windows 代理例外格式无效，请先在系统代理设置中修复".to_owned();
    if !matches!(value["type"].as_u64(), Some(1 | 2)) {
        return Err(invalid());
    }
    let bytes: Vec<u8> = serde_json::from_value(value["bytes"].clone()).map_err(|_| invalid())?;
    if bytes.len() % 2 != 0 {
        return Err(invalid());
    }
    let words: Vec<u16> = bytes
        .chunks_exact(2)
        .map(|pair| u16::from_le_bytes([pair[0], pair[1]]))
        .collect();
    let text = String::from_utf16(&words).map_err(|_| invalid())?;
    let text = text.trim_end_matches('\0');
    if text.contains('\0') {
        return Err(invalid());
    }
    Ok(text.to_owned())
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
    use winreg::{enums::*, types::ToRegValue, RegKey, RegValue};
    const KEY: &str = "Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings";
    const NAMES: [&str; 5] = [
        "ProxyOverride",
        "ProxyEnable",
        "AutoConfigURL",
        "AutoDetect",
        // Keep the ownership marker until every other field has been restored.
        "ProxyServer",
    ];
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
            let v = v
                .map(|v| serde_json::json!({"bytes":v.bytes,"type":v.vtype as u32}))
                .unwrap_or(serde_json::Value::Null);
            if name == "ProxyOverride" {
                // Validate before writing a recovery journal or changing any setting.
                windows_original_override(&v)?;
            }
            values.insert(name.into(), v);
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
        let override_value = managed_override(s)?;
        k.set_value("ProxyServer", &windows_server(s.port))
            .map_err(|_| "无法设置代理地址")?;
        if let Some(value) = override_value {
            k.set_value("ProxyOverride", &value)
                .map_err(|_| "无法设置本地代理例外")?;
        }
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
        let owned_override = if let Some(value) = managed_override(s)? {
            match k.get_raw_value("ProxyOverride") {
                Ok(current) => current == value.to_reg_value(),
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => false,
                Err(_) => return Err("无法读取 Windows 代理例外，恢复记录已保留".into()),
            }
        } else {
            false
        };
        for name in NAMES {
            // Older recovery journals never owned ProxyOverride. A missing key is not
            // the same as a captured null (which means the original value was absent).
            let Some(v) = s.original.get(name) else {
                continue;
            };
            if name == "ProxyOverride" && !owned_override {
                continue;
            }
            if v.is_null() {
                match k.delete_value(name) {
                    Ok(()) => {}
                    Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
                    Err(_) => return Err("无法恢复 Windows 代理".into()),
                }
            } else {
                k.set_raw_value(name, &stored_value(v)?)
                    .map_err(|_| "无法恢复 Windows 代理")?;
            }
        }
        Ok(true)
    }
    fn stored_value(value: &serde_json::Value) -> Result<RegValue, String> {
        let bytes =
            serde_json::from_value(value["bytes"].clone()).map_err(|_| "代理恢复记录无效")?;
        let vtype = match value["type"].as_u64() {
            Some(1) => REG_SZ,
            Some(2) => REG_EXPAND_SZ,
            Some(3) => REG_BINARY,
            Some(4) => REG_DWORD,
            _ => return Err("代理恢复记录类型不支持".into()),
        };
        Ok(RegValue { bytes, vtype })
    }
    fn managed_override(s: &Snapshot) -> Result<Option<String>, String> {
        let Some(value) = s.original.get("ProxyOverride") else {
            return Ok(None);
        };
        let original = windows_original_override(value)?;
        Ok(Some(windows_loopback_override(&original)))
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
            let mut original_override = "corp.example;LOCALHOST;<local>".to_reg_value();
            original_override.vtype = REG_EXPAND_SZ;
            k.set_raw_value("ProxyOverride", &original_override)
                .unwrap();
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
            assert_eq!(
                k.get_value::<String, _>("ProxyOverride").unwrap(),
                "corp.example;LOCALHOST;<local>;127.0.0.1;::1;[::1]"
            );
            assert!(restore_to(k, &snapshot).unwrap());
            assert_eq!(capture_from(k).unwrap(), original);
            assert_eq!(
                k.get_value::<String, _>("ProxyOverride").unwrap(),
                "corp.example;LOCALHOST;<local>"
            );
            assert!(k.get_raw_value("ProxyOverride").unwrap() == original_override);
            assert!(k.get_raw_value("AutoConfigURL").is_err());
        }

        #[test]
        fn windows_registry_recovers_legacy_journal_without_touching_unowned_override() {
            let fixture = RegistryFixture::new();
            let k = &fixture.key;
            k.set_value("ProxyOverride", &"corp.example;<local>")
                .unwrap();
            let mut original = capture_from(k).unwrap();
            original.as_object_mut().unwrap().remove("ProxyOverride");
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
            let mut restored = capture_from(k).unwrap();
            restored.as_object_mut().unwrap().remove("ProxyOverride");
            assert_eq!(restored, original);
            assert_eq!(
                k.get_value::<String, _>("ProxyOverride").unwrap(),
                "corp.example;<local>"
            );
        }

        #[test]
        fn windows_registry_only_restores_owned_override_values() {
            let fixture = RegistryFixture::new();
            let k = &fixture.key;
            let snapshot = Snapshot {
                port: 32198,
                original: capture_from(k).unwrap(),
            };
            // A new snapshot explicitly records null and removes its own new value on restore.
            apply_to(k, &snapshot).unwrap();
            assert!(k
                .get_value::<String, _>("ProxyOverride")
                .unwrap()
                .contains("127.0.0.1"));
            assert!(restore_to(k, &snapshot).unwrap());
            assert!(k.get_raw_value("ProxyOverride").is_err());

            apply_to(k, &snapshot).unwrap();
            k.set_value("ProxyOverride", &"user-changed.example;localhost")
                .unwrap();
            assert!(restore_to(k, &snapshot).unwrap());
            assert_eq!(
                k.get_value::<String, _>("ProxyOverride").unwrap(),
                "user-changed.example;localhost"
            );

            apply_to(k, &snapshot).unwrap();
            let mut changed_type = k.get_raw_value("ProxyOverride").unwrap();
            changed_type.vtype = REG_EXPAND_SZ;
            k.set_raw_value("ProxyOverride", &changed_type).unwrap();
            assert!(restore_to(k, &snapshot).unwrap());
            assert!(k.get_raw_value("ProxyOverride").unwrap() == changed_type);

            apply_to(k, &snapshot).unwrap();
            k.delete_value("ProxyOverride").unwrap();
            assert!(restore_to(k, &snapshot).unwrap());
            assert!(k.get_raw_value("ProxyOverride").is_err());
        }

        #[test]
        fn windows_registry_preserves_all_settings_after_foreign_proxy_takes_over() {
            let fixture = RegistryFixture::new();
            let k = &fixture.key;
            let snapshot = Snapshot {
                port: 32198,
                original: capture_from(k).unwrap(),
            };
            apply_to(k, &snapshot).unwrap();
            let override_before = k.get_raw_value("ProxyOverride").unwrap();
            k.set_value("ProxyServer", &"127.0.0.1:32199").unwrap();
            assert!(!restore_to(k, &snapshot).unwrap());
            assert_eq!(
                k.get_value::<String, _>("ProxyServer").unwrap(),
                "127.0.0.1:32199"
            );
            assert_eq!(k.get_value::<u32, _>("ProxyEnable").unwrap(), 1);
            assert!(k.get_raw_value("ProxyOverride").unwrap() == override_before);
        }

        #[test]
        fn windows_registry_invalid_override_fails_before_any_proxy_write() {
            let fixture = RegistryFixture::new();
            let k = &fixture.key;
            k.set_value("ProxyServer", &"old.proxy.example:8080")
                .unwrap();
            for invalid in [
                RegValue {
                    bytes: vec![1, 2, 3],
                    vtype: REG_BINARY,
                },
                RegValue {
                    bytes: vec![65],
                    vtype: REG_SZ,
                },
                RegValue {
                    bytes: vec![0, 216, 0, 0],
                    vtype: REG_SZ,
                },
            ] {
                k.set_raw_value("ProxyOverride", &invalid).unwrap();
                assert!(capture_from(k).is_err());
                let snapshot = Snapshot {
                    port: 32198,
                    original: serde_json::json!({"ProxyOverride": {"bytes":invalid.bytes,"type":invalid.vtype.clone() as u32}}),
                };
                assert!(apply_to(k, &snapshot).is_err());
                assert_eq!(
                    k.get_value::<String, _>("ProxyServer").unwrap(),
                    "old.proxy.example:8080"
                );
                assert!(k.get_raw_value("ProxyEnable").is_err());
                assert!(k.get_raw_value("ProxyOverride").unwrap() == invalid);
            }
        }

        #[test]
        fn windows_registry_failed_restore_keeps_ownership_for_retry() {
            let fixture = RegistryFixture::new();
            let k = &fixture.key;
            k.set_value("ProxyEnable", &0u32).unwrap();
            k.set_value("AutoDetect", &1u32).unwrap();
            k.set_value("ProxyServer", &"old.proxy.example:8080")
                .unwrap();
            let original = capture_from(k).unwrap();
            let snapshot = Snapshot {
                port: 32198,
                original: original.clone(),
            };
            apply_to(k, &snapshot).unwrap();
            let mut invalid_snapshot = snapshot.clone();
            invalid_snapshot.original["AutoDetect"]["type"] = serde_json::json!(7);
            assert!(restore_to(k, &invalid_snapshot).is_err());
            assert_eq!(
                k.get_value::<String, _>("ProxyServer").unwrap(),
                "127.0.0.1:32198"
            );
            assert!(restore_to(k, &snapshot).unwrap());
            assert_eq!(capture_from(k).unwrap(), original);
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
    fn windows_loopback_exceptions_bypass_local_services_but_keep_remote_proxying() {
        for original in ["", "<local>", "127.*;<local>", "corp.example;LOCALHOST;"] {
            // Mirror the older Windows system matcher normalization, which does not
            // understand <local> or IPv4 wildcards. Explicit entries must still work.
            let exceptions = windows_loopback_override(original);
            assert!(exceptions.starts_with(original));
            let matcher = hyper_util::client::proxy::matcher::Matcher::builder()
                .http(windows_server(32198))
                .https(windows_server(32198))
                .no(exceptions
                    .split(';')
                    .map(str::trim)
                    .collect::<Vec<_>>()
                    .join(",")
                    .replace("*.", ""))
                .build();
            for local in [
                "http://127.0.0.1:15721/v1/responses",
                "http://localhost:15721/v1/responses",
                "http://[::1]:15721/v1/responses",
            ] {
                assert!(
                    matcher.intercept(&local.parse().unwrap()).is_none(),
                    "local request must bypass proxy: {local}"
                );
            }
            for remote in [
                "https://chatgpt.com/backend-api/codex/responses",
                "http://localhost.example/",
                "http://127.0.0.1.example/",
            ] {
                assert!(
                    matcher.intercept(&remote.parse().unwrap()).is_some(),
                    "remote request must keep using proxy: {remote}"
                );
            }
        }
    }

    #[test]
    fn windows_loopback_merge_preserves_existing_text_and_is_idempotent() {
        for original in [
            "",
            "<local>",
            "corp.example; LOCALHOST ;127.0.0.1;",
            "localhost;127.0.0.1;::1;[::1]",
        ] {
            let merged = windows_loopback_override(original);
            assert!(merged.starts_with(original));
            assert_eq!(windows_loopback_override(&merged), merged);
        }
        assert_eq!(
            windows_loopback_override("corp.example; LOCALHOST ;127.0.0.1;"),
            "corp.example; LOCALHOST ;127.0.0.1;::1;[::1]"
        );
    }

    #[test]
    fn windows_override_decode_preserves_valid_text_and_rejects_malformed_values() {
        assert_eq!(
            windows_original_override(&serde_json::Value::Null).unwrap(),
            ""
        );
        let bytes: Vec<u8> = "corp.example;<local>\0"
            .encode_utf16()
            .flat_map(u16::to_le_bytes)
            .collect();
        for kind in [1, 2] {
            assert_eq!(
                windows_original_override(&serde_json::json!({"bytes":bytes,"type":kind})).unwrap(),
                "corp.example;<local>"
            );
        }
        for invalid in [
            serde_json::json!({"bytes":[1, 2, 3],"type":3}),
            serde_json::json!({"bytes":[65],"type":1}),
            serde_json::json!({"bytes":[0, 216, 0, 0],"type":1}),
            serde_json::json!({"bytes":[65, 0, 0, 0, 66, 0, 0, 0],"type":2}),
            serde_json::json!({"type":1}),
        ] {
            assert!(windows_original_override(&invalid).is_err());
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
