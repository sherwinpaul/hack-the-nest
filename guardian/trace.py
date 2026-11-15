"""Live trace via SDK lifecycle hooks.

We use hooks on a normal (non-streamed) run instead of Runner.run_streamed: with
Gemini 3 through the OpenAI-compatible endpoint, streamed tool calls lose the
model's thought signature and the follow-up request fails with 400.
"""

import json
from collections.abc import Callable
from typing import Any

from agents import RunHooks

MAX_CHARS = 1500


def _text(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if len(text) <= MAX_CHARS else text[:MAX_CHARS] + " …"


class TraceHooks(RunHooks):
    """Turns agent and tool lifecycle callbacks into UI events: {type, agent, ...}."""

    def __init__(self, emit: Callable[[dict], None]):
        self.emit = emit

    async def on_agent_start(self, context, agent) -> None:
        self.emit({"type": "agent", "agent": agent.name})

    async def on_tool_start(self, context, agent, tool) -> None:
        args = getattr(context, "tool_arguments", "") or ""
        self.emit(
            {
                "type": "tool_called",
                "agent": agent.name,
                "tool": tool.name,
                "args": _text(args),
            }
        )

    async def on_tool_end(self, context, agent, tool, result) -> None:
        self.emit(
            {
                "type": "tool_output",
                "agent": agent.name,
                "tool": tool.name,
                "output": _text(result),
            }
        )
