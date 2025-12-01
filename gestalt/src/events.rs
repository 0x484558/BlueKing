//! `events` module provides processing of events received from computers and their forwarding to the "Brain".

use crate::actions::{ComputerAction, ComputerDispatchService};
use crate::brain::{Brain, BrainService};
use crate::websocket::{ClientRegistry, LuaCommand};
use blueking as pb;
use blueking::DispatchError;
use pin_project_lite::pin_project;
use serde::{Deserialize, Serialize};
use std::pin::Pin;
use std::sync::Arc;
use std::task::{Context, Poll};
use tower::Service;
use tower::ServiceExt;

/// Capability advertised by a client on registration.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, Hash)]
#[serde(rename_all = "snake_case")]
pub enum Capability {
    Chat,
}

fn default_capabilities() -> Vec<Capability> {
    vec![]
}

/// Event sent from a computer when a chat message occurs.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ComputerChatEvent {
    pub username: String,
    pub message: String,
}

impl From<pb::ChatEvent> for ComputerChatEvent {
    fn from(event: pb::ChatEvent) -> Self {
        ComputerChatEvent {
            username: event.username,
            message: event.message,
        }
    }
}

/// Event sent from a computer after executing a command.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CommandResultEvent {
    pub command_id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

/// All possible events that can be received from computers.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ComputerEvent {
    Register {
        id: i32,
        #[serde(default = "default_capabilities")]
        capabilities: Vec<Capability>,
    },
    Chat(ComputerChatEvent),
    CommandResult(CommandResultEvent),
    /// Emitted when a client disconnects; `timed_out` distinguishes timeout vs negotiated close.
    Deregister {
        id: i32,
        timed_out: bool,
    },
}

#[derive(Debug)]
pub enum ControlError {
    Brain(crate::brain::BrainError),
    Dispatch(DispatchError),
}

impl std::fmt::Display for ControlError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ControlError::Brain(e) => write!(f, "brain error: {e}"),
            ControlError::Dispatch(e) => write!(f, "dispatch error: {e}"),
        }
    }
}

impl std::error::Error for ControlError {}

/// Tower service that routes client events by invoking the brain and registry.
#[derive(Clone)]
pub struct ComputerEventService<B: Brain> {
    brain: Arc<B>,
    registry: ClientRegistry,
    dispatch: ComputerDispatchService,
}

pub type AppComputerControlService = ComputerEventService<BrainService>;

impl<B: Brain> ComputerEventService<B> {
    pub fn new(brain: Arc<B>, registry: ClientRegistry, dispatch: ComputerDispatchService) -> Self {
        Self {
            brain,
            registry,
            dispatch,
        }
    }

    async fn handle_chat(
        brain: Arc<B>,
        dispatch: ComputerDispatchService,
        chat_event: ComputerChatEvent,
    ) -> Result<(), ControlError> {
        let reply = brain.chat(chat_event).await.map_err(ControlError::Brain)?;
        if reply.is_empty() {
            return Ok(());
        }

        let cmd = LuaCommand::chat_message(reply);
        dispatch
            .oneshot(ComputerAction::SendToCapability {
                capability: Capability::Chat,
                command: cmd,
            })
            .await
            .map_err(ControlError::Dispatch)
    }

    async fn handle_command_result(result_event: CommandResultEvent) -> Result<(), ControlError> {
        match result_event.error {
            None => tracing::info!("Command {} succeeded", result_event.command_id),
            Some(err) => tracing::warn!("Command {} failed: {}", result_event.command_id, err),
        }
        Ok(())
    }

    async fn handle_register(
        registry: ClientRegistry,
        id: i32,
        capabilities: Vec<Capability>,
    ) -> Result<(), ControlError> {
        match registry.update_capabilities(id, capabilities.clone()).await {
            Ok(()) => tracing::info!("Client {} refreshed capabilities {:?}", id, capabilities),
            Err(err) => tracing::warn!(
                "Client {} attempted to refresh capabilities but is not registered: {}",
                id,
                err
            ),
        }
        Ok(())
    }

    async fn handle_deregister(id: i32, timed_out: bool) -> Result<(), ControlError> {
        if timed_out {
            tracing::warn!("Client {} timed out and was deregistered", id);
        } else {
            tracing::info!("Client {} deregistered", id);
        }
        Ok(())
    }
}

impl<B: Brain> Service<ComputerEvent> for ComputerEventService<B> {
    type Response = ();
    type Error = ControlError;
    type Future = EventFuture;

    fn poll_ready(&mut self, _cx: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
        Poll::Ready(Ok(()))
    }

    fn call(&mut self, event: ComputerEvent) -> Self::Future {
        tracing::info!("Processing event: {:?}", event);
        let brain = Arc::clone(&self.brain);
        let registry = self.registry.clone();
        let dispatch = self.dispatch.clone();

        let handle = tokio::spawn(async move {
            match event {
                ComputerEvent::Chat(chat_event) => {
                    Self::handle_chat(brain, dispatch, chat_event).await
                }
                ComputerEvent::CommandResult(result_event) => {
                    Self::handle_command_result(result_event).await
                }
                ComputerEvent::Register { id, capabilities } => {
                    Self::handle_register(registry, id, capabilities).await
                }
                ComputerEvent::Deregister { id, timed_out } => {
                    Self::handle_deregister(id, timed_out).await
                }
            }
        });

        EventFuture::new(handle)
    }
}

pin_project! {
    /// Manual future for `ComputerEventService` so the outer service remains a concrete type.
    pub struct EventFuture {
        #[pin]
        handle: tokio::task::JoinHandle<Result<(), ControlError>>,
    }
}

impl EventFuture {
    fn new(handle: tokio::task::JoinHandle<Result<(), ControlError>>) -> Self {
        Self { handle }
    }
}

impl Future for EventFuture {
    type Output = Result<(), ControlError>;

    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        let this = self.project();
        let join = std::task::ready!(this.handle.poll(cx));
        match join {
            Ok(res) => Poll::Ready(res),
            Err(err) => {
                tracing::warn!("Control task join error: {}", err);
                Poll::Ready(Ok(()))
            }
        }
    }
}

// /// Handle command execution results
// async fn handle_command_result(result_event: CommandResultEvent, history: &History) {
//     let succeeded = result_event.error.is_none();

//     if succeeded {
//         tracing::info!("Command {} executed successfully", result_event.command_id);
//     } else {
//         tracing::warn!(
//             "Command {} failed: {}",
//             result_event.command_id,
//             result_event.error.as_deref().unwrap_or("unknown error")
//         );
//     }

//     // Add to history for context
//     let status_text = match result_event.error {
//         None => "succeeded".to_string(),
//         Some(err) if err.is_empty() => "succeeded".to_string(),
//         Some(err) => format!("failed: {err}"),
//     };

//     let result_msg = Message {
//         role: "system".to_string(),
//         content: Some(format!(
//             "Command {} {}",
//             result_event.command_id, status_text
//         )),
//         name: None,
//         tool_calls: None,
//         tool_call_id: None,
//     };

//     history.push(result_msg).await;
// }
