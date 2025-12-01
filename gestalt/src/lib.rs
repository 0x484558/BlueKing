use std::fmt;

/// Shared error type for dispatching actions to clients.
#[derive(Debug)]
pub enum DispatchError {
    SendFailed(String),
    NoClient,
}

impl fmt::Display for DispatchError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            DispatchError::SendFailed(e) => write!(f, "send failed: {e}"),
            DispatchError::NoClient => write!(f, "no client available"),
        }
    }
}

impl std::error::Error for DispatchError {}

tonic::include_proto!("blueking");
