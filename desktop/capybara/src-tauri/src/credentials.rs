//! Keep Keychain authorization out of startup and background work.
#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Access {
    Background,
    UserInitiated,
}

/// Ad-hoc signed macOS builds have different Keychain identities. Do not read
/// or overwrite an older build's item when the user signs in again: even a
/// password update in keyring first reads that old item and requests its ACL.
pub fn account_name(_device: &str) -> Result<String, String> {
    #[cfg(target_os = "macos")]
    {
        if publisher_signed() {
            return Ok(format!("desktop-session-v3-{_device}"));
        }
        account_for_binary(&std::env::current_exe().map_err(|_| "无法识别当前应用")?)
    }
    #[cfg(not(target_os = "macos"))]
    {
        Ok("desktop-session".into())
    }
}

#[cfg(not(test))]
pub const SERVICE: &str = "us.taige.capybara";
#[cfg(test)]
pub const SERVICE: &str = "us.taige.capybara.unit-test";

pub fn publisher_signed() -> bool {
    cfg!(target_os = "macos") && option_env!("CAPYBARA_DEVELOPER_ID_BUILD") == Some("1")
}

#[cfg(any(target_os = "macos", test))]
fn legacy_account(account: &str) -> bool {
    account
        .strip_prefix("desktop-session-v2-")
        .is_some_and(|hash| hash.len() == 64 && hash.bytes().all(|b| b.is_ascii_hexdigit()))
}

#[cfg(all(target_os = "macos", not(test)))]
pub fn previous_account() -> keyring::Result<Option<String>> {
    use core_foundation::{
        base::{CFType, TCFType},
        date::CFDate,
        dictionary::CFDictionary,
        string::CFString,
    };
    use security_framework::item::{ItemClass, ItemSearchOptions, Limit, SearchResult};
    // Query public attributes only. Reading the selected secret is a separate,
    // user-initiated operation. Never try older accounts on authorization failure.
    access(Access::Background, || {
        let results = match ItemSearchOptions::new()
            .class(ItemClass::generic_password())
            .service(SERVICE)
            .load_attributes(true)
            .limit(Limit::All)
            .search()
        {
            Ok(items) => items,
            Err(e) if e.code() == -25300 => return Ok(None),
            Err(e) => return Err(keyring::Error::PlatformFailure(Box::new(e))),
        };
        let newest = results
            .into_iter()
            .filter_map(|item| {
                let SearchResult::Dict(dict) = item else {
                    return None;
                };
                // SecItemCopyMatching returns a CFString-keyed attribute dictionary.
                let attrs: CFDictionary<CFString, CFType> =
                    unsafe { CFDictionary::wrap_under_get_rule(dict.as_concrete_TypeRef()) };
                let account = attrs
                    .find(&CFString::new("acct"))?
                    .downcast::<CFString>()?
                    .to_string();
                if !legacy_account(&account) {
                    return None;
                }
                let modified = attrs
                    .find(&CFString::new("mdat"))?
                    .downcast::<CFDate>()?
                    .abs_time();
                Some((modified, account))
            })
            .max_by(|a, b| a.0.total_cmp(&b.0).then_with(|| a.1.cmp(&b.1)));
        Ok(newest.map(|(_, account)| account))
    })
}

#[cfg(any(not(target_os = "macos"), test))]
pub fn previous_account() -> keyring::Result<Option<String>> {
    Ok(None)
}

#[cfg(any(target_os = "macos", test))]
fn account_for_binary(path: &std::path::Path) -> Result<String, String> {
    use sha2::{Digest, Sha256};
    use std::io::Read;
    let mut binary = std::fs::File::open(path).map_err(|_| "无法读取当前应用身份")?;
    let mut digest = Sha256::new();
    let mut buffer = [0; 64 * 1024];
    loop {
        let count = binary
            .read(&mut buffer)
            .map_err(|_| "无法校验当前应用身份")?;
        if count == 0 {
            break;
        }
        digest.update(&buffer[..count]);
    }
    Ok(format!("desktop-session-v2-{:x}", digest.finalize()))
}

