mod actions;
mod brain;
mod events;
mod grpc;
mod websocket;

use crate::actions::ComputerDispatchService;
use crate::brain::BrainService;
use crate::events::ComputerEventService;
use crate::websocket::ClientRegistry;
use futures::TryFutureExt;
use std::sync::Arc;
use tokio::runtime::Builder;
use tokio::sync::Notify;

/// Debug logging level environment variable.
/// For debug builds, this is enabled by default.
/// Setting to `0` or `false` disables debug logging. `trace` enables trace-level logging.
const ENV_BLUEKING_DEBUG: &str = "BLUEKING_DEBUG";
/// tracing crate configuration.
const ENV_BLUEKING_LOG: &str = "BLUEKIND_LOG";

fn main() -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    init_tracing();
    tracing::info!("Blueking Gestalt v{}", env!("CARGO_PKG_VERSION"));
    Builder::new_multi_thread()
        .enable_all()
        .thread_name_fn(|| {
            static ATOM: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(0);
            let idx = ATOM.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
            format!("blueking-{idx}")
        })
        .build()
        .expect("Failed to build Tokio runtime")
        .block_on(start())
}

async fn start() -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    let shutdown = {
        let notify = Arc::new(Notify::new());
        let flag = Arc::new(std::sync::atomic::AtomicBool::new(false));
        let runner_notify = notify.clone();
        let runner_flag = flag.clone();
        tokio::spawn(async move {
            shutdown_signal_once().await;
            runner_flag.store(true, std::sync::atomic::Ordering::SeqCst);
            runner_notify.notify_waiters();
        });
        ShutdownSignal { notify, flag }
    };

    let registry = ClientRegistry::new();
    let brain = Arc::new(BrainService::new(shutdown.clone()));
    let dispatch = ComputerDispatchService::new(registry.clone());
    let control = ComputerEventService::new(brain, registry.clone(), dispatch.clone());

    let ws = websocket::run_websocket(registry, control, shutdown.clone())
        .map_err(|e| -> Box<dyn std::error::Error + Send + Sync> { Box::new(e) });
    let grpc = grpc::run_grpc(dispatch, shutdown)
        .map_err(|e| -> Box<dyn std::error::Error + Send + Sync> { Box::new(e) });

    futures::try_join!(ws, grpc).map(|_| ())
}

#[inline(always)]
fn init_tracing() {
    use tracing::Level;
    let debug = cfg!(debug_assertions);
    #[cfg(debug_assertions)]
    let default_level = Level::DEBUG;
    #[cfg(not(debug_assertions))]
    let default_level = Level::INFO;
    let trace_level = if let Ok(mut value) = std::env::var(ENV_BLUEKING_DEBUG) {
        value = value.trim().chars().take(5).collect();
        if value.is_empty() {
            default_level
        } else if value == "0" || value.eq_ignore_ascii_case("false") {
            Level::INFO
        } else if value.eq_ignore_ascii_case("true")
            || value == "1"
            || value.eq_ignore_ascii_case("debug")
        {
            Level::DEBUG
        } else if value.eq_ignore_ascii_case("trace") || value.parse::<u8>().unwrap_or(0) > 1 {
            Level::TRACE
        } else {
            eprintln!("Invalid value for {}: {}", ENV_BLUEKING_DEBUG, value);
            default_level
        }
    } else {
        default_level
    };

    const ENVFILTER_ERROR_MSG: &str = "EnvFilter configuration failed";
    tracing_subscriber::fmt()
        .with_line_number(debug)
        .with_file(debug)
        .with_thread_names(debug)
        .with_env_filter(
            tracing_subscriber::EnvFilter::builder()
                .with_default_directive(
                    tracing::level_filters::LevelFilter::from_level(trace_level).into(),
                )
                .with_env_var(ENV_BLUEKING_LOG)
                .from_env_lossy()
                .add_directive("hyper=info".parse().expect(ENVFILTER_ERROR_MSG))
                .add_directive("tower=info".parse().expect(ENVFILTER_ERROR_MSG))
                .add_directive("h2=info".parse().expect(ENVFILTER_ERROR_MSG))
                .add_directive("reqwest=info".parse().expect(ENVFILTER_ERROR_MSG)),
        )
        .compact()
        .init();
}

async fn shutdown_signal_once() {
    #[cfg(windows)]
    {
        tracing::info!("Listening for shutdown signal (Ctrl+C)");
        tokio::signal::ctrl_c()
            .inspect(|_| tracing::warn!("Ctrl+C received, shutting down"))
            .await
            .expect("Failed to listen for Ctrl+C");
    }

    #[cfg(unix)]
    {
        use futures::future::try_join4;
        use tokio::signal::unix::{SignalKind, signal};

        tracing::info!("Listening for shutdown signals (SIGINT, SIGTERM, SIGQUIT, SIGHUP)");

        let mut sigint = signal(SignalKind::interrupt()).expect("Failed to listen for SIGINT");
        let mut sigterm = signal(SignalKind::terminate()).expect("Failed to listen for SIGTERM");
        let mut sigquit = signal(SignalKind::quit()).expect("Failed to listen for SIGQUIT");
        let mut sighup = signal(SignalKind::hangup()).expect("Failed to listen for SIGHUP");

        let sigint_fut = async {
            sigint.recv().await;
            Err::<(), &'static str>("SIGINT")
        };
        let sigterm_fut = async {
            sigterm.recv().await;
            Err::<(), &'static str>("SIGTERM")
        };
        let sigquit_fut = async {
            sigquit.recv().await;
            Err::<(), &'static str>("SIGQUIT")
        };
        let sighup_fut = async {
            sighup.recv().await;
            Err::<(), &'static str>("SIGHUP")
        };

        if let Err(signal) = try_join4(sigint_fut, sigterm_fut, sigquit_fut, sighup_fut).await {
            eprintln!();
            tracing::warn!("{signal} received, shutting down");
        }
    }
}

/// One-shot shutdown broadcaster backed by a `Notify`.
#[derive(Clone)]
pub struct ShutdownSignal {
    notify: Arc<Notify>,
    flag: Arc<std::sync::atomic::AtomicBool>,
}

impl ShutdownSignal {
    /// Future that resolves when shutdown is requested.
    pub fn subscribe(&self) -> impl std::future::Future<Output = ()> + Send + 'static {
        let notify = self.notify.clone();
        let flag = self.flag.clone();
        async move {
            if flag.load(std::sync::atomic::Ordering::SeqCst) {
                return;
            }
            notify.notified().await;
        }
    }
}
