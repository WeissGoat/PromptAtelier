from __future__ import annotations

from abc import ABC, abstractmethod

from tags_machine_core.contracts import PromptBundle, RenderRequest


class RenderAdapter(ABC):
    @abstractmethod
    def build_request(self, bundle: PromptBundle, **kwargs) -> RenderRequest:
        raise NotImplementedError
