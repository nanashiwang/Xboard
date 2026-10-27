use crate::{
    account, private_write, proxy,
    routing::{RoutingMode, RoutingSettings},
};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{
    io::{BufRead, BufReader, Write},
    path::{Path, PathBuf},
    process::{Child, ChildStdin, Command, Stdio},
    time::{Duration, Instant},
};
#[derive(Serialize, Deserialize)]
struct Launch {
    dir: PathBuf,
    binary: PathBuf,
    port: u16,
    api: u16,
    secret: String,
}
#[derive(Clone, Serialize, Deserialize, Default)]
pub struct Route {
    pub group: String,
    pub selected: String,
    pub choices: Vec<String>,
}
pub struct Engine {
    worker: Child,
    input: ChildStdin,
    control: Controller,
    content: String,
    settings: RoutingSettings,
}
#[derive(Clone)]
pub struct Controller {
    pub port: u16,
    api: u16,
    secret: String,
}
struct ExpectedConfig {
    mode: String,
    port: u16,
    targets: Vec<String>,
    global_choices: Vec<String>,
    rule_count: usize,
}
impl ExpectedConfig {
    fn from_yaml(content: &str) -> Result<Self, String> {
        let config: serde_yaml::Value =
            serde_yaml::from_str(content).map_err(|_| "无法读取内核启动配置")?;
        let mode = config["mode"]
            .as_str()
            .ok_or("内核启动模式无效")?
            .to_owned();
        let port = config["mixed-port"]
            .as_u64()
            .and_then(|p| u16::try_from(p).ok())
            .filter(|p| *p > 0)
            .ok_or("内核启动端口无效")?;
        let mut targets = Vec::new();
        for key in ["proxies", "proxy-groups"] {
            for item in config[key].as_sequence().ok_or("内核启动节点无效")? {
                targets.push(
                    item["name"]
                        .as_str()
                        .ok_or("内核启动节点名称无效")?
                        .to_owned(),
                );
            }
        }
        let global = config["proxy-groups"]
            .as_sequence()
            .unwrap()
            .iter()
            .find(|group| group["name"].as_str() == Some("GLOBAL"))
            .ok_or("内核缺少全局分流组")?;
        let global_choices: Vec<String> = global["proxies"]
            .as_sequence()
            .ok_or("内核全局节点无效")?
            .iter()
            .map(|v| v.as_str().map(str::to_owned).ok_or("内核全局节点无效"))
            .collect::<Result<_, _>>()?;
        if global_choices.is_empty() {
            return Err("内核缺少全局代理节点".into());
        }
        let rule_count = config["rules"]
            .as_sequence()
            .ok_or("内核启动规则无效")?
            .len();
        Ok(Self {
            mode,
            port,
            targets,
            global_choices,
            rule_count,
        })
    }
    fn matches(&self, general: &Value, proxies: &Value, rules: &Value) -> bool {
        let map = &proxies["proxies"];
        general["mode"].as_str() == Some(self.mode.as_str())
            && general["mixed-port"].as_u64() == Some(u64::from(self.port))
            && self.targets.iter().all(|name| map[name].is_object())
            && map["GLOBAL"]["type"] == "Selector"
            && map["GLOBAL"]["now"].as_str() == self.global_choices.first().map(String::as_str)
            && map["GLOBAL"]["all"] == json!(self.global_choices)
            && rules["rules"]
                .as_array()
                .is_some_and(|rules| rules.len() == self.rule_count)
    }
}
impl std::ops::Deref for Engine {
    type Target = Controller;
    fn deref(&self) -> &Controller {
        &self.control
    }
}
#[allow(unused_mut)]
fn cmd(binary: impl AsRef<std::ffi::OsStr>) -> Command {
    let mut c = Command::new(binary);
    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        c.creation_flags(0x08000000);
    }
    c
}
fn port() -> Result<u16, String> {
    std::net::TcpListener::bind("127.0.0.1:0")
        .and_then(|s| s.local_addr())
        .map(|a| a.port())
        .map_err(|_| "无法分配本地连接端口".into())
}
pub fn sanitize(content: &str, port: u16, api: u16, secret: &str) -> Result<String, String> {
    sanitize_routing(content, port, api, secret, &RoutingSettings::default())
}
pub fn routing_targets(content: &str) -> Result<Vec<String>, String> {
    let source: serde_yaml::Mapping =
        serde_yaml::from_str(content).map_err(|_| "订阅配置格式无效")?;
    let mut targets = Vec::new();
    for key in ["proxy-groups", "proxies"] {
        if let Some(items) = source
            .get(serde_yaml::Value::String(key.into()))
            .and_then(|v| v.as_sequence())
        {
            for item in items {
                if let Some(name) = item.get("name").and_then(|v| v.as_str()) {
                    if !["DIRECT", "REJECT", "GLOBAL"].contains(&name)
                        && !name.chars().any(|c| c.is_control() || c == ',')
                        && !targets.iter().any(|v| v == name)
                    {
                        targets.push(name.to_owned());
                    }
                }
            }
        }
    }
    Ok(targets)
}
pub fn global_targets(content: &str) -> Result<Vec<String>, String> {
    let source: serde_yaml::Mapping =
        serde_yaml::from_str(content).map_err(|_| "订阅配置格式无效")?;
    Ok(source
        .get(serde_yaml::Value::String("proxies".into()))
        .and_then(|v| v.as_sequence())
        .into_iter()
        .flatten()
        .filter_map(|proxy| proxy.get("name").and_then(|v| v.as_str()))
        .filter(|name| {
            !["DIRECT", "REJECT", "GLOBAL"].contains(name)
                && !name.chars().any(|c| c.is_control() || c == ',')
        })
        .map(str::to_owned)
        .collect())
}
// Global applies to public destinations; private networks must remain reachable locally.
const PRIVATE_RULES: &[&str] = &[
    "DOMAIN-SUFFIX,localhost,DIRECT",
    "DOMAIN-SUFFIX,local,DIRECT",
    "IP-CIDR,10.0.0.0/8,DIRECT",
    "IP-CIDR,100.64.0.0/10,DIRECT",
    "IP-CIDR,127.0.0.0/8,DIRECT",
    "IP-CIDR,169.254.0.0/16,DIRECT",
    "IP-CIDR,172.16.0.0/12,DIRECT",
    "IP-CIDR,192.168.0.0/16,DIRECT",
    "IP-CIDR6,::1/128,DIRECT",
    "IP-CIDR6,fc00::/7,DIRECT",
    "IP-CIDR6,fe80::/10,DIRECT",
];
fn core_mode(mode: RoutingMode) -> &'static str {
    match mode {
        RoutingMode::Global => "rule",
        _ => mode.as_str(),
    }
}
fn sanitize_routing(
    content: &str,
    port: u16,
    api: u16,
    secret: &str,
    settings: &RoutingSettings,
) -> Result<String, String> {
    settings.validate(Some(&routing_targets(content)?))?;
    let source: serde_yaml::Mapping =
        serde_yaml::from_str(content).map_err(|_| "订阅配置格式无效")?;
    // Keep only subscription data and rule semantics; never inherit listeners, TUN, scripts or local paths.
    let mut output = serde_yaml::Mapping::new();
    for key in [
        "proxies",
        "proxy-groups",
        "rules",
        "dns",
        "hosts",
        "unified-delay",
        "tcp-concurrent",
        "ipv6",
    ] {
        if let Some(v) = source.get(serde_yaml::Value::String(key.into())) {
            output.insert(key.into(), v.clone());
        }
    }
    if let Some(proxies) = output
        .get(serde_yaml::Value::String("proxies".into()))
        .and_then(|v| v.as_sequence())
    {
        if proxies.is_empty() {
            return Err("当前套餐没有可用线路".into());
        }
        for p in proxies {
            for key in [
                "private-key-path",
                "certificate-path",
                "ca-cert",
                "ca-cert-path",
            ] {
                if p.get(key).is_some() {
                    return Err("订阅包含不支持的本地证书路径".into());
                }
            }
        }
    } else {
        return Err("当前套餐没有可用线路".into());
    }
    // Define GLOBAL in the configuration itself, so a live global-mode reload never briefly
    // exposes Mihomo's implicit DIRECT default before a later controller selection arrives.
    let mut global_choices = global_targets(content)?;
    if let Some(target) = &settings.global_target {
        if !global_choices.contains(target) {
            return Err("全局代理目标必须是当前订阅中的节点".into());
        }
        global_choices.retain(|name| name != target);
        global_choices.insert(0, target.clone());
    }
    if global_choices.is_empty() {
        return Err("当前没有可用的代理节点".into());
    }
    let groups = output
        .entry(serde_yaml::Value::String("proxy-groups".into()))
        .or_insert_with(|| serde_yaml::Value::Sequence(vec![]));
    let groups = groups.as_sequence_mut().ok_or("订阅分流组格式无效")?;
    groups.retain(|group| group.get("name").and_then(|value| value.as_str()) != Some("GLOBAL"));
    groups.push(
        serde_yaml::to_value(json!({"name":"GLOBAL", "type":"select", "proxies":global_choices}))
            .map_err(|_| "无法生成全局分流组")?,
    );
    for (key, value) in [
        ("mixed-port", json!(port)),
        ("port", json!(0)),
        ("socks-port", json!(0)),
        ("redir-port", json!(0)),
        ("tproxy-port", json!(0)),
        ("allow-lan", json!(false)),
        ("bind-address", json!("127.0.0.1")),
        ("mode", json!(core_mode(settings.mode))),
        ("log-level", json!("silent")),
        ("external-controller", json!(format!("127.0.0.1:{api}"))),
        ("secret", json!(secret)),
        ("tun", json!({"enable":false})),
        (
            "profile",
            json!({"store-selected":false,"store-fake-ip":false}),
        ),
    ] {
        output.insert(
            key.into(),
            serde_yaml::to_value(value).map_err(|_| "无法生成配置")?,
        );
    }
    if let Some(dns) = output
        .get_mut(serde_yaml::Value::String("dns".into()))
        .and_then(|v| v.as_mapping_mut())
    {
        dns.remove(serde_yaml::Value::String("listen".into()));
        // Direct connections should use the same resolver as other local applications.
        // Preserve an explicit subscription choice and all public/proxy DNS policies.
        dns.entry(serde_yaml::Value::String("direct-nameserver".into()))
            .or_insert_with(|| serde_yaml::to_value(["system"]).unwrap());
    }
    // User overrides remain first in rule mode. Private IP rules must resolve domains:
    // no-resolve would miss an intranet name resolved only by a later GEOIP rule.
    let existing = output
        .entry(serde_yaml::Value::String("rules".into()))
        .or_insert_with(|| serde_yaml::Value::Sequence(vec![]));
    let rules = existing.as_sequence_mut().ok_or("订阅规则格式无效")?;
    if settings.mode == RoutingMode::Global {
        *rules = PRIVATE_RULES.iter().map(|rule| (*rule).into()).collect();
        rules.push("MATCH,GLOBAL".into());
    } else {
        rules.splice(0..0, PRIVATE_RULES.iter().map(|rule| (*rule).into()));
        rules.insert(0, "DOMAIN,taige.us,DIRECT".into());
        for rule in settings.rules.iter().rev() {
            rules.insert(0, rule.line().into());
        }
    }
    serde_yaml::to_string(&output).map_err(|_| "无法生成本地配置".into())
}
impl Engine {
    pub async fn routes(&self) -> Result<Vec<Route>, String> {
        self.control.routes(self.settings.mode).await
    }
    pub async fn start(
        dir: &Path,
        binary: PathBuf,
        content: &str,
        settings: &RoutingSettings,
    ) -> Result<Self, String> {
        let port = port()?;
        let api = port_fn(port)?;
        let secret = uuid::Uuid::new_v4().to_string();
        let config = sanitize_routing(content, port, api, &secret, settings)?;
        private_write(&dir.join("runtime.yaml"), config.as_bytes())?;
        let launch = Launch {
            dir: dir.into(),
            binary,
            port,
            api,
            secret: secret.clone(),
        };
        let mut worker = cmd(std::env::current_exe().map_err(|_| "无法定位桌面程序")?)
            .arg("--capybara-engine")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|_| "无法启动连接管理进程")?;
        let mut input = worker.stdin.take().ok_or("无法连接管理进程")?;
        if writeln!(
            input,
            "{}",
            serde_json::to_string(&launch).map_err(|_| "无法初始化连接")?
        )
        .is_err()
        {
            let _ = worker.kill();
            return Err("无法初始化连接进程".into());
        }
        let stdout = worker.stdout.take().ok_or("无法读取连接状态")?;
        let result = tauri::async_runtime::spawn_blocking(move || {
            let mut line = String::new();
            BufReader::new(stdout)
                .read_line(&mut line)
                .map_err(|_| "无法读取内核状态")?;
            serde_json::from_str::<Value>(&line)
                .map_err(|_| "内核启动失败，请检查系统代理权限或防火墙")
        })
        .await
        .map_err(|_| "连接进程异常")?;
        match result {
            Ok(value) if value["ready"] == true => {
                let mut engine = Self {
                    worker,
                    input,
                    control: Controller { port, api, secret },
                    content: content.to_owned(),
                    settings: settings.clone(),
                };
                if let Err(error) = engine.control.confirm_routing(content, settings).await {
                    let _ = engine.stop();
                    return Err(error);
                }
                Ok(engine)
            }
            other => {
                let _ = writeln!(input, "stop");
                let _ = worker.wait();
                Err(other
                    .ok()
                    .and_then(|v| v["error"].as_str().map(str::to_owned))
                    .unwrap_or_else(|| "内核启动失败，请检查网络和系统代理权限".into()))
            }
        }
    }
    pub async fn checkpoint(&self) -> Result<(String, RoutingSettings, Vec<Route>), String> {
        Ok((
            self.content.clone(),
            self.settings.clone(),
            self.control.all_routes().await?,
        ))
    }
    pub async fn selection_for_mode(
        &self,
        settings: &mut RoutingSettings,
        rule_group: Option<&str>,
    ) -> Result<Vec<Route>, String> {
        let data = self
            .control
            .call(reqwest::Method::GET, "/proxies", None)
            .await?;
        mode_selection(
            &data,
            self.settings.mode,
            settings,
            rule_group,
            &global_targets(&self.content)?,
        )
    }
    pub async fn reload(
        &mut self,
        content: &str,
        settings: &RoutingSettings,
        selection: Option<&[Route]>,
    ) -> Result<(), String> {
        // Compose and validate before touching the running core. Roll back even on an ambiguous timeout.
        let config = sanitize_routing(content, self.port, self.api, &self.secret, settings)?;
        let selected = self.control.all_routes().await?;
        if let Err(error) = self
            .control
            .apply_config(&config, content, settings, selection.unwrap_or(&selected))
            .await
        {
            let old = sanitize_routing(
                &self.content,
                self.port,
                self.api,
                &self.secret,
                &self.settings,
            )?;
            if self
                .control
                .apply_config(&old, &self.content, &self.settings, &selected)
                .await
                .is_err()
            {
                let _ = self.stop();
                return Err("分流更新失败，旧配置恢复失败，连接组件已停止，请重新连接".into());
            }
            return Err(error);
        }
        self.content = content.to_owned();
        self.settings = settings.clone();
        Ok(())
    }
    pub fn remember_global_target(&mut self, target: String) {
        self.settings.global_target = Some(target);
    }
    pub fn alive(&mut self) -> bool {
        matches!(self.worker.try_wait(), Ok(None))
    }
    pub fn stop(&mut self) -> Result<(), String> {
        let _ = writeln!(self.input, "stop");
        let status = self.worker.wait().map_err(|_| "无法停止连接进程")?;
        if status.success() {
            Ok(())
        } else {
            Err("连接已停止，但代理恢复未完成，请重启应用修复".into())
        }
    }
}
impl Controller {
    async fn wait_ready<F>(
        &self,
        expected: &ExpectedConfig,
        timeout: Duration,
        mut check_lifecycle: F,
    ) -> Result<(), String>
    where
        F: FnMut() -> Result<(), String>,
    {
        let client = account::http()?;
        let started = Instant::now();
        loop {
            check_lifecycle()?;
            let remaining = timeout
                .checked_sub(started.elapsed())
                .filter(|remaining| !remaining.is_zero())
                .ok_or("内核配置加载超时，请检查线路配置或安全软件")?;
            // The controller starts before Mihomo installs proxies, rules and listeners. A version
            // response cannot prove readiness. Check the complete startup contract with a deadline.
            let result = tokio::time::timeout(remaining.min(Duration::from_millis(800)), async {
                let mut data = Vec::new();
                for path in ["/configs", "/proxies", "/rules"] {
                    let response = match client
                        .get(format!("http://127.0.0.1:{}{path}", self.api))
                        .bearer_auth(&self.secret)
                        .send()
                        .await
                    {
                        Ok(response) => response,
                        Err(_) => return Ok(false),
                    };
                    if matches!(
                        response.status(),
                        reqwest::StatusCode::UNAUTHORIZED | reqwest::StatusCode::FORBIDDEN
                    ) {
                        return Err("本地连接组件鉴权失败，请重新启动客户端".to_owned());
                    }
                    if !response.status().is_success() {
                        return Ok(false);
                    }
                    let value = match response.json::<Value>().await {
                        Ok(value) => value,
                        Err(_) => return Ok(false),
                    };
                    data.push(value);
                }
                if !expected.matches(&data[0], &data[1], &data[2]) {
                    return Ok(false);
                }
                // GetPorts normally reflects an active listener; also reject a socket closed after
                // a partial listener setup failure. This probe does not change the system proxy.
                Ok(
                    tokio::net::TcpStream::connect((std::net::Ipv4Addr::LOCALHOST, expected.port))
                        .await
                        .is_ok(),
                )
            })
            .await;
            if let Ok(result) = result {
                if result? {
                    check_lifecycle()?;
                    return Ok(());
                }
            }
            let remaining = timeout.saturating_sub(started.elapsed());
            tokio::time::sleep(remaining.min(Duration::from_millis(200))).await;
        }
    }
    async fn call(
        &self,
        method: reqwest::Method,
        path: &str,
        body: Option<Value>,
    ) -> Result<Value, String> {
        let mut request = account::http()?
            .request(method, format!("http://127.0.0.1:{}{path}", self.api))
            .bearer_auth(&self.secret)
            .timeout(Duration::from_secs(3));
        if let Some(body) = body {
            request = request.json(&body);
        }
        let response = request
            .send()
            .await
            .map_err(|_| "本地连接组件没有响应")?
            .error_for_status()
            .map_err(|_| "本地连接操作失败")?;
        if response.status() == reqwest::StatusCode::NO_CONTENT {
            return Ok(Value::Null);
        }
        response.json().await.map_err(|_| "本地连接响应无效".into())
    }
    async fn apply_config(
        &self,
        config: &str,
        content: &str,
        settings: &RoutingSettings,
        selected: &[Route],
    ) -> Result<(), String> {
        let config = selected_config(config, selected)?;
        self.call(
            reqwest::Method::PUT,
            "/configs?force=true",
            Some(json!({"payload": config})),
        )
        .await?;
        let available = self.all_routes().await?;
        for route in selected {
            if route.group != "GLOBAL"
                && available
                    .iter()
                    .any(|r| r.group == route.group && r.choices.contains(&route.selected))
            {
                self.select(&route.group, &route.selected).await?;
            }
        }
        let confirmed = self.all_routes().await?;
        for route in selected {
            if route.group != "GLOBAL"
                && available
                    .iter()
                    .any(|r| r.group == route.group && r.choices.contains(&route.selected))
                && !confirmed
                    .iter()
                    .any(|r| r.group == route.group && r.selected == route.selected)
            {
                return Err("分流组节点未能生效".into());
            }
        }
        self.confirm_routing(content, settings).await
    }
    async fn confirm_routing(
        &self,
        content: &str,
        settings: &RoutingSettings,
    ) -> Result<(), String> {
        // Mihomo's built-in GLOBAL selector starts at DIRECT. Always select a real subscription target.
        let targets = global_targets(content)?;
        if let Some(target) = settings.global_target.as_ref().or_else(|| targets.first()) {
            self.select("GLOBAL", target).await?;
            let routes = self.all_routes().await?;
            if !routes
                .iter()
                .any(|r| r.group == "GLOBAL" && &r.selected == target)
            {
                return Err("全局代理目标未能生效".into());
            }
        } else if settings.mode == RoutingMode::Global {
            return Err("当前没有可用的全局代理节点".into());
        }
        // Rule and public-global share the core's rule mode. Confirm the generated rule
        // count and complete proxy contract too, so mode alone cannot accept a stale reload.
        let expected = ExpectedConfig::from_yaml(&sanitize_routing(
            content,
            self.port,
            self.api,
            &self.secret,
            settings,
        )?)?;
        let config = self.call(reqwest::Method::GET, "/configs", None).await?;
        let proxies = self.call(reqwest::Method::GET, "/proxies", None).await?;
        let rules = self.call(reqwest::Method::GET, "/rules", None).await?;
        if !expected.matches(&config, &proxies, &rules) {
            return Err("分流配置未能生效".into());
        }
        Ok(())
    }
    async fn all_routes(&self) -> Result<Vec<Route>, String> {
        let data = self.call(reqwest::Method::GET, "/proxies", None).await?;
        selector_routes(&data)
    }
    async fn routes(&self, mode: RoutingMode) -> Result<Vec<Route>, String> {
        let config = self.call(reqwest::Method::GET, "/configs", None).await?;
        if config["mode"].as_str() != Some(core_mode(mode)) {
            return Err("分流模式未能生效".into());
        }
        let global = mode == RoutingMode::Global;
        if mode == RoutingMode::Direct {
            return Ok(vec![]);
        }
        let mut routes: Vec<Route> = self
            .all_routes()
            .await?
            .into_iter()
            .filter(|r| (r.group == "GLOBAL") == global)
            .collect();
        if global {
            for route in &mut routes {
                route
                    .choices
                    .retain(|name| name != "DIRECT" && name != "REJECT" && name != "GLOBAL");
            }
        }
        Ok(routes)
    }
    pub async fn select(&self, group: &str, name: &str) -> Result<(), String> {
        let mut url = reqwest::Url::parse("http://localhost").map_err(|_| "地址无效")?;
        url.path_segments_mut().map_err(|_| "地址无效")?.push(group);
        let encoded = url.path();
        self.call(
            reqwest::Method::PUT,
            &format!("/proxies{encoded}"),
            Some(json!({"name":name})),
        )
        .await?;
        Ok(())
    }
    pub async fn delay(&self, name: &str) -> Result<u64, String> {
        self.delay_at(name, "https://www.gstatic.com/generate_204")
            .await
    }
    async fn delay_at(&self, name: &str, target: &str) -> Result<u64, String> {
        let mut url = reqwest::Url::parse(&format!("http://127.0.0.1:{}", self.api))
            .map_err(|_| "测速地址无效")?;
        url.path_segments_mut()
            .map_err(|_| "测速地址无效")?
            .extend(["proxies", name, "delay"]);
        url.query_pairs_mut()
            .append_pair("url", target)
            .append_pair("timeout", "5000")
            .append_pair("expected", "204");
        let response = account::http()?
            .get(url)
            .bearer_auth(&self.secret)
            .timeout(Duration::from_secs(6))
            .send()
            .await
            .map_err(|_| "测速超时")?;
        if response.status() == reqwest::StatusCode::GATEWAY_TIMEOUT {
            return Err("超时".into());
        }
        let data: Value = response
            .error_for_status()
            .map_err(|_| "不可达")?
            .json()
            .await
            .map_err(|_| "测速响应无效")?;
        data["delay"]
            .as_u64()
            .filter(|v| *v > 0)
            .ok_or_else(|| "不可达".into())
    }
    pub async fn check(&self) -> Result<(), String> {
        let proxy = reqwest::Proxy::all(format!("http://127.0.0.1:{}", self.port))
            .map_err(|_| "检测代理地址无效")?;
        let client = reqwest::Client::builder()
            .no_proxy()
            .proxy(proxy)
            .redirect(reqwest::redirect::Policy::none())
            .timeout(Duration::from_secs(12))
            .build()
            .map_err(|_| "无法初始化连接检测")?;
        let response = client
            .get("https://www.gstatic.com/generate_204")
            .send()
            .await
            .map_err(|_| "线路暂时无法访问检测站点，可切换线路或重试")?;
        if response.status() != reqwest::StatusCode::NO_CONTENT {
            return Err("线路连通检测未通过，可切换线路或重试".into());
        }
        Ok(())
    }
}
fn selector_routes(data: &Value) -> Result<Vec<Route>, String> {
    let map = data["proxies"].as_object().ok_or("线路数据无效")?;
    Ok(map
        .iter()
        .filter(|(_, v)| v["type"] == "Selector")
        .map(|(name, v)| Route {
            group: name.clone(),
            selected: v["now"].as_str().unwrap_or("").into(),
            choices: v["all"]
                .as_array()
                .map(|a| {
                    a.iter()
                        .filter_map(|v| v.as_str().map(str::to_owned))
                        .collect()
                })
                .unwrap_or_default(),
        })
        .collect())
}

