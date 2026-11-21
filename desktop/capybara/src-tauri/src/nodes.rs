use crate::{
    account::Fault,
    engine::{Engine, Route},
    routing::{RoutingSettings, RoutingState},
    AppState,
};
use futures_util::{stream, StreamExt};
use serde::Serialize;
use std::collections::BTreeMap;
use std::{
    net::IpAddr,
    time::{Duration, Instant},
};
use tokio::sync::Mutex;

#[derive(Clone, Serialize)]
pub struct Delay {
    status: String,
    ms: Option<u64>,
}
#[derive(Clone, Serialize)]
pub struct NodeView {
    pub revision: u64,
    pub routes: Vec<Route>,
    pub loading: bool,
    pub error: Option<String>,
    pub subscription_synced_at: Option<u64>,
    pub subscription_interval_seconds: u64,
    testing: bool,
    delays: BTreeMap<String, Delay>,
    entries: BTreeMap<String, Delay>,
}
impl Default for NodeView {
    fn default() -> Self {
        Self {
            revision: 0,
            routes: vec![],
            loading: false,
            error: None,
            subscription_synced_at: None,
            subscription_interval_seconds: crate::subscription::DEFAULT_INTERVAL_SECONDS,
            testing: false,
            delays: BTreeMap::new(),
            entries: BTreeMap::new(),
        }
    }
}
#[derive(Default)]
pub struct Nodes {
    pub engine: Option<Engine>,
    pub routing: RoutingState,
    pub view: NodeView,
    generation: u64,
    source: Option<String>,
    subscription_settings_error: Option<String>,
    dir: std::path::PathBuf,
    binary: Option<std::path::PathBuf>,
}
impl Nodes {
    pub fn new(dir: &std::path::Path) -> Self {
        let (interval, error) = crate::subscription::load_interval(dir);
        Self {
            routing: RoutingState::load(dir),
            dir: dir.to_owned(),
            subscription_settings_error: error.clone(),
            view: NodeView {
                subscription_interval_seconds: interval,
                error,
                ..NodeView::default()
            },
            ..Self::default()
        }
    }
    pub fn set_subscription_interval(&mut self, seconds: u64) -> Result<(), Fault> {
        crate::subscription::save_interval(&self.dir, seconds)?;
        if self.view.error == self.subscription_settings_error {
            self.view.error = None;
        }
        self.subscription_settings_error = None;
        self.view.subscription_interval_seconds = seconds;
        self.changed();
        Ok(())
    }
    pub fn reusable_config(&mut self) -> Option<&str> {
        self.check_process();
        let engine = self.engine.as_ref()?;
        if self.routing.storage_invalid
            || self.routing.error.is_some()
            || self.view.error.is_some()
            || self.source.as_deref() != Some(engine.content())
        {
            return None;
        }
        Some(engine.content())
    }
    pub async fn prepare(
        &mut self,
        dir: &std::path::Path,
        binary: std::path::PathBuf,
        content: &str,
    ) -> Result<(), String> {
        self.dir = dir.to_owned();
        self.binary = Some(binary);
        // Keep the new source and targets for repairs even when a saved rule prevents reload.
        self.source = Some(content.to_owned());
        self.routing.targets = crate::engine::routing_targets(content)?;
        if self.routing.storage_invalid {
            return Err("分流设置文件无效，请在分流规则中确认并重新保存".into());
        }
        let settings = self.routing.settings.clone();
        self.apply_settings(settings).await
    }
    fn normalize_settings(
        &mut self,
        mut settings: RoutingSettings,
    ) -> Result<RoutingSettings, String> {
        if let Some(content) = self.source.as_ref() {
            settings = settings.resolve_targets(&self.routing.targets)?;
            let global_targets = crate::engine::global_targets(content)?;
            if settings
                .global_target
                .as_ref()
                .is_some_and(|target| !global_targets.contains(target))
            {
                settings.global_target = global_targets.first().cloned();
            }
        }
        Ok(settings)
    }
    pub async fn apply_settings(&mut self, settings: RoutingSettings) -> Result<(), String> {
        self.apply_routing_settings(settings, None).await
    }
    pub async fn apply_routing_settings(
        &mut self,
        settings: RoutingSettings,
        rule_group: Option<&str>,
    ) -> Result<(), String> {
        let mut settings = self.normalize_settings(settings)?;
        let previous = match self.engine.as_ref() {
            Some(engine) => Some(engine.checkpoint().await?),
            None => None,
        };
        if let (Some(content), Some(binary)) = (self.source.as_ref(), self.binary.as_ref()) {
            if let Some(engine) = self.engine.as_mut() {
                let selection = if settings.mode != self.routing.settings.mode {
                    Some(engine.selection_for_mode(&mut settings, rule_group).await?)
                } else {
                    None
                };
                engine
                    .reload(content, &settings, selection.as_deref())
                    .await?;
            } else {
                self.engine =
                    Some(Engine::start(&self.dir, binary.clone(), content, &settings).await?);
            }
        }
        if let Err(error) = self.routing.save(&settings) {
            if let Some((content, previous, selection)) = previous {
                if let Some(engine) = self.engine.as_mut() {
                    if engine
                        .reload(&content, &previous, Some(&selection))
                        .await
                        .is_err()
                    {
                        let _ = self.stop();
                        return Err("分流设置保存失败，恢复旧配置失败，连接组件已停止".into());
                    }
                }
            } else if self.engine.is_some() {
                let _ = self.stop();
            }
            return Err(error);
        }
        self.routing.settings = settings;
        self.routing.storage_invalid = false;
        self.routing.error = None;
        self.view.error = self.subscription_settings_error.clone();
        if let Some(engine) = self.engine.as_ref() {
            match engine.routes().await {
                Ok(routes) => self.view.routes = routes,
                Err(error) => self.view.error = Some(error),
            }
        }
        self.invalidate();
        Ok(())
    }
    pub async fn select_route(&mut self, group: String, name: String) -> Result<NodeView, Fault> {
        if !self
            .view
            .routes
            .iter()
            .any(|r| r.group == group && r.choices.contains(&name))
        {
            return Err(Fault::local("节点已变更，请等待列表刷新"));
        }
        let engine = self
            .engine
            .as_ref()
            .ok_or_else(|| Fault::local("节点正在准备，请稍候"))?;
        if let Err(error) = engine.select(&group, &name).await {
            // A lost local response is ambiguous; reconcile before reporting the error.
            if let Ok(routes) = engine.routes().await {
                self.view.routes = routes;
                self.changed();
            }
            return Err(error.into());
        }
        if group == "GLOBAL" {
            let old = self
                .view
                .routes
                .iter()
                .find(|route| route.group == group)
                .map(|route| route.selected.clone());
            let mut settings = self.routing.settings.clone();
            settings.global_target = Some(name.clone());
            if let Err(error) = self.routing.save(&settings) {
                if let (Some(engine), Some(old)) = (self.engine.as_ref(), old) {
                    if engine.select("GLOBAL", &old).await.is_err() {
                        let _ = self.stop();
                        return Err(Fault::local(
                            "全局节点保存失败，恢复旧节点失败，连接组件已停止",
                        ));
                    }
                }
                return Err(error.into());
            }
            self.routing.settings = settings;
            if let Some(engine) = self.engine.as_mut() {
                engine.remember_global_target(name.clone());
            }
        }
        for route in &mut self.view.routes {
            if route.group == group {
                route.selected = name.clone();
            }
        }
        self.changed();
        Ok(self.view.clone())
    }
    pub fn changed(&mut self) {
        self.view.revision += 1;
    }
    pub fn invalidate(&mut self) {
        self.generation += 1;
        self.view.testing = false;
        self.view.delays.clear();
        self.view.entries.clear();
        self.changed();
    }
    pub fn stop(&mut self) -> Result<(), String> {
        self.invalidate();
        let result = self.engine.take().map(|mut e| e.stop()).unwrap_or(Ok(()));
        self.view.routes.clear();
        self.routing.targets.clear();
        self.source = None;
        self.binary = None;
        self.view.loading = false;
        self.view.error = result
            .as_ref()
            .err()
            .cloned()
            .or_else(|| self.subscription_settings_error.clone());
        self.view.subscription_synced_at = None;
        result
    }
    pub fn check_process(&mut self) {
        if self.engine.as_mut().is_some_and(|e| !e.alive()) {
            let _ = self.stop();
            self.view
                .error
                .get_or_insert("节点组件已退出，稍后会自动重试加载".into());
        }
    }
}

