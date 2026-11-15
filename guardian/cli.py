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
from guardian.tools import compute_ranking


def print_ranking(ranked: list[ScoredOption]) -> None:
    print(f"{'#':<3}{'option':<22}{'route':<16}{'P(on time)':>11}{'+cost':>8}{'exp. loss':>11}")
    for i, s in enumerate(ranked, 1):
        o = s.option
        print(
            f"{i:<3}{o.id:<22}{'-'.join(o.airports):<16}{s.p_on_time:>11.0%}"
            f"{s.extra_cost_usd:>8.0f}{s.expected_loss_usd:>11,.0f}"
        )


def dry_run() -> list[ScoredOption]:
    c = data.load_commitment()
    print(f"Protecting: {c.title} — arrive {c.airport} by {c.must_arrive_by:%a %H:%MZ}\n")
    ranked = [ScoredOption.model_validate(r) for r in compute_ranking()]
    print_ranking(ranked)
    return ranked


async def list_mcp_tools() -> None:
    from guardian.mcp_servers import connect_all

    async with AsyncExitStack() as stack:
        for name, srv in (await connect_all(stack)).items():
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
        result = await Runner.run(guardian, "Check my upcoming trip and protect my meeting.", max_turns=20)
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
    a = p.parse_args()
    if a.dry:
        dry_run()
    elif a.list_mcp_tools:
        asyncio.run(list_mcp_tools())
    else:
        asyncio.run(agent_run())


if __name__ == "__main__":
    main()
