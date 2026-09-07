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

### Agent Skill 入口

部分 Agent 会把 MCP 工具放进按需加载的隐藏目录。仓库内置 [`qq-messages`](../skills/qq-messages/SKILL.md) Skill，使用短小、明确的技能描述匹配 QQ 读取、搜索、总结、回顾和监控请求；其 `agents/openai.yaml` 声明了 `qqnt-local` MCP 依赖，并允许隐式调用。

```bash
mkdir -p "$HOME/.codex/skills"
ln -s "$PWD/skills/qq-messages" "$HOME/.codex/skills/qq-messages"
```

安装后重启 Codex 并新建任务。正常请求无需写工具名；若想强制选中技能，可在请求中写 `$qq-messages`。Skill 只提供发现和调用流程，不保存 key、数据库或聊天正文。

## MCP 内置意图路由

MCP 服务在初始化时直接向 Agent 发布中英双语的路由规则、工具说明、参数说明和只读/幂等标注。正常使用不需要修改全局 `~/.codex/AGENTS.md`，也不需要在每次请求里强调“使用 MCP”。

内置路由关系如下：

- 查看、读取、搜索、总结、回顾或监控 QQ 消息：`qq_recent_messages`；
- 用户给出群名：直接放进 `conversation_name`，不要求用户提供群号；
- 查找群、名称不完整或出现多个同名候选：`qq_find_conversations`；
- 查看最近有哪些会话活跃及消息数：`qq_recent_conversations`；
- 诊断数据库 key、账号发现或热镜像故障：`qq_bridge_status`，正常读取前不必先调用；
- 完整摘要或搜索：持续传递 `next_cursor`，直到 `has_more=false`。

QQ 消息读取不得静默改用 Computer Use、屏幕截图、辅助功能、OCR 或 QQ 界面；只有用户明确要求检查界面时才允许使用 UI。工具失败时应直接报告错误。服务器最关键的路由规则放在初始化指令的前 512 个字符内，避免客户端截断较长说明时丢失。

这些元数据只有 MCP 成功初始化后才会进入 Agent 的工具目录，因此应把服务设置为 `required = true`。修改服务代码或配置后，在桌面端重启该 MCP，并新建任务验证；已经启动的任务不会自动刷新工具说明。

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
