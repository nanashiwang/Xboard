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
        ("mode", json!(settings.mode.as_str())),
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
    }
    // User overrides take precedence, followed by the service access exception and subscription rules.
    let existing = output
        .entry(serde_yaml::Value::String("rules".into()))
        .or_insert_with(|| serde_yaml::Value::Sequence(vec![]));
    let rules = existing.as_sequence_mut().ok_or("订阅规则格式无效")?;
    rules.insert(0, "DOMAIN,taige.us,DIRECT".into());
    for rule in settings.rules.iter().rev() {
        rules.insert(0, rule.line().into());
    }
    serde_yaml::to_string(&output).map_err(|_| "无法生成本地配置".into())
}
impl Engine {
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
    pub fn checkpoint(&self) -> (String, RoutingSettings) {
        (self.content.clone(), self.settings.clone())
    }
    pub async fn reload(
        &mut self,
        content: &str,
        settings: &RoutingSettings,
    ) -> Result<(), String> {
        // Compose and validate before touching the running core. Roll back even on an ambiguous timeout.
        let config = sanitize_routing(content, self.port, self.api, &self.secret, settings)?;
        let selected = self.control.all_routes().await?;
        if let Err(error) = self
            .control
            .apply_config(&config, content, settings, &selected)
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
        let config = self.call(reqwest::Method::GET, "/configs", None).await?;
        if config["mode"].as_str() != Some(settings.mode.as_str()) {
            return Err("分流模式未能生效".into());
        }
        Ok(())
    }
    async fn all_routes(&self) -> Result<Vec<Route>, String> {
        let data = self.call(reqwest::Method::GET, "/proxies", None).await?;
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
    pub async fn routes(&self) -> Result<Vec<Route>, String> {
        let mode = self.call(reqwest::Method::GET, "/configs", None).await?;
        let global = mode["mode"] == "global";
        if mode["mode"] == "direct" {
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
    struct ReadinessServer {
        api: u16,
        stop: std::sync::Arc<std::sync::atomic::AtomicBool>,
        thread: Option<std::thread::JoinHandle<()>>,
    }
    impl Drop for ReadinessServer {
        fn drop(&mut self) {
            self.stop.store(true, std::sync::atomic::Ordering::SeqCst);
            if let Some(thread) = self.thread.take() {
                thread.join().unwrap();
            }
        }
    }
    fn readiness_server<F>(response: F) -> ReadinessServer
    where
        F: Fn(&str, &str) -> (u16, Value) + Send + 'static,
    {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let api = listener.local_addr().unwrap().port();
        listener.set_nonblocking(true).unwrap();
        let stop = std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false));
        let done = stop.clone();
        let thread = std::thread::spawn(move || {
            use std::io::Read;
            while !done.load(std::sync::atomic::Ordering::SeqCst) {
                match listener.accept() {
                    Ok((mut socket, _)) => {
                        socket
                            .set_read_timeout(Some(Duration::from_secs(1)))
                            .unwrap();
                        let mut bytes = [0; 4096];
                        let size = socket.read(&mut bytes).unwrap_or(0);
                        let request = String::from_utf8_lossy(&bytes[..size]);
                        let path = request.split_whitespace().nth(1).unwrap_or("");
                        let (status, data) = response(path, &request);
                        let body = data.to_string();
                        let _ = write!(socket, "HTTP/1.1 {status} Test\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}", body.len());
                    }
                    Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                        std::thread::sleep(Duration::from_millis(5))
                    }
                    Err(_) => break,
                }
            }
        });
        ReadinessServer {
            api,
            stop,
            thread: Some(thread),
        }
    }
    fn startup_fixture(port: u16) -> (ExpectedConfig, Value, Value, Value) {
        let config = sanitize("proxies: [{name: one, type: direct}]\nproxy-groups: [{name: group, type: select, proxies: [one]}]\nrules: ['MATCH,group']", port, 19091, "private").unwrap();
        (
            ExpectedConfig::from_yaml(&config).unwrap(),
            json!({"mode":"rule", "mixed-port":port}),
            json!({"proxies":{"one":{"type":"Direct"},"group":{"type":"Selector"},"GLOBAL":{"type":"Selector","now":"one","all":["one"]}}}),
            json!({"rules":[{},{}]}),
        )
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
            .wait_ready(&expected, Duration::from_secs(2), || Ok(()))
            .await
            .unwrap();
        assert_eq!(attempts.load(Ordering::SeqCst), 3);
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
        let started = Instant::now();
        assert!(controller
            .wait_ready(&expected, Duration::from_secs(2), || Ok(()))
            .await
            .unwrap_err()
            .contains("鉴权"));
        assert!(started.elapsed() < Duration::from_secs(1));
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
        assert_eq!(data["mode"], "global");
        assert_eq!(data["rules"][0], "DOMAIN-SUFFIX,example.com,代理组");
        assert_eq!(data["rules"][1], "DOMAIN,taige.us,DIRECT");
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
    struct Running(Child, PathBuf);
    impl Drop for Running {
        fn drop(&mut self) {
            let _ = self.0.kill();
            let _ = self.0.wait();
            let _ = std::fs::remove_dir_all(&self.1);
        }
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
            use std::io::Read;
            let (mut socket, _) = listener.accept().unwrap();
            socket
                .set_read_timeout(Some(Duration::from_secs(3)))
                .unwrap();
            let mut data = [0; 1024];
            let _ = socket.read(&mut data).unwrap();
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
        assert_eq!(controller.routes().await.unwrap()[0].selected, "测试线路");
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
        let server = std::thread::spawn(move || {
            use std::io::Read;
            while !finish.load(std::sync::atomic::Ordering::SeqCst) {
                match listener.accept() {
                    Ok((mut socket, _)) => {
                        let _ = socket.set_read_timeout(Some(Duration::from_secs(2)));
                        let mut request = [0; 1024];
                        let _ = socket.read(&mut request);
                        let _ = socket
                            .write_all(b"HTTP/1.1 204 No Content\r\nConnection: close\r\n\r\n");
                    }
                    Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                        std::thread::sleep(Duration::from_millis(5))
                    }
                    Err(_) => break,
                }
            }
        });
        let unavailable = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let closed_port = unavailable.local_addr().unwrap().port();
        drop(unavailable);
        let raw = format!("proxies: [{{name: 测试线路, type: direct}}, {{name: 阻断线路, type: http, server: 127.0.0.1, port: {closed_port}}}]\nproxy-groups: [{{name: 订阅组, type: select, proxies: [DIRECT, 测试线路]}}]\nrules: ['MATCH,DIRECT']\n");
        let proxy_client = reqwest::Client::builder()
            .no_proxy()
            .proxy(reqwest::Proxy::all(format!("http://127.0.0.1:{port}")).unwrap())
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
        assert_eq!(controller.routes().await.unwrap()[0].group, "GLOBAL");
        assert_eq!(controller.routes().await.unwrap()[0].selected, "阻断线路");
        assert!(!controller.routes().await.unwrap()[0]
            .choices
            .contains(&"订阅组".into()));
        assert!(
            proxy_client
                .get(&target)
                .send()
                .await
                .map(|r| r.status() != reqwest::StatusCode::NO_CONTENT)
                .unwrap_or(true),
            "global must use the selected unavailable proxy"
        );
        settings.mode = RoutingMode::Direct;
        let config = sanitize_routing(&raw, port, api, &secret, &settings).unwrap();
        controller
            .apply_config(&config, &raw, &settings, &[])
            .await
            .unwrap();
        assert!(controller.routes().await.unwrap().is_empty());
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
            .routes()
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
        server.join().unwrap();
    }
}
