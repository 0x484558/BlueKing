//! `brain` module is a gRPC client for the external Python-based agentic AI "Brain" service.

use blueking as pb;
use blueking::brain_client::BrainClient;

use crate::{ShutdownSignal, events::ComputerChatEvent};
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::Mutex;
use tonic::transport::Endpoint;
use tower::ServiceExt;

const BRAIN_BIND: ([u8; 4], u16) = ([192, 168, 50, 157], 50051);

/// Shared connection state for `BrainService`, guarded by a mutex to allow reconnect.
struct BrainInner {
    endpoint: Endpoint,
    channel: Option<tonic::transport::Channel>,
}

/// gRPC-backed brain client that forwards chat events to the Python service.
#[derive(Clone)]
pub struct BrainService {
    inner: Arc<Mutex<BrainInner>>,
    shutdown: ShutdownSignal,
}

#[derive(Debug)]
pub enum BrainError {
    Transport(tonic::transport::Error),
    Rpc(tonic::Status),
    Canceled,
}

impl std::fmt::Display for BrainError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            BrainError::Transport(e) => write!(f, "transport error: {}", e),
            BrainError::Rpc(e) => write!(f, "rpc error: {}", e),
            BrainError::Canceled => write!(f, "canceled"),
        }
    }
}

impl std::error::Error for BrainError {}

impl From<tonic::transport::Error> for BrainError {
    fn from(err: tonic::transport::Error) -> Self {
        BrainError::Transport(err)
    }
}

impl From<tonic::Status> for BrainError {
    fn from(err: tonic::Status) -> Self {
        BrainError::Rpc(err)
    }
}

/// Trait to allow mocking / swapping the brain backend.
#[tonic::async_trait]
pub trait Brain: Send + Sync + 'static {
    /// Forward an in‑game chat event to the Brain and return its textual reply.
    ///
    /// An empty reply means "no response".
    async fn chat(&self, chat_event: ComputerChatEvent) -> Result<String, BrainError>;
}

impl BrainService {
    /// Create a new brain client, initially disconnected.
    ///
    /// The first call to `chat` (or `ensure_channel`) will establish a connection.
    pub fn new(shutdown: ShutdownSignal) -> Self {
        let endpoint = tonic::transport::Endpoint::from_shared(
            std::net::SocketAddr::from(BRAIN_BIND).to_string(),
        )
        .expect("failed to parse brain endpoint");

        Self {
            inner: Arc::new(Mutex::new(BrainInner {
                endpoint,
                channel: None,
            })),
            shutdown,
        }
    }

    /// Ensure we have a ready channel, reconnecting with backoff and honoring shutdown.
    async fn ensure_channel(&self) -> Result<tonic::transport::Channel, BrainError> {
        loop {
            // Fast path: reuse existing channel if ready.
            {
                let mut inner = self.inner.lock().await;
                if let Some(channel) = inner.channel.as_mut() {
                    match channel.ready().await {
                        Ok(_) => return Ok(channel.clone()),
                        Err(err) => {
                            tracing::warn!("Brain channel not ready, reconnecting: {}", err);
                            inner.channel = None;
                        }
                    }
                }
                // fall through to (re)connect
            }

            let endpoint = {
                let inner = self.inner.lock().await;
                inner.endpoint.clone()
            };

            // Attempt to connect, but bail on shutdown.
            let connect = endpoint.connect();
            let connect_result = tokio::select! {
                _ = self.shutdown.subscribe() => {
                    return Err(BrainError::Canceled);
                }
                res = connect => res,
            };

            match connect_result {
                Ok(channel) => {
                    let mut inner = self.inner.lock().await;
                    inner.channel = Some(channel.clone());
                    return Ok(channel);
                }
                Err(err) => {
                    tracing::warn!(
                        "Failed to connect to brain at {} ({}), retrying...",
                        endpoint.uri(),
                        err
                    );
                    tokio::select! {
                        _ = self.shutdown.subscribe() => return Err(BrainError::Canceled),
                        _ = tokio::time::sleep(Duration::from_millis(3000)) => {},
                    }
                }
            }
        }
    }
}

#[tonic::async_trait]
impl Brain for BrainService {
    async fn chat(&self, chat_event: ComputerChatEvent) -> Result<String, BrainError> {
        let channel = self.ensure_channel().await?;
        let mut client = BrainClient::new(channel);
        let request = tonic::Request::new(pb::ChatEvent::from(chat_event));
        let response = client.chat(request).await?;
        Ok(response.into_inner().reply)
    }
}

impl From<ComputerChatEvent> for pb::ChatEvent {
    fn from(event: ComputerChatEvent) -> Self {
        pb::ChatEvent {
            username: event.username,
            message: event.message,
        }
    }
}
