"""Tests for the tool layer.

Every tool is a thin wrapper that forwards to the mod's HTTP API, so these tests use
``set_transport`` to stub the transport and assert on the request each tool makes. No socket
and no running game are involved.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from stardew_mcp_server import server

BASE_URL = "http://127.0.0.1:8788"


def envelope(data: Any = None, *, ok: bool = True, date: Any = None) -> dict[str, Any]:
    """Build a response shaped like the mod's own envelope."""
    return {"ok": ok, "data": data, "date": date, "error": None}


def stub(
    requests: list[httpx.Request],
    payload: httpx.Response | dict[str, Any] | None = None,
) -> None:
    """Answer every request with ``payload`` and record it in ``requests``."""
    response = payload if isinstance(payload, httpx.Response) else httpx.Response(200, json=payload)

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return response

    server.set_transport(httpx.MockTransport(handler))


@pytest.fixture(autouse=True)
def _reset_transport():
    """Don't leak the stub into other tests."""
    yield
    server.set_transport(None)


async def test_every_tool_is_registered():
    tools = await server.mcp.list_tools()

    assert {tool.name for tool in tools} == {
        "check_health",
        "get_current_date",
        "get_todays_events",
        "get_week_birthdays",
        "get_birthdays_on_day",
        "get_events_on_day",
        "get_month_calendar",
        "get_household",
        "get_relationship",
        "get_npc_location",
        "get_gift_tastes",
        "suggest_gift",
        "get_current_state",
        "get_recent_activity",
        "get_recent_events",
    }


@pytest.mark.parametrize(
    ("call", "path"),
    [
        (lambda: server.get_household(), "/household"),
        (lambda: server.get_current_state(), "/state"),
        (lambda: server.get_recent_activity(), "/activity/recent"),
    ],
)
async def test_argument_less_tools_hit_their_endpoint(call, path):
    requests: list[httpx.Request] = []
    stub(requests, envelope({"stub": True}))

    result = await call()

    assert result == envelope({"stub": True})
    assert len(requests) == 1
    assert requests[0].url.path == path
    assert requests[0].url.query == b""


async def test_get_relationship_without_npc_asks_for_all_of_them():
    requests: list[httpx.Request] = []
    stub(requests, envelope([{"npc": "Haley"}]))

    result = await server.get_relationship()

    assert result["ok"] is True
    assert requests[0].url.path == "/relationship"
    assert requests[0].url.query == b""


async def test_get_relationship_with_npc_passes_it_through():
    requests: list[httpx.Request] = []
    stub(requests, envelope({"npc": "Haley", "relationship": "married"}))

    result = await server.get_relationship("Haley")

    assert result["data"]["npc"] == "Haley"
    assert requests[0].url.path == "/relationship"
    assert requests[0].url.params["npc"] == "Haley"


async def test_get_npc_location_passes_the_name_through():
    requests: list[httpx.Request] = []
    stub(requests, envelope({"npc": "Haley", "current": {"location": "Town"}}))

    result = await server.get_npc_location("Haley")

    assert result["data"]["npc"] == "Haley"
    assert requests[0].url.path == "/npc/location"
    assert requests[0].url.params["npc"] == "Haley"


async def test_get_npc_location_requires_a_name():
    tools = await server.mcp.list_tools()
    schema = next(tool for tool in tools if tool.name == "get_npc_location").input_schema

    assert schema["required"] == ["npc"]


async def test_get_gift_tastes_without_npc_asks_for_the_whole_catalog():
    requests: list[httpx.Request] = []
    stub(requests, envelope({"universal": {}, "villagers": []}))

    result = await server.get_gift_tastes()

    assert result["ok"] is True
    assert requests[0].url.path == "/gift/tastes"
    assert requests[0].url.query == b""


async def test_get_gift_tastes_with_npc_passes_it_through():
    requests: list[httpx.Request] = []
    stub(requests, envelope({"npc": "Abigail", "tastes": {}}))

    result = await server.get_gift_tastes("Abigail")

    assert result["data"]["npc"] == "Abigail"
    assert requests[0].url.path == "/gift/tastes"
    assert requests[0].url.params["npc"] == "Abigail"


async def test_suggest_gift_defaults_to_ten_suggestions():
    requests: list[httpx.Request] = []
    stub(requests, envelope({"npc": "Abigail", "suggestions": []}))

    await server.suggest_gift("Abigail")

    assert requests[0].url.path == "/gift/suggest"
    assert requests[0].url.params["npc"] == "Abigail"
    assert requests[0].url.params["limit"] == "10"


async def test_suggest_gift_forwards_the_limit():
    requests: list[httpx.Request] = []
    stub(requests, envelope({"npc": "Abigail", "suggestions": []}))

    await server.suggest_gift("Abigail", 5)

    assert requests[0].url.params["limit"] == "5"


async def test_get_recent_events_defaults_to_three_days():
    requests: list[httpx.Request] = []
    stub(requests, envelope([]))

    await server.get_recent_events()

    assert requests[0].url.params["days"] == "3"


async def test_get_recent_events_forwards_the_day_window():
    requests: list[httpx.Request] = []
    stub(requests, envelope([]))

    await server.get_recent_events(7)

    assert requests[0].url.path == "/events/recent"
    assert requests[0].url.params["days"] == "7"


async def test_mod_errors_stay_in_the_envelope():
    requests: list[httpx.Request] = []
    stub(
        requests,
        httpx.Response(
            404,
            json={"ok": False, "error": {"code": "unknown_npc", "message": "No such villager."}},
        ),
    )

    result = await server.get_relationship("Nobody")

    assert result["ok"] is False
    assert result["error"]["code"] == "unknown_npc"


async def test_unreachable_mod_becomes_a_connection_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused", request=request)

    server.set_transport(httpx.MockTransport(handler))

    result = await server.get_current_state()

    assert result["ok"] is False
    assert result["error"]["code"] == "connection_error"


async def test_recent_event_days_schema_bounds():
    tools = await server.mcp.list_tools()
    schema = next(tool for tool in tools if tool.name == "get_recent_events").input_schema

    assert schema["properties"]["days"] == {
        "default": 3,
        "description": "How far before and after today to look, in days",
        "maximum": 28,
        "minimum": 0,
        "title": "Days",
        "type": "integer",
    }


async def test_suggest_gift_limit_schema_bounds():
    tools = await server.mcp.list_tools()
    schema = next(tool for tool in tools if tool.name == "suggest_gift").input_schema

    assert schema["properties"]["limit"] == {
        "default": 10,
        "description": "How many gift suggestions to return, best first",
        "maximum": 50,
        "minimum": 1,
        "title": "Limit",
        "type": "integer",
    }
    assert schema["required"] == ["npc"]
