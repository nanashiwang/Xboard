//! Keep Keychain authorization out of startup and background work.
#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Access {
    Background,
    UserInitiated,
}

/// Ad-hoc signed macOS builds have different Keychain identities. Do not read
/// or overwrite an older build's item when the user signs in again: even a
/// password update in keyring first reads that old item and requests its ACL.
pub fn account_name() -> Result<String, String> {
    #[cfg(target_os = "macos")]
    {
        account_for_binary(&std::env::current_exe().map_err(|_| "无法识别当前应用")?)
    }
    #[cfg(not(target_os = "macos"))]
    {
        Ok("desktop-session".into())
    }
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
