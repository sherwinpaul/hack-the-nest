"""Live trace via SDK lifecycle hooks.

We use hooks on a normal (non-streamed) run instead of Runner.run_streamed: with
Gemini 3 through the OpenAI-compatible endpoint, streamed tool calls lose the
model's thought signature and the follow-up request fails with 400.
"""

import json
import re
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

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
        if tool.name == "web_search_exa":
            query = _query(getattr(context, "tool_arguments", "") or "")
            sources = parse_exa_sources(result)
            if sources:
                self.emit({"type": "sources", "query": query, "items": sources})


# Exa MCP returns blocks like "Title: ...\nURL: ...\nPublished: ...". The result may
# arrive JSON-encoded, so accept literal "\n" escapes as line breaks too.
_NL = r"(?:\r?\n|\\n)"
_EXA_RESULT = re.compile(
    rf"Title:\s*(?P<title>.+?){_NL}URL:\s*(?P<url>https?://[^\s\\\"]+)"
    rf"(?:{_NL}Published:\s*(?P<published>[0-9T:\-.Z]+))?"
)


def parse_exa_sources(result: Any, limit: int = 8) -> list[dict]:
    text = result if isinstance(result, str) else json.dumps(result, default=str)
    seen, out = set(), []
    for m in _EXA_RESULT.finditer(text):
        url = m["url"].rstrip(".,)")
        if url in seen:
            continue
        seen.add(url)
        out.append(
            {
                "title": m["title"].strip()[:160],
                "url": url,
                "domain": urlparse(url).netloc.removeprefix("www."),
                "published": (m["published"] or "")[:10],
            }
        )
        if len(out) >= limit:
            break
    return out


def _query(args: str) -> str:
    try:
        return str(json.loads(args).get("query", ""))
    except (ValueError, AttributeError):
        return ""