fn resolved_node(data: &Value, name: &str, targets: &[String]) -> Option<String> {
    let mut name = name;
    let mut seen = std::collections::BTreeSet::new();
    while seen.insert(name) {
        if targets.iter().any(|target| target == name) {
            return Some(name.to_owned());
        }
        name = data["proxies"][name]["now"].as_str()?;
    }
    None
}

fn mode_selection(
    data: &Value,
    previous: RoutingMode,
    settings: &mut RoutingSettings,
    rule_group: Option<&str>,
    targets: &[String],
) -> Result<Vec<Route>, String> {
    let mut routes = selector_routes(data)?;
    if previous == settings.mode || previous == RoutingMode::Direct {
        return Ok(routes);
    }
    // Home uses the first rule selector when no explicit group is selected (or it was removed).
    let index = rule_group
        .and_then(|group| {
            routes
                .iter()
                .position(|r| r.group == group && r.group != "GLOBAL")
        })
        .or_else(|| routes.iter().position(|r| r.group != "GLOBAL"));
    let Some(index) = index else {
        return Ok(routes);
    };
    if previous == RoutingMode::Rule {
        if let Some(target) = resolved_node(data, &routes[index].selected, targets) {
            settings.global_target = Some(target);
        }
    } else if let Some(target) = resolved_node(data, "GLOBAL", targets) {
        // Keep an automatic/nested choice if it already resolves to this node.
        if resolved_node(data, &routes[index].selected, targets).as_ref() != Some(&target) {
            if !routes[index].choices.contains(&target) {
                return Err("当前分流组不包含已选节点，请先在全局模式选择该组支持的节点".into());
            }
            routes[index].selected = target.clone();
        }
        settings.global_target = Some(target);
    }
    Ok(routes)
}

