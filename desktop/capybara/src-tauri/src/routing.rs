use crate::{account::Fault, private_write, AppState};
use serde::{Deserialize, Serialize};
use std::{
    net::IpAddr,
    path::{Path, PathBuf},
};
const MAX_SETTINGS_BYTES: usize = 150_000;

#[derive(Clone, Copy, Debug, Default, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum RoutingMode {
    #[default]
    Rule,
    Global,
    Direct,
}
impl RoutingMode {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Rule => "rule",
            Self::Global => "global",
            Self::Direct => "direct",
        }
    }
}
#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
pub enum RuleKind {
    #[serde(rename = "DOMAIN")]
    Domain,
    #[serde(rename = "DOMAIN-SUFFIX")]
    DomainSuffix,
    #[serde(rename = "IP-CIDR")]
    IpCidr,
    #[serde(rename = "IP-CIDR6")]
    IpCidr6,
}
impl RuleKind {
    fn as_str(&self) -> &'static str {
        match self {
            Self::Domain => "DOMAIN",
            Self::DomainSuffix => "DOMAIN-SUFFIX",
            Self::IpCidr => "IP-CIDR",
            Self::IpCidr6 => "IP-CIDR6",
        }
    }
}
#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct CustomRule {
    pub kind: RuleKind,
    pub value: String,
    pub target: String,
}
impl CustomRule {
    pub fn line(&self) -> String {
        let suffix = if matches!(self.kind, RuleKind::IpCidr | RuleKind::IpCidr6) {
            ",no-resolve"
        } else {
            ""
        };
        format!(
            "{},{},{}{suffix}",
            self.kind.as_str(),
            self.value,
            self.target
        )
    }
}
#[derive(Clone, Debug, Default, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct RoutingSettings {
    pub mode: RoutingMode,
    pub rules: Vec<CustomRule>,
    #[serde(default)]
    pub global_target: Option<String>,
}
impl RoutingSettings {
    fn encoded(&self) -> Result<Vec<u8>, String> {
        let bytes = serde_json::to_vec_pretty(self).map_err(|_| "无法编码分流设置")?;
        if bytes.len() > MAX_SETTINGS_BYTES {
            return Err("分流设置内容过大，请减少规则数量或缩短目标名称".into());
        }
        Ok(bytes)
    }
    pub fn resolve_targets(&self, targets: &[String]) -> Result<Self, String> {
        self.validate(None)?;
        let mut settings = self.clone();
        if settings
            .global_target
            .as_ref()
            .is_some_and(|target| !targets.contains(target))
        {
            // Subscriptions may remove nodes. A stale global selection must not block all modes.
            settings.global_target = targets.first().cloned();
        }
        settings.validate(Some(targets))?;
        Ok(settings)
    }
    pub fn validate(&self, targets: Option<&[String]>) -> Result<(), String> {
        if self.rules.len() > 200 {
            return Err("自定义规则最多 200 条".into());
        }
        for (index, rule) in self.rules.iter().enumerate() {
            let invalid = || format!("第 {} 条规则无效，请检查域名、网段或目标", index + 1);
            if !safe_name(&rule.target) || rule.value.len() > 253 || rule.value.trim() != rule.value
            {
                return Err(invalid());
            }
            match rule.kind {
                RuleKind::Domain | RuleKind::DomainSuffix => {
                    if !valid_domain(&rule.value) {
                        return Err(invalid());
                    }
                }
                RuleKind::IpCidr | RuleKind::IpCidr6 => {
                    let Some((address, prefix)) = rule.value.split_once('/') else {
                        return Err(invalid());
                    };
                    let Ok(address) = address.parse::<IpAddr>() else {
                        return Err(invalid());
                    };
                    let Ok(prefix) = prefix.parse::<u8>() else {
                        return Err(invalid());
                    };
                    if !prefix
                        .to_string()
                        .eq(rule.value.rsplit('/').next().unwrap_or_default())
                        || !matches!(
                            (&rule.kind, address),
                            (RuleKind::IpCidr, IpAddr::V4(_)) | (RuleKind::IpCidr6, IpAddr::V6(_))
                        )
                        || prefix > if address.is_ipv4() { 32 } else { 128 }
                    {
                        return Err(invalid());
                    }
                }
            }
            if rule.target != "DIRECT" && rule.target != "REJECT" {
                if let Some(targets) = targets {
                    if !targets.contains(&rule.target) {
                        return Err(format!("第 {} 条规则的目标已不存在，请重新选择", index + 1));
                    }
                }
            }
        }
        if let Some(target) = &self.global_target {
            if !safe_name(target) || target == "DIRECT" || target == "REJECT" || target == "GLOBAL"
            {
                return Err("请选择有效的全局代理节点或分流组".into());
            }
            if let Some(targets) = targets {
                if !targets.contains(target) {
                    return Err("全局代理目标已不存在，请重新选择节点".into());
                }
            }
        }
        // Check the same representation that save writes before applying anything to the core.
        self.encoded()?;
        Ok(())
    }
}
fn safe_name(name: &str) -> bool {
    !name.is_empty()
        && name.len() <= 512
        && name.trim() == name
        && !name.chars().any(|c| c.is_control() || c == ',')
}
fn valid_domain(value: &str) -> bool {
    !value.is_empty()
        && value.is_ascii()
        && value.split('.').all(|label| {
            !label.is_empty()
                && label.len() <= 63
                && !label.starts_with('-')
                && !label.ends_with('-')
                && label
                    .bytes()
                    .all(|c| c.is_ascii_alphanumeric() || c == b'-')
        })
        && value.parse::<IpAddr>().is_err()
}
#[derive(Clone, Serialize)]
pub struct RoutingView {
    pub settings: RoutingSettings,
    pub targets: Vec<String>,
    pub ready: bool,
    pub error: Option<String>,
}
#[derive(Default)]
pub struct RoutingState {
    pub settings: RoutingSettings,
    pub targets: Vec<String>,
    pub error: Option<String>,
    pub storage_invalid: bool,
    path: PathBuf,
}
impl RoutingState {
    fn editor_settings(&self, mut settings: RoutingSettings) -> Result<RoutingSettings, String> {
        settings.global_target = self.settings.global_target.clone();
        if self.targets.is_empty() {
            settings.validate(None)?;
            Ok(settings)
        } else {
            settings.resolve_targets(&self.targets)
        }
    }
    pub fn load(dir: &Path) -> Self {
        let path = dir.join("routing.json");
        let result = match std::fs::read(&path) {
            Ok(bytes) if bytes.len() <= MAX_SETTINGS_BYTES => {
                serde_json::from_slice::<RoutingSettings>(&bytes)
                    .map_err(|_| "分流设置文件无效，请重新保存分流设置".to_owned())
                    .and_then(|settings| {
                        settings.validate(None)?;
                        Ok(settings)
                    })
            }
            Ok(_) => Err("分流设置文件过大，请重新保存分流设置".into()),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                Ok(RoutingSettings::default())
            }
            Err(_) => Err("无法读取分流设置，请重新保存分流设置".into()),
        };
        match result {
            Ok(settings) => Self {
                settings,
                path,
                ..Self::default()
            },
            Err(error) => Self {
                error: Some(error),
                storage_invalid: true,
                path,
                ..Self::default()
            },
        }
    }
    pub fn save(&self, settings: &RoutingSettings) -> Result<(), String> {
        settings.validate(None)?;
        private_write(&self.path, &settings.encoded()?)
    }
    pub fn view(&self, ready: bool) -> RoutingView {
        RoutingView {
            settings: self.settings.clone(),
            targets: self.targets.clone(),
            ready,
            error: self.error.clone(),
        }
    }
}

