from __future__ import annotations

from typing import Any

from crewai import Agent

from blueking.base import BKLLM
from blueking.tools import MemorizeTool, RecallTool
from blueking.utils.config_loader import load_config

AGENT_CONFIG_FILENAME = "config.yaml"


def _normalize_name(name: str) -> str:
    """
    Convert agent names into valid module identifiers.

    :param name: Original agent name.
    :return: Normalized module-friendly name.
    """
    return name.replace("-", "_")


def _resolve_package(name: str) -> str:
    """
    Build the full package path for an agent module.

    :param name: Agent name to resolve.
    :return: Dotted module path to the agent package.
    """
    normalized = _normalize_name(name)
    return f"blueking.agents.{normalized}"


def build_agent(name: str, **kwargs: Any) -> Agent:
    """
    Load the agent configuration and return an instantiated CrewAI Agent
    using the shared BKLLM implementation.

    :param name: Agent package to load.
    :param kwargs: Additional Agent constructor arguments.
    :return: A configured Agent instance.
    """
    package = _resolve_package(name)
    config = load_config(package, AGENT_CONFIG_FILENAME)
    if name == "gestalt" and "tools" not in kwargs:
        kwargs["tools"] = [MemorizeTool(), RecallTool()]
    return Agent(config=config, llm=BKLLM(), **kwargs)
