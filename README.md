# stardew-mcp-server

把《星露谷物语》(Stardew Valley) 的游戏内日历数据接入 LLM 的 [MCP](https://modelcontextprotocol.io) 服务器。

## 效果
<img width="1380" height="1310" alt="image" src="https://github.com/user-attachments/assets/c793ac52-0a7f-4071-8aa2-a761ca6c20c0" />


它本身不读写游戏内存，而是作为一层 **MCP ⇄ HTTP 代理**：MCP 客户端（如 Claude Code）通过 stdio 调用工具，服务器再把请求转发给游戏内 mod **[HelloStardew](https://github.com/HeptaneL/HelloStardew)** 暴露的本地 HTTP 桥接服务。

```
Claude Code / 其他 MCP 客户端
        │  stdio (JSON-RPC)
        ▼
stardew-mcp-server  (本仓库)
        │  HTTP GET  http://127.0.0.1:8788
        ▼
HelloStardew mod  (游戏内, HttpBridge)
        │
        ▼
Stardew Valley 存档
```

## 功能

通过 mod 的 HTTP API 提供以下只读能力：

- 查询游戏内当前日期、季节、星期
- 查询今天的所有事件（生日 / 节日 / 被动节日 / 钓鱼赛 / 书商）
- 查询指定季节某一天的事件与村民生日
- 查询本周（周一至周日）的村民生日
- 获取整个季节（28 天）的日历

## 环境要求

- Python **3.12+**
- [uv](https://docs.astral.sh/uv/)（推荐，用于依赖管理）
- 已安装并加载 [HelloStardew](https://github.com/HeptaneL/HelloStardew) mod，且游戏已进入存档
- mod 的 HTTP 服务默认监听 `http://127.0.0.1:8788`

## 安装

```bash
git clone <本仓库地址> stardew-mcp-server
cd stardew-mcp-server
uv sync
```

`uv sync` 会根据 `pyproject.toml` / `uv.lock` 创建 `.venv` 并安装 `mcp`、`httpx`。

## 在 Claude Code 中接入

本仓库使用 stdio 传输，由 Claude Code 启动进程并通过标准输入输出通信。

```bash
claude mcp add stardew --transport stdio \
  --env STARDEW_API_URL=http://127.0.0.1:8788 \
  -- /Users/heptane/Project/Agents/stardew-mcp-server/.venv/bin/python /Users/heptane/Project/Agents/stardew-mcp-server/src/stardew_mcp_server/server.py
```

> 请把路径替换成你自己 clone 后的实际路径。`.venv/bin/python` 由 `uv sync` 生成。

如果已经通过 `uv sync` 安装，也可以直接用控制台脚本：

```bash
claude mcp add stardew --transport stdio \
  --env STARDEW_API_URL=http://127.0.0.1:8788 \
  -- uv run --project /path/to/stardew-mcp-server stardew-mcp-server
```

添加完成后可在 Claude Code 中用 `/mcp` 查看连接状态。

### 其他 MCP 客户端

多数客户端使用如下 JSON 配置（Claude Desktop 的 `claude_desktop_config.json`、Cursor 等）：

```json
{
  "mcpServers": {
    "stardew": {
      "command": "/Users/heptane/Project/Agents/stardew-mcp-server/.venv/bin/python",
      "args": [
        "/Users/heptane/Project/Agents/stardew-mcp-server/src/stardew_mcp_server/server.py"
      ],
      "env": {
        "STARDEW_API_URL": "http://127.0.0.1:8788"
      }
    }
  }
}
```

## 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `STARDEW_API_URL` | `http://127.0.0.1:8788` | mod HTTP 服务的地址，每次调用时读取，末尾 `/` 会被去掉 |
| `STARDEW_API_TIMEOUT` | `5.0` | 单次 HTTP 请求超时（秒）；未设置或非法时回退到默认值 |

## 可用工具

| 工具 | 参数 | 说明 |
| --- | --- | --- |
| `check_health` | — | 检查 mod HTTP 服务是否在线、存档是否已加载 |
| `get_current_date` | — | 获取游戏内当前日期、季节、星期 |
| `get_todays_events` | — | 获取今天的所有事件 |
| `get_week_birthdays` | `include_past: bool = false` | 本周村民生日；`include_past=true` 时包含已过去的日子 |
| `get_birthdays_on_day` | `season`, `day` | 指定季节/日期的村民生日 |
| `get_events_on_day` | `season`, `day` | 指定季节/日期的所有事件 |
| `get_month_calendar` | `season: optional` | 整季日历，缺省为当前季节 |

- `season` 取值：`spring` | `summer` | `fall` | `winter`
- `day` 取值：`1` – `28`

## mod 的 HTTP API

服务器仅使用 `GET`，不带鉴权。每个接口都返回统一信封：

```json
{ "ok": true, "data": {}, "date": {}, "error": null }
```

| 工具 | 请求 |
| --- | --- |
| `check_health` | `GET /health` |
| `get_current_date` | `GET /date` |
| `get_todays_events` | `GET /events/today` |
| `get_week_birthdays` | `GET /birthdays/week?includePast=true\|false` |
| `get_birthdays_on_day` | `GET /birthdays/day?season={season}&day={day}` |
| `get_events_on_day` | `GET /events/day?season={season}&day={day}` |
| `get_month_calendar` | `GET /calendar` 或 `GET /calendar?season={season}` |

## 错误处理

工具调用不会抛异常，而是返回统一格式的错误信封，便于模型直接读取：

```json
{ "ok": false, "data": null, "date": null, "error": { "code": "...", "message": "...", "status": 503 } }
```

常见 `code`：

| code | 含义 |
| --- | --- |
| `connection_error` | 连不上 mod 服务，通常是游戏未启动或 mod 未加载 |
| `http_error` | mod 返回非 2xx 状态 |
| `invalid_response` | mod 返回的不是合法 JSON 或不是对象 |

当 mod 返回 **503** 时，表示**存档尚未加载或游戏正忙**，请先进入游戏存档后重试。

## 常见问题

- **调用工具报 `connection_error`**：确认游戏正在运行、HelloStardew mod 已加载，且 `STARDEW_API_URL` 指向的端口（默认 `8788`）可访问。
- **返回 503 / “存档尚未加载”**：进入任意存档后再调用。
- **不要向 stdout 打印内容**：stdio MCP 服务器的 stdout 是 JSON-RPC 通道，任何多余输出都会破坏协议握手。控制台脚本 `stardew-mcp-server` 已保证这一点。

## 开发

```bash
uv run stardew-mcp-server        # 以 stdio 方式启动服务器
uv run pytest                    # 运行测试（tests/ 目录）
```

服务器内部通过 `set_transport()` 允许替换 `httpx` 传输层，便于在测试中注入模拟响应而无需真实 socket。

## 相关仓库

- mod 端：[HeptaneL/HelloStardew](https://github.com/HeptaneL/HelloStardew)

## License

见仓库中的许可文件（如有）。
