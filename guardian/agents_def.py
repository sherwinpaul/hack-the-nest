"""Agent graph: an orchestrator that calls specialist agents as tools (parallel fan-out)."""

from agents import Agent, RunHooks
from agents.mcp import MCPServer

from guardian import tools
from guardian.config import settings
from guardian.models import model_for, model_settings


def build_agents(
    mcp: dict[str, MCPServer] | None = None,
    hooks: RunHooks | None = None,
) -> Agent:
    """Build the agent graph. `hooks` also run inside sub-agents, so the UI sees their tool calls."""
    mcp = mcp or {}
    live = settings().data_mode == "live"

    weather = Agent(
        name="Weather Risk",
        model=model_for("weather"),
        model_settings=model_settings(),
        instructions=(
            "You assess weather disruption risk for every airport on the user's current trip, "
            "including connections. Call get_current_trip, then get_airport_weather_risk for each "
            "airport at its scheduled time. Reply with a short per-airport summary and the single "
            "biggest threat."
        ),
        tools=[tools.get_current_trip, tools.get_airport_weather_risk],
    )

    has_exa = "exa" in mcp
    exa_rules = (
        "Use web_search_exa with specific queries (airport code, airline, 'travel waiver', "
        "'ground stop', 'NWS warning'); call web_fetch_exa only if a result needs more detail. "
        "At most 3 searches. "
    )
    if live:
        intel_instructions = (
            "You find live evidence about travel disruption for the airports you are given: FAA "
            "ground stops and delay programs, NWS warnings, airline travel waivers, strikes, "
            "closures. " + exa_rules
        )
    else:
        intel_instructions = (
            "This is a recorded scenario. First call get_disruption_news for the scenario's "
            "evidence. "
            + (
                "Then use Exa to find the booked airline's real, current weather travel-waiver "
                "and rebooking policy for the highest-risk airport in the evidence (usually the "
                "connecting hub, not the destination), which tells the traveller what changes "
                "are free. "
                + exa_rules
                if has_exa
                else ""
            )
        )
    intel = Agent(
        name="Web Intel",
        model=model_for("intel"),
        model_settings=model_settings(),
        instructions=intel_instructions
        + "Return 3-6 bullet findings, each ending with its source URL. Never invent a source "
        "or a URL; only cite URLs that appear in tool results.",
        tools=[] if live and has_exa else [tools.get_disruption_news],
        mcp_servers=[mcp["exa"]] if has_exa else [],
    )

    fares = Agent(
        name="Fare Search",
        model=model_for("fares"),
        model_settings=model_settings(),
        instructions=(
            "You find alternative itineraries that reach the meeting city before the deadline, "
            "preferring routes that avoid the airports at risk. Return a concise list with price, "
            "route and arrival time."
        ),
        tools=[] if live and "kiwi" in mcp else [tools.search_alternative_trips],
        mcp_servers=[mcp["kiwi"]] if live and "kiwi" in mcp else [],
    )

    comms = Agent(
        name="Comms",
        model=model_for("comms"),
        model_settings=model_settings(),
        instructions=(
            "Draft a brief, professional message to the meeting host. Describe the disruption "
            "accurately, including its real severity (never downplay a blizzard as 'minor'), then "
            "the new plan and ETA, and offer a video fallback if arrival is uncertain. Under 90 words."
        ),
    )

    return Agent(
        name="Trip Guardian",
        model=model_for("orchestrator"),
        model_settings=model_settings(),
        instructions=(
            "You protect the user's meeting, not just their flight.\n"
            "1. Call get_commitment to learn the deadline and stakes.\n"
            "2. Call weather_risk and web_intel (in parallel) on the current trip.\n"
            "3. If risk is material, call fare_search for alternatives.\n"
            "4. Call rank_options. Use ONLY its numbers; never compute scores yourself.\n"
            "5. Recommend the top option: why (cite evidence), P(on time), extra cost.\n"
            "6. Call draft_host_message for the recommended plan.\n"
            "Never book anything. Booking happens only after the user approves in the app."
        ),
        tools=[
            tools.get_commitment,
            tools.rank_options,
            weather.as_tool(
                "weather_risk",
                "Assess weather disruption risk on the current trip.",
                hooks=hooks,
            ),
            intel.as_tool(
                "web_intel",
                "Search the live web for disruption evidence with sources.",
                hooks=hooks,
            ),
            fares.as_tool(
                "fare_search",
                "Find alternative itineraries before the deadline.",
                hooks=hooks,
            ),
            comms.as_tool(
                "draft_host_message",
                "Draft a message to the meeting host.",
                hooks=hooks,
            ),
        ],
    )