#[cfg(test)]
mod identity_tests {
    use super::*;
    #[test]
    fn credential_identity_follows_binary_not_install_path_or_version_label() {
        let dir = std::env::temp_dir().join(format!("capybara-identity-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir_all(&dir).unwrap();
        let original = dir.join("app");
        let moved = dir.join("moved-app");
        std::fs::write(&original, b"same-version-build-a").unwrap();
        std::fs::copy(&original, &moved).unwrap();
        let account = account_for_binary(&original).unwrap();
        assert!(legacy_account(&account));
        assert!(!legacy_account("desktop-session-v3-example"));
        assert_eq!(account, account_for_binary(&moved).unwrap());
        std::fs::write(&moved, b"same-version-build-b").unwrap();
        assert_ne!(account, account_for_binary(&moved).unwrap());
        assert_ne!(account, "desktop-session");
        assert!(account_for_binary(&dir.join("missing")).is_err());
        std::fs::remove_dir_all(dir).unwrap();
    }
}

pub fn access<T>(
    mode: Access,
    operation: impl FnOnce() -> keyring::Result<T>,
) -> keyring::Result<T> {
    // macOS's interaction setting is process-wide. Every credential operation,
    // including explicit user actions, must use this gate. Never hold it over await.
    #[cfg(target_os = "macos")]
    {
        static GATE: std::sync::Mutex<()> = std::sync::Mutex::new(());
        let _gate = GATE.lock().unwrap_or_else(|e| e.into_inner());
        mac_access(mode, operation)
    }
    #[cfg(not(target_os = "macos"))]
    {
        let _ = mode;
        operation()
    }
}

#[cfg(target_os = "macos")]
fn mac_access<T>(
    mode: Access,
    operation: impl FnOnce() -> keyring::Result<T>,
) -> keyring::Result<T> {
    use security_framework::os::macos::keychain::SecKeychain;
    let failure = |e| keyring::Error::PlatformFailure(Box::new(e));
    let _quiet = if mode == Access::Background
        && SecKeychain::user_interaction_allowed().map_err(failure)?
    {
        Some(SecKeychain::disable_user_interaction().map_err(failure)?)
    } else {
        None
    };
    operation()
}

#[cfg(all(test, target_os = "macos"))]
mod tests {
    use super::*;
    use security_framework::os::macos::keychain::SecKeychain;

    #[test]
    #[ignore = "manual native test: creates and removes a disposable Keychain item"]
    fn native_keychain_across_processes_without_prompt() {
        const SERVICE: &str = "us.taige.capybara.self-test";
        if let Ok(id) = std::env::var("CAPYBARA_KEYCHAIN_TEST_ID") {
            assert!(uuid::Uuid::parse_str(&id).is_ok());
            let entry = keyring::Entry::new(SERVICE, &id).unwrap();
            access(Access::Background, || {
                match std::env::var("CAPYBARA_KEYCHAIN_TEST_PHASE")
                    .unwrap()
                    .as_str()
                {
                    "create" => entry.set_password("disposable-test-a")?,
                    "renew" => {
                        assert_eq!(entry.get_password()?, "disposable-test-a");
                        entry.set_password("disposable-test-b")?;
                    }
                    "remove" => {
                        assert_eq!(entry.get_password()?, "disposable-test-b");
                        entry.delete_credential()?;
                        assert!(matches!(entry.get_password(), Err(keyring::Error::NoEntry)));
                    }
                    _ => panic!("invalid phase"),
                }
                Ok(())
            })
            .unwrap();
            return;
        }
        let id = uuid::Uuid::new_v4().to_string();
        for phase in ["create", "renew", "remove"] {
            let output = std::process::Command::new(std::env::current_exe().unwrap())
                .args([
                    "--ignored",
                    "--exact",
                    "credentials::tests::native_keychain_across_processes_without_prompt",
                ])
                .env("CAPYBARA_KEYCHAIN_TEST_ID", &id)
                .env("CAPYBARA_KEYCHAIN_TEST_PHASE", phase)
                .output()
                .unwrap();
            assert!(
                output.status.success(),
                "native phase {phase} failed: {}{}",
                String::from_utf8_lossy(&output.stdout),
                String::from_utf8_lossy(&output.stderr)
            );
        }
    }

    #[test]
    fn background_suppresses_ui_and_restores_it_on_success_and_failure() {
        for fail in [false, true] {
            let result = access(Access::Background, || {
                assert!(!SecKeychain::user_interaction_allowed().unwrap());
                if fail {
                    Err(keyring::Error::NoEntry)
                } else {
                    Ok(())
                }
            });
            assert_eq!(result.is_err(), fail);
            access(Access::UserInitiated, || {
                assert!(SecKeychain::user_interaction_allowed().unwrap());
                Ok(())
            })
            .unwrap();
        }
        // A caller that already disabled interaction must retain that policy.
        access(Access::UserInitiated, || {
            let _quiet = SecKeychain::disable_user_interaction().unwrap();
            mac_access(Access::Background, || Ok(()))?;
            assert!(!SecKeychain::user_interaction_allowed().unwrap());
            Ok(())
        })
        .unwrap();
    }
}
