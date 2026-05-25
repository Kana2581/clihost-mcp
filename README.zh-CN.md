# clihost-mcp

[English](README.md) | **中文**

一个 MCP server，把本地 CLI —— Claude Code、Codex CLI、shell 命令，以及任何
你在 YAML 中声明的自定义 CLI —— 暴露为 MCP tools。

为这种场景而生：一个 agent（例如 Claude Desktop、Cursor、Claude Code 本身）
想把工作委派给另一个本地 AI CLI，或者通过 HTTP 委派给远端 CLI。

需要 Python 3.10+。

> ### ⚠ 安全须知 —— 安装前请先阅读
>
> `config.example.yaml` 默认带着 `--dangerously-skip-permissions`（Claude
> Code）和 `--dangerously-bypass-approvals-and-sandbox`（Codex CLI）这两个
> 参数。这些 flag **会关闭被启动的 CLI 自己的逐操作审批提示** —— 对无人值守
> 的 MCP 使用是必要的（否则交互提示会把调用卡死），但同时意味着被启动的
> CLI 可以以你的完整用户权限读、写、删、执行其工作目录里的任何东西。
> clihost-mcp 此时就是唯一的信任边界。
>
> 投入生产前：设置 `defaults.cwd_allowlist`，给 HTTP 传输配上 `auth_token`，
> 而且只把 clihost-mcp 指向你愿意让 LLM 改写的目录。完整威胁模型和关闭危险
> 默认值的方法见下面的 [安全模型](#安全模型)。

---

## 安装

下面 **二选一**。

### 方案 A —— uv（推荐）

```powershell
# 先装一次 uv：https://docs.astral.sh/uv/
uv tool install --from "/path/to/clihost_mcp" clihost-mcp
```

这会把 `clihost-mcp` 装到 PATH 上（`~/.local/bin` 下），跑在自己的隔离环境里。
改了代码想升级，加 `--force` 重跑一次即可。

如果你完全不想安装、直接从源码跑，uv 也能搞定：

```powershell
uv run --directory "/path/to/clihost_mcp" clihost-mcp
```

### 方案 B —— pip

```powershell
pip install -e "/path/to/clihost_mcp"
```

不管走哪个，`clihost-mcp --print-config` 都应该能打印出解析后的配置。

---

## 接入 MCP 客户端

所有主流 MCP 客户端接受同一种形状的 JSON 配置，只是文件位置不同。

| 客户端 | 配置文件 |
| --- | --- |
| Claude Desktop | `%APPDATA%\Claude\claude_desktop_config.json` |
| Cursor | `%USERPROFILE%\.cursor\mcp.json` |
| Claude Code (CLI) | 用 `claude mcp add`（见下）或 `~/.claude/settings.json` |
| Cline / Continue / 其他 | 各自的 JSON，但都是同样的 `mcpServers` 形状 |

### 配置 —— `clihost-mcp` 已在 PATH 上

走完方案 A 或 B 之后：

```json
{
  "mcpServers": {
    "clihost-mcp": {
      "command": "clihost-mcp"
    }
  }
}
```

### 配置 —— uv，不安装

跳过安装步骤；uv 会在首次运行时同步依赖，之后复用缓存的 `.venv`：

```json
{
  "mcpServers": {
    "clihost-mcp": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/clihost_mcp",
        "run",
        "clihost-mcp"
      ]
    }
  }
}
```

### 配置 —— 带自定义配置文件或环境变量

```json
{
  "mcpServers": {
    "clihost-mcp": {
      "command": "clihost-mcp",
      "args": ["--config", "C:\\Users\\you\\my_clihost_mcp.yaml"],
      "env": {
        "ANTHROPIC_API_KEY": "sk-ant-...",
        "OPENAI_API_KEY": "sk-..."
      }
    }
  }
}
```

这里的 `env` 是注入到 `clihost-mcp` 进程里的，再由它把 `defaults.env_passthrough`
白名单允许的变量转发给被启动的 CLI 子进程。

### Claude Code CLI 快捷方式

不想手改 JSON，可以直接在终端注册：

```powershell
# 如果 clihost-mcp 已经在 PATH 上
claude mcp add clihost-mcp -- clihost-mcp

# 或者用 uv，不安装
claude mcp add clihost-mcp -- uv --directory "/path/to/clihost_mcp" run clihost-mcp
```

重启之后，任何 Claude Code 会话里 `/mcp` 都能列出 `clihost-mcp`，调用它的任何
工具即可。

---

## 暴露的工具

| 工具 | 作用 |
| --- | --- |
| `claude_run(prompt, cwd?, timeout_sec?, adapter_kwargs?)` | 调 `claude -p ...` |
| `codex_run(prompt, cwd?, timeout_sec?, adapter_kwargs?)` | 调 `codex exec ...` |
| `shell_run(prompt, cwd?, timeout_sec?)` | 执行白名单内的 shell 命令（默认禁用） |
| `<custom>_run(...)` | 任何你在 YAML 中 `custom_adapters` 下声明的 adapter |
| `list_adapters()` | 列出所有已启用的 adapter 及其可接受的参数 |

每个 `*_run` 工具都返回一个统一的 dict：`{stdout, stderr, exit_code,
duration_ms, truncated, timed_out, run_id, full_output_path, error}`。
当 Claude Code 的 JSON 输出可解析时，`claude_run` 会额外返回 `parsed` 字段。

---

## HTTP 模式（给远端 agent 用）

```powershell
clihost-mcp --transport http --host 127.0.0.1 --port 8765 --auth-token YOUR_TOKEN
```

客户端调用 MCP 端点时要带上 `Authorization: Bearer YOUR_TOKEN`。
绑定非 localhost host 时如果没有 auth token，会在启动时直接拒绝。

---

## 配置

把 `config.example.yaml` 复制为 `~/.clihost_mcp/config.yaml`（或者通过
`--config <path>` 传入，或者设置 `$CLIHOST_MCP_CONFIG`）。解析顺序是：
`--config` > 环境变量 > `~/.clihost_mcp/config.yaml` > 内置默认值。

要点：

- `defaults.default_cwd` —— 调用方不传 `cwd` 时，被启动的 CLI 运行所在的目录。
  **在 server 启动时就会校验**：必须存在、必须是目录，并且（如果
  `cwd_allowlist` 非空）必须落在它里面 —— 拼写错误 / 目录不存在 / 自相矛盾
  的配置会在加载时就 fail，而不是第一次调用工具时才报错。详见下面的"工作
  目录"。
- `defaults.cwd_allowlist` —— 限制工具调用可以指向哪些工作目录。空列表 =
  无限制。
- `defaults.env_passthrough` —— 转发到子进程的环境变量白名单。留空则继承
  完整父进程环境。
- `defaults.proxy` —— 注入到每个被启动的 CLI env 中的出站 HTTP 代理（绕过
  `env_passthrough`）。在 Anthropic / OpenAI API 被地理封锁时需要。完整形态
  和注意事项见下面的"出站代理"。
- `adapters.shell.command_allowlist` —— `shell.enabled: true` 时必需。按
  basename 大小写不敏感比对；`.exe` / `.bat` / `.cmd` / `.ps1` 在匹配前被剥掉。
- `custom_adapters` —— 不写 Python 代码就能声明额外的 CLI。`argv_template`
  里的 `{prompt}` token 会在调用时被替换。

### 工作目录

每次调用的 cwd 解析顺序：

1. 调用方（例如 Claude）传给工具的 `cwd` 参数。会按 `cwd_allowlist` 校验。
   不在范围内则返回结构化错误拒绝。
2. 否则用配置里的 `defaults.default_cwd`（启动时已校验过）。
3. 否则继承 `clihost-mcp` 自己的 cwd —— 在 MCP stdio 启动模式下，这就是 MCP
   客户端启动 clihost-mcp 时所在的目录（一般是客户端当前的项目目录）。这个
   最后兜底通常**不是**你想要的 —— 像"codex 怎么跑到我 Claude Code 项目目录
   里去了"这种意外行为，就是跳过了步骤 1 和 2。

推荐配置：把 `default_cwd` 设成一个固定的沙箱 / scratch 目录，再用
`cwd_allowlist` 覆盖这个目录加上你愿意让调用方显式指定的项目目录。

```yaml
defaults:
  default_cwd: "C:\\Users\\you\\scratch"
  cwd_allowlist:
    - "C:\\Users\\you\\scratch"
    - "C:\\Users\\you\\projects"
```

### 出站代理

Anthropic 和 OpenAI 对若干地区做了地理封锁（中国大陆是其中之一）。从
`clihost-mcp` 内部看到的症状大致是这样：

```json
{
  "exit_code": 1,
  "stdout": "{... \"is_error\": true, \"api_error_status\": 403,
              \"result\": \"Failed to authenticate. API Error: 403 Request not allowed\" ...}"
}
```

403 而非网络超时 —— 说明请求**确实**到了上游，只是源 IP 不在允许范围。把被
启动的 CLI 指向一个出口在允许地区的本地代理就能修。

在 `~/.clihost_mcp/config.yaml` 里配置一次：

```yaml
defaults:
  # 简写：HTTP 和 HTTPS 用同一个 URL
  proxy: "http://127.0.0.1:7890"
```

或者完整 mapping 形式，需要按协议分别控制 / 设置 bypass 列表时用：

```yaml
defaults:
  proxy:
    url: "http://127.0.0.1:7890"      # 没被覆盖的 scheme 走这个
    https: "http://127.0.0.1:7891"    # 仅覆盖 https
    no_proxy: "localhost,127.0.0.1,.internal"
```

会注入到每个被启动的 CLI env 中的变量：

| 变量 | 来源 |
| --- | --- |
| `HTTP_PROXY` / `http_proxy` | `http` 设了就用，否则用 `url` |
| `HTTPS_PROXY` / `https_proxy` | `https` 设了就用，否则用 `url` |
| `ALL_PROXY` / `all_proxy` | `https` 设了就用，否则用 `http` |
| `NO_PROXY` / `no_proxy` | `no_proxy` 设了就用 |

注意事项：

- **绕过 `env_passthrough`。** 即便你设了严格的透传白名单（比如
  `[ANTHROPIC_API_KEY, OPENAI_API_KEY]`），代理变量依然会被注入。透传过滤是
  为了管秘密，不是为了管管道。
- **选一个跟你代理客户端匹配的端口。** Clash 默认 `7890`，v2rayN 的 HTTP 口
  一般是 `10809`，Shadowsocks 的本地 HTTP bridge 各家不一。用
  `netstat -ano | findstr LISTEN` 看实际监听端口。
- **改完 YAML 要重启 MCP 客户端。** `clihost-mcp` 每个 MCP 会话只启动一次，
  Python 不热加载，所以 `config.yaml` 的改动要等重启 Claude Desktop / Cursor
  / Claude Code 之后才生效。
- **`clihost-mcp --print-config` 会显示解析后的 proxy 块** —— 重启客户端前
  先用它确认 YAML 是按你预期解析的。
- 这个设置只影响 `clihost-mcp` 启动的子进程。`clihost-mcp` 本身不发出站
  请求，所以它自己的 env 不受影响。

如果你完全不想为每个项目维护一份 YAML，可以直接通过 clihost-mcp 命令行传
覆盖参数。三个都会在启动时校验。

| 参数 | 覆盖的项 | 备注 |
| --- | --- | --- |
| `--default-cwd PATH` | `defaults.default_cwd` | 在 `cwd_allowlist` 非空时，会自动扩展它使其覆盖到 PATH。 |
| `--default-timeout-sec N` | `defaults.timeout_sec` | 调用方不传 `timeout_sec` 时的单次调用默认值。 |
| `--max-timeout-sec N` | `defaults.max_timeout_sec` | 任意单次工具调用的硬上限。要跑长时间的 agentic CLI 时调大（codex agent 模式经常需要超过 600s 的默认值）。 |

需要长时间跑 codex 的项目，典型的 MCP 客户端接线长这样：

```json
{
  "mcpServers": {
    "clihost-mcp": {
      "command": "uv",
      "args": [
        "--directory", "/path/to/clihost_mcp",
        "run", "clihost-mcp",
        "--default-cwd", "/path/to/your/project",
        "--default-timeout-sec", "600",
        "--max-timeout-sec", "1800"
      ]
    }
  }
}
```

### 不写代码就接入自定义 CLI

```yaml
custom_adapters:
  - name: gemini
    description: "Google Gemini CLI"
    argv_template: ["gemini", "-p", "{prompt}"]
```

注册一个 `gemini_run` MCP 工具 —— 没有代码改动；只需要重启 `clihost-mcp`
进程（你的 MCP 客户端会自动重连）。

---

## 安全模型

### ⚠ 那些危险默认值，说人话版

`config.example.yaml` 默认开了两个 flag，会关掉被启动的 CLI 自己的安全提示：

| CLI | Flag | 它做了什么 |
| --- | --- | --- |
| Claude Code | `--dangerously-skip-permissions` | 自动批准每一次工具使用（Read、Write、Edit、Bash、…）。Claude 永远不会停下来问你。 |
| Codex CLI | `--dangerously-bypass-approvals-and-sandbox` | 关掉 Codex 的逐操作审批**以及**它的文件系统/网络沙箱。Codex 用你的用户权限直接跑 shell 命令。 |

这不是过度紧张的警告 —— 它们字面上就是 CLI 自己对自己的描述。只要任何一个
flag 开了，被启动的 CLI 就可以：

- 读 OS 用户能读的任意文件。
- 写 / 删 OS 用户能写的任意文件 —— 在 `cwd_allowlist` 为空时是磁盘上任意位置。
- 执行任意 shell 命令。
- 访问网络（设了 `defaults.proxy` 就走代理）。

**为什么默认开？** 不开的话，CLI 会卡在 stdin 上等人类批准 —— 但 clihost-mcp
给子进程的 stdin 是 `DEVNULL`（父进程的 stdin 是 MCP JSON-RPC 管道，子进程
不能动）。所以调用会一直挂到 timeout。在一个非交互的包装层里没有中间地带：
要么子进程拿满权限，要么它在第一个非平凡操作上就死锁。

**威胁模型。** 危险 flag 开着的时候，**clihost-mcp 就是唯一的信任边界** ——
它下游没有任何更安全的东西了。这意味着责任落在你身上：

1. **设 `cwd_allowlist`。** 不设的话，调用方可以指向任意目录。设了之后，
   被启动的 CLI 就被限制在那些前缀里。这是单条最重要的防御 —— 求你别留空。
2. **给 HTTP 传输上锁。** 非 localhost 绑定且没设 `transport.http.auth_token`
   会在启动时被拒。即便在 localhost，只要本机还有别的东西可能调它，就设个
   token。
3. **小心 prompt 来源。** Prompt 是直接喂给一个能执行代码的 CLI 的。把任何
   `claude_run` / `codex_run` 的调用方都当作等同于给了它一个在 `default_cwd`
   里的 shell。不可信的 prompt 文本 + 危险默认值 = 远程代码执行。
4. **别把 `default_cwd` 指向敏感目录。** 你愿意让 LLM 改写的源码仓库可以。
   `~`、`/etc`、任何带凭据 / 秘密 / 生产配置的目录 —— 不可以。

**怎么关掉。** 在你的配置里把惹事的 flag 从 `adapters.claude.default_args`
（和/或 `adapters.codex.default_args`）里删掉。之后需要审批的调用会挂到
timeout —— 这是在一个非交互包装层里选安全所要付的代价。你大概会想顺手把
`defaults.timeout_sec` 也调小（比如 30s），让 hang 早点 fail。

### 其他保证（独立于危险 flag）

- 任何地方都没有 `shell=True`；argv 始终是 list —— 命令注入在结构上不可能发生。
- `cwd` 参数会按 `cwd_allowlist` 校验。
- `shell` adapter 默认禁用；启用它需要显式的 `command_allowlist`。命令按
  basename 匹配（大小写不敏感，`.exe` / `.bat` / `.cmd` / `.ps1` 被剥掉）。
- 单次调用有 timeout，server 端按 `defaults.max_timeout_sec` 封顶，无视调用方
  输入。
- HTTP 传输：没 auth token 时仅限 localhost；设了之后每个请求必须带
  `Authorization: Bearer <token>`。
- `env_passthrough` 过滤哪些 env var 能到被启动的 CLI —— 有助于把无关秘密挡在
  子进程外面。`defaults.proxy` 是唯一的例外：它无条件被注入，因为它是网络
  管道、不是秘密。
- 每路输出截断在 100 KiB（可配置）。被截断的运行结果会完整写到
  `~/.clihost_mcp/runs/<run_id>/`，路径会返回给调用方。

---

## 各 CLI 特有的说明

- **Codex CLI** 在不带 `--skip-git-repo-check` 时拒绝在非 git 仓库里跑。示例
  配置把这个 flag 放进了默认参数 —— 如果你只在仓库里调用，可以删掉。
- **Claude Code** 认证：`claude -p` 复用你交互登录时的 OAuth / 凭据状态。
  遇到 `403 Request not allowed`，问题在 `claude` CLI 这一侧
  （账户 / 地区 / 认证），不在 clihost_mcp 里 —— 在你自己的 shell 里直接跑
  `claude -p "test"` 验证一下。
- **Windows + `.cmd` shim**（npm 装的 CLI 比如 `codex.cmd`）：自动处理 ——
  runner 通过 `shutil.which` 解析裸名字，它会尊重 PATHEXT。

---

## 目录结构

```
src/clihost_mcp/
├── server.py       # FastMCP 接线；动态工具注册
├── runner.py       # subprocess 执行（timeout、截断、PATHEXT）
├── config.py       # YAML + Pydantic
├── registry.py     # 内置 + 自定义 adapter 装配
├── cli.py          # `clihost-mcp` 入口
└── adapters/
    ├── base.py
    ├── claude_code.py
    ├── codex.py
    └── shell.py
```

---

## 开发

```powershell
# 用 uv
uv sync --extra dev
uv run pytest

# 用 pip
pip install -e ".[dev]"
pytest
```

repo 根目录下的 `smoke_test.py` 会在进程内启动 server，并通过 FastMCP `Client`
驱动它 —— 在没接真正的 MCP 客户端时也能做端到端验证。
