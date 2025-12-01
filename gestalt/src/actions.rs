//! `actions` module hosts outbound actions on computers and the service for dispatching them.

use crate::events::Capability;
use crate::websocket::{ClientRegistry, LuaCommand};
use axum::extract::ws::Message as WsMessage;
use blueking::DispatchError;
use pin_project_lite::pin_project;
use std::future::Future;
use std::pin::Pin;
use std::task::{Context, Poll};
use tower::Service;

/// Outbound actions towards computers / websocket clients.
#[derive(Clone)]
pub enum ComputerAction {
    #[allow(dead_code)]
    SendToId { id: i32, message: WsMessage },
    SendToCapability {
        capability: Capability,
        command: LuaCommand,
    },
}

/// Service that dispatches outbound actions to connected websocket clients via the registry.
#[derive(Clone)]
pub struct ComputerDispatchService {
    registry: ClientRegistry,
}

impl ComputerDispatchService {
    pub fn new(registry: ClientRegistry) -> Self {
        Self { registry }
    }

    fn dispatch_action(&self, action: ComputerAction) -> ClientDispatchFuture {
        let registry = self.registry.clone();
        ClientDispatchFuture {
            handle: tokio::spawn(async move { Self::handle_action(registry, action).await }),
        }
    }

    async fn handle_action(
        registry: ClientRegistry,
        action: ComputerAction,
    ) -> Result<(), DispatchError> {
        match action {
            ComputerAction::SendToId { id, message } => {
                registry
                    .send_to(id, message)
                    .await
                    .map_err(DispatchError::SendFailed)?;
            }
            ComputerAction::SendToCapability {
                capability,
                command,
            } => {
                if let Some(sender) = registry.find_by_capability(capability).await {
                    sender
                        .send_lua_command(&command)
                        .await
                        .map_err(|e| DispatchError::SendFailed(e.to_string()))?;
                } else {
                    return Err(DispatchError::NoClient);
                }
            }
        }
        Ok(())
    }
}

impl Service<ComputerAction> for ComputerDispatchService {
    type Response = ();
    type Error = DispatchError;
    type Future = ClientDispatchFuture;

    fn poll_ready(&mut self, _cx: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
        Poll::Ready(Ok(()))
    }

    fn call(&mut self, action: ComputerAction) -> Self::Future {
        self.dispatch_action(action)
    }
}

pin_project! {
    pub struct ClientDispatchFuture {
        #[pin]
        handle: tokio::task::JoinHandle<Result<(), DispatchError>>,
    }
}

impl Future for ClientDispatchFuture {
    type Output = Result<(), DispatchError>;

    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        let this = self.project();
        let join = std::task::ready!(this.handle.poll(cx));
        match join {
            Ok(res) => Poll::Ready(res),
            Err(err) => {
                tracing::warn!("Dispatch task join error: {}", err);
                Poll::Ready(Ok(()))
            }
        }
    }
}
