//! `websocket` module is responsible for terminating the `/cc` WebSocket endpoint (via Axum), tracking connected in‑game computers in `ClientRegistry`, turning raw websocket frames into `ComputerEvent`s and forwarding them into the Tower `ComputerEventService`.

use crate::{
    ShutdownSignal,
    events::{AppComputerControlService, ComputerEvent},
};
use axum::{
    extract::ws::{Message, WebSocket},
    extract::{State, WebSocketUpgrade},
    response::IntoResponse,
};
use futures::{sink::SinkExt, stream::StreamExt};
use std::sync::Arc;
use std::{collections::HashMap, net::SocketAddr};
use tokio::sync::Mutex as AsyncMutex;
use tokio::sync::{Mutex, mpsc};
use tower::ServiceExt;

const WS_BIND: ([u8; 4], u16) = ([0, 0, 0, 0], 3000);

/// Start Axum WebSocket server listening on `/cc`.
///
/// The server is parameterised by:
/// - `registry`: shared registry of connected computers.
/// - `control`: Tower service that handles `ComputerEvent`s.
/// - `shutdown`: cooperative shutdown signal.
pub async fn run_websocket(
    registry: ClientRegistry,
    control: AppComputerControlService,
    shutdown: ShutdownSignal,
) -> Result<(), std::io::Error> {
    let addr = SocketAddr::from(WS_BIND);
    tracing::info!("Binding Command&Control WebSocket HTTP server: {}", addr);
    let shutdown = shutdown.subscribe();
    if let Err(error) = axum::serve(
        match tokio::net::TcpListener::bind(addr).await {
            Ok(listener) => listener,
            Err(err) => {
                tracing::error!("Failed to bind WebSocket listener: {}", err);
                return Err(err);
            }
        },
        axum::Router::new()
            .route("/cc", axum::routing::get(ws_handler))
            .with_state(WebsocketState::new(registry, control)),
    )
    .with_graceful_shutdown(shutdown)
    .await
    {
        tracing::error!("Fatal error in WebSocket server: {}", error);
        Err(error)
    } else {
        Ok(())
    }
}

/// Registry of connected WebSocket clients.
#[derive(Clone)]
pub struct ClientRegistry {
    clients: Arc<Mutex<HashMap<i32, ClientEntry>>>,
}

#[derive(Clone)]
struct ClientEntry {
    sender: ClientSender,
    capabilities: Vec<crate::events::Capability>,
}

#[derive(Clone)]
pub struct ClientSender {
    sender: mpsc::Sender<Message>,
}

#[derive(Debug)]
pub enum ClientSendError {
    SerializeFailed(serde_json::Error),
    SendFailed(String),
}

impl std::fmt::Display for ClientSendError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ClientSendError::SerializeFailed(e) => write!(f, "serialize failed: {e}"),
            ClientSendError::SendFailed(e) => write!(f, "send failed: {e}"),
        }
    }
}

impl ClientSender {
    fn new(sender: mpsc::Sender<Message>) -> Self {
        Self { sender }
    }

    /// Send a raw WebSocket message into the client's mpsc channel.
    pub async fn send_message(&self, message: Message) -> Result<(), ClientSendError> {
        self.sender
            .send(message)
            .await
            .map_err(|e| ClientSendError::SendFailed(e.to_string()))
    }

    pub async fn send_text(&self, text: String) -> Result<(), ClientSendError> {
        self.send_message(Message::Text(text)).await
    }

    /// Serialize and send a typed Lua command to the client.
    pub async fn send_lua_command(&self, cmd: &LuaCommand) -> Result<(), ClientSendError> {
        let serialized = serialize_lua_command(cmd).map_err(ClientSendError::SerializeFailed)?;
        self.send_text(serialized).await
    }
}

impl ClientRegistry {
    pub fn new() -> Self {
        Self {
            clients: Arc::new(Mutex::new(HashMap::new())),
        }
    }

