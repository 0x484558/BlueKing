#!/usr/bin/env python
from __future__ import annotations

import asyncio
import logging
from typing import Any

from crewai import Agent
from crewai.flow import Flow, listen, router, start
from crewai.flow.visualization.builder import build_flow_structure
from crewai.flow.visualization.renderers.interactive import render_interactive
from crewai.flow.visualization.types import FlowStructure, StructureEdge

from blueking.agents.builder import build_agent
from blueking.events import BrainSubmission, BrainQueue
from blueking.flows.example_flow import ExampleFlow
from blueking.grpc import outbound_connection, serve_brain
from blueking.utils.context import (
    init_chroma,
    set_brain_state,
    reset_brain_state,
)
from blueking.utils.state_db import LmdbDict, BrainState


logger = logging.getLogger(__name__)


class Brain(Flow[LmdbDict]):  # pyright: ignore[reportInvalidTypeArguments]
    state: BrainState  # pyright:ignore[reportIncompatibleMethodOverride]

    def __init__(
        self,
        queue: BrainQueue | None = None,
        gestalt_agent: Agent | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Create the Brain flow and configure shared resources.

        :param queue: Queue used to receive submissions from gRPC.
        :param gestalt_agent: Optional shared Gestalt agent instance.
        :param kwargs: Additional Flow initialization parameters.
        :return: None.
        """
        self._queue: BrainQueue | None = queue
        self._tasks: set[asyncio.Task[Any]] = set()
        self._gestalt: Agent = gestalt_agent or build_agent("gestalt")
        super().__init__(**kwargs)
        # Initialize shared Chroma store once at startup.
        _ = init_chroma()

    @property
    def gestalt(self) -> Agent:
        """
        Access the Gestalt agent associated with the Brain.

        :return: Gestalt Agent instance.
        """
        return self._gestalt

    @start("continue_intake")
    async def intake(self) -> BrainSubmission | None:
        """
        Ingest chat submissions from the queue and emit them into the flow.

        :return: Next BrainSubmission or None when shutdown is requested.
        """
        if self._queue is None:
            raise RuntimeError("Brain queue is not configured")
        logger.info("Brain waiting for submissions")
        try:
            submission = await self._queue.get()
        except KeyboardInterrupt:
            logger.info("Brain interrupted, shutting down gracefully")
            return None
        if submission is None:
            await self._await_pending_tasks()
        logger.info("Brain received submission")
        return submission

    @router(intake)
    def route_submission(self, submission: BrainSubmission | None) -> str | None:
        """
        Route the intake output toward processing listeners.

        :param submission: BrainSubmission instance or None sentinel from the queue.
        :return: Routing label for downstream listeners.
        """
        if submission is None:
            return None
        return "process_submission"

    @listen("process_submission")
    async def handle_submission(self, submission: BrainSubmission) -> str | None:
        """
        Launch processing for a single brain submission and continue the intake loop.

        :param submission: Incoming chat submission wrapper.
        :return: Continuation trigger name or None when not continuing.
        """
        task = asyncio.create_task(self._process_submission(submission))
        self._track_task(task)
        return "continue_intake"

    @router(handle_submission)
    def continue_loop(self, result: str | None) -> str | None:
        """
        Signal the intake method to pull the next submission while tasks run.

        :param result: Result emitted by the submission handler.
        :return: Trigger to re-run intake or None to stop looping.
        """
        if result != "continue_intake":
            return None
        return "continue_intake"

    async def _process_submission(self, submission: BrainSubmission) -> None:
        """
        Execute the example flow for an incoming submission and reply.

        :param submission: Incoming chat submission wrapper.
        :return: None.
        """
        self.state.username = submission.event.username
        self.state.message = submission.event.message
        state_token = set_brain_state(self.state)

        example_flow = ExampleFlow(gestalt_agent=self._gestalt)
        try:
            _ = await example_flow.kickoff_async(
                inputs={
                    "crewai_trigger_payload": {
                        "prompt": self.state.message or "No message provided"
                    }
                }
            )
            reply = example_flow.state.echo or f"Brain captured: {self.state.message}"
            self.state.reply = reply
            if not submission.response.done():
                submission.response.set_result(reply)
        except Exception as exc:  # pragma: no cover - handled by task tracking
            logger.exception("Failed to process submission", exc_info=exc)
            if not submission.response.done():
                submission.response.set_exception(exc)
            raise
        finally:
            reset_brain_state(state_token)

    def _track_task(self, task: asyncio.Task[Any]) -> None:
        """
        Track background tasks and log any raised exceptions.

        :param task: Task to monitor until completion.
        :return: None.
        """
        self._tasks.add(task)

        def _remove(completed: asyncio.Task[Any]) -> None:
            """
            Remove completed tasks from tracking and surface exceptions.

            :param completed: Task that finished running.
            :return: None.
            """
            self._tasks.discard(completed)
            if completed.cancelled():
                return
            exception = completed.exception()
            if exception is not None:
                logger.exception("Brain event task raised", exc_info=exception)

        task.add_done_callback(_remove)

    async def _await_pending_tasks(self) -> None:
        """
        Await all currently tracked tasks to ensure clean shutdown.

        :return: None.
        """
        while self._tasks:
            _ = await asyncio.wait(self._tasks.copy(), return_when=asyncio.ALL_COMPLETED)


async def _run_brain(queue: BrainQueue) -> None:
    """
    Kick off the Brain flow with the provided queue.

    :param queue: Queue for receiving chat submissions.
    :return: None.
    """
    brain = Brain(queue=queue)
    _ = await brain.kickoff_async()


async def main(queue: BrainQueue) -> None:
    """
    Start inbound/outbound gRPC services and the Brain flow lifecycle.

    :param queue: Queue used for passing submissions between services.
    :return: None.
    """
    shutdown_event = asyncio.Event()
    brain_task = asyncio.create_task(_run_brain(queue))
    inbound_task = asyncio.create_task(serve_brain(queue=queue, shutdown=shutdown_event))
    outbound_task = asyncio.create_task(outbound_connection())

    tasks: set[asyncio.Task[Any]] = {brain_task, inbound_task, outbound_task}

    async def _cleanup(message: str | None = None) -> None:
        """
        Cancel all running tasks and notify services to stop.

        :param message: Optional log message describing the shutdown reason.
        :return: None.
        """
        await queue.put(None)
        shutdown_event.set()
        for task in tasks:
            if not task.done():
                _ = task.cancel()
        _ = await asyncio.gather(*tasks, return_exceptions=True)
        if message:
            logger.info(message)

    try:
        done, pending = await asyncio.wait(
            tasks,
            return_when=asyncio.FIRST_COMPLETED,
        )
    except asyncio.CancelledError:
        await _cleanup("Cancellation requested; shutting down Brain services.")
        return

    await queue.put(None)
    shutdown_event.set()

    for task in pending:
        _ = task.cancel()

    _ = await asyncio.gather(*pending, return_exceptions=True)

    for completed in done:
        if completed.cancelled():
            continue
        if exc := completed.exception():
            raise exc


async def _run_with_queue() -> None:
    """
    Convenience entrypoint that wires up the Brain queue lifecycle.

    :return: None.
    """
    queue: BrainQueue = asyncio.Queue()
    try:
        await main(queue)
    except KeyboardInterrupt:
        await queue.put(None)


def kickoff() -> None:
    """
    Launch the async entrypoint with a managed queue.

    :return: None.
    """
    try:
        asyncio.run(_run_with_queue())
        print()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received; exiting cleanly.")


def _namespace_structure(structure: FlowStructure, namespace: str) -> FlowStructure:
    """
    Prefix node and edge names so we can embed child flows under a distinct namespace.

    :param structure: FlowStructure to namespace.
    :param namespace: Namespace prefix to apply.
    :return: Namespaced FlowStructure copy.
    """
    nodes = {f"{namespace}.{name}": meta for name, meta in structure["nodes"].items()}
    edges: list[StructureEdge] = []
    for edge in structure["edges"]:
        edges.append(
            StructureEdge(
                source=f"{namespace}.{edge['source']}",  # pyright:ignore[reportTypedDictNotRequiredAccess]
                target=f"{namespace}.{edge['target']}",  # pyright:ignore[reportTypedDictNotRequiredAccess]
                condition_type=edge.get("condition_type"),
                is_router_path=edge.get("is_router_path", False),
                **(
                    {}
                    if "router_path_label" not in edge
                    else {"router_path_label": edge["router_path_label"]}
                ),
            )
        )

    return FlowStructure(
        nodes=nodes,
        edges=edges,
        start_methods=[f"{namespace}.{name}" for name in structure["start_methods"]],
        router_methods=[f"{namespace}.{name}" for name in structure["router_methods"]],
    )


def _merge_structures(base: FlowStructure, addition: FlowStructure) -> FlowStructure:
    """
    Combine two FlowStructure graphs into one.

    :param base: Existing FlowStructure.
    :param addition: FlowStructure to merge into the base.
    :return: Combined FlowStructure containing nodes and edges from both.
    """
    merged = FlowStructure(
        nodes={**base["nodes"], **addition["nodes"]},
        edges=[*base["edges"], *addition["edges"]],
        start_methods=[*base["start_methods"], *addition["start_methods"]],
        router_methods=[*base["router_methods"], *addition["router_methods"]],
    )
    return merged


def plot(show: bool = True) -> None:
    """
    Generate an interactive HTML graph that includes the Brain flow and its child subflows/crews.

    :param show: Whether to open the visualization after rendering.
    :return: None.
    """
    brain = Brain()
    brain_structure = build_flow_structure(brain)

    # Add ExampleFlow as a namespaced child with OR edges from the submission handler.
    child_flows: dict[str, Flow[Any]] = {"ExampleFlow": ExampleFlow(gestalt_agent=brain.gestalt)}
    composite = brain_structure
    for namespace, flow in child_flows.items():
        namespaced = _namespace_structure(build_flow_structure(flow), namespace)
        composite = _merge_structures(composite, namespaced)
        for start_method in namespaced["start_methods"]:
            composite["edges"].append(
                StructureEdge(
                    source="handle_submission",
                    target=start_method,
                    condition_type="OR",
                    is_router_path=False,
                )
            )

    # Represent available crews as leaf nodes reachable from the submission handler.
    try:
        from blueking.crews.turtle_crew import build_turtle_crew

        turtle_crew = build_turtle_crew(manager_agent=brain.gestalt)
        composite["nodes"]["turtle_crew"] = {  # pyright:ignore[reportArgumentType]
            "type": "crew",
            "method_signature": {"name": "build_turtle_crew", "params": ["manager_agent"]},
            "class_name": "Crew",
            "trigger_methods": ["handle_submission"],
            "tasks": [task.description for task in getattr(turtle_crew, "tasks", [])],
        }
        composite["edges"].append(
            StructureEdge(
                source="handle_submission",
                target="turtle_crew",
                condition_type="OR",
                is_router_path=False,
            )
        )
    except Exception:
        # Crew visualization is optional; skip if crew modules are unavailable.
        pass

    _ = render_interactive(composite, filename="BrainFlowPlot.html", show=show)


if __name__ == "__main__":
    print("Main kicked")
    kickoff()
