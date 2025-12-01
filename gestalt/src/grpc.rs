//! gRPC server for the Gestalt API. Exposes a dispatch service to the Python "Brain" so that it can ask to send commands to computers over WebSocket.

use crate::ShutdownSignal;
use crate::actions::{ComputerAction, ComputerDispatchService};
use crate::events::Capability;
use crate::websocket::LuaCommand;
use blueking::DispatchError;
use blueking::gestalt_server::{Gestalt as GestaltApi, GestaltServer};
use blueking::send_chat_message_response::Status as SendStatus;
use blueking::{SendChatMessageRequest, SendChatMessageResponse};
use std::net::SocketAddr;
use tonic::{Request, Response, Status};
use tower::ServiceExt;

const GRPC_BIND: ([u8; 4], u16) = ([127, 0, 0, 1], 50052);

/// Run the Gestalt gRPC server, wiring it to the computer dispatch service.
pub async fn run_grpc(
    dispatch: ComputerDispatchService,
    shutdown: ShutdownSignal,
) -> Result<(), tonic::transport::Error> {
    let addr = SocketAddr::from(GRPC_BIND);
    tracing::info!("Binding gRPC server: {}", addr);
    tonic::transport::server::Server::builder()
        .add_service(GestaltServer::new(GestaltService::new(dispatch)))
        .serve_with_shutdown(addr, shutdown.subscribe())
        .await
}

/// Tonic service implementation for the generated `Gestalt` gRPC API.
pub struct GestaltService {
    dispatch: ComputerDispatchService,
}

impl GestaltService {
    pub fn new(dispatch: ComputerDispatchService) -> Self {
        Self { dispatch }
    }
}

#[tonic::async_trait]
impl GestaltApi for GestaltService {
    async fn send_chat_message(
        &self,
        request: Request<SendChatMessageRequest>,
    ) -> Result<Response<SendChatMessageResponse>, Status> {
        let payload = request.into_inner().payload;
        let cmd = LuaCommand::chat_message(payload);
        // Delegate to the internal Tower service that knows how to talk to
        // WebSocket clients via the registry.
        let send_res = self
            .dispatch
            .clone()
            .oneshot(ComputerAction::SendToCapability {
                capability: Capability::Chat,
                command: cmd,
            })
            .await;

        let (status, error_message) = match send_res {
            Ok(()) => (SendStatus::Ok, String::new()),
            Err(DispatchError::NoClient) => (
                SendStatus::NoChatClient,
                "no chat clients connected".to_string(),
            ),
            Err(DispatchError::SendFailed(err)) => (SendStatus::SendFailed, err),
        };

        Ok(Response::new(SendChatMessageResponse {
            status: status as i32,
            error_message,
        }))
    }
}
