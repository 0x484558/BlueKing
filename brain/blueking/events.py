from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TypeAlias, TypeGuard

import blueking_pb2


BrainEvent: TypeAlias = "blueking_pb2.ChatEvent"


@dataclass
class BrainSubmission:
    """
    Wrapper for passing chat events through the Brain queue with a reply handle.

    :param event: The inbound chat event.
    :param response: Future used to deliver the Brain's reply asynchronously.
    """

    event: BrainEvent
    response: asyncio.Future[str]


def chatevent_typeguard(event: BrainEvent) -> TypeGuard[blueking_pb2.ChatEvent]:
    return isinstance(event, blueking_pb2.ChatEvent)


guards = [chatevent_typeguard]

def autocast(event: BrainEvent) -> blueking_pb2.ChatEvent:
    for guard in guards:
        if guard(event):
            return event
    raise ValueError(f"Event type not supported: {type(event)}")


BrainQueue: TypeAlias = "asyncio.Queue[BrainSubmission | None]"
