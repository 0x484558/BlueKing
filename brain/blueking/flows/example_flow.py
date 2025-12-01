from typing import Any

from crewai import Agent
from crewai.flow import Flow, listen, start
from pydantic import BaseModel


class ExampleFlowState(BaseModel):
    prompt: str = ""
    echo: str = ""


class ExampleFlow(Flow[ExampleFlowState]):
    """
    A simple subflow to demonstrate how the brain can delegate work.
    """

    def __init__(self, gestalt_agent: Agent | None = None, **kwargs: Any) -> None:
        """
        Initialize the flow with an optional Gestalt agent for downstream use.

        :param gestalt_agent: Shared Gestalt agent to reference within the flow.
        :param kwargs: Additional Flow configuration forwarded to the base class.
        :return: None.
        """
        super().__init__(**kwargs)
        self.gestalt_agent: Agent | None = gestalt_agent

    @start()
    def pick_prompt(self, crewai_trigger_payload: dict[str, Any] | None = None) -> None:
        """
        Capture the incoming prompt from the trigger payload.

        :param crewai_trigger_payload: Payload provided by the Flow trigger.
        :return: None.
        """
        if crewai_trigger_payload is None:
            raise ValueError("No payload provided")
        self.state.prompt = crewai_trigger_payload.get("prompt", "No prompt provided")

    @listen(pick_prompt)
    def echo_prompt(self) -> None:
        """
        Echo the prompt into flow state for downstream consumers.

        :return: None.
        """
        self.state.echo = f"Subflow echoing: {self.state.prompt}"
