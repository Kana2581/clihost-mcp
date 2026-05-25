# AGENTS.md

## 项目概述

`clihost-mcp` 是一个 Python 3.10+ 项目，用 FastMCP 提供 MCP server，把本地 CLI 暴露为 MCP tools。README 中列出的典型目标包括 Claude Code、Codex CLI、受 allowlist 约束的 shell 命令，以及 YAML 中声明的自定义 CLI。

项目边界集中在安全、可控地启动本地子进程：

- 子进程参数必须保持为 argv list；不要引入 `shell=True`，不要把命令拼成 shell 字符串执行。
- `cwd` 可通过 `defaults.cwd_allowlist` 约束；`defaults.default_cwd` 会在启动时校验。
- `shell` adapter 默认禁用；启用时必须维护 `command_allowlist`。
- 单次调用有 timeout，调用方传入值会受 `defaults.max_timeout_sec` 限制。
- HTTP transport 绑定非 localhost 时必须配置 auth token；配置 token 后请求需携带 `Authorization: Bearer <token>`。
- stdout/stderr 按 `defaults.max_output_bytes` 截断；截断时完整输出可写入 runs 目录，并把路径返回给调用方。
- `config.example.yaml` 默认包含 Claude Code 和 Codex CLI 的危险跳过审批参数；生产使用前应设置 `cwd_allowlist`、HTTP auth token，并只指向可接受被 LLM 修改的目录。

## 仓库结构

基于 README、`pyproject.toml`、`config.example.yaml`、当前 AGENTS，以及当前 `src/clihost_mcp` 和 `tests` 文件名：

```text
.
├── AGENTS.md
├── README.md
├── pyproject.toml
├── config.example.yaml
├── smoke_test.py
├── src/
│   └── clihost_mcp/
│       ├── __init__.py
│       ├── cli.py
│       ├── config.py
│       ├── registry.py
│       ├── runner.py
│       ├── server.py
│       └── adapters/
│           ├── __init__.py
│           ├── base.py
│           ├── claude_code.py
│           ├── codex.py
│           └── shell.py
└── tests/
    ├── __init__.py
    ├── test_adapters.py
    ├── test_config.py
    ├── test_runner.py
    └── test_server.py
```

不要把 `__pycache__`、`.pytest_cache`、`.venv`、用户私有配置、API key、认证状态或 runs 输出等运行产物纳入提交。

## 关键命令

初始化开发环境：

```powershell
uv sync --extra dev
```

或：

```powershell
pip install -e ".[dev]"
```

从源码运行：

```powershell
uv run --directory "/path/to/clihost_mcp" clihost-mcp
```

安装或强制重装本地工具：

```powershell
uv tool install --from "/path/to/clihost_mcp" clihost-mcp
uv tool install --force --from "/path/to/clihost_mcp" clihost-mcp
```

打印解析后的配置：

```powershell
clihost-mcp --print-config
```

指定配置文件：

```powershell
clihost-mcp --config "C:\Users\you\my_clihost_mcp.yaml"
```

HTTP 模式：

```powershell
clihost-mcp --transport http --host 127.0.0.1 --port 8765 --auth-token YOUR_TOKEN
```

命令行覆盖默认运行目录和 timeout：

```powershell
clihost-mcp --default-cwd "D:\some\project" --default-timeout-sec 600 --max-timeout-sec 1800
```

运行测试：

```powershell
uv run pytest
```

或：

```powershell
pytest
```

`pyproject.toml` 已配置 `asyncio_mode = "auto"` 和 `testpaths = ["tests"]`。README 还提到根目录 `smoke_test.py` 可在进程内构建 server，并通过 FastMCP `Client` 做冒烟测试。

## 配置要点

