# qqnt-export-macos

在 Apple Silicon macOS 上，以本地优先方式导出自己账号的 QQNT 聊天记录，或让外部 Agent 按需读取最近消息：

- 不关闭 SIP
- 不安装 NapCat、LiteLoader 等 QQ 插件
- 不长期注入或 Hook `/Applications/QQ.app`
- 只对工作目录中的 QQ 副本做临时 ad-hoc 签名
- 密钥、数据库副本、明文和导出结果均保存在本机
- 输出 HTML、ChatLab JSON 和 JSONL
- 可复制 macOS QQ 的本地图片、头像、表情及语音缓存
- 离线模式不会自动下载缺失的 QQ CDN 资源
- 提供只读、本机 `stdio` MCP 接口，不开放网络端口
- 运行 QQ 时可从数据库与 WAL 建立数秒级的最新消息镜像

> [!WARNING]
> 仅处理你有权访问的账号与数据。数据库密钥、明文数据库和导出结果都是敏感信息；不要上传、提交或发送给第三方。本项目与腾讯无关，QQ 更新后流程可能失效。

## 已测试环境

- Apple Silicon（arm64）
- macOS 15.7.9，SIP 开启
- QQ 应用基线 6.9.80、运行时热更新 7.0.1
- Python 3.14
- SQLCipher 4.x

这不是版本承诺。`locate` 会解析当前 `wrapper.node` 的 Mach-O，而不是使用固定偏移；数据库结构仍可能随 QQ 更新变化。

## 原理与安全边界

```text
官方 QQ（只读来源）
  ├─ 完全退出后复制数据 ──> 私有 snapshot ──> HTML / JSON / JSONL
  ├─ 运行时 DB + WAL ─────> 私有热镜像 ─────> 本机 MCP ──> Agent
  └─ 复制 App ───────────> 临时 ad-hoc QQ 副本
                                │
snapshot + 临时副本 ── LLDB ───> 私有 key candidates
                                │
snapshot/nt_db + key ──────────> 明文数据库副本
                                │
明文数据库 + 本地媒体缓存 ─────> HTML / JSON / JSONL
```

LLDB 断点只加在临时 QQ 进程上；回调从 arm64 的 `x2/x3` 读取密钥候选，文件名使用 SHA-256 指纹，终端不打印密钥内容。解密命令会尝试候选并只接受恰好一个能打开 `nt_msg.db` 的密钥。

## 安装

需要 Xcode Command Line Tools、Homebrew、Python 3.11+：

```bash
xcode-select --install
brew install python sqlcipher
git clone https://github.com/jielosc/qqnt-export-macos.git
cd qqnt-export-macos
python3 -m venv .venv
.venv/bin/pip install -e '.[bridge]'
.venv/bin/qqnt-export-macos doctor
```

`doctor` 应显示 macOS、Apple Silicon、SIP、LLDB、codesign 和 git 均为 `ok`。QQ 完整签名若为 `WARN`，先从腾讯官方渠道重装 QQ，再继续。

## Agent 最近消息桥接

取得数据库 key 后，不必为每次查询重复注入 QQ。桥接器会在每次 Agent 调用时复制一个一致的主库/WAL 视图，并以只读方式查询最近消息；首次刷新通常需要复制主库，之后一般只更新很小的 WAL。它不会向 QQ 发送、删除或修改任何内容。

先从候选目录中验证并单独保存唯一可用的 key：

```bash
.venv/bin/qqnt-export-macos install-bridge-key \
  work/keys "$HOME/Library/Application Support/qqnt-export-macos/database.key"

.venv/bin/qqnt-export-macos bridge-status \
  --key "$HOME/Library/Application Support/qqnt-export-macos/database.key"
```

然后在支持 MCP 的 Agent 中添加本地 `stdio` 服务。下面是通用配置结构，路径需要替换为本机绝对路径：

```json
{
  "mcpServers": {
    "qqnt-local": {
      "command": "/absolute/path/qqnt-export-macos/.venv/bin/qqnt-mcp",
      "env": {
        "QQNT_KEY_PATH": "/absolute/path/database.key",
        "QQNT_ALLOW_CONTENT": "1"
      }
    }
  }
}
```

