import os
from logging import getLogger
from typing import Any

from crewai import LLM

logger = getLogger()


class BKLLM(LLM):
    def __new__(cls, is_litellm: bool = False, **kwargs: Any) -> LLM:
        """
        Create a configured LLM instance using environment-backed settings.

        :param is_litellm: Ignored; retained for compatibility with CrewAI.
        :param kwargs: Additional keyword arguments forwarded to the LLM constructor.
        :return: A fully configured LLM instance.
        """
        model = os.environ.get("BLUEKING_API_MODEL", None)
        if model is None:
            raise ValueError("Model must be set via BLUEKING_API_MODEL")

        return super().__new__(cls, model, is_litellm=True, provider=None, **kwargs)

    def __init__(self, *args: tuple[object], **kwargs: dict[str, object]):  # pyright: ignore[reportInconsistentConstructor]
        """
        Initialize the LLM with environment variables overriding explicit kwargs.

        :param args: Positional arguments forwarded to the base LLM.
        :param kwargs: Keyword arguments forwarded to the base LLM.
        :return: None.
        """
        env_config = {
            "api_key": os.environ.get("BLUEKING_API_KEY", None),
            # "provider": os.environ.get("BLUEKING_API_PROVIDER", "openai"),
            "api_base": os.environ.get("BLUEKING_API_BASE", None),
            "model": os.environ.get("BLUEKING_API_MODEL", None),
        }

        merged = {**env_config, **kwargs}

        if not all([merged["api_base"], merged["model"]]):
            logger.error(
                "Missing required environment variables: BLUEKING_API_BASE='%s', BLUEKING_API_MODEL='%s'",
                merged["api_base"],
                merged["model"],
            )
            raise ValueError(
                "API Base and API model must be set via env. vars BLUEKING_API_BASE and BLUEKING_API_MODEL"
            )

        super().__init__(*args, **merged)  # pyright: ignore[reportArgumentType]
