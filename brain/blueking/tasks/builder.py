from __future__ import annotations

from typing import Any

from crewai import Task

from blueking.utils.config_loader import load_config

TASK_CONFIG_FILENAME = "config.yaml"


def _normalize_name(name: str) -> str:
    """
    Convert task package names into valid module identifiers.

    :param name: Original task name (e.g., "navigate-task").
    :return: Normalized module-friendly name.
    """
    return name.replace("-", "_")


def _resolve_package(name: str) -> str:
    """
    Build the full package path for a task module.

    :param name: Original task name.
    :return: Dotted module path to the task package.
    """
    normalized = _normalize_name(name)
    return f"blueking.tasks.{normalized}"


def build_task(name: str, **kwargs: Any) -> Task:
    """
    Return a Task configured from the matching task package yaml file.

    :param name: Name of the task package to load.
    :param kwargs: Additional Task constructor arguments.
    :return: An instantiated CrewAI Task.
    """
    package = _resolve_package(name)
    config = load_config(package, TASK_CONFIG_FILENAME)
    return Task(config=config, **kwargs)