#[tauri::command]
pub async fn nodes_snapshot(state: tauri::State<'_, AppState>) -> Result<NodeView, Fault> {
    let mut nodes = state.1.lock().await;
    nodes.check_process();
    Ok(nodes.view.clone())
}
#[tauri::command]
pub async fn select_route(
    state: tauri::State<'_, AppState>,
    group: String,
    name: String,
) -> Result<NodeView, Fault> {
    // Account HTTP requests use a different lock; switching only waits for the local core.
    let mut nodes = state.1.lock().await;
    nodes.select_route(group, name).await
}

// Only concrete choices have an end-to-end result. Group selectors stay selectable.
#[derive(Default)]
struct ProbeTargets {
    names: Vec<String>,
    entries: BTreeMap<(String, u16), Vec<String>>,
}
fn probe_targets(content: &str, view: &NodeView) -> Result<ProbeTargets, Fault> {
    let config: serde_yaml::Value =
        serde_yaml::from_str(content).map_err(|_| Fault::local("订阅配置格式无效"))?;
    let choices: std::collections::BTreeSet<_> = view
        .routes
        .iter()
        .flat_map(|r| r.choices.iter().map(String::as_str))
        .collect();
    let mut targets = ProbeTargets::default();
    for proxy in config["proxies"].as_sequence().into_iter().flatten() {
        let (Some(name), Some(kind)) = (proxy["name"].as_str(), proxy["type"].as_str()) else {
            continue;
        };
        if !choices.contains(name) || matches!(kind, "direct" | "reject" | "dns" | "pass") {
            continue;
        }
        targets.names.push(name.into());
        // TCP is meaningful only for transports that actually connect over it.
        if !matches!(
            kind,
            "vless" | "vmess" | "trojan" | "ss" | "ssr" | "socks5" | "http" | "anytls" | "snell"
        ) || proxy.get("dialer-proxy").is_some()
            || !matches!(
                proxy["network"].as_str(),
                None | Some("tcp" | "ws" | "http" | "h2" | "grpc" | "httpupgrade" | "xhttp")
            )
            || proxy["plugin-opts"]["mode"].as_str() == Some("quic")
        {
            continue;
        }
        let port = proxy["port"]
            .as_u64()
            .and_then(|v| u16::try_from(v).ok())
            .or_else(|| proxy["port"].as_str()?.parse::<u16>().ok());
        if let (Some(host), Some(port)) = (proxy["server"].as_str(), port.filter(|p| *p != 0)) {
            let host = host
                .trim_start_matches('[')
                .trim_end_matches(']')
                .to_ascii_lowercase();
            targets
                .entries
                .entry((host, port))
                .or_default()
                .push(name.into());
        }
    }
    Ok(targets)
}

