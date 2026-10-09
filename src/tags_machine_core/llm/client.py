from __future__ import annotations

import json
import os
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TypeVar

import requests
from pydantic import BaseModel, ValidationError

from tags_machine_core.config import LLMConfig
from tags_machine_core.logging_config import get_logger

from .cache import LLMCache, cache_key


logger = get_logger(__name__)

ModelT = TypeVar("ModelT", bound=BaseModel)

_FENCE_RE = re.compile(r"^\s*```(?:json|JSON)?\s*\n?(.*?)\n?\s*```\s*$", re.DOTALL)


class LLMError(RuntimeError):
    pass


class LLMUnavailableError(LLMError):
    pass


def resolve_api_key(config: LLMConfig) -> str | None:
    if config.api_key:
        return config.api_key
    env_value = os.environ.get(config.api_key_env, "").strip() if config.api_key_env else ""
    if env_value:
        return env_value
    if config.api_key_file:
        path = Path(config.api_key_file).expanduser()
        if not path.is_file():
            logger.warning("llm.api_key_file not found: %s", path)
            return None
        text = path.read_text(encoding="utf-8").strip()
        if text.startswith("{"):
            try:
                value = json.loads(text).get(config.api_key_field)
            except (json.JSONDecodeError, AttributeError):
                logger.warning("llm.api_key_file is not valid JSON: %s", path)
                return None
            return str(value).strip() if value else None
        return text or None
    return None


def extract_message_content(payload: Any) -> str:
    """取出回复文本；兼容标准响应和代理多包一层 data 的响应。"""
    if isinstance(payload, dict) and "choices" not in payload and isinstance(payload.get("data"), dict):
        payload = payload["data"]
    if not isinstance(payload, dict):
        raise LLMError("LLM response is not a JSON object")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LLMError("LLM response has no choices")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, list):
        content = "".join(str(part.get("text") or "") for part in content if isinstance(part, dict))
    return str(content or "").strip()


def parse_json_content(text: str) -> Any:
    """解析 JSON 回复：去掉 markdown 代码块围栏，回复前后夹杂说明文字时取第一个 JSON 对象。"""
    match = _FENCE_RE.match(text)
    if match:
        text = match.group(1)
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


class LLMClient:
    def __init__(
        self,
        config: LLMConfig,
        *,
        session: requests.Session | None = None,
        cache: LLMCache | None = None,
    ):
        self.config = config
        self.api_key = resolve_api_key(config)
        self.session = session or requests.Session()
        self._cache = cache

    @property
    def available(self) -> bool:
        return bool(self.config.base_url and self.api_key)

    @property
    def cache(self) -> LLMCache:
        if self._cache is None:
            self._cache = LLMCache(self.config.cache_path)
        return self._cache

    def status(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "base_url": self.config.base_url,
            "models": self.config.models.model_dump(),
        }

    def model_chain(self, *, vision: bool = False, fast: bool = False) -> list[str]:
        models = self.config.models
        if vision:
            return [models.vision or models.text]
        chain = [models.fast, models.text, models.fallback] if fast else [models.text, models.fallback]
        return list(dict.fromkeys(model for model in chain if model))

    def chat(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        model: str,
        json_mode: bool = False,
        temperature: float = 0.2,
    ) -> str:
        if not self.available:
            raise LLMUnavailableError("LLM is not configured (llm.base_url / api key)")
        body: dict[str, Any] = {"model": model, "messages": list(messages), "temperature": temperature}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        url = f"{str(self.config.base_url).rstrip('/')}/chat/completions"
        try:
            response = self.session.post(
                url,
                json=body,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=self.config.timeout,
            )
        except requests.RequestException as exc:
            raise LLMError(f"{model}: request failed: {exc}") from exc
        if response.status_code >= 400:
            raise LLMError(f"{model}: HTTP {response.status_code}: {response.text[:300]}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise LLMError(f"{model}: response is not JSON") from exc
        content = extract_message_content(payload)
        if not content:
            raise LLMError(f"{model}: empty response")
        return content

    def run_json(
        self,
        *,
        task: str,
        version: str,
        messages: Sequence[dict[str, Any]],
        schema: type[ModelT],
        cache_input: Any,
        vision: bool = False,
        fast: bool = False,
        use_cache: bool = True,
    ) -> ModelT:
        """按模型链依次尝试，直到拿到能通过 schema 校验的 JSON；结果按任务 + 版本 + 输入缓存。"""
        key = cache_key(task, version, cache_input)
        if use_cache:
            cached = self.cache.get(key)
            if cached is not None:
                try:
                    return schema.model_validate(cached)
                except ValidationError:
                    logger.warning("Discarding stale LLM cache entry task=%s", task)
        errors: list[str] = []
        for model in self.model_chain(vision=vision, fast=fast):
            try:
                text = self.chat(messages, model=model, json_mode=True)
                result = schema.model_validate(parse_json_content(text))
            except (LLMError, json.JSONDecodeError, ValidationError) as exc:
                logger.warning("LLM task %s failed on %s: %s", task, model, exc)
                errors.append(f"{model}: {exc}")
                continue
            if use_cache:
                self.cache.set(key, result.model_dump(mode="json"), task=task, model=model)
            return result
        raise LLMError(f"LLM task {task} failed: " + " | ".join(errors))
