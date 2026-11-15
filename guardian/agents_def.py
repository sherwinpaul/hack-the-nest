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
        tools=[tools.search_alternative_trips],
    )

    comms = Agent(
        name="Comms",
        model=model_for("comms"),
        model_settings=model_settings(),
        instructions=(
            "Draft a short, friendly message from the traveller to the person they are meeting "
            "or the event's organiser (a host, family member, interviewer...). Match the tone "
            "to the event: warm for personal events, professional for work. Cover: (1) any "
            "disruption that threatens the ORIGINAL booking, described accurately with its real "
            "severity (never downplay a blizzard as 'minor'); (2) the flight they are now taking, "
            "which is the solution, not a delayed flight; (3) its arrival time in the "
            "destination's local time if given. Offer to join remotely only if you are told "
            "that is possible. If nothing threatens the trip, just confirm the arrival time. "
            "Use only facts you are given. Under 80 words."
        ),
    )

    return Agent(
        name="Trip Guardian",
        model=model_for("orchestrator"),
        model_settings=model_settings(),
        instructions=(
            "You help a traveller reach an event on time (a wedding, interview, meeting, "
            "appointment...) by finding the best flight for what they care about: the lowest "
            "price, the most reliable option, or a balance of the two.\n"
            "1. Call get_commitment for the event, deadline and the traveller's priority.\n"
            "2. Call weather_risk and web_intel (in parallel) on the current trip.\n"
            "3. Call fare_search for alternatives.\n"
            "4. Call rank_options. Use ONLY its numbers and tags; never compute scores yourself.\n"
            "5. Recommend the option tagged 'recommended' and explain it in plain, friendly "
            "language: why it fits their priority, its on-time chance, its price versus their "
            "current booking, and the evidence behind any risk (cite sources). Also name the "
            "cheapest and the most reliable options if they differ, so the traveller sees the "
            "trade-off. If the recommendation is their current booking, say they can keep it.\n"
            "6. Call draft_host_message. In its input, state the event, the original booking "
            "and anything threatening it, the flight the traveller should take (number, route, "
            "arrival time), and whether joining remotely is possible.\n"
            "Avoid jargon such as 'expected loss' or 'P(on time)'; say 'chance of arriving on "
            "time'. Never book anything; booking happens only after the traveller approves."
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
