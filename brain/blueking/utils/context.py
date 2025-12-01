from __future__ import annotations

import hashlib
import os
from contextvars import ContextVar, Token
from pathlib import Path
from typing import TYPE_CHECKING

import chromadb
from chromadb import Collection
from chromadb.api import ClientAPI
from chromadb.config import Settings

from blueking.utils.state_db import BrainState

# Align with state_db env-style: allow override of the local Chroma storage path.
_DEFAULT_VECTOR_DB_ENV = "BLUEKING_VECTOR_DB_PATH"
_DEFAULT_VECTOR_DB_PATH = "./vector.db"
_EMBED_DIMENSIONS = 128

_chroma_client: ContextVar[ClientAPI | None] = ContextVar(
    "blueking.context.chroma_client", default=None
)
_gestalt_collection: ContextVar[Collection | None] = ContextVar(
    "blueking.context.gestalt_collection", default=None
)
_brain_state: ContextVar[BrainState | None] = ContextVar(
    "blueking.context.brain_state", default=None
)

if TYPE_CHECKING:
    from blueking import blueking_pb2_grpc


def _hash_embed(text: str, dimensions: int = _EMBED_DIMENSIONS) -> list[float]:
    """
    Cheap, deterministic embedding to avoid remote embedding dependencies.

    :param text: Input string to embed.
    :param dimensions: Desired embedding vector length.
    :return: List of floating point values representing the embedding.
    """
    digest = hashlib.sha256(text.encode()).digest()
    scale = 1.0 / 255.0
    return [digest[i % len(digest)] * scale for i in range(dimensions)]


def ensure_chroma_client(
    persist_directory: str | os.PathLike[str] | None = None,
) -> ClientAPI:
    """
    Get or create a Chroma client rooted at the provided directory.

    :param persist_directory: Optional path for the Chroma persistence directory.
    :return: Active Chroma client instance.
    """
    client = _chroma_client.get()
    if client is not None:
        return client

    directory = Path(
        persist_directory
        or os.getenv(_DEFAULT_VECTOR_DB_ENV, _DEFAULT_VECTOR_DB_PATH)
    ).expanduser()
    directory.mkdir(parents=True, exist_ok=True)

    client = chromadb.PersistentClient(
        path=str(directory),
        settings=Settings(anonymized_telemetry=False),
    )
    _ = _chroma_client.set(client)
    return client


def ensure_gestalt_collection(
    persist_directory: str | os.PathLike[str] | None = None,
) -> Collection:
    """
    Get or create the shared Gestalt collection from the current Chroma client.

    :param persist_directory: Optional Chroma persistence directory.
    :return: Gestalt Chroma collection.
    """
    collection = _gestalt_collection.get()
    if collection is not None:
        return collection

    client = ensure_chroma_client(persist_directory=persist_directory)
    collection = client.get_or_create_collection(name="gestalt")
    _ = _gestalt_collection.set(collection)
    return collection


def init_chroma(persist_directory: str | os.PathLike[str] | None = None) -> Collection:
    """
    Initialize the shared Chroma client and Gestalt collection.

    :param persist_directory: Optional Chroma persistence directory.
    :return: Initialized Gestalt Chroma collection.
    """
    return ensure_gestalt_collection(persist_directory)


def embed_text(text: str) -> list[float]:
    """
    Produce a deterministic embedding for use with Chroma add/query APIs.

    :param text: Raw text to embed.
    :return: Deterministic embedding vector.
    """
    return _hash_embed(text)


def set_brain_state(state: BrainState) -> Token[BrainState | None]:
    """
    Publish the current BrainState into a context variable for subflows/crews.

    :param state: Brain state to publish.
    :return: Token for resetting the context variable.
    """
    return _brain_state.set(state)


def reset_brain_state(token: Token[BrainState | None]) -> None:
    """
    Reset the BrainState context to its previous value.

    :param token: Token returned from :func:`set_brain_state`.
    :return: None.
    """
    _brain_state.reset(token)


def get_brain_state(default: BrainState | None = None) -> BrainState | None:
    """
    Retrieve the current BrainState from context.

    :param default: Fallback value when no state is set.
    :return: Current BrainState or the provided default.
    """
    state = _brain_state.get()
    return state if state is not None else default


class Context:
    """
    Convenience accessor for global context variables used across the app.
    """

    @property
    def chroma_client(self) -> ClientAPI | None:
        return _chroma_client.get()

    @property
    def gestalt_collection(self) -> Collection | None:
        return _gestalt_collection.get()

    @property
    def brain_state(self) -> BrainState | None:
        return _brain_state.get()

    @property
    def outbound_stub(self) -> blueking_pb2_grpc.GestaltStub | None:
        """
        Retrieve the Gestalt gRPC stub if an outbound connection is configured.

        :return: GestaltStub instance or None when unavailable.
        """
        # Lazy import to avoid cycles; returns None if stub is unavailable.
        try:
            from blueking.grpc import _outbound_stub  # type: ignore
        except Exception:
            return None
        return _outbound_stub.get()


# Shared instance for easy import.
context = Context()


__all__ = [
    "ensure_chroma_client",
    "ensure_gestalt_collection",
    "init_chroma",
    "embed_text",
    "set_brain_state",
    "reset_brain_state",
    "get_brain_state",
    "Context",
    "context",
]
