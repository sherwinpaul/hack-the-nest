"""Remote MCP servers. Used in live mode only; replay mode uses fixtures.

Endpoints come from public listings. Confirm them at kickoff with:
    uv run python -m guardian.cli --list-mcp-tools
"""

from contextlib import AsyncExitStack

from agents.mcp import MCPServerStreamableHttp

from guardian.config import settings


def exa_server() -> MCPServerStreamableHttp | None:
    s = settings()
    if not s.exa_api_key:
        return None
    return MCPServerStreamableHttp(
        name="exa",
        params={"url": s.exa_mcp_url, "headers": {"x-api-key": s.exa_api_key}},
        cache_tools_list=True,
        client_session_timeout_seconds=30,
    )


def kiwi_server() -> MCPServerStreamableHttp:
    return MCPServerStreamableHttp(
        name="kiwi",
        params={"url": settings().kiwi_mcp_url},
        cache_tools_list=True,
        client_session_timeout_seconds=30,
    )


async def connect_all(stack: AsyncExitStack) -> dict[str, MCPServerStreamableHttp]:
    servers = {}
    for name, srv in (("exa", exa_server()), ("kiwi", kiwi_server())):
        if srv is None:
            continue
        try:
            servers[name] = await stack.enter_async_context(srv)
        except Exception as e:  # noqa: BLE001 — keep running without a server rather than crash the demo
            print(f"[mcp] {name} unavailable: {e}")
    return servers
