from __future__ import annotations

from abc import ABC, abstractmethod

from tags_machine_core.contracts import PromptBundle


class PromptComposer(ABC):
    @abstractmethod
    def compose(self) -> PromptBundle:
        raise NotImplementedError
