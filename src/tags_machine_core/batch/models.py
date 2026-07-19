from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from tags_machine_core.nodes.artist_input_filter import ArtistInputFilterConfig
from tags_machine_core.policies import PromptPolicyConfig, PromptPolicySource


ComposerMode = Literal["full", "agent", "script"]
ExecutionMode = Literal["real", "mock"]
ExpandMode = Literal[
    "product",
    "zip",
    "prompt_list",
    "manual",
    "character_action_group",
    "blackboard_rounds",
]
ActionGroupStrategyName = Literal["random", "ordered", "balanced_random"]
BatchStatus = Literal[
    "pending",
    "ready",
    "running",
    "requires_agent",
    "succeeded",
    "succeeded_with_warning",
    "failed",
    "skipped",
    "cancelled",
]


class RetryConfig(BaseModel):
    max_attempts: int = 3
    timeout_seconds: float | None = None
    retry_on: list[str] = Field(
        default_factory=lambda: ["429", "500", "502", "503", "504", "timeout"]
    )
    backoff_seconds: list[float] = Field(default_factory=lambda: [1.0, 2.0, 5.0, 10.0])

    @field_validator("max_attempts")
    @classmethod
    def _max_attempts_positive(cls, value: int) -> int:
        if value < 1:
            raise ValueError("retry.max_attempts must be >= 1")
        return value


class RunConfig(BaseModel):
    resume: bool = True
    stop_on_error: bool = False
    execution_mode: ExecutionMode = "real"
    max_images: int | None = None
    execute_requires_agent: bool = False
    fresh: bool = False
    output_mode: Literal["global", "task_dir"] = "task_dir"
    retry: RetryConfig = Field(default_factory=RetryConfig)


class ArchiveConfig(BaseModel):
    save_prompt_bundle: bool = True
    save_render_request: bool = True
    save_generation_result: bool = True
    save_png_params: bool = True
    save_parameter_image: bool = False
    copy_images: bool = False


class ReportConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    markdown: bool = True
    json_report: bool = Field(default=True, alias="json")
    include_prompt_preview: bool = True
    include_png_params_summary: bool = True
    visual_check_template: bool = True


