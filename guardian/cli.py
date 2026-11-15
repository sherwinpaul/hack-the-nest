"""Entry point.

  uv run python -m guardian.cli --dry             # no LLM: deterministic ranking only
  uv run python -m guardian.cli                   # full multi-agent run
  uv run python -m guardian.cli --list-mcp-tools  # check live MCP endpoints
"""

import argparse
import asyncio
import logging
from contextlib import AsyncExitStack

from guardian import booking, data
from guardian.config import settings
from guardian.models import configure_tracing, describe_routing
from guardian.schemas import ScoredOption
from guardian.tools import compute_ranking, ensure_live_fares


def print_ranking(ranked: list[ScoredOption]) -> None:
    print(f"{'#':<3}{'option':<22}{'route':<14}{'on time':>8}{'price':>8}{'score':>9}  tags")
    for i, s in enumerate(ranked, 1):
        o = s.option
        print(
            f"{i:<3}{o.id:<22}{'-'.join(o.airports):<14}{s.p_on_time:>8.0%}"
            f"{o.price_usd:>8.0f}{s.score_usd:>9,.0f}  {', '.join(s.tags)}"
        )


def dry_run(priority: str | None = None) -> list[ScoredOption]:
    c = data.load_commitment()
    p = priority or data.get_priority()
    print(f"Trip: {c.title} — arrive {c.airport} by {c.must_arrive_by:%a %H:%MZ} | priority: {p}\n")
    ranked = [ScoredOption.model_validate(r) for r in compute_ranking(p)]
    print_ranking(ranked)
    return ranked


async def list_mcp_tools() -> None:
    from guardian.mcp_servers import connect_all

    async with AsyncExitStack() as stack:
        for name, srv in (await connect_all(stack, include_kiwi=True)).items():
            print(f"\n[{name}]")
            for t in await srv.list_tools():
                print(f"  - {t.name}: {(t.description or '')[:80]}")


async def agent_run() -> None:
    from agents import Runner

    from guardian.agents_def import build_agents
    from guardian.mcp_servers import connect_all

    configure_tracing()
    print("Model routing:", describe_routing(), f"| data: {settings().data_mode}\n")
    async with AsyncExitStack() as stack:
        mcp = await connect_all(stack)
        print("MCP connected:", ", ".join(mcp) or "none")
        guardian = build_agents(mcp)
        result = await Runner.run(guardian, "Check my upcoming trip and find the best way to get me to my event on time.", max_turns=20)
    print(result.final_output, "\n")

    ranked = dry_run()
    if not ranked:
        return
    top = ranked[0].option
    if input(f"\nApprove booking {top.id} (${top.price_usd:.0f})? [y/N] ").strip().lower() == "y":
        print(booking.book(top))
    else:
        print("Not booked.")


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="[%(name)s] %(message)s")
    p = argparse.ArgumentParser(prog="guardian")
    p.add_argument("--dry", action="store_true", help="deterministic ranking only, no LLM")
    p.add_argument("--list-mcp-tools", action="store_true")
    p.add_argument("--priority", choices=data.PRIORITIES, help="price, balanced or reliability")
    a = p.parse_args()
    if a.priority:
        data.set_priority(a.priority)
    if a.dry:
        asyncio.run(ensure_live_fares())  # no-op in replay mode
        dry_run()
    elif a.list_mcp_tools:
        asyncio.run(list_mcp_tools())
    else:
        asyncio.run(agent_run())


if __name__ == "__main__":
    main()
