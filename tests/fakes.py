"""A scripted fake model for offline tests (PydanticAI's FunctionModel).

Each step is the model's next reply: a string is text, a (name, args) pair is a
tool call. The fake records what each call was shown.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic_ai.messages import (ModelMessage, ModelResponse, RetryPromptPart, TextPart, ToolCallPart,
                                  ToolReturnPart)
from pydantic_ai.models.function import AgentInfo, FunctionModel


@dataclass
class Scripted:
    steps: list[list[Any]]
    seen: list[tuple[list[ModelMessage], AgentInfo]] = field(default_factory=list)

    @property
    def model(self) -> FunctionModel:
        return FunctionModel(self._respond)

    def _respond(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        self.seen.append((messages, info))
        step = self.steps[len(self.seen) - 1]
        return ModelResponse(parts=[TextPart(p) if isinstance(p, str) else ToolCallPart(p[0], p[1]) for p in step])

    def tools_offered(self, call: int = 0) -> dict:
        return {t.name: t for t in self.seen[call][1].function_tools}

    def results(self, call: int) -> list[ToolReturnPart | RetryPromptPart]:
        """What the model was given back on this call: tool results and errors."""
        return [p for p in self.seen[call][0][-1].parts if isinstance(p, (ToolReturnPart, RetryPromptPart))]


def is_error(part) -> bool:
    """A tool error sent back to the model so it can try again."""
    return isinstance(part, RetryPromptPart) or getattr(part, "outcome", None) == "retried"


def script(*steps: list[Any]) -> Scripted:
    return Scripted(list(steps))