#[tauri::command]
pub async fn routing_snapshot(state: tauri::State<'_, AppState>) -> Result<RoutingView, Fault> {
    let mut nodes = state.1.lock().await;
    nodes.check_process();
    Ok(nodes.routing.view(nodes.engine.is_some()))
}

#[tauri::command]
pub async fn save_routing(
    state: tauri::State<'_, AppState>,
    settings: RoutingSettings,
) -> Result<RoutingView, Fault> {
    let mut nodes = state.1.lock().await;
    nodes.check_process();
    // Only select_route owns the global selection; an editor snapshot can predate a node click.
    let settings = nodes.routing.editor_settings(settings)?;
    if let Err(error) = nodes.apply_settings(settings).await {
        nodes.routing.error = Some(error.clone());
        return Err(error.into());
    }
    Ok(nodes.routing.view(nodes.engine.is_some()))
}

#[cfg(test)]
mod tests {
    use super::*;
    fn rule(kind: RuleKind, value: &str, target: &str) -> RoutingSettings {
        RoutingSettings {
            rules: vec![CustomRule {
                kind,
                value: value.into(),
                target: target.into(),
            }],
            ..Default::default()
        }
    }
    #[test]
    fn validates_domains_network_families_targets_and_injection() {
        assert!(rule(RuleKind::DomainSuffix, "example.com", "DIRECT")
            .validate(Some(&[]))
            .is_ok());
        assert!(rule(RuleKind::IpCidr, "192.168.0.0/16", "REJECT")
            .validate(Some(&[]))
            .is_ok());
        assert!(rule(RuleKind::IpCidr6, "fd00::/8", "节点")
            .validate(Some(&["节点".into()]))
            .is_ok());
        for value in [
            "https://example.com",
            "example.com,REJECT",
            "*.example.com",
            "a\nb",
            "-a.com",
            "127.0.0.1",
        ] {
            assert!(
                rule(RuleKind::Domain, value, "DIRECT")
                    .validate(None)
                    .is_err(),
                "{value}"
            );
        }
        for value in [
            "192.168.0.0/33",
            "192.168.0.0/016",
            "::1/32",
            "1.2.3.4",
            "1.2.3.4/24,no-resolve",
        ] {
            assert!(
                rule(RuleKind::IpCidr, value, "DIRECT")
                    .validate(None)
                    .is_err(),
                "{value}"
            );
        }
        assert!(rule(RuleKind::Domain, "example.com", "missing")
            .validate(Some(&[]))
            .is_err());
        assert!(rule(RuleKind::Domain, "example.com", "DIRECT\n")
            .validate(None)
            .is_err());
        assert!(serde_json::from_str::<RoutingSettings>(r#"{"mode":"bad","rules":[]}"#).is_err());
    }
    #[test]
    fn persists_order_and_mode_and_reports_corrupt_storage() {
        let dir =
            std::env::temp_dir().join(format!("capybara-routing-test-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir_all(&dir).unwrap();
        let state = RoutingState::load(&dir);
        let mut settings = rule(RuleKind::Domain, "example.com", "REJECT");
        settings.mode = RoutingMode::Global;
        settings.global_target = Some("代理组".into());
        state.save(&settings).unwrap();
        assert_eq!(RoutingState::load(&dir).settings, settings);
        std::fs::write(dir.join("routing.json"), "bad").unwrap();
        assert!(RoutingState::load(&dir).error.is_some());
        std::fs::remove_dir_all(dir).unwrap();
    }
    #[test]
    fn editor_cannot_overwrite_a_newer_global_selection_and_removed_targets_can_recover() {
        let mut state = RoutingState::default();
        state.targets = vec!["A".into(), "B".into()];
        state.settings.global_target = Some("B".into());
        let stale = RoutingSettings {
            mode: RoutingMode::Direct,
            global_target: Some("A".into()),
            ..Default::default()
        };
        assert_eq!(
            state
                .editor_settings(stale)
                .unwrap()
                .global_target
                .as_deref(),
            Some("B")
        );
        state.targets = vec!["C".into()];
        let repaired = state.editor_settings(RoutingSettings::default()).unwrap();
        assert_eq!(repaired.global_target.as_deref(), Some("C"));
        let invalid_rule = rule(RuleKind::Domain, "example.com", "A");
        assert!(state.editor_settings(invalid_rule).is_err());
    }
    #[test]
    fn serialized_size_boundary_round_trips_and_oversize_cannot_replace_saved_settings() {
        let dir = std::env::temp_dir().join(format!(
            "capybara-routing-size-test-{}",
            uuid::Uuid::new_v4()
        ));
        std::fs::create_dir_all(&dir).unwrap();
        let state = RoutingState::load(&dir);
        let domain = [
            "a".repeat(63),
            "b".repeat(63),
            "c".repeat(63),
            "d".repeat(61),
        ]
        .join(".");
        let mut settings = RoutingSettings {
            rules: vec![
                CustomRule {
                    kind: RuleKind::DomainSuffix,
                    value: domain,
                    target: "x".into()
                };
                200
            ],
            ..Default::default()
        };
        let mut remaining =
            MAX_SETTINGS_BYTES - serde_json::to_vec_pretty(&settings).unwrap().len();
        for rule in &mut settings.rules {
            let added = remaining.min(512 - rule.target.len());
            rule.target.push_str(&"x".repeat(added));
            remaining -= added;
        }
        assert_eq!(remaining, 0);
        assert_eq!(settings.encoded().unwrap().len(), MAX_SETTINGS_BYTES);
        state.save(&settings).unwrap();
        assert_eq!(RoutingState::load(&dir).settings, settings);
        let saved = std::fs::read(dir.join("routing.json")).unwrap();
        let mut oversized = settings.clone();
        oversized
            .rules
            .iter_mut()
            .find(|rule| rule.target.len() < 512)
            .unwrap()
            .target
            .push('x');
        assert_eq!(
            serde_json::to_vec_pretty(&oversized).unwrap().len(),
            MAX_SETTINGS_BYTES + 1
        );
        assert!(oversized.validate(None).is_err());
        assert!(state.save(&oversized).is_err());
        assert_eq!(std::fs::read(dir.join("routing.json")).unwrap(), saved);
        assert_eq!(RoutingState::load(&dir).settings, settings);
        std::fs::remove_dir_all(dir).unwrap();
    }
}