- 配置解析顺序：`--config` > `CLIHOST_MCP_CONFIG` > `~/.clihost_mcp/config.yaml` > 内置默认值。
- `config.example.yaml` 可复制到 `~/.clihost_mcp/config.yaml`，也可通过 `--config <path>` 指定。
- README 列出的内置默认值包括：`timeout_sec=120`、`max_timeout_sec=600`、`max_output_bytes=102400`、`shell.enabled=false`。
- `config.example.yaml` 示例中 `max_timeout_sec` 为 `1800`，用于较长的 agentic CLI 调用。
- `defaults.default_cwd` 是调用方未传 `cwd` 时的运行目录；启动时要求存在且是目录。如果 `cwd_allowlist` 非空，它还必须位于 allowlist 内。
- `defaults.cwd_allowlist` 非空时，调用方传入的 `cwd` 必须位于允许前缀内。
- `defaults.env_passthrough` 为空时继承完整父环境；非空时只透传列出的变量加基础环境变量。
- `defaults.proxy` 支持字符串或 mapping（`url` / `http` / `https` / `no_proxy`），会在每次 subprocess 启动时注入 proxy env，且不受 `env_passthrough` 过滤。
- `transport.default` 示例值为 `stdio`；HTTP 模式可通过 CLI 参数启用。
- `transport.http.auth_token` 在 HTTP 非 localhost 绑定时是强制要求。
- `custom_adapters` 中每个启用条目会注册为 `<name>_run` MCP tool；`argv_template` 使用 `{prompt}` 替换调用方 prompt。

## 工具与返回值

README 列出的 MCP tools：

- `claude_run(prompt, cwd?, timeout_sec?, adapter_kwargs?)`
- `codex_run(prompt, cwd?, timeout_sec?, adapter_kwargs?)`
- `shell_run(prompt, cwd?, timeout_sec?)`
- `<custom>_run(...)`
- `list_adapters()`

每个 `*_run` tool 返回统一 dict：`stdout`、`stderr`、`exit_code`、`duration_ms`、`truncated`、`timed_out`、`run_id`、`full_output_path`、`error`。README 还说明 `claude_run` 在 Claude Code JSON 输出可解析时额外返回 `parsed`。

## 代码约定

- 保持当前模块边界：配置相关内容在 `config.py`，执行相关内容在 `runner.py`，server/tool 相关内容在 `server.py`，adapter argv 拼装在 `adapters/`。
- 使用现代 Python 类型标注和 `pathlib.Path`；涉及路径或命令解析时注意 Windows。
- 不要引入 `shell=True`，不要把命令拼成 shell 字符串执行。
- 新增依赖前确认必要性，并同步更新 `pyproject.toml` 和相关文档。
- 当前运行依赖为 `fastmcp>=2.0`、`pydantic>=2.0`、`pyyaml>=6.0`；dev 依赖为 `pytest>=8.0`、`pytest-asyncio>=0.23`。
- 当前项目未声明 ruff、black、mypy 等固定工具；不要把它们当作必须步骤，除非后续配置文件明确加入。
- 保持 README、`config.example.yaml`、CLI 参数和实际行为一致。若发现不一致，优先修正实际偏差或文档。

## 测试约定

- 修改 subprocess 执行、安全校验、配置解析、adapter argv 或 tool 注册时，应补充或更新对应测试。
- 单元测试不要依赖真实 `claude`、`codex`、`gemini` 等外部 CLI。
- 可优先使用 `sys.executable`、`python -c ...`、临时目录和直接构造配置对象来覆盖行为。
- 测试文件当前包括 `test_adapters.py`、`test_config.py`、`test_runner.py`、`test_server.py`。

## 协作约定

- 修改前只读取完成任务需要的文件；如果用户限定可查看范围，严格遵守。
- 处理已有改动时不要随意回滚用户修改；只改动当前任务必要文件。
- 不要把本机绝对路径、用户目录、密钥、认证状态或 runs 输出写成通用默认值；`config.example.yaml` 中的路径只是示例。
- 如需提交，保持提交范围清晰，提交消息描述实际变更即可。仓库材料中未体现 Conventional Commits、Git Flow、分支前缀或 PR 审批规则，不要编造这些要求。
- 准备 PR 说明时至少包含变更摘要、已运行测试及结果、安全影响说明、配置或文档变更说明。
