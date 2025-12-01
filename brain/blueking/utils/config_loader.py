from importlib.resources import files
from typing import Any

import yaml


def load_config(package: str, config_file: str) -> dict[str, Any]:
    """
    Load a YAML configuration file from a package resource.

    :param package: Package containing the configuration file.
    :param config_file: Name of the YAML file to load.
    :return: Parsed configuration dictionary.
    """
    config_path = files(package) / config_file
    if not config_path.is_file():
        raise FileNotFoundError(f"{config_file} not found in package {package}")

    with config_path.open() as handle:
        return yaml.safe_load(handle) or {}