可用工具只有四个：

- `qq_bridge_status`：检查只读热镜像状态；
- `qq_find_conversations`：按可读群名或会话 ID 查找会话；
- `qq_recent_conversations`：列出活跃会话、群名及窗口内消息数；
- `qq_recent_messages`：读取消息，每页最多 1000 条，并用 `next_cursor` 连续分页。

没有发送消息工具。Agent 可以直接按群名查询；若重名或模糊命中多个群，接口会返回候选名称和群号供用户确认，不会自行猜测。若只允许 Agent 查看指定聊天，可再设置：

```text
QQNT_ALLOW_CONVERSATIONS=c2c:会话标识,group:群标识
```

正文读取默认关闭，必须明确设置 `QQNT_ALLOW_CONTENT=1`。桥接器本身不联网，但 MCP 返回的正文会进入调用它的 Agent 上下文；使用云端 Agent 时，不能把这理解为“聊天内容完全不离机”。完整说明见 [Agent 桥接](docs/agent-bridge.md)。

ChatGPT/Codex 桌面端添加或修改 MCP 配置后，需要在“设置 → MCP servers”中执行一次 Restart。若服务可以单独启动、却没有出现在 Agent 的工具列表，可将 `mcp_servers.qqnt-local.required` 设为 `true`，并把 `startup_timeout_sec` 设为 `30`；这能避免启动较慢时错过初始工具目录。

