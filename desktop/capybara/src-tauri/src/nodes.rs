use crate::{
    account::Fault,
    engine::{Engine, Route},
    AppState,
};
use serde::Serialize;
use std::{collections::BTreeMap, sync::Arc, time::Instant};
use tokio::{sync::Mutex, task::JoinSet};

#[derive(Clone, Serialize)]
pub struct Delay {
    status: String,
    ms: Option<u64>,
}
#[derive(Clone, Serialize, Default)]
pub struct NodeView {
    pub revision: u64,
    pub routes: Vec<Route>,
    pub loading: bool,
    pub error: Option<String>,
    testing: bool,
    delays: BTreeMap<String, Delay>,
}
#[derive(Default)]
pub struct Nodes {
    pub engine: Option<Engine>,
    pub view: NodeView,
    pub synced: Option<Instant>,
    generation: u64,
}
impl Nodes {
    pub fn changed(&mut self) {
        self.view.revision += 1;
    }
    pub fn invalidate(&mut self) {
        self.generation += 1;
        self.view.testing = false;
        self.view.delays.clear();
        self.changed();
    }
    pub fn stop(&mut self) -> Result<(), String> {
        self.invalidate();
        let result = self.engine.take().map(|mut e| e.stop()).unwrap_or(Ok(()));
        self.view.routes.clear();
        self.view.loading = false;
        self.view.error = result.as_ref().err().cloned();
        self.synced = None;
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
    if !nodes
        .view
        .routes
        .iter()
        .any(|r| r.group == group && r.choices.contains(&name))
    {
        return Err(Fault::local("节点已变更，请等待列表刷新"));
    }
    let engine = nodes
        .engine
        .as_ref()
        .ok_or_else(|| Fault::local("节点正在准备，请稍候"))?;
    if let Err(error) = engine.select(&group, &name).await {
        // A lost local response is ambiguous; reconcile before reporting the error.
        if let Ok(routes) = engine.routes().await {
            nodes.view.routes = routes;
            nodes.changed();
        }
        return Err(error.into());
    }
    for route in &mut nodes.view.routes {
        if route.group == group {
            route.selected = name.clone();
        }
    }
    nodes.changed();
    Ok(nodes.view.clone())
}

fn names(view: &NodeView) -> Vec<String> {
    view.routes
        .iter()
        .flat_map(|r| r.choices.iter().cloned())
        .collect::<std::collections::BTreeSet<_>>()
        .into_iter()
        .collect()
}
#[tauri::command]
pub async fn test_nodes(state: tauri::State<'_, AppState>) -> Result<NodeView, Fault> {
    let shared = state.1.clone();
    let mut nodes = shared.lock().await;
    if nodes.view.testing {
        return Ok(nodes.view.clone());
    }
    let controller = std::ops::Deref::deref(
        nodes
            .engine
            .as_ref()
            .ok_or_else(|| Fault::local("节点尚未加载，请稍候"))?,
    )
    .clone();
    let pending = names(&nodes.view);
    if pending.is_empty() {
        return Err(Fault::local("当前没有可测速的节点"));
    }
    nodes.invalidate();
    let generation = nodes.generation;
    nodes.view.testing = true;
    nodes.view.delays = pending
        .iter()
        .map(|name| {
            (
                name.clone(),
                Delay {
                    status: "pending".into(),
                    ms: None,
                },
            )
        })
        .collect();
    let view = nodes.view.clone();
    drop(nodes);
    tauri::async_runtime::spawn(run_tests(shared, controller, pending, generation));
    Ok(view)
}
async fn run_tests(
    shared: Arc<Mutex<Nodes>>,
    controller: crate::engine::Controller,
    pending: Vec<String>,
    generation: u64,
) {
    run_probes(shared, pending, generation, move |name| {
        let controller = controller.clone();
        async move { controller.delay(&name).await }
    })
    .await;
}
async fn run_probes<F, Fut>(
    shared: Arc<Mutex<Nodes>>,
    pending: Vec<String>,
    generation: u64,
    probe: F,
) where
    F: Fn(String) -> Fut + Clone + Send + 'static,
    Fut: std::future::Future<Output = Result<u64, String>> + Send + 'static,
{
    let mut queue = pending.into_iter();
    let mut jobs = JoinSet::new();
    loop {
        {
            let nodes = shared.lock().await;
            if nodes.generation != generation {
                return;
            } // Dropping JoinSet cancels old requests.
        }
        while jobs.len() < 4 {
            let Some(name) = queue.next() else { break };
            let probe = probe.clone();
            jobs.spawn(async move {
                let result = probe(name.clone()).await;
                (name, result)
            });
        }
        let Some(result) = jobs.join_next().await else {
            break;
        };
        let mut nodes = shared.lock().await;
        if nodes.generation != generation {
            return;
        }
        if let Ok((name, result)) = result {
            let delay = match result {
                Ok(ms) => Delay {
                    status: "ok".into(),
                    ms: Some(ms),
                },
                Err(error) => Delay {
                    status: error,
                    ms: None,
                },
            };
            nodes.view.delays.insert(name, delay);
        }
        nodes.changed();
    }
    let mut nodes = shared.lock().await;
    if nodes.generation == generation {
        nodes.view.testing = false;
        nodes.changed();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn measurements_are_deduplicated_and_cleared_when_config_changes() {
        let mut nodes = Nodes::default();
        nodes.view.routes = vec![Route {
            group: "A".into(),
            selected: "one".into(),
            choices: vec!["one".into(), "two".into(), "one".into()],
        }];
        assert_eq!(names(&nodes.view), vec!["one", "two"]);
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
    async fn probes_are_bounded_incremental_and_ignore_results_after_logout() {
        use std::sync::atomic::{AtomicUsize, Ordering};
        let nodes = Arc::new(Mutex::new(Nodes::default()));
        nodes.lock().await.view.testing = true;
        let running = Arc::new(AtomicUsize::new(0));
        let peak = Arc::new(AtomicUsize::new(0));
        let starts = Arc::new(AtomicUsize::new(0));
        let permit = Arc::new(tokio::sync::Semaphore::new(0));
        let task = tokio::spawn(run_probes(
            nodes.clone(),
            (0..20).map(|i| i.to_string()).collect(),
            0,
            {
                let running = running.clone();
                let peak = peak.clone();
                let starts = starts.clone();
                let permit = permit.clone();
                move |name| {
                    let running = running.clone();
                    let peak = peak.clone();
                    let starts = starts.clone();
                    let permit = permit.clone();
                    async move {
                        let count = running.fetch_add(1, Ordering::SeqCst) + 1;
                        peak.fetch_max(count, Ordering::SeqCst);
                        starts.fetch_add(1, Ordering::SeqCst);
                        permit.acquire().await.unwrap().forget();
                        running.fetch_sub(1, Ordering::SeqCst);
                        if name == "0" {
                            Err("超时".into())
                        } else {
                            Ok(38)
                        }
                    }
                }
            },
        ));
        tokio::time::timeout(std::time::Duration::from_secs(2), async {
            while starts.load(Ordering::SeqCst) < 4 {
                tokio::task::yield_now().await;
            }
        })
        .await
        .unwrap();
        assert_eq!(starts.load(Ordering::SeqCst), 4);
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
        permit.add_permits(4);
        task.await.unwrap();
        assert!(peak.load(Ordering::SeqCst) <= 4);
        assert!(starts.load(Ordering::SeqCst) <= 5); // no new work after invalidation
        assert!(nodes.lock().await.view.delays.is_empty());
    }
}
