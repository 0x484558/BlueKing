from __future__ import annotations

from crewai import Agent, Crew, Process, Task
from crewai.agents.agent_builder.base_agent import BaseAgent

from blueking.agents.builder import build_agent
from blueking.tasks.builder import build_task


def _build_turtle_agents(manager_agent: Agent) -> list[BaseAgent]:
    """
    Construct the agent roster for the turtle crew.

    :param manager_agent: Manager responsible for delegation and coordination.
    :return: Ordered list of agents participating in the crew.
    """
    # The manager leads delegation; the task-specific turtle agent executes plans.
    return [manager_agent, build_agent("turtle-agent")]


def _build_navigation_tasks() -> list[Task]:
    """
    Create navigation tasks for the turtle crew.

    :return: List of CrewAI tasks to execute.
    """
    return [build_task("navigate-task")]


def build_turtle_crew(manager_agent: Agent) -> Crew:
    """
    Assemble the turtle crew with agents and tasks wired to the manager.

    :param manager_agent: Agent orchestrating the crew.
    :return: Configured Crew instance ready for execution.
    """
    return Crew(
        agents=_build_turtle_agents(manager_agent),
        tasks=_build_navigation_tasks(),
        manager_agent=manager_agent,
        process=Process.sequential,
        verbose=True,
    )