fn selected_config(config: &str, selected: &[Route]) -> Result<String, String> {
    let mut data: serde_yaml::Value =
        serde_yaml::from_str(config).map_err(|_| "本地分流配置无效")?;
    if let Some(groups) = data
        .get_mut("proxy-groups")
        .and_then(|v| v.as_sequence_mut())
    {
        for group in groups {
            let Some(name) = group.get("name").and_then(|v| v.as_str()) else {
                continue;
            };
            if name == "GLOBAL" || group.get("type").and_then(|v| v.as_str()) != Some("select") {
                continue;
            }
            let Some(route) = selected.iter().find(|route| route.group == name) else {
                continue;
            };
            if let Some(choices) = group.get_mut("proxies").and_then(|v| v.as_sequence_mut()) {
                if let Some(index) = choices
                    .iter()
                    .position(|v| v.as_str() == Some(&route.selected))
                {
                    let current = choices.remove(index);
                    choices.insert(0, current);
                }
            }
        }
    }
    serde_yaml::to_string(&data).map_err(|_| "无法保留已选节点".into())
}
fn port_fn(other: u16) -> Result<u16, String> {
    for _ in 0..10 {
        let p = port()?;
        if p != other {
            return Ok(p);
        }
    }
    Err("无法分配内核端口".into())
}
impl Drop for Engine {
    fn drop(&mut self) {
        let _ = writeln!(self.input, "stop");
    }
}

