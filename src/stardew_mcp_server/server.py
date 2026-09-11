"""MCP server exposing the HelloStardew calendar HTTP API as tools.

The mod (see ``StardewMods/HelloStardew/Bridge/HttpBridge.cs``) listens on
``http://127.0.0.1:8788`` by default and answers every endpoint with the same
envelope::

    {"ok": true, "data": ..., "date": {...}, "error": null}

This module talks to that API and never touches the game process directly, so
it can run in any Python environment.
"""

from __future__ import annotations

import os
from typing import Annotated, Any, Literal

import httpx
from mcp.server.mcpserver import MCPServer
from pydantic import Field

DEFAULT_BASE_URL = "http://127.0.0.1:8788"
DEFAULT_TIMEOUT = 5.0

Season = Literal["spring", "summer", "fall", "winter"]
DayOfSeason = Annotated[int, Field(ge=1, le=28, description="Day of the season (1-28)")]

mcp = MCPServer("stardew_valley")

# Overridable in tests via ``set_transport`` so no real socket is needed.
_transport: httpx.AsyncBaseTransport | None = None


def set_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    """Force the httpx transport used for every request (mainly for tests)."""
    global _transport
    _transport = transport


def _base_url() -> str:
    """Resolve the mod's base URL at call time so env changes are picked up."""
    return os.environ.get("STARDEW_API_URL", DEFAULT_BASE_URL).rstrip("/")


def _timeout() -> float:
    """Resolve the request timeout, falling back to the default when unset/invalid."""
    raw = os.environ.get("STARDEW_API_TIMEOUT")
    if not raw:
        return DEFAULT_TIMEOUT
    try:
        return float(raw)
    except ValueError:
        return DEFAULT_TIMEOUT


def _failure(code: str, message: str, status: int | None = None) -> dict[str, Any]:
    """Build an error payload shaped like the mod's own response envelope."""
    error: dict[str, Any] = {"code": code, "message": message}
    if status is not None:
        error["status"] = status
    return {"ok": False, "data": None, "date": None, "error": error}


def _failure_from_response(resp: httpx.Response) -> dict[str, Any]:
    """Turn a non-2xx response into a friendly error payload."""
    code = "http_error"
    message = f"mod 返回 HTTP {resp.status_code}"

    try:
        payload = resp.json()
    except ValueError:
        payload = None

    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            code = str(error.get("code") or code)
            message = str(error.get("message") or message)

    if resp.status_code == 503:
        # The mod reports "no save loaded" / "game busy" as 503.
        message = f"存档尚未加载或游戏正忙，请先进入游戏存档（{message}）"

    return _failure(code, message, status=resp.status_code)


async def _get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """GET ``path`` from the mod and return its JSON envelope.

    Transport and HTTP errors are converted into an error envelope instead of
    raising, so a tool call always yields something the model can read.
    """
    url = f"{_base_url()}{path}"
    try:
        async with httpx.AsyncClient(timeout=_timeout(), transport=_transport) as client:
            resp = await client.get(url, params=params)
    except httpx.HTTPError as exc:
        return _failure(
            "connection_error",
            f"无法连接星露谷 mod 的 HTTP 服务 {url}，请确认游戏已启动且 mod 已加载（{exc}）",
        )

    if resp.status_code >= 400:
        return _failure_from_response(resp)

    try:
        payload = resp.json()
    except ValueError:
        return _failure("invalid_response", f"mod 返回了非 JSON 响应：{resp.text[:200]!r}")

    if not isinstance(payload, dict):
        return _failure("invalid_response", f"mod 返回了非预期的响应类型：{type(payload).__name__}")

    return payload


@mcp.tool()
async def check_health() -> dict[str, Any]:
    """检查星露谷 mod 的 HTTP 服务是否在线，以及存档是否已加载。"""
    return await _get("/health")


@mcp.tool()
async def get_current_date() -> dict[str, Any]:
    """获取游戏内当前日期、季节和星期信息。"""
    return await _get("/date")


@mcp.tool()
async def get_todays_events() -> dict[str, Any]:
    """获取今天的所有事件：生日 / 节日 / 被动节日 / 钓鱼赛 / 书商。"""
    return await _get("/events/today")


@mcp.tool()
async def get_week_birthdays(include_past: bool = False) -> dict[str, Any]:
    """获取本周（游戏内周，从周一到周日）的村民生日列表。

    Args:
        include_past: 是否包含本周已经过去的日子，默认只返回今天及之后。
    """
    return await _get("/birthdays/week", {"includePast": "true" if include_past else "false"})


@mcp.tool()
async def get_birthdays_on_day(season: Season, day: DayOfSeason) -> dict[str, Any]:
    """查询指定季节和日期的村民生日。"""
    return await _get("/birthdays/day", {"season": season, "day": day})


@mcp.tool()
async def get_events_on_day(season: Season, day: DayOfSeason) -> dict[str, Any]:
    """查询指定季节和日期的所有事件（节日 / 被动节日 / 钓鱼赛 / 书商 / 生日）。"""
    return await _get("/events/day", {"season": season, "day": day})


@mcp.tool()
async def get_month_calendar(season: Season | None = None) -> dict[str, Any]:
    """获取整个季节（28 天）的日历，不传 season 则默认为当前季节。"""
    params = {"season": season} if season else None
    return await _get("/calendar", params=params)


def start() -> None:
    """Run the MCP server over stdio (the transport MCP clients spawn)."""
    mcp.run(transport="stdio")

if __name__ == "__main__":
    start()
