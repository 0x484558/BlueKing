from __future__ import annotations

import asyncio
import logging
import os
from contextvars import ContextVar
from typing import cast, override

import grpc
from grpc.aio import ServicerContext

from blueking.events import BrainQueue, BrainSubmission
from blueking import blueking_pb2, blueking_pb2_grpc

DEFAULT_BRAIN_BIND = "127.0.0.1:50051"
DEFAULT_GESTALT_ENDPOINT = "127.0.0.1:50052"
_gestalt_endpoint_override: str | None = None
_outbound_stub: ContextVar[blueking_pb2_grpc.GestaltStub | None] = ContextVar(
    "blueking.grpc.outbound_stub", default=None
)
logger = logging.getLogger(__name__)


def configure(gestalt_endpoint: str | None = None) -> None:
    """
    Allow the embedding host to override the Gestalt endpoint.

    :param gestalt_endpoint: Optional endpoint override for outbound Gestalt calls.
    :return: None.
    """
    global _gestalt_endpoint_override
    if gestalt_endpoint:
        _gestalt_endpoint_override = gestalt_endpoint


def _get_outbound_stub() -> blueking_pb2_grpc.GestaltStub:
    """
    Retrieve the Gestalt stub from context or raise if unavailable.

    :return: Active Gestalt gRPC stub.
    :raises RuntimeError: When no stub has been configured.
    """
    stub = _outbound_stub.get()
    if stub is None:
        raise RuntimeError("Outbound gestalt stub is not available")
    return stub


async def serve_brain(
    queue: BrainQueue,
    bind: str | None = None,
    shutdown: asyncio.Event | None = None,
) -> None:
    """
    Run the Brain gRPC server that receives Chat events from Rust.

    :param queue: Queue receiving Brain submissions from the gRPC service.
    :param bind: Address to bind for incoming connections.
    :param shutdown: Optional event used to signal a graceful shutdown.
    :return: None.
    """
    address = bind or os.getenv("BRAIN_GRPC_ADDR", DEFAULT_BRAIN_BIND)
    server = grpc.aio.server()

    class _BrainServicer(blueking_pb2_grpc.BrainServicer):
        @override
        async def Chat(self, request: blueking_pb2.ChatEvent, context: ServicerContext[blueking_pb2.ChatEvent,blueking_pb2.ChatResponse]):
            future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
            submission = BrainSubmission(
                event=blueking_pb2.ChatEvent(username=request.username, message=request.message),
                response=future,
            )
            await queue.put(submission)
            try:
                reply = await future
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - service boundary
                logger.exception("Failed to process chat event", exc_info=exc)
                context.set_details("Internal server error")
                context.set_code(grpc.StatusCode.INTERNAL)
                raise
            return blueking_pb2.ChatResponse(reply=reply)

    blueking_pb2_grpc.add_BrainServicer_to_server(_BrainServicer(), server)
    _ = server.add_insecure_port(address)
    await server.start()
    logger.info("Python Brain gRPC started on %s", address)

    try:
        if shutdown is None:
            _ = await server.wait_for_termination()
        else:
            termination = asyncio.create_task(server.wait_for_termination())
            shutdown_task = asyncio.create_task(shutdown.wait())
            done, pending = await asyncio.wait(
                {termination, shutdown_task}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                _ = task.cancel()
            for task in done:
                try:
                    _ = task.result()
                except asyncio.CancelledError:
                    pass
            logger.info("Shutdown signal received; stopping Python Brain gRPC")
            await server.stop(0)
            _ = await server.wait_for_termination()
    except asyncio.CancelledError:
        logger.info("serve_brain cancelled; stopping Python Brain gRPC")
        await server.stop(0)
        _ = await server.wait_for_termination()
    finally:
        logger.info("Python Brain gRPC stopped")


async def outbound_connection(endpoint: str | None = None) -> None:
    """
    Keep an outbound Gestalt channel alive in a context variable.

    :param endpoint: Optional override for the Gestalt endpoint.
    :return: None.
    """
    target = (
        endpoint
        or _gestalt_endpoint_override
        or os.getenv("GESTALT_GRPC_ENDPOINT", DEFAULT_GESTALT_ENDPOINT)
    )
    async with grpc.aio.insecure_channel(target) as channel:
        stub = blueking_pb2_grpc.GestaltStub(channel)
        token = _outbound_stub.set(stub)
        try:
            await asyncio.Future()
        finally:
            _outbound_stub.reset(token)


async def send_chat_message(
    payload: str,
) -> blueking_pb2.SendChatMessageResponse:
    """
    Ask the Gestalt service to broadcast a message.

    :param payload: Message payload to broadcast.
    :param endpoint: Optional override for the Gestalt endpoint.
    :return: Response from the Gestalt SendChatMessage RPC.
    """
    stub = _get_outbound_stub()
    request = blueking_pb2.SendChatMessageRequest(payload=payload)
    return cast(blueking_pb2.SendChatMessageResponse,await stub.SendChatMessage(request))