pub fn worker_main() -> i32 {
    let mut stdin = BufReader::new(std::io::stdin());
    let mut line = String::new();
    if stdin.read_line(&mut line).is_err() {
        return 1;
    }
    let launch: Launch = match serde_json::from_str(&line) {
        Ok(v) => v,
        Err(_) => return 1,
    };
    let runtime = match tokio::runtime::Runtime::new() {
        Ok(r) => r,
        Err(_) => return 1,
    };
    let expected = match std::fs::read_to_string(launch.dir.join("runtime.yaml"))
        .map_err(|_| "无法读取内核启动配置".to_owned())
        .and_then(|config| ExpectedConfig::from_yaml(&config))
    {
        Ok(expected) => expected,
        Err(error) => {
            println!("{}", json!({"error":error}));
            return 1;
        }
    };
    let mut core = match cmd(&launch.binary)
        .arg("-d")
        .arg(&launch.dir)
        .arg("-f")
        .arg(launch.dir.join("runtime.yaml"))
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
    {
        Ok(c) => c,
        Err(_) => {
            println!(
                "{}",
                json!({"error":"未找到代理内核，请重新安装完整客户端"})
            );
            return 1;
        }
    };
    let (tx, rx) = std::sync::mpsc::channel();
    std::thread::spawn(move || {
        let mut line = String::new();
        let _ = stdin.read_line(&mut line);
        let _ = tx.send(());
    });
    let controller = Controller {
        port: launch.port,
        api: launch.api,
        secret: launch.secret.clone(),
    };
    let ready = runtime.block_on(
        controller.wait_ready(&expected, Duration::from_secs(35), || {
            if rx.try_recv().is_ok() {
                return Err("连接已取消".to_string());
            }
            if !matches!(core.try_wait(), Ok(None)) {
                return Err("内核未能加载配置，请检查线路配置或重新连接".into());
            }
            Ok(())
        }),
    );
    if let Err(error) = ready {
        let _ = core.kill();
        let _ = core.wait();
        let recovery = proxy::recover(&launch.dir);
        println!(
            "{}",
            json!({"error":if recovery.is_err(){"代理恢复失败，请重启应用修复".to_owned()}else{error}})
        );
        let _ = std::fs::remove_file(launch.dir.join("runtime.yaml"));
        return 1;
    }
    println!("{}", json!({"ready":true}));
    let _ = std::io::stdout().flush();
    loop {
        if rx.recv_timeout(Duration::from_millis(500)).is_ok()
            || !matches!(core.try_wait(), Ok(None))
        {
            break;
        }
    }
    let recovery = proxy::recover(&launch.dir);
    let _ = core.kill();
    let _ = core.wait();
    let _ = std::fs::remove_file(launch.dir.join("runtime.yaml"));
    if recovery.is_ok() {
        0
    } else {
        1
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    pub(super) struct ReadinessServer {
        pub(super) api: u16,
        stop: std::sync::Arc<std::sync::atomic::AtomicBool>,
        thread: Option<std::thread::JoinHandle<Result<(), String>>>,
    }
    impl ReadinessServer {
        pub(super) fn finish(mut self) -> Result<(), String> {
            self.stop.store(true, std::sync::atomic::Ordering::SeqCst);
            self.thread
                .take()
                .unwrap()
                .join()
                .map_err(|_| "模拟控制器断言失败".to_owned())?
        }
    }
    impl Drop for ReadinessServer {
        fn drop(&mut self) {
            self.stop.store(true, std::sync::atomic::Ordering::SeqCst);
            if let Some(thread) = self.thread.take() {
                // Tests explicitly call finish on success. Cleanup must not panic again while a
                // client assertion is already unwinding and hide the original test failure.
                let _ = thread.join();
            }
        }
    }
    pub(super) fn read_headers(
        socket: &mut std::net::TcpStream,
        stop: &std::sync::atomic::AtomicBool,
    ) -> std::io::Result<Option<String>> {
        use std::io::Read;
        // Winsock accepted sockets retain the listener's nonblocking mode. Explicitly
        // restore blocking reads so the bounded read timeout applies on every platform.
        socket.set_nonblocking(false)?;
        let started = Instant::now();
        let mut request = Vec::new();
        while started.elapsed() < Duration::from_secs(2)
            && !stop.load(std::sync::atomic::Ordering::SeqCst)
        {
            socket.set_read_timeout(Some(Duration::from_millis(100)))?;
            let mut chunk = [0; 1024];
            match socket.read(&mut chunk) {
                Ok(0) => return Ok(None), // The deadline may cancel a connection before headers arrive.
                Ok(size) => {
                    request.extend_from_slice(&chunk[..size]);
                    if request.len() > 16 * 1024 {
                        return Err(std::io::Error::new(
                            std::io::ErrorKind::InvalidData,
                            "请求头过大",
                        ));
                    }
                    if request.windows(4).any(|bytes| bytes == b"\r\n\r\n") {
                        return String::from_utf8(request).map(Some).map_err(|_| {
                            std::io::Error::new(std::io::ErrorKind::InvalidData, "请求头不是UTF-8")
                        });
                    }
                }
                Err(error)
                    if matches!(
                        error.kind(),
                        std::io::ErrorKind::Interrupted
                            | std::io::ErrorKind::WouldBlock
                            | std::io::ErrorKind::TimedOut
                    ) =>
                {
                    continue
                }
                Err(error)
                    if matches!(
                        error.kind(),
                        std::io::ErrorKind::ConnectionReset | std::io::ErrorKind::ConnectionAborted
                    ) =>
                {
                    return Ok(None)
                }
                Err(error) => return Err(error),
            }
        }
        Ok(None)
    }
    pub(super) fn readiness_server<F>(response: F) -> ReadinessServer
    where
        F: Fn(&str, &str) -> (u16, Value) + Send + 'static,
    {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let api = listener.local_addr().unwrap().port();
        listener.set_nonblocking(true).unwrap();
        let stop = std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false));
        let done = stop.clone();
        let thread = std::thread::spawn(move || {
            while !done.load(std::sync::atomic::Ordering::SeqCst) {
                match listener.accept() {
                    Ok((mut socket, _)) => {
                        let Some(request) =
                            read_headers(&mut socket, &done).map_err(|error| error.to_string())?
                        else {
                            continue;
                        };
                        let path = request
                            .split_whitespace()
                            .nth(1)
                            .ok_or("模拟请求缺少路径")?;
                        let (status, data) = response(path, &request);
                        let body = data.to_string();
                        // A timed-out readiness request can legitimately close before the response.
                        let _ = write!(socket, "HTTP/1.1 {status} Test\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}", body.len());
                    }
                    Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                        std::thread::sleep(Duration::from_millis(5))
                    }
                    Err(error) => return Err(error.to_string()),
                }
            }
            Ok(())
        });
        ReadinessServer {
            api,
            stop,
            thread: Some(thread),
        }
    }
    fn startup_fixture(port: u16) -> (ExpectedConfig, Value, Value, Value) {
        let config = sanitize("proxies: [{name: one, type: direct}]\nproxy-groups: [{name: group, type: select, proxies: [one]}]\nrules: ['MATCH,group']", port, 19091, "private").unwrap();
        let expected = ExpectedConfig::from_yaml(&config).unwrap();
        let rules = json!({"rules": vec![json!({}); expected.rule_count]});
        (
            expected,
            json!({"mode":"rule", "mixed-port":port}),
            json!({"proxies":{"one":{"type":"Direct"},"group":{"type":"Selector"},"GLOBAL":{"type":"Selector","now":"one","all":["one"]}}}),
            rules,
        )
    }
    #[test]
    fn http_fixture_reads_complete_headers_from_an_initially_nonblocking_socket() {
        use std::io::Read;
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let (accepted, ready) = std::sync::mpsc::channel();
        let server = std::thread::spawn(move || {
            let (mut socket, _) = listener.accept().unwrap();
            socket.set_nonblocking(true).unwrap();
            accepted.send(()).unwrap();
            let request = read_headers(&mut socket, &std::sync::atomic::AtomicBool::new(false))
                .unwrap()
                .expect("complete request headers");
            assert!(request.ends_with("Host: localhost\r\n\r\n"));
            socket
                .write_all(b"HTTP/1.1 204 No Content\r\nConnection: close\r\n\r\n")
                .unwrap();
        });
        let mut socket = std::net::TcpStream::connect(address).unwrap();
        ready.recv_timeout(Duration::from_secs(2)).unwrap();
        socket
            .set_read_timeout(Some(Duration::from_millis(50)))
            .unwrap();
        socket.write_all(b"GET /routing-test HTTP/1.1\r\n").unwrap();
        let mut buffer = [0; 256];
        let pending = socket.read(&mut buffer).unwrap_err();
        assert!(matches!(
            pending.kind(),
            std::io::ErrorKind::WouldBlock | std::io::ErrorKind::TimedOut
        ));
        socket.write_all(b"Host: localhost\r\n\r\n").unwrap();
        socket
            .set_read_timeout(Some(Duration::from_secs(2)))
            .unwrap();
        let mut response = String::new();
        socket.read_to_string(&mut response).unwrap();
        assert!(response.starts_with("HTTP/1.1 204 No Content\r\n"));
        server.join().unwrap();
    }
    #[test]
    fn readiness_server_waits_for_split_headers_and_discards_cancelled_requests() {
        use std::io::Read;
        use std::sync::atomic::{AtomicUsize, Ordering};
        let calls = std::sync::Arc::new(AtomicUsize::new(0));
        let received = calls.clone();
        let server = readiness_server(move |path, request| {
            assert_eq!(path, "/configs");
            assert!(request
                .to_lowercase()
                .contains("authorization: bearer private\r\n"));
            received.fetch_add(1, Ordering::SeqCst);
            (200, json!({"ready":true}))
        });
        // A client may cancel both before sending and in the middle of an HTTP header.
        drop(std::net::TcpStream::connect(("127.0.0.1", server.api)).unwrap());
        let mut cancelled = std::net::TcpStream::connect(("127.0.0.1", server.api)).unwrap();
        cancelled
            .write_all(b"GET /configs HTTP/1.1\r\nAuthor")
            .unwrap();
        drop(cancelled);
        let mut socket = std::net::TcpStream::connect(("127.0.0.1", server.api)).unwrap();
        socket
            .set_read_timeout(Some(Duration::from_secs(10)))
            .unwrap();
        for fragment in [
            b"GET /configs HTTP/1.1\r\nAuthor".as_slice(),
            b"ization: Bearer ",
            b"private\r\nHost: localhost\r\n",
        ] {
            socket.write_all(fragment).unwrap();
            std::thread::sleep(Duration::from_millis(10));
        }
        assert_eq!(calls.load(Ordering::SeqCst), 0);
        socket.write_all(b"\r\n").unwrap();
        let mut response = String::new();
        socket.read_to_string(&mut response).unwrap();
        assert!(response.starts_with("HTTP/1.1 200"));
        assert_eq!(calls.load(Ordering::SeqCst), 1);
        server.finish().unwrap();
    }
    #[test]
    fn startup_requires_mode_nodes_global_selection_and_rules_to_match() {
        let (expected, general, proxies, rules) = startup_fixture(12345);
        assert!(expected.matches(&general, &proxies, &rules));
        assert!(!expected.matches(
            &json!({"mode":"global", "mixed-port":12345}),
            &proxies,
            &rules
        ));
        assert!(!expected.matches(&json!({"mode":"rule", "mixed-port":0}), &proxies, &rules));
        for target in ["one", "group", "GLOBAL"] {
            let mut missing = proxies.clone();
            missing["proxies"].as_object_mut().unwrap().remove(target);
            assert!(!expected.matches(&general, &missing, &rules));
        }
        let mut wrong_global = proxies.clone();
        wrong_global["proxies"]["GLOBAL"]["now"] = json!("DIRECT");
        assert!(!expected.matches(&general, &wrong_global, &rules));
        assert!(!expected.matches(&general, &proxies, &json!({"rules":[]})));
    }
    #[tokio::test]
    async fn startup_waits_for_configuration_after_controller_accepts_requests() {
        use std::sync::atomic::{AtomicUsize, Ordering};
        let mixed = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let (expected, general, proxies, rules) =
            startup_fixture(mixed.local_addr().unwrap().port());
        let attempts = std::sync::Arc::new(AtomicUsize::new(0));
        let probes = attempts.clone();
        let server = readiness_server(move |path, request| {
            assert!(request
                .to_lowercase()
                .contains("authorization: bearer private"));
            (
                200,
                match path {
                    "/configs" => general.clone(),
                    "/proxies" => {
                        if probes.fetch_add(1, Ordering::SeqCst) < 2 {
                            json!({"proxies":{}})
                        } else {
                            proxies.clone()
                        }
                    }
                    "/rules" => rules.clone(),
                    "/version" => json!({"version":"already-listening"}),
                    _ => panic!("unexpected readiness endpoint"),
                },
            )
        });
        let controller = Controller {
            port: expected.port,
            api: server.api,
            secret: "private".into(),
        };
        controller
            .wait_ready(&expected, Duration::from_secs(10), || Ok(()))
            .await
            .unwrap();
        assert!(attempts.load(Ordering::SeqCst) >= 3);
        server.finish().unwrap();
    }
    #[tokio::test]
    async fn startup_rejects_auth_failure_closed_listener_timeout_and_cancellation() {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let (expected, general, proxies, rules) =
            startup_fixture(listener.local_addr().unwrap().port());
        let denied = readiness_server(|_, _| (401, json!({})));
        let controller = Controller {
            port: expected.port,
            api: denied.api,
            secret: "wrong".into(),
        };
        assert!(controller
            .wait_ready(&expected, Duration::from_secs(10), || Ok(()))
            .await
            .unwrap_err()
            .contains("鉴权"));
        denied.finish().unwrap();
        let ready_but_closed = readiness_server(move |path, _| {
            (
                200,
                match path {
                    "/configs" => general.clone(),
                    "/proxies" => proxies.clone(),
                    _ => rules.clone(),
                },
            )
        });
        drop(listener);
        let controller = Controller {
            api: ready_but_closed.api,
            ..controller
        };
        assert!(controller
            .wait_ready(&expected, Duration::from_millis(250), || Ok(()))
            .await
            .unwrap_err()
            .contains("超时"));
        assert_eq!(
            controller
                .wait_ready(&expected, Duration::from_secs(2), || Err(
                    "连接已取消".into()
                ))
                .await
                .unwrap_err(),
            "连接已取消"
        );
        ready_but_closed.finish().unwrap();
    }
    #[test]
    fn config_cannot_open_network_listeners_or_tun() {
        let raw="proxies:\n  - { name: one, type: ss, server: example.com, port: 443, cipher: aes-128-gcm, password: x }\nproxy-groups: []\nrules: [MATCH,DIRECT]\nallow-lan: true\ntun: { enable: true }\nexternal-ui: /etc\nlisteners: [{port: 80}]\ndns: { listen: '0.0.0.0:53' }\n";
        let output = sanitize(raw, 17897, 19091, "private").unwrap();
        let data: serde_yaml::Value = serde_yaml::from_str(&output).unwrap();
        assert_eq!(data["allow-lan"], false);
        assert_eq!(data["bind-address"], "127.0.0.1");
        assert_eq!(data["tun"]["enable"], false);
        assert!(data["listeners"].is_null());
        assert!(data["external-ui"].is_null());
        assert!(data["dns"]["listen"].is_null());
        assert_eq!(data["rules"][0], "DOMAIN,taige.us,DIRECT");
    }
    #[test]
    fn direct_dns_defaults_to_system_without_replacing_subscription_policies() {
        let raw = "proxies: [{name: one, type: direct}]\ndns: {enable: true, nameserver: [https://dns.example/dns-query], nameserver-policy: {'+.example.com': [https://special.example/dns-query]}}";
        let config: serde_yaml::Value =
            serde_yaml::from_str(&sanitize(raw, 1, 2, "x").unwrap()).unwrap();
        assert_eq!(config["dns"]["direct-nameserver"][0], "system");
        assert_eq!(
            config["dns"]["nameserver"][0],
            "https://dns.example/dns-query"
        );
        assert_eq!(
            config["dns"]["nameserver-policy"]["+.example.com"][0],
            "https://special.example/dns-query"
        );
        let explicit = raw.replace(
            "enable: true,",
            "enable: true, direct-nameserver: [192.0.2.53],",
        );
        let config: serde_yaml::Value =
            serde_yaml::from_str(&sanitize(&explicit, 1, 2, "x").unwrap()).unwrap();
        assert_eq!(config["dns"]["direct-nameserver"][0], "192.0.2.53");
        assert!(PRIVATE_RULES
            .iter()
            .all(|rule| !rule.contains("no-resolve")));
    }
    #[test]
    fn refuses_empty_and_local_key_config() {
        assert!(sanitize("proxies: []", 1, 2, "x").is_err());
        assert!(sanitize(
            "proxies: [{name: x, private-key-path: /etc/passwd}]",
            1,
            2,
            "x"
        )
        .is_err());
    }
    #[test]
    fn config_places_overrides_and_actual_global_target_before_any_fallback() {
        use crate::routing::{CustomRule, RuleKind};
        let raw = "proxies: [{name: one, type: direct}, {name: two, type: direct}]\nproxy-groups: [{name: 代理组, type: select, proxies: [DIRECT, one, two]}]\nrules: ['MATCH,DIRECT']";
        let mut settings = RoutingSettings {
            mode: RoutingMode::Global,
            global_target: Some("two".into()),
            rules: vec![CustomRule {
                kind: RuleKind::DomainSuffix,
                value: "example.com".into(),
                target: "代理组".into(),
            }],
        };
        let config = sanitize_routing(raw, 1, 2, "x", &settings).unwrap();
        let selected = selected_config(
            &config,
            &[Route {
                group: "代理组".into(),
                selected: "two".into(),
                choices: vec![],
            }],
        )
        .unwrap();
        let data: serde_yaml::Value = serde_yaml::from_str(&selected).unwrap();
        assert_eq!(data["mode"], "rule");
        assert_eq!(
            data["rules"].as_sequence().unwrap().last().unwrap(),
            "MATCH,GLOBAL"
        );
        assert_eq!(
            data["rules"].as_sequence().unwrap().len(),
            PRIVATE_RULES.len() + 1
        );
        settings.mode = RoutingMode::Rule;
        let rule_config = sanitize_routing(raw, 1, 2, "x", &settings).unwrap();
        let rule_data: serde_yaml::Value = serde_yaml::from_str(&rule_config).unwrap();
        assert_eq!(rule_data["rules"][0], "DOMAIN-SUFFIX,example.com,代理组");
        assert_eq!(rule_data["rules"][1], "DOMAIN,taige.us,DIRECT");
        assert_eq!(data["proxy-groups"][0]["proxies"][0], "two");
        assert_eq!(data["proxy-groups"][1]["name"], "GLOBAL");
        assert_eq!(
            data["proxy-groups"][1]["proxies"],
            serde_yaml::to_value(vec!["two", "one"]).unwrap()
        );
        settings.global_target = Some("代理组".into());
        assert!(sanitize_routing(raw, 1, 2, "x", &settings).is_err());
    }
}

