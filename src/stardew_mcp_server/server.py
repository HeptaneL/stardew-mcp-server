"""MCP server exposing the HelloStardew game-state HTTP API as tools.

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
RecentEventDays = Annotated[
    int,
    Field(ge=0, le=28, description="How far before and after today to look, in days"),
]
NpcName = Annotated[
    str,
    Field(description="Villager name. Internal or display name both work, case-insensitively."),
]
GiftLimit = Annotated[
    int,
    Field(ge=1, le=50, description="How many gift suggestions to return, best first"),
]

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


@mcp.tool()
async def get_household() -> dict[str, Any]:
    """获取玩家住所信息：农夫名字、农场名字、配偶名字、宠物名字与类型、孩子名字。"""
    return await _get("/household")


@mcp.tool()
async def get_relationship(npc: NpcName | None = None) -> dict[str, Any]:
    """查询玩家与村民的关系（好感度、心数、是否结婚等）。

    Args:
        npc: 村民名字，如 ``Haley``。不传则返回玩家已认识的所有村民，按好感度从高到低排序。
    """
    params = {"npc": npc} if npc else None
    return await _get("/relationship", params=params)


@mcp.tool()
async def get_npc_location(npc: NpcName) -> dict[str, Any]:
    """查询某个村民现在在哪、接下来会去哪。

    数据有两块：``NPC.Schedule``（游戏已按季节 / 星期 / 天气 / 婚后状态解析好的当天计划）和 NPC 的实时坐标。
    两者不一致时以 ``current`` 为准，``currentTarget`` 只是计划。

    - ``current``：实际所在的图和格子；``isTravelling`` 为 true 时 ``travellingTo`` 是这一段的终点
    - ``currentTarget``：现在应该生效的日程。为空表示今天的日程还没开始（通常还在家）
    - ``nextTarget``：下一个日程点，回答“待会儿去哪”
    - ``home``：村民自己的家，游戏按 ``Data/Characters`` 的 Home 条件解析
    - ``isInEvent``：节日 / 事件会临时覆盖日程，此时计划不可信
    - 日程的 key 是**出发时间**，走路还要几分钟，所以别把 ``time`` 当成到达时间

    Args:
        npc: 村民名字，如 ``Haley``。必须是当前已出现在世界里的村民。
    """
    return await _get("/npc/location", {"npc": npc})


@mcp.tool()
async def get_gift_tastes(npc: NpcName | None = None) -> dict[str, Any]:
    """查询村民对礼物的喜好，来源是游戏的 Data/NPCGiftTastes。

    每档的条目有三种：具体物品（给出物品名与 ID）、分类（如 ``Fish``，对应 ``-4`` 这类负数分类）、
    上下文标签（如 ``category_fish``，表示该标签下的一整类物品）。

    Args:
        npc: 村民名字，如 ``Abigail``。不传则返回全部村民，外加所有村民共用的 universal 列表。
    """
    params = {"npc": npc} if npc else None
    return await _get("/gift/tastes", params=params)


@mcp.tool()
async def suggest_gift(npc: NpcName, limit: GiftLimit = 10) -> dict[str, Any]:
    """推荐现在该送给某个村民什么礼物。

    会扫描玩家背包和世界上所有的箱子，用游戏自己的 getGiftTasteForThisItem 给每件物品打分，
    按预计好感收益排序，并说明今天还能不能送（每日一次、每周两次、生日 ×8、配偶减半）。
    同时返回 avoid 列表，列出背包里对方讨厌的东西，避免送错。

    Args:
        npc: 村民名字，如 ``Abigail``。
        limit: 最多返回多少条推荐，范围 1-50，默认 10。
    """
    return await _get("/gift/suggest", {"npc": npc, "limit": limit})


@mcp.tool()
async def get_current_state() -> dict[str, Any]:
    """获取玩家当前状态快照：时间、地点、金钱、体力、生命、天气、技能等级、背包内容。"""
    return await _get("/state")


@mcp.tool()
async def get_recent_activity() -> dict[str, Any]:
    """获取玩家最近（最近 3 个游戏日）做过的事：对话、送礼、钓鱼、出货、升级、消费等。"""
    return await _get("/activity/recent")


@mcp.tool()
async def get_recent_events(days: RecentEventDays = 3) -> dict[str, Any]:
    """获取今天前后若干天的日历事件（节日 / 被动节日 / 钓鱼赛 / 书商 / 生日）。

    Args:
        days: 今天往前、往后各看多少天，0 表示只看今天，最大 28。默认 3。
    """
    return await _get("/events/recent", {"days": days})


@mcp.tool()
async def get_incomplete_quests() -> dict[str, Any]:
    """获取玩家当前**还没完成**的任务列表，等同于游戏里的任务日志。

    包含两类，都放在同一个数组里、按紧迫程度排序（有期限的在前，`daysLeft` 小的更靠前）：

    - 普通任务：`type` 是 `basic` / `item_delivery` / `monster` / `fishing` / `socialize` 等，
      `questType` 给出游戏内部的类型常量
    - 特别订单：`type` 为 `special_order`，`isSpecialOrder` 为 true，并带 `requester`（委托人）

    每个任务的字段：

    - `id` / `title` / `description`：任务 ID、标题、说明
    - `objectives`：目标清单。`text` 已经是游戏翻译好的整句；特别订单还带 `currentCount` /
      `requiredCount`（进度，如 3/10）和 `isComplete`，普通任务的进度已经写进 `text` 里，所以这两个字段为 null
    - `isTimed` / `daysLeft`：是否有期限、还剩几天。`isTimed` 为 false 时 `daysLeft` 无意义
    - `isDailyQuest`：true 表示是公告板（布告栏）任务，两天内过期
    - `canBeCancelled`：能否在任务日志里取消
    - `moneyReward` / `rewardDescription`：完成后的金钱奖励与非金钱奖励说明

    注意：**已经达成目标、但还没领奖的任务不会出现在这里**（游戏已把它标记为完成），
    它们会一直留在任务日志里直到玩家领奖。
    """
    return await _get("/quests/incomplete")


def start() -> None:
    """Run the MCP server over stdio (the transport MCP clients spawn)."""
    mcp.run(transport="stdio")

if __name__ == "__main__":
    start()