MCP 自身已经内置中英双语的意图路由、参数说明、只读/幂等标注和禁止 UI 回退规则，因此不需要在全局 `~/.codex/AGENTS.md` 重复写 QQ 指令。Agent 会区分正文读取、群名查找、活跃会话概览和故障诊断；长窗口摘要会按游标读完，而不是停在第一页。详见 [Agent 桥接文档](docs/agent-bridge.md#mcp-内置意图路由)。

### 安装 QQ 消息 Skill

有些 Agent 会把 MCP 工具按需隐藏，只有在识别到相关能力后才加载。仓库内置的 [`qq-messages` Skill](skills/qq-messages/SKILL.md) 提供轻量的意图入口，并声明对 `qqnt-local` MCP 的依赖。安装到 Codex：

```bash
mkdir -p "$HOME/.codex/skills"
ln -s "$PWD/skills/qq-messages" "$HOME/.codex/skills/qq-messages"
```

Skill 默认允许隐式调用。新建任务后，用户只需说“总结某某 QQ 群最近两小时的消息”；也可以显式使用 `$qq-messages`。这不会把聊天记录复制进 Skill，实际正文仍由本地只读 MCP 按需返回。

## 完整流程

以下命令均在仓库根目录执行。工作目录已被 `.gitignore` 排除。

### 1. 退出 QQ 并制作完整快照

从菜单完全退出 QQ，然后执行：

```bash
.venv/bin/qqnt-export-macos snapshot work/snapshot --mode full
```

工具在 QQ 仍运行、目标已存在或数据库带有非空 WAL/回滚日志时会拒绝继续。快照默认来源是：

```text
~/Library/Containers/com.tencent.qq/Data/Library/Application Support/QQ
```

### 2. 创建临时 QQ 副本并 ad-hoc 签名

```bash
.venv/bin/qqnt-export-macos prepare-app work/QQ-adhoc.app
```

该命令内部使用 `ditto` 复制、对目标执行 ad-hoc 签名并严格校验。它会拒绝已存在的目标以及 `/Applications` 内的目标。不要使用 `sudo`，也不要对 `/Applications/QQ.app` 执行签名命令。

### 3. 定位当前运行时的 key 函数

```bash
WRAPPER=$(.venv/bin/qqnt-export-macos find-wrapper \
  'work/snapshot/Library/Application Support/QQ' \
  --qq-app work/QQ-adhoc.app)
OFFSET=$(.venv/bin/qqnt-export-macos locate "$WRAPPER")
printf '%s\n' "$WRAPPER" "$OFFSET"
```

`OFFSET` 应为十六进制模块虚拟地址，例如 `0x3719d50`；不同版本会不同。

### 4. 在隔离数据副本中捕获候选 key

先取得随包安装的 LLDB 脚本路径：

```bash
LLDB_SCRIPT=$(.venv/bin/qqnt-export-macos lldb-script)
mkdir -m 700 -p work/keys
QQNT_KEY_DIR="$PWD/work/keys" lldb work/QQ-adhoc.app/Contents/MacOS/QQ
```

在 LLDB 中执行以下命令；把路径和偏移替换成上一步输出的绝对值：

```text
(lldb) settings set target.env-vars CFFIXED_USER_HOME=/absolute/path/to/work/snapshot
(lldb) run
```

等隔离 QQ 界面加载后按 `Ctrl-C`，再执行：

```text
(lldb) command script import /absolute/path/from/lldb-script
(lldb) qqnt-install 0xYOUR_OFFSET
(lldb) process kill
(lldb) run
```

看到 `candidate saved privately` 后按 `Ctrl-C`：

```text
(lldb) process kill
(lldb) quit
```

一个启动过程可能捕获多个不同数据库的候选 key，这是正常现象。不要把 `.key` 文件内容粘贴到终端、Issue 或日志中。

### 5. 找到账号数据库并解密副本

```bash
.venv/bin/qqnt-export-macos accounts \
  'work/snapshot/Library/Application Support/QQ'
```

选择需要的 `nt_qq_.../nt_db` 路径：

```bash
.venv/bin/qqnt-export-macos decrypt \
  '/absolute/path/to/nt_qq_ACCOUNT/nt_db' \
  work/plaintext \
  work/keys
```

默认解密 `nt_msg.db`、`profile_info.db`、`group_info.db` 和 `emoji.db`。输出目录必须不存在，源数据库不会被修改；输出会逐库执行 SQLite `quick_check`。

### 6. 准备并运行 QQNT_Export

本项目使用固定提交的 [QQNT_Export](https://github.com/Tealina28/QQNT_Export) 作为格式导出后端，并应用 GPLv3 补丁以支持 macOS 缓存、离线 HTML 与空时间戳：

```bash
.venv/bin/qqnt-export-macos bootstrap-exporter work/QQNT_Export

.venv/bin/qqnt-export-macos make-config work/export.toml \
  --plaintext work/plaintext \
  --nt-data '/absolute/path/to/nt_qq_ACCOUNT/nt_data' \
  --output work/output

.venv/bin/qqnt-export-macos export work/QQNT_Export work/export.toml
```

### 7. 校验和收紧权限

```bash
.venv/bin/qqnt-export-macos verify work/output --privatize
```

校验内容包括：

- 所有 JSON 和 JSONL 可解析
- 每份 HTML 有完成标记
- HTML 没有自动加载的远程图片、音频或视频
- 文件不允许组用户或其他用户读取
- 汇总会话格式、消息和本地资源数量，但不打印聊天名称或内容

## 再次导出

同一账号的 key 可能可以继续使用，但不作保证。每次都应：

1. 完全退出 QQ；
2. 创建新的时间戳快照；
3. 使用新的明文与输出目录；
4. 让 `decrypt` 重新验证 key；
5. 如果 key 不再匹配，再执行 LLDB 捕获步骤。

密钥不能跨账号通用。切换账号后需要让隔离 QQ 登录相应账号并重新捕获。

## 清理

确认导出结果可用后，可删除以下临时内容：

```text
work/QQ-adhoc.app
work/keys
work/plaintext
work/snapshot
```

保留 `work/output` 即可。删除前自行确认没有需要重新导出的数据；本工具不会自动删除它们。

## 故障排查与来源

- [取 key 说明](docs/key-capture.md)
- [常见问题](docs/troubleshooting.md)
- [安全策略](SECURITY.md)
- [第三方项目与许可证](THIRD_PARTY.md)

本实现基于对 [QQBackup/QQDecrypt](https://github.com/QQBackup/QQDecrypt) 和 [QQBackup/qq-win-db-key](https://github.com/QQBackup/qq-win-db-key) 公开研究的验证，并使用 [QQNT_Export](https://github.com/Tealina28/QQNT_Export) 作为导出后端。请分别遵守上游许可证。

## 许可证

本仓库代码采用 [GNU GPL v3](LICENSE)。QQ、QQNT 和相关商标归其权利人所有。