class BatchDefaults(BaseModel):
    backend: str = "novelai"
    composer: ComposerMode = "full"
    artist: str | None = None
    nt: int = 1
    resolution: str = "random_standard"
    width: int | None = None
    height: int | None = None
    seed: int | None = None
    image_format: str = "png"
    model: str | None = "nai-diffusion-4-5-full"
    prompt_policy: PromptPolicySource | None = None
    agent_model: str | None = None
    cache_dir: str | None = None
    add_male_caption: bool = True
    character_prompts: str | None = "auto"
    params: dict[str, Any] = Field(default_factory=dict)
    artist_input_filter: ArtistInputFilterConfig | None = None

    @field_validator("artist", mode="before")
    @classmethod
    def _optional_text(cls, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @field_validator("nt")
    @classmethod
    def _nt_positive(cls, value: int) -> int:
        if value < 1:
            raise ValueError("defaults.nt must be >= 1")
        return value


class SelectorSpec(BaseModel):
    selector: str
    refs: list[str] = Field(default_factory=list)
    root: str | None = None
    name: str | None = None
    pattern: str | None = None
    path: str | None = None
    format: str = "lines"
    items: list[dict[str, Any]] = Field(default_factory=list)
    recursive: bool = False
    node_files: list[str] = Field(default_factory=lambda: ["meta.yaml", "node.yaml", "tags.txt"])
    include: dict[str, Any] = Field(default_factory=dict)
    exclude: dict[str, Any] = Field(default_factory=dict)
    limit: int | None = None
    shuffle: bool = False

    @field_validator("refs", mode="before")
    @classmethod
    def _refs_as_strings(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value]
        return [str(value)]


class BatchSelect(BaseModel):
    artists: list[SelectorSpec] = Field(default_factory=list)
    characters: list[SelectorSpec] = Field(default_factory=list)
    actions: list[SelectorSpec] = Field(default_factory=list)
    action_groups: list[SelectorSpec] = Field(default_factory=list)
    backgrounds: list[SelectorSpec] = Field(default_factory=list)
    prompts: list[SelectorSpec] = Field(default_factory=list)


class ExpandConfig(BaseModel):
    mode: ExpandMode = "product"
    max_tasks: int | None = None
    auto_num: bool = False
    shuffle: bool = False
    action_group_strategy: ActionGroupStrategyName = "balanced_random"
    action_group_record: str | None = None
    allow_fill_missing_cp_from_candidates: bool = False
    seed: int | None = None


class NodeRef(BaseModel):
    role: str
    ref: str
    index: int = 0

    @field_validator("role", "ref")
    @classmethod
    def _not_empty(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("node ref role/ref must not be empty")
        return text


class PromptItem(BaseModel):
    id: str
    prompt: str
    negative: str | None = None
    nodes: list[NodeRef] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id", "prompt")
    @classmethod
    def _prompt_item_not_empty(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("prompt item id/prompt must not be empty")
        return text


class RenderOptions(BaseModel):
    backend: str = "novelai"
    artist: str | None = None
    nt: int = 1
    resolution: str = "random_standard"
    width: int | None = None
    height: int | None = None
    seed: int | None = None
    model: str | None = "nai-diffusion-4-5-full"
    image_format: str = "png"
    output_dir: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class AgentOptions(BaseModel):
    agent_model: str | None = None
    cache_dir: str | None = None


class TaskOutput(BaseModel):
    task_dir: str
    output_dir: str | None = None


class BatchTask(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_id: str = Field(default="tags-machine-core.batch-task/v1", alias="schema")
    id: str
    index: int
    composer: ComposerMode
    nodes: list[NodeRef] = Field(default_factory=list)
    prompt: str | None = None
    negative: str | None = None
    extra_prompt: str = ""
    render: RenderOptions
    agent: AgentOptions = Field(default_factory=AgentOptions)
    policy: PromptPolicyConfig | None = None
    artist_input_filter: ArtistInputFilterConfig | None = None
    output: TaskOutput
    source: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def _id_not_empty(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("BatchTask id must not be empty")
        return text

    @model_validator(mode="after")
    def _validate_prompt_mode(self):
        if self.composer == "full" and not (self.prompt or "").strip():
            raise ValueError("full composer task requires prompt")
        return self


class ManifestEntry(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_id: str = Field(default="tags-machine-core.batch-manifest-entry/v1", alias="schema")
    task_id: str
    status: BatchStatus
    attempt: int = 0
    task_path: str
    status_path: str
    generation_result_path: str | None = None
    image_paths: list[str] = Field(default_factory=list)
    error: str | None = None
    updated_at: str


class BatchSpec(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_id: str = Field(default="tags-machine-core.batch/v1", alias="schema")
    require: list[str] = Field(default_factory=list)
    name: str
    description: str | None = None
    config: str = "configs/local.example.yaml"
    work_root: str | None = None
    output_root: str | None = None
    output_dir: str | None = None
    defaults: BatchDefaults = Field(default_factory=BatchDefaults)
    collections: dict[str, dict[str, list[Any]]] = Field(default_factory=dict)
    select: BatchSelect = Field(default_factory=BatchSelect)
    expand: ExpandConfig = Field(default_factory=ExpandConfig)
    run: RunConfig = Field(default_factory=RunConfig)
    archive: ArchiveConfig = Field(default_factory=ArchiveConfig)
    report: ReportConfig = Field(default_factory=ReportConfig)
    tasks: list[dict[str, Any]] = Field(default_factory=list)

    def config_path(self, base_dir: Path) -> Path:
        path = Path(self.config)
        return path if path.is_absolute() else base_dir / path
