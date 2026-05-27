from __future__ import annotations

from typing import Any, Literal

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
        if self.status == "ready":
            if self.prompt_bundle is None:
                raise ValueError("ready agent resolution requires prompt_bundle")
            if self.agent_task is not None:
                raise ValueError("ready agent resolution must not include agent_task")
        if self.status == "requires_agent":
            if self.agent_task is None:
                raise ValueError("requires_agent resolution requires agent_task")
            if self.prompt_bundle is not None:
                raise ValueError("requires_agent resolution must not include prompt_bundle")
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
                raise ValueError(
                    "ready compose render plan resolution requires prompt_bundle and render_request"
                )
            if self.agent_task is not None:
                raise ValueError("ready compose render plan resolution must not include agent_task")
        if self.status == "requires_agent":
            if self.agent_task is None:
                raise ValueError("requires_agent compose render plan resolution requires agent_task")
            if self.prompt_bundle is not None or self.render_request is not None:
                raise ValueError(
                    "requires_agent compose render plan resolution must not include prompt_bundle or render_request"
                )
        return self


class BatchOutputPolicy(BaseModel):
    dir: str
    archive_acceptance: bool = False


class BatchItemRequest(BaseModel):
    id: str
    compose: dict[str, Any]
    render: dict[str, Any]
    output: BatchOutputPolicy


class BatchItemResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_id: str = Field(
        default="tags-machine-core.batch-item-result/v1",
        alias="schema",
    )
    id: str
    status: Literal["ready", "requires_agent", "failed"]
    output: BatchOutputPolicy | None = None
    prompt_bundle: PromptBundle | None = None
    render_request: RenderRequest | None = None
    generation_result: dict[str, Any] | None = None
    agent_task: AgentCompositionTask | None = None
    report_path: str | None = None
    error: str | None = None

    @model_validator(mode="after")
    def validate_status_payload(self):
        if self.status == "ready":
            if self.prompt_bundle is None or self.render_request is None:
                raise ValueError("ready batch item requires prompt_bundle and render_request")
            if self.agent_task is not None:
                raise ValueError("ready batch item must not include agent_task")
        if self.status == "requires_agent":
            if self.agent_task is None:
                raise ValueError("requires_agent batch item requires agent_task")
            if self.prompt_bundle is not None or self.render_request is not None:
                raise ValueError(
                    "requires_agent batch item must not include prompt_bundle or render_request"
                )
        if self.status == "failed" and not self.error:
            raise ValueError("failed batch item requires error")
        return self
