from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from tags_machine_core.composers import AgentCompositionTask
from tags_machine_core.contracts import PromptBundle, RenderRequest


JsonApiStatus = Literal["ready", "requires_agent"]


class AgentComposeResolution(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_id: str = Field(
        default="tags-machine-core.agent-compose-resolution/v1",
        alias="schema",
    )
    status: JsonApiStatus
    prompt_bundle: PromptBundle | None = None
    agent_task: AgentCompositionTask | None = None

    @model_validator(mode="after")
    def validate_status_payload(self):
        if self.status == "ready" and self.prompt_bundle is None:
            raise ValueError("ready agent resolution requires prompt_bundle")
        if self.status == "requires_agent" and self.agent_task is None:
            raise ValueError("requires_agent resolution requires agent_task")
        return self


class ComposeRenderPlanResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_id: str = Field(
        default="tags-machine-core.compose-render-plan-result/v1",
        alias="schema",
    )
    prompt_bundle: PromptBundle
    render_request: RenderRequest


class ComposeRenderPlanResolution(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_id: str = Field(
        default="tags-machine-core.compose-render-plan-resolution/v1",
        alias="schema",
    )
    status: JsonApiStatus
    prompt_bundle: PromptBundle | None = None
    render_request: RenderRequest | None = None
    agent_task: AgentCompositionTask | None = None

    @model_validator(mode="after")
    def validate_status_payload(self):
        if self.status == "ready":
            if self.prompt_bundle is None or self.render_request is None:
                raise ValueError("ready compose render plan resolution requires prompt_bundle and render_request")
        if self.status == "requires_agent" and self.agent_task is None:
            raise ValueError("requires_agent compose render plan resolution requires agent_task")
        return self
