# Agent 最近消息桥接

## 能做到什么

`qqnt-mcp` 是一个只读 MCP `stdio` 服务。Agent 可以检查同步状态、按群名查找会话、列出最近活跃会话，并读取某个时间窗口内的消息。服务不监听 TCP 端口，也没有发送、删除、撤回或修改 QQ 消息的工具。

正文接口不是“最多只能读 200 条”：单页上限为 1000 条，响应中的 `has_more` 和 `next_cursor` 用于继续读取更早的一页。游标会固定首次请求的时间窗口起点，翻页期间新到的消息不会造成重复或漏页。Agent 在总结长窗口时应逐页读取并分段归纳，直到 `has_more=false`，不能把第一页当成完整结果。

群名来自同账号 `group_info.db` 的当前群列表和历史群详情。`qq_find_conversations` 支持按群名或群号搜索；`qq_recent_messages` 也接受 `conversation_name`。名称唯一时直接解析，模糊匹配到多个群时返回候选供用户确认。

这是一种按需的“准实时”读取：每次工具调用前，程序都会刷新本地数据库镜像。通常延迟为数百毫秒到数秒；它不是 QQ 官方事件流，也不承诺逐毫秒推送。

## 为什么不需要长期 Hook

LLDB 只用于首次取得 SQLCipher key。之后程序直接读取官方 QQ 沙盒里的数据库文件和 WAL，并执行以下步骤：

1. 检查主库在复制期间是否发生 checkpoint；
2. 去掉 QQNT 的 1024 字节自定义头部；
3. 复制一个稳定的 WAL 前缀；
4. 同步 `group_info.db` 的只读副本以解析群名；
5. 在权限为 `0700/0600` 的缓存中以 SQLCipher 只读模式打开；
6. 只投影最近消息需要的字段，不向 Agent 返回原始 protobuf。

若复制期间数据库发生变化，程序会短暂退避并重试。QQ 更新或账号切换导致 key 失效时，状态工具会报错，需要重新执行一次取 key 流程。

## MCP 环境变量

- `QQNT_KEY_PATH`：必填，单个 key 文件或候选目录。
- `QQNT_ALLOW_CONTENT=1`：允许正文工具返回内容；默认关闭。
- `QQNT_ALLOW_CONVERSATIONS`：可选，逗号分隔的会话 allowlist。设置后，正文工具必须显式指定其中一个会话。
- `QQNT_DATA_ROOT`：可选，QQ 数据根目录。
- `QQNT_ACCOUNT`：可选，明确指定 `nt_qq_…` 目录；否则选择最近有活动的账号。
- `QQNT_CACHE_DIR`：可选，私有热镜像目录。

不要把 key 的实际内容直接写进 Agent 配置；只传文件路径。key 文件应为 `0600`，父目录应为 `0700`。

## ChatGPT/Codex 桌面端

桌面端、Codex CLI 和 IDE 扩展共享同一个 Codex 主机的 MCP 配置。添加服务后，在桌面端“设置 → MCP servers”中确认 `qqnt-local` 已启用，然后执行一次 Restart。在输入框键入 `/mcp`，应能看到 `qqnt-local` 及其四个工具。

如果 `codex mcp list` 显示服务已启用，但新任务仍没有这些工具，可在 `~/.codex/config.toml` 的服务段加入：

```toml
[mcp_servers.qqnt-local]
required = true
startup_timeout_sec = 30
```

`required` 会让客户端等待服务完成初始化，而不是把启动较慢的服务从初始工具目录中略过。若服务本身无法初始化，新任务也会明确报错，不再悄悄回退到 Computer Use。

## 禁止静默回退到界面

MCP 服务的初始化指令已经要求：所有 QQ 消息读取都使用 `qqnt-local`；工具失败时报告错误，不得静默改用 Computer Use、屏幕截图、辅助功能、OCR 或 QQ 界面。只有用户明确要求检查 QQ 界面时才能使用 UI。

服务器指令只有在 MCP 成功初始化后才存在。若要让“工具没有加载”的任务也禁止回退，可把下面的规则加入 `~/.codex/AGENTS.md`：

```markdown
# Local QQ read routing

- For any request to read, inspect, summarize, search, or monitor QQ messages or QQ conversations, use the read-only `qqnt-local` MCP tools (`qq_bridge_status`, `qq_find_conversations`, `qq_recent_messages`, and `qq_recent_conversations`). Do not use Computer Use, screen capture, accessibility APIs, OCR, or the QQ user interface for these requests unless the user explicitly asks to inspect the UI.
- If the `qqnt-local` tools are unavailable in the current task, say that the task did not load the local QQ MCP server and ask the user to start a new task after restarting the MCP server. Do not silently fall back to Computer Use.
- When the user identifies a group by name, resolve it with `qq_find_conversations` or `conversation_name`; do not expect the user to know its numeric ID. If multiple groups match, show the named candidates and ask which one they mean.
- For summaries, keep calling `qq_recent_messages` with the returned `next_cursor` until `has_more` is false, and summarize incrementally; never treat the first page as the complete requested window.
```

Codex 只在任务启动时读取这份指令；修改后要新建任务验证。正常读取无需在请求中额外写“用 MCP”。

## 数据边界

“本地桥接”只代表 QQ 数据库的复制、解密和筛选在本机完成。Agent 请求到的消息正文会成为其模型上下文：

- 本地模型：可以做到消息内容不离机；
- 云端模型或云端 Agent：被请求的那部分消息可能离开本机；
- 不调用正文工具：不会向 Agent 提供消息正文。

建议配置会话 allowlist，并让 Agent 使用尽可能小的 `minutes` 和 `limit`。

## 当前限制

- 只读，不支持代发或自动回复；
- 单次工具调用最多返回 1000 条正文，但可用游标读取完整时间窗口；
- 文本、常见媒体、语音转写和系统提示提供摘要，复杂卡片可能只显示类型；
- 已退出或元数据已被 QQ 清理的极少数旧群可能仍只能显示群号；联系人名称目前仍可能退化为 QQ 号或 UID；
- 数据库结构、protobuf 字段或加密参数随 QQ 更新后可能需要适配。