#[cfg(test)]
mod integration {
    use super::*;
    #[test]
    fn mode_selection_resolves_groups_without_overwriting_unrelated_choices() {
        let mut data = json!({"proxies": {
            "GLOBAL": {"type":"Selector", "now":"one", "all":["one","two"]},
            "A": {"type":"Selector", "now":"one", "all":["one","two"]},
            "B": {"type":"Selector", "now":"auto", "all":["auto","one","two"]},
            "auto": {"type":"URLTest", "now":"two", "all":["one","two"]}
        }});
        let targets = vec!["one".into(), "two".into()];
        let mut settings = RoutingSettings {
            mode: RoutingMode::Global,
            ..Default::default()
        };
        let routes =
            mode_selection(&data, RoutingMode::Rule, &mut settings, Some("B"), &targets).unwrap();
        assert_eq!(settings.global_target.as_deref(), Some("two"));
        assert_eq!(
            routes.iter().find(|r| r.group == "A").unwrap().selected,
            "one"
        );
        assert_eq!(
            routes.iter().find(|r| r.group == "B").unwrap().selected,
            "auto"
        );
        // Switching away from GLOBAL selects its current node only in the displayed rule group.
        settings.mode = RoutingMode::Rule;
        let routes = mode_selection(
            &data,
            RoutingMode::Global,
            &mut settings,
            Some("B"),
            &targets,
        )
        .unwrap();
        assert_eq!(
            routes.iter().find(|r| r.group == "B").unwrap().selected,
            "one"
        );
        data["proxies"]["GLOBAL"]["now"] = json!("two");
        let routes = mode_selection(
            &data,
            RoutingMode::Global,
            &mut settings,
            Some("B"),
            &targets,
        )
        .unwrap();
        assert_eq!(
            routes.iter().find(|r| r.group == "B").unwrap().selected,
            "auto"
        );
        // Automatic groups remain automatic, and cycles or DIRECT are never actual proxy nodes.
        data["proxies"]["auto"]["now"] = json!("B");
        assert_eq!(resolved_node(&data, "B", &targets), None);
        assert_eq!(resolved_node(&data, "DIRECT", &targets), None);
        data["proxies"]["A"]["all"] = json!(["one"]);
        assert!(mode_selection(
            &data,
            RoutingMode::Global,
            &mut settings,
            Some("A"),
            &targets
        )
        .is_err());
        // Rule edits and return from direct mode do not reinterpret independent selectors.
        for previous in [RoutingMode::Rule, RoutingMode::Direct] {
            let routes =
                mode_selection(&data, previous, &mut settings, Some("B"), &targets).unwrap();
            assert_eq!(
                routes.iter().find(|r| r.group == "B").unwrap().selected,
                "auto"
            );
        }
    }