    /// Register a fresh client id with its outbound sender and advertised capabilities.
    pub async fn register(
        &self,
        id: i32,
        sender: mpsc::Sender<Message>,
        capabilities: Vec<crate::events::Capability>,
    ) {
        let mut clients = self.clients.lock().await;
        clients.insert(
            id,
            ClientEntry {
                sender: ClientSender::new(sender),
                capabilities,
            },
        );
        tracing::info!("Client {} registered. Total clients: {}", id, clients.len());
    }

    /// Remove a client from the registry (usually on disconnect).
    pub async fn remove(&self, id: i32) {
        let mut clients = self.clients.lock().await;
        clients.remove(&id);
        tracing::info!(
            "Client {} disconnected. Total clients: {}",
            id,
            clients.len()
        );
    }

    // pub async fn broadcast(&self, command: Command) {
    //     let clients = self.clients.lock().await;

    //     if clients.is_empty() {
    //         tracing::warn!("No clients connected to broadcast command to");
    //         return;
    //     }

    //     let command_json = match serde_json::to_string(&command) {
    //         Ok(json) => json,
    //         Err(e) => {
    //             tracing::error!("Failed to serialize command: {}", e);
    //             return;
    //         }
    //     };

    //     tracing::info!(
    //         "Broadcasting command '{}' (id: {}) to {} client(s)",
    //         command.name,
    //         command.id,
    //         clients.len()
    //     );

    //     for client in clients.values() {
    //         if let Err(e) = client.sender.send_text(command_json.clone()).await {
    //             tracing::error!("Failed to send command to client: {:?}", e);
    //         }
    //     }
    // }

    /// Send a WebSocket message to a single client, if still registered.
    pub async fn send_to(&self, id: i32, message: Message) -> Result<(), String> {
        // Clone the sender without holding the lock while awaiting.
        let sender = {
            let clients = self.clients.lock().await;
            clients.get(&id).map(|c| c.sender.clone())
        };

        match sender {
            Some(tx) => tx
                .send_message(message)
                .await
                .map_err(|e| format!("Failed to send to client {id}: {e:?}")),
            None => Err(format!("Client {id} is not registered")),
        }
    }

    /// Refresh capabilities for an already-registered client.
    pub async fn update_capabilities(
        &self,
        id: i32,
        capabilities: Vec<crate::events::Capability>,
    ) -> Result<(), String> {
        let mut clients = self.clients.lock().await;
        match clients.get_mut(&id) {
            Some(entry) => {
                entry.capabilities = capabilities;
                Ok(())
            }
            None => Err(format!("Client {id} is not registered")),
        }
    }

    /// Find any client that advertises the requested capability.
    pub async fn find_by_capability(
        &self,
        capability: crate::events::Capability,
    ) -> Option<ClientSender> {
        let clients = self.clients.lock().await;
        clients
            .values()
            .find(|entry| entry.capabilities.contains(&capability))
            .map(|entry| entry.sender.clone())
    }
}

/// Axum state for the WebSocket endpoint.
#[derive(Clone)]
pub struct WebsocketState {
    registry: ClientRegistry,
    control: AppComputerControlService,
}

impl WebsocketState {
    pub fn new(registry: ClientRegistry, control: AppComputerControlService) -> Self {
        Self { registry, control }
    }
}

pub async fn ws_handler(
    ws: WebSocketUpgrade,
    State(state): State<WebsocketState>,
) -> impl IntoResponse {
    ws.on_upgrade(move |socket| handle_socket(socket, state.clone()))
}