fn virtual_ip(ip: IpAddr) -> bool {
    match ip {
        IpAddr::V4(addr) => matches!(addr.octets(), [198, 18 | 19, _, _]),
        IpAddr::V6(addr) => {
            addr.to_ipv4_mapped().is_some_and(|v| virtual_ip(v.into()))
                || addr.segments()[..3] == [0x2001, 2, 0]
        }
    }
}
async fn entry_delay((host, port): (String, u16)) -> Result<u64, String> {
    tokio::time::timeout(Duration::from_millis(1800), async {
        let started = Instant::now();
        let addresses = tokio::net::lookup_host((host.as_str(), port))
            .await
            .map_err(|_| "解析失败")?;
        let addresses: Vec<_> = addresses.filter(|a| !virtual_ip(a.ip())).collect();
        if addresses.is_empty() {
            return Err("无真实地址");
        }
        let _socket = tokio::net::TcpStream::connect(addresses.as_slice())
            .await
            .map_err(|_| "不可达")?;
        Ok(started.elapsed().as_millis().max(1) as u64)
    })
    .await
    .map_err(|_| "超时".to_owned())?
    .map_err(str::to_owned)
}
impl Delay {
    fn pending() -> Self {
        Self {
            status: "pending".into(),
            ms: None,
        }
    }
    fn measured(result: Result<u64, String>) -> Self {
        match result {
            Ok(ms) => Self {
                status: "ok".into(),
                ms: Some(ms),
            },
            Err(status) => Self { status, ms: None },
        }
    }
}
#[tauri::command]
pub async fn test_nodes(state: tauri::State<'_, AppState>) -> Result<NodeView, Fault> {
    let shared = state.1.clone();
    let mut nodes = shared.lock().await;
    if nodes.view.testing {
        return Ok(nodes.view.clone());
    }
    let engine = nodes
        .engine
        .as_ref()
        .ok_or_else(|| Fault::local("节点尚未加载，请稍候"))?;
    let controller = std::ops::Deref::deref(engine).clone();
    let targets = probe_targets(engine.content(), &nodes.view)?;
    if targets.names.is_empty() {
        return Err(Fault::local("当前没有可测速的节点"));
    }
    nodes.invalidate();
    let generation = nodes.generation;
    nodes.view.testing = true;
    nodes.view.delays = targets
        .names
        .iter()
        .map(|n| (n.clone(), Delay::pending()))
        .collect();
    nodes.view.entries = targets
        .entries
        .values()
        .flatten()
        .map(|n| (n.clone(), Delay::pending()))
        .collect();
    let view = nodes.view.clone();
    drop(nodes);
    tauri::async_runtime::spawn(async move {
        let web = targets.names.into_iter().map(|name| {
            let controller = controller.clone();
            async move {
                let result = controller.delay(&name).await;
                (vec![name], result)
            }
        });
        let tcp = targets
            .entries
            .into_iter()
            .map(|(address, names)| async move { (names, entry_delay(address).await) });
        tokio::join!(
            run_probes(&shared, generation, web, false),
            run_probes(&shared, generation, tcp, true)
        );
        let mut nodes = shared.lock().await;
        if nodes.generation == generation {
            nodes.view.testing = false;
            nodes.changed();
        }
    });
    Ok(view)
}