    struct Running(Child, PathBuf);
    impl Drop for Running {
        fn drop(&mut self) {
            let _ = self.0.kill();
            let _ = self.0.wait();
            let _ = std::fs::remove_dir_all(&self.1);
        }
    }
    #[tokio::test]
    async fn bundled_core_routes_private_domains_locally_and_public_global_to_selected_proxy() {
        use std::sync::{
            atomic::{AtomicUsize, Ordering},
            Arc,
        };
        use tokio::io::{AsyncReadExt, AsyncWriteExt};
        let origin = super::tests::readiness_server(|_, _| (204, json!(null)));
        let proxy_hits = Arc::new(AtomicUsize::new(0));
        let hits = proxy_hits.clone();
        let proxy = super::tests::readiness_server(move |_, request| {
            assert!(
                request.starts_with("CONNECT "),
                "core must contact the selected HTTP proxy"
            );
            hits.fetch_add(1, Ordering::SeqCst);
            (503, json!({}))
        });
        // Controlled DNS: one private answer, one public documentation address, no external queries.
        let dns = tokio::net::UdpSocket::bind("127.0.0.1:0").await.unwrap();
        let dns_address = dns.local_addr().unwrap();
        let dns_task = tokio::spawn(async move {
            let mut packet = [0u8; 512];
            loop {
                let (len, peer) = dns.recv_from(&mut packet).await.unwrap();
                let mut end = 12;
                let mut labels = Vec::new();
                while packet[end] != 0 {
                    let size = packet[end] as usize;
                    labels.push(
                        String::from_utf8_lossy(&packet[end + 1..end + 1 + size]).to_string(),
                    );
                    end += size + 1;
                }
                end += 1;
                let name = labels.join(".");
                let is_a = packet[end..end + 2] == [0, 1];
                let address = match name.as_str() {
                    "office.capybara.test" => Some([127, 0, 0, 1]),
                    "public.capybara.test" => Some([192, 0, 2, 1]),
                    _ => None,
                }
                .filter(|_| is_a);
                let mut response = packet[..len].to_vec();
                response[2..4].copy_from_slice(&[0x81, 0x80]);
                response[6..12].fill(0);
                if let Some(address) = address {
                    response[7] = 1;
                    response.extend_from_slice(&[0xc0, 0x0c, 0, 1, 0, 1, 0, 0, 0, 1, 0, 4]);
                    response.extend_from_slice(&address);
                }
                dns.send_to(&response, peer).await.unwrap();
            }
        });
        let dir =
            std::env::temp_dir().join(format!("capybara-private-test-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir_all(&dir).unwrap();
        let binary = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("binaries")
            .join(format!(
                "mihomo-{}{}",
                crate::host_target(),
                if cfg!(windows) { ".exe" } else { "" }
            ));
        let port = port().unwrap();
        let api = port_fn(port).unwrap();
        let secret = uuid::Uuid::new_v4().to_string();
        let raw = format!("proxies: [{{name: selected, type: http, server: 127.0.0.1, port: {}}}]\nproxy-groups: [{{name: group, type: select, proxies: [selected]}}]\nrules: ['IP-CIDR,127.0.0.0/8,DIRECT,no-resolve', 'MATCH,group']\ndns: {{enable: true, ipv6: false, enhanced-mode: redir-host, nameserver: ['{dns_address}'], direct-nameserver: ['{dns_address}']}}\n", proxy.api);
        let mut settings = RoutingSettings::default();
        let config = sanitize_routing(&raw, port, api, &secret, &settings).unwrap();
        private_write(&dir.join("config.yaml"), config.as_bytes()).unwrap();
        let mut core = Running(
            cmd(binary)
                .arg("-d")
                .arg(&dir)
                .arg("-f")
                .arg(dir.join("config.yaml"))
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .spawn()
                .unwrap(),
            dir,
        );
        let controller = Controller { port, api, secret };
        controller
            .wait_ready(
                &ExpectedConfig::from_yaml(&config).unwrap(),
                Duration::from_secs(35),
                || {
                    if matches!(core.0.try_wait(), Ok(None)) {
                        Ok(())
                    } else {
                        Err("test core exited".into())
                    }
                },
            )
            .await
            .unwrap();
        let client = reqwest::Client::builder()
            .no_proxy()
            .proxy(reqwest::Proxy::all(format!("http://127.0.0.1:{port}")).unwrap())
            .pool_max_idle_per_host(0)
            .timeout(Duration::from_secs(4))
            .build()
            .unwrap();
        for mode in [RoutingMode::Rule, RoutingMode::Global, RoutingMode::Direct] {
            let before_hits = proxy_hits.load(Ordering::SeqCst);
            settings.mode = mode;
            let config = sanitize_routing(&raw, port, api, &controller.secret, &settings).unwrap();
            controller
                .apply_config(&config, &raw, &settings, &[])
                .await
                .unwrap();
            assert_eq!(
                client
                    .get(format!("http://office.capybara.test:{}/", origin.api))
                    .send()
                    .await
                    .unwrap()
                    .status(),
                reqwest::StatusCode::NO_CONTENT,
                "private domain in {mode:?}"
            );
            // Browser HTTPS starts with CONNECT. Verify a domain tunnel carries bytes end to end
            // without depending on external certificates or changing OS proxy/DNS settings.
            let tunnel = async {
                let mut stream = tokio::net::TcpStream::connect(("127.0.0.1", port))
                    .await
                    .unwrap();
                stream.write_all(format!("CONNECT office.capybara.test:{} HTTP/1.1\r\nHost: office.capybara.test:{}\r\n\r\n", origin.api, origin.api).as_bytes()).await.unwrap();
                let mut headers = Vec::new();
                while !headers.ends_with(b"\r\n\r\n") {
                    headers.push(stream.read_u8().await.unwrap());
                    assert!(headers.len() < 4096);
                }
                assert!(String::from_utf8(headers).unwrap().contains("200"));
                stream.write_all(b"GET / HTTP/1.1\r\nHost: office.capybara.test\r\nConnection: close\r\n\r\n").await.unwrap();
                let mut response = String::new();
                stream.read_to_string(&mut response).await.unwrap();
                assert!(response.starts_with("HTTP/1.1 204"));
            };
            tokio::time::timeout(Duration::from_secs(4), tunnel)
                .await
                .unwrap();
            assert_eq!(proxy_hits.load(Ordering::SeqCst), before_hits);
            if mode == RoutingMode::Global {
                let response = client.get("http://public.capybara.test:80/").send().await;
                assert!(response.map(|r| !r.status().is_success()).unwrap_or(true));
                assert!(
                    proxy_hits.load(Ordering::SeqCst) > before_hits,
                    "public global traffic must reach selected proxy"
                );
            }
        }
        // With no explicit direct resolver, localhost succeeds through system resolution even
        // though our configured general DNS deliberately has no address for it.
        let system_raw = raw.replace(&format!(", direct-nameserver: ['{dns_address}']"), "");
        let config =
            sanitize_routing(&system_raw, port, api, &controller.secret, &settings).unwrap();
        controller
            .apply_config(&config, &system_raw, &settings, &[])
            .await
            .unwrap();
        assert_eq!(
            client
                .get(format!("http://localhost:{}/", origin.api))
                .send()
                .await
                .unwrap()
                .status(),
            reqwest::StatusCode::NO_CONTENT
        );
        dns_task.abort();
        drop(core);
        origin.finish().unwrap();
        proxy.finish().unwrap();
    }
    #[tokio::test]
    async fn bundled_core_enforces_controller_auth_and_keeps_config_after_invalid_reload() {
        let binary = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("binaries")
            .join(format!(
                "mihomo-{}{}",
                crate::host_target(),
                if cfg!(windows) { ".exe" } else { "" }
            ));
        assert!(
            binary.exists(),
            "Run npm run core:prepare before native tests"
        );
        let dir = std::env::temp_dir().join(format!("capybara-core-test-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir_all(&dir).unwrap();
        std::fs::copy(
            PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("resources/geoip.metadb"),
            dir.join("geoip.metadb"),
        )
        .unwrap();
        let port = port().unwrap();
        let api = port_fn(port).unwrap();
        let secret = uuid::Uuid::new_v4().to_string();
        let raw="proxies: [{name: 测试线路, type: direct}]\nproxy-groups: [{name: 卡皮巴拉, type: select, proxies: [测试线路]}]\nrules: ['GEOIP,CN,DIRECT', 'MATCH,卡皮巴拉']\n";
        let config = sanitize(raw, port, api, &secret).unwrap();
        private_write(&dir.join("config.yaml"), config.as_bytes()).unwrap();
        let mut core = Running(
            cmd(binary)
                .args([
                    "-d",
                    dir.to_str().unwrap(),
                    "-f",
                    dir.join("config.yaml").to_str().unwrap(),
                ])
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .spawn()
                .unwrap(),
            dir,
        );
        let client = account::http().unwrap();
        let base = format!("http://127.0.0.1:{api}");
        let controller = Controller {
            port,
            api,
            secret: secret.clone(),
        };
        controller
            .wait_ready(
                &ExpectedConfig::from_yaml(&config).unwrap(),
                Duration::from_secs(35),
                || {
                    if matches!(core.0.try_wait(), Ok(None)) {
                        Ok(())
                    } else {
                        Err("bundled core exited before becoming ready".into())
                    }
                },
            )
            .await
            .unwrap();
        assert_eq!(
            client
                .get(format!("{base}/proxies"))
                .send()
                .await
                .unwrap()
                .status(),
            reqwest::StatusCode::UNAUTHORIZED
        );
        let before: Value = client
            .get(format!("{base}/proxies"))
            .bearer_auth(&secret)
            .send()
            .await
            .unwrap()
            .json()
            .await
            .unwrap();
        assert!(before["proxies"]["卡皮巴拉"].is_object());
        controller.select("卡皮巴拉", "测试线路").await.unwrap();
        assert!(controller.select("卡皮巴拉", "not-a-node").await.is_err());
        // Real bundled core measures a controlled HTTP target, without setting the system proxy.
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let server = std::thread::spawn(move || {
            let (mut socket, _) = listener.accept().unwrap();
            super::tests::read_headers(&mut socket, &std::sync::atomic::AtomicBool::new(false))
                .unwrap()
                .expect("complete delay request headers");
            std::thread::sleep(Duration::from_millis(40));
            socket
                .write_all(b"HTTP/1.1 204 No Content\r\nConnection: close\r\n\r\n")
                .unwrap();
        });
        let delay = controller
            .delay_at("测试线路", &format!("http://{address}/generate_204"))
            .await
            .unwrap();
        assert!(delay >= 30 && delay < 5000);
        server.join().unwrap();
        assert!(controller
            .delay_at("missing / %?", "http://127.0.0.1:1/")
            .await
            .is_err());
        assert_eq!(
            controller.routes(RoutingMode::Rule).await.unwrap()[0].selected,
            "测试线路"
        );
        assert!(!core.1.join("proxy-recovery.json").exists());
        let response = client
            .put(format!("{base}/configs?force=true"))
            .bearer_auth(&secret)
            .json(&json!({"payload":"rules: ['MATCH,不存在的组']"}))
            .send()
            .await
            .unwrap();
        assert!(!response.status().is_success());
        let after: Value = client
            .get(format!("{base}/proxies"))
            .bearer_auth(&secret)
            .send()
            .await
            .unwrap()
            .json()
            .await
            .unwrap();
        assert_eq!(
            before["proxies"]["卡皮巴拉"]["now"],
            after["proxies"]["卡皮巴拉"]["now"]
        );
        let response = client
            .put(format!("{base}/configs?force=true"))
            .bearer_auth(&secret)
            .json(&json!({"payload":config}))
            .send()
            .await
            .unwrap();
        assert!(response.status().is_success());

        // End-to-end routing: use a local HTTP server and a deliberately unavailable proxy.
        // These requests go through the bundled core's mixed port, never through system settings.
        use crate::routing::{CustomRule, RuleKind};
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let target = format!("http://{}/routing-test", listener.local_addr().unwrap());
        listener.set_nonblocking(true).unwrap();
        let stop = std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false));
        let finish = stop.clone();
        let server = std::thread::spawn(move || -> Result<(), String> {
            while !finish.load(std::sync::atomic::Ordering::SeqCst) {
                match listener.accept() {
                    Ok((mut socket, _)) => {
                        if super::tests::read_headers(&mut socket, &finish)
                            .map_err(|error| error.to_string())?
                            .is_none()
                        {
                            continue;
                        }
                        let _ = socket
                            .write_all(b"HTTP/1.1 204 No Content\r\nConnection: close\r\n\r\n");
                    }
                    Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                        std::thread::sleep(Duration::from_millis(5))
                    }
                    Err(error) => return Err(error.to_string()),
                }
            }
            Ok(())
        });
        let unavailable = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let closed_port = unavailable.local_addr().unwrap().port();
        drop(unavailable);
        let raw = format!("proxies: [{{name: 测试线路, type: direct}}, {{name: 阻断线路, type: http, server: 127.0.0.1, port: {closed_port}}}]\nproxy-groups: [{{name: 订阅组, type: select, proxies: [DIRECT, 测试线路]}}]\nrules: ['MATCH,DIRECT']\n");
        let proxy_client = reqwest::Client::builder()
            .no_proxy()
            .proxy(reqwest::Proxy::all(format!("http://127.0.0.1:{port}")).unwrap())
            // Rules apply to new connections. Never carry a proxy connection from
            // a preceding global/direct/rejected request across a configuration update.
            .pool_max_idle_per_host(0)
            .timeout(Duration::from_secs(2))
            .build()
            .unwrap();
        let mut settings = RoutingSettings {
            mode: RoutingMode::Global,
            global_target: Some("阻断线路".into()),
            rules: vec![CustomRule {
                kind: RuleKind::IpCidr,
                value: "127.0.0.1/32".into(),
                target: "REJECT".into(),
            }],
        };
        let config = sanitize_routing(&raw, port, api, &secret, &settings).unwrap();
        // Check the immediately loaded GLOBAL choice before any select command can hide a DIRECT window.
        controller
            .call(
                reqwest::Method::PUT,
                "/configs?force=true",
                Some(json!({"payload": config})),
            )
            .await
            .unwrap();
        assert_eq!(
            controller.routes(settings.mode).await.unwrap()[0].group,
            "GLOBAL"
        );
        assert_eq!(
            controller.routes(settings.mode).await.unwrap()[0].selected,
            "阻断线路"
        );
        assert!(!controller.routes(settings.mode).await.unwrap()[0]
            .choices
            .contains(&"订阅组".into()));
        assert_eq!(
            proxy_client.get(&target).send().await.unwrap().status(),
            reqwest::StatusCode::NO_CONTENT,
            "global bypasses private targets and ignores custom rejection"
        );
        settings.mode = RoutingMode::Direct;
        let config = sanitize_routing(&raw, port, api, &secret, &settings).unwrap();
        controller
            .apply_config(&config, &raw, &settings, &[])
            .await
            .unwrap();
        assert!(controller.routes(settings.mode).await.unwrap().is_empty());
        assert_eq!(
            proxy_client.get(&target).send().await.unwrap().status(),
            reqwest::StatusCode::NO_CONTENT,
            "direct bypasses custom rejection"
        );
        settings.mode = RoutingMode::Rule;
        let config = sanitize_routing(&raw, port, api, &secret, &settings).unwrap();
        controller
            .apply_config(&config, &raw, &settings, &[])
            .await
            .unwrap();
        assert!(controller
            .routes(settings.mode)
            .await
            .unwrap()
            .iter()
            .all(|route| route.group != "GLOBAL"));
        assert!(
            proxy_client
                .get(&target)
                .send()
                .await
                .map(|r| r.status() != reqwest::StatusCode::NO_CONTENT)
                .unwrap_or(true),
            "custom rule must precede subscription MATCH,DIRECT"
        );
        settings.rules.insert(
            0,
            CustomRule {
                kind: RuleKind::IpCidr,
                value: "127.0.0.1/32".into(),
                target: "DIRECT".into(),
            },
        );
        let refreshed = raw.replace("MATCH,DIRECT", "MATCH,阻断线路");
        let config = sanitize_routing(&refreshed, port, api, &secret, &settings).unwrap();
        controller
            .apply_config(&config, &refreshed, &settings, &[])
            .await
            .unwrap();
        assert_eq!(
            proxy_client.get(&target).send().await.unwrap().status(),
            reqwest::StatusCode::NO_CONTENT,
            "first user rule remains effective after subscription refresh"
        );
        let saved = controller
            .call(reqwest::Method::GET, "/rules", None)
            .await
            .unwrap();
        assert_eq!(saved["rules"][0]["proxy"], "DIRECT");
        assert_eq!(saved["rules"][1]["proxy"], "REJECT");
        assert_eq!(
            controller
                .call(reqwest::Method::GET, "/configs", None)
                .await
                .unwrap()["mode"],
            "rule"
        );
        let mut invalid = settings.clone();
        invalid.rules[0].target = "不存在".into();
        assert!(sanitize_routing(&refreshed, port, api, &secret, &invalid).is_err());
        assert_eq!(
            controller
                .call(reqwest::Method::GET, "/rules", None)
                .await
                .unwrap(),
            saved
        );
        stop.store(true, std::sync::atomic::Ordering::SeqCst);
        server.join().unwrap().unwrap();

        // Exercise the real Nodes transaction against the isolated bundled core. The stand-in
        // worker only lists tests and exits; Running owns the core, and no system proxy is touched.
        let raw = "proxies: [{name: one, type: direct}, {name: two, type: direct}]\nproxy-groups: [{name: A, type: select, proxies: [one, two]}, {name: B, type: select, proxies: [one, two]}]\nrules: ['MATCH,B']\n";
        let settings = RoutingSettings::default();
        let config = sanitize_routing(raw, port, api, &secret, &settings).unwrap();
        controller
            .apply_config(&config, raw, &settings, &[])
            .await
            .unwrap();
        let mut worker = cmd(std::env::current_exe().unwrap())
            .arg("--list")
            .stdin(Stdio::piped())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .unwrap();
        let input = worker.stdin.take().unwrap();
        let mut nodes = crate::nodes::Nodes::new(&core.1);
        nodes.engine = Some(Engine {
            worker,
            input,
            control: controller.clone(),
            content: raw.into(),
            settings: settings.clone(),
        });
        nodes.prepare(&core.1, PathBuf::new(), raw).await.unwrap();
        nodes.select_route("B".into(), "two".into()).await.unwrap();
        for mode in [
            RoutingMode::Global,
            RoutingMode::Rule,
            RoutingMode::Direct,
            RoutingMode::Global,
        ] {
            let mut next = nodes.routing.settings.clone();
            next.mode = mode;
            nodes.apply_routing_settings(next, Some("B")).await.unwrap();
            let data = controller
                .call(reqwest::Method::GET, "/proxies", None)
                .await
                .unwrap();
            assert_eq!(data["proxies"]["GLOBAL"]["now"], "two");
            assert_eq!(data["proxies"]["B"]["now"], "two");
            assert_eq!(data["proxies"]["A"]["now"], "one");
        }
        nodes
            .select_route("GLOBAL".into(), "one".into())
            .await
            .unwrap();
        let before = std::fs::read(core.1.join("routing.json")).unwrap();
        let mut next = nodes.routing.settings.clone();
        next.mode = RoutingMode::Rule;
        std::fs::create_dir(core.1.join("routing.tmp")).unwrap();
        assert!(nodes
            .apply_routing_settings(next.clone(), Some("B"))
            .await
            .is_err());
        assert_eq!(std::fs::read(core.1.join("routing.json")).unwrap(), before);
        assert_eq!(nodes.routing.settings.mode, RoutingMode::Global);
        let data = controller
            .call(reqwest::Method::GET, "/proxies", None)
            .await
            .unwrap();
        assert_eq!(data["proxies"]["GLOBAL"]["now"], "one");
        assert_eq!(
            data["proxies"]["B"]["now"], "two",
            "save failure must restore the previous rule choice"
        );
        assert_eq!(
            controller
                .call(reqwest::Method::GET, "/configs", None)
                .await
                .unwrap()["mode"],
            "rule"
        );
        std::fs::remove_dir(core.1.join("routing.tmp")).unwrap();
        next.mode = RoutingMode::Direct;
        nodes.apply_routing_settings(next, Some("B")).await.unwrap();
        let mut next = nodes.routing.settings.clone();
        next.mode = RoutingMode::Rule;
        nodes.apply_routing_settings(next, Some("B")).await.unwrap();
        nodes.prepare(&core.1, PathBuf::new(), raw).await.unwrap();
        assert_eq!(
            nodes
                .view
                .routes
                .iter()
                .find(|r| r.group == "B")
                .unwrap()
                .selected,
            "one"
        );
        assert_eq!(
            nodes
                .view
                .routes
                .iter()
                .find(|r| r.group == "A")
                .unwrap()
                .selected,
            "one"
        );
        drop(nodes);
    }
}