/// Drive a single WebSocket connection: register, then forward frames as `ComputerEvent`s.
async fn handle_socket(socket: WebSocket, state: WebsocketState) {
    let (sender, mut receiver) = socket.split();
    let sender = Arc::new(AsyncMutex::new(sender));
    let registry = state.registry.clone();
    let control = state.control.clone();

    // Expect first message to be register
    let register_msg = receiver.next().await;
    let register_msg = match register_msg {
        Some(Ok(Message::Text(msg))) => msg,
        _ => {
            tracing::error!("Expected register message");
            return;
        }
    };

    let register_event: ComputerEvent = match serde_json::from_str(&register_msg) {
        Ok(event) => event,
        Err(e) => {
            tracing::error!("Invalid register message: {}", e);
            return;
        }
    };

    let (client_id, capabilities) = match register_event.clone() {
        ComputerEvent::Register { id, capabilities } => (id, capabilities),
        _ => {
            tracing::error!("First message must be register event");
            return;
        }
    };

    // Register client
    let (tx, mut rx) = mpsc::channel::<Message>(8);
    registry.register(client_id, tx, capabilities).await;
    // Inform the control service about registration for bookkeeping.
    dispatch_event(&control, register_event, client_id).await;

    // Forward messages from other tasks to this websocket
    let sender_forward = Arc::clone(&sender);
    tokio::spawn(async move {
        while let Some(msg) = rx.recv().await {
            if sender_forward.lock().await.send(msg).await.is_err() {
                break;
            }
        }
    });

    // Handle incoming messages
    use tokio::time::{Duration, timeout};
    const CLIENT_TIMEOUT_SECS: u64 = 120;

    loop {
        let msg = timeout(Duration::from_secs(CLIENT_TIMEOUT_SECS), receiver.next()).await;
        match msg {
            Ok(Some(Ok(Message::Text(text)))) => {
                match serde_json::from_str::<ComputerEvent>(&text) {
                    Ok(event) => dispatch_event(&control, event, client_id).await,
                    Err(e) => tracing::error!("Invalid event: {}", e),
                }
            }
            Ok(Some(Ok(Message::Close(_)))) => {
                tracing::info!("Client {} disconnected", client_id);
                registry.remove(client_id).await;
                dispatch_event(
                    &control,
                    ComputerEvent::Deregister {
                        id: client_id,
                        timed_out: false,
                    },
                    client_id,
                )
                .await;
                break;
            }
            Ok(Some(Ok(_))) => {} // ignore non-text frames
            Ok(Some(Err(e))) => {
                tracing::warn!("WebSocket error for client {}: {}", client_id, e);
            }
            Ok(None) => {
                tracing::info!("Client {} stream ended", client_id);
                registry.remove(client_id).await;
                dispatch_event(
                    &control,
                    ComputerEvent::Deregister {
                        id: client_id,
                        timed_out: false,
                    },
                    client_id,
                )
                .await;
                break;
            }
            Err(_) => {
                tracing::warn!("Client {} timed out (no activity)", client_id);
                registry.remove(client_id).await;
                dispatch_event(
                    &control,
                    ComputerEvent::Deregister {
                        id: client_id,
                        timed_out: true,
                    },
                    client_id,
                )
                .await;
                // Attempt to close the socket gracefully.
                let _ = sender.lock().await.send(Message::Close(None)).await;
                break;
            }
        }
    }
}

/// JSON payload for a chat message Lua command.
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct MessageArgs {
    pub message: String,
}

/// Commands sent to Lua clients, tagged by `name` in the JSON envelope.
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
#[serde(tag = "name", rename_all = "snake_case")]
pub enum LuaCommand {
    Message { id: String, args: MessageArgs },
}

impl LuaCommand {
    /// Construct a chat message command with a fresh id.
    pub fn chat_message(message: String) -> Self {
        LuaCommand::Message {
            id: uuid::Uuid::new_v4().to_string(),
            args: MessageArgs { message },
        }
    }
}

/// Serialize any Lua command to JSON string for transport over WebSocket.
pub fn serialize_lua_command(cmd: &LuaCommand) -> Result<String, serde_json::Error> {
    serde_json::to_string(cmd)
}

/// Helper to send one `ComputerEvent` into the Tower service.
async fn dispatch_event(service: &AppComputerControlService, event: ComputerEvent, client_id: i32) {
    if let Err(err) = service.clone().oneshot(event).await {
        tracing::error!("Failed to process event for client {}: {}", client_id, err);
    }
}