const PROBE_CONCURRENCY: usize = 6;

async fn run_probes<F: std::future::Future<Output = (Vec<String>, Result<u64, String>)>>(
    shared: &Mutex<Nodes>,
    generation: u64,
    jobs: impl Iterator<Item = F>,
    entry: bool,
) {
    let mut pending = stream::iter(jobs).buffer_unordered(PROBE_CONCURRENCY);
    while let Some((names, result)) = pending.next().await {
        let mut nodes = shared.lock().await;
        if nodes.generation != generation {
            return;
        }
        let delays = if entry {
            &mut nodes.view.entries
        } else {
            &mut nodes.view.delays
        };
        let delay = Delay::measured(result);
        for name in names {
            delays.insert(name, delay.clone());
        }
        nodes.changed();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Arc;

    #[tokio::test]
    async fn stale_selection_cannot_replace_the_current_node_or_global_setting() {
        let mut nodes = Nodes::default();
        nodes.routing.settings.global_target = Some("current".into());
        nodes.view.routes = vec![Route {
            group: "GLOBAL".into(),
            selected: "current".into(),
            choices: vec!["current".into()],
        }];
        let revision = nodes.view.revision;
        for (group, name) in [("GLOBAL", "removed"), ("old-group", "current")] {
            let error = nodes
                .select_route(group.into(), name.into())
                .await
                .err()
                .unwrap();
            assert_eq!(error.message, "节点已变更，请等待列表刷新");
            assert_eq!(nodes.view.revision, revision);
            assert_eq!(nodes.view.routes[0].selected, "current");
            assert_eq!(
                nodes.routing.settings.global_target.as_deref(),
                Some("current")
            );
        }
    }

    #[tokio::test]
    async fn unavailable_core_cannot_publish_a_successful_selection() {
        let mut nodes = Nodes::default();
        nodes.view.routes = vec![Route {
            group: "GLOBAL".into(),
            selected: "current".into(),
            choices: vec!["current".into(), "new".into()],
        }];
        let revision = nodes.view.revision;
        let error = nodes
            .select_route("GLOBAL".into(), "new".into())
            .await
            .err()
            .unwrap();
        assert_eq!(error.message, "节点正在准备，请稍候");
        assert_eq!(nodes.view.revision, revision);
        assert_eq!(nodes.view.routes[0].selected, "current");
        assert!(nodes.routing.settings.global_target.is_none());
    }

    #[test]
    fn interval_write_failure_preserves_published_settings_and_refresh_time() {
        let dir = std::env::temp_dir().join(format!(
            "capybara-subscription-save-test-{}",
            uuid::Uuid::new_v4()
        ));
        std::fs::create_dir_all(&dir).unwrap();
        let mut nodes = Nodes::new(&dir);
        nodes.set_subscription_interval(1800).unwrap();
        nodes.view.subscription_synced_at = Some(1000);
        std::fs::create_dir(dir.join("subscription.tmp")).unwrap();
        assert!(nodes.set_subscription_interval(3600).is_err());
        assert_eq!(nodes.view.subscription_interval_seconds, 1800);
        assert_eq!(nodes.view.subscription_synced_at, Some(1000));
        assert_eq!(crate::subscription::load_interval(&dir), (1800, None));
        nodes.stop().unwrap();
        assert_eq!(nodes.view.subscription_synced_at, None);
        assert_eq!(nodes.view.subscription_interval_seconds, 1800);
        std::fs::remove_dir_all(dir).unwrap();
    }

    #[tokio::test]
    async fn corrupt_subscription_settings_remain_visible_until_saved() {
        let dir = std::env::temp_dir().join(format!(
            "capybara-subscription-corrupt-test-{}",
            uuid::Uuid::new_v4()
        ));
        std::fs::create_dir_all(&dir).unwrap();
        std::fs::write(dir.join("subscription.json"), b"bad").unwrap();
        let mut nodes = Nodes::new(&dir);
        assert_eq!(nodes.view.subscription_interval_seconds, 3600);
        assert!(nodes.view.error.is_some());
        nodes
            .apply_settings(RoutingSettings::default())
            .await
            .unwrap();
        assert!(nodes.view.error.is_some());
        nodes.set_subscription_interval(3600).unwrap();
        assert!(nodes.view.error.is_none());
        assert_eq!(crate::subscription::load_interval(&dir), (3600, None));
        std::fs::remove_dir_all(dir).unwrap();
    }
    #[tokio::test]
    async fn removed_targets_leave_the_new_subscription_available_for_editor_repairs() {
        use crate::routing::{CustomRule, RoutingMode, RuleKind};
        let dir = std::env::temp_dir().join(format!(
            "capybara-node-repair-test-{}",
            uuid::Uuid::new_v4()
        ));
        std::fs::create_dir_all(&dir).unwrap();
        let mut nodes = Nodes::new(&dir);
        nodes.routing.settings = RoutingSettings {
            mode: RoutingMode::Rule,
            global_target: Some("old".into()),
            rules: vec![CustomRule {
                kind: RuleKind::Domain,
                value: "example.com".into(),
                target: "old".into(),
            }],
        };
        let content = "proxies: [{name: new, type: direct}]\nproxy-groups: [{name: group, type: select, proxies: [DIRECT, new]}]\nrules: ['MATCH,group']";
        assert!(nodes
            .prepare(&dir, dir.join("not-started"), content)
            .await
            .is_err());
        assert_eq!(nodes.routing.targets, vec!["group", "new"]);
        assert_eq!(nodes.source.as_deref(), Some(content));
        assert!(nodes.engine.is_none());
        let mut repaired = nodes.routing.settings.clone();
        repaired.rules[0].target = "new".into();
        assert_eq!(
            nodes
                .normalize_settings(repaired)
                .unwrap()
                .global_target
                .as_deref(),
            Some("new")
        );
        std::fs::remove_dir_all(dir).unwrap();
    }
    #[tokio::test]
    async fn storage_failure_does_not_publish_unsaved_preferences() {
        let dir = std::env::temp_dir().join(format!(
            "capybara-routing-write-test-{}",
            uuid::Uuid::new_v4()
        ));
        std::fs::create_dir_all(&dir).unwrap();
        let mut nodes = Nodes::new(&dir);
        // A directory at the temporary-file path deterministically prevents atomic write on all OSes.
        std::fs::create_dir(dir.join("routing.tmp")).unwrap();
        let settings = RoutingSettings {
            mode: crate::routing::RoutingMode::Direct,
            ..Default::default()
        };
        assert!(nodes.apply_settings(settings).await.is_err());
        assert_eq!(
            nodes.routing.settings.mode,
            crate::routing::RoutingMode::Rule
        );
        assert!(!dir.join("routing.json").exists());
        std::fs::remove_dir_all(dir).unwrap();
    }
    #[test]
    fn measurements_are_deduplicated_and_cleared_when_config_changes() {
        let mut nodes = Nodes::default();
        nodes.view.routes = vec![Route {
            group: "A".into(),
            selected: "one".into(),
            choices: vec!["one".into(), "two".into(), "one".into()],
        }];
        nodes.view.routes[0]
            .choices
            .extend(["DIRECT".into(), "fallback".into(), "udp".into()]);
        let targets = probe_targets("proxies: [{name: one, type: vless, server: host, port: 443}, {name: two, type: trojan, server: HOST, port: '443'}, {name: udp, type: tuic, server: host, port: 443}]", &nodes.view).unwrap();
        assert_eq!(targets.names, ["one", "two", "udp"]);
        assert_eq!(targets.entries.len(), 1);
        assert_eq!(targets.entries[&("host".into(), 443)], ["one", "two"]);
        nodes.view.testing = true;
        nodes.view.delays.insert(
            "one".into(),
            Delay {
                status: "ok".into(),
                ms: Some(45),
            },
        );
        let generation = nodes.generation;
        nodes.stop().unwrap();
        assert!(nodes.generation > generation);
        assert!(!nodes.view.testing);
        assert!(nodes.view.routes.is_empty() && nodes.view.delays.is_empty());
    }
    #[tokio::test]
    async fn entry_probe_requires_real_address_and_successful_socket() {
        let socket = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = socket.local_addr().unwrap().port();
        assert!(entry_delay(("127.0.0.1".into(), port)).await.is_ok());
        drop(socket);
        assert!(entry_delay(("127.0.0.1".into(), port)).await.is_err());
        assert_eq!(
            entry_delay(("198.18.0.1".into(), port)).await.unwrap_err(),
            "无真实地址"
        );
    }
    #[tokio::test]
    async fn probes_are_bounded_incremental_and_ignore_results_after_logout() {
        use std::sync::atomic::{AtomicUsize, Ordering};
        let nodes = Arc::new(Mutex::new(Nodes::default()));
        nodes.lock().await.view.testing = true;
        let running = Arc::new(AtomicUsize::new(0));
        let peak = Arc::new(AtomicUsize::new(0));
        let starts = Arc::new(AtomicUsize::new(0));
        let permit = Arc::new(tokio::sync::Semaphore::new(0));
        let task = tokio::spawn({
            let nodes = nodes.clone();
            let running = running.clone();
            let peak = peak.clone();
            let starts = starts.clone();
            let permit = permit.clone();
            async move {
                let jobs = (0..20).map(|i| {
                    let (running, peak, starts, permit) = (
                        running.clone(),
                        peak.clone(),
                        starts.clone(),
                        permit.clone(),
                    );
                    async move {
                        let count = running.fetch_add(1, Ordering::SeqCst) + 1;
                        peak.fetch_max(count, Ordering::SeqCst);
                        starts.fetch_add(1, Ordering::SeqCst);
                        permit.acquire().await.unwrap().forget();
                        running.fetch_sub(1, Ordering::SeqCst);
                        (vec![i.to_string()], Ok(38))
                    }
                });
                run_probes(&nodes, 0, jobs, false).await;
            }
        });
        tokio::time::timeout(std::time::Duration::from_secs(2), async {
            while starts.load(Ordering::SeqCst) < PROBE_CONCURRENCY {
                tokio::task::yield_now().await;
            }
        })
        .await
        .unwrap();
        assert_eq!(starts.load(Ordering::SeqCst), PROBE_CONCURRENCY);
        permit.add_permits(1);
        tokio::time::timeout(std::time::Duration::from_secs(2), async {
            while nodes.lock().await.view.delays.is_empty() {
                tokio::task::yield_now().await;
            }
        })
        .await
        .unwrap();
        assert!(nodes.lock().await.view.testing); // partial results while others are still running
        nodes.lock().await.stop().unwrap();
        permit.add_permits(PROBE_CONCURRENCY);
        task.await.unwrap();
        assert!(peak.load(Ordering::SeqCst) <= PROBE_CONCURRENCY);
        assert!(starts.load(Ordering::SeqCst) <= PROBE_CONCURRENCY + 1); // no new work after invalidation
        assert!(nodes.lock().await.view.delays.is_empty());
    }
}
