"""Remote MCP servers.

Exa (web intel) runs in every mode. Kiwi (fare search) runs in live mode only;
replay mode uses the recorded fares so the demo stays deterministic.

Check endpoints with:
    uv run python -m guardian.cli --list-mcp-tools
"""

from contextlib import AsyncExitStack
from urllib.parse import urlencode

from agents.mcp import MCPServerStreamableHttp, create_static_tool_filter

from guardian.config import settings

EXA_TOOLS = ["web_search_exa", "web_fetch_exa"]


def exa_server() -> MCPServerStreamableHttp:
    s = settings()
    url = s.exa_mcp_url
    if s.exa_api_key:
        # Exa's hosted MCP takes the key as a query parameter; without one it uses
        # Exa's anonymous free tier, which is rate-limited.
        url += ("&" if "?" in url else "?") + urlencode({"exaApiKey": s.exa_api_key})
    return MCPServerStreamableHttp(
        name="exa",
        params={"url": url},
        cache_tools_list=True,
        client_session_timeout_seconds=60,
        tool_filter=create_static_tool_filter(allowed_tool_names=EXA_TOOLS),
        max_retry_attempts=2,
    )


def kiwi_server() -> MCPServerStreamableHttp:
    return MCPServerStreamableHttp(
        name="kiwi",
        params={"url": settings().kiwi_mcp_url},
        cache_tools_list=True,
        client_session_timeout_seconds=60,
        # never expose feedback-to-devs: it would let an agent post messages to Kiwi
        tool_filter=create_static_tool_filter(allowed_tool_names=["search-flight"]),
    )


async def connect_all(
    stack: AsyncExitStack, include_kiwi: bool = False
) -> dict[str, MCPServerStreamableHttp]:
    """Connect agent-facing servers; a failed server is skipped, not fatal.

    Kiwi is normally called from code (guardian/kiwi.py) so fares are parsed and ranked
    deterministically; include_kiwi is for inspecting its tools.
    """
    wanted = [("exa", exa_server())]
    if include_kiwi:
        wanted.append(("kiwi", kiwi_server()))
    servers = {}
    for name, srv in wanted:
        try:
            servers[name] = await stack.enter_async_context(srv)
        except Exception as e:  # noqa: BLE001 — keep running without a server rather than crash the demo
            print(f"[mcp] {name} unavailable: {e}")
    return servers
