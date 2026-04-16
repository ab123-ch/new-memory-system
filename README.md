# Memory System MCP

<div align="center">

**AI 记忆系统 + 多人格支持 + 技能驱动自我进化**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![MCP Compatible](https://img.shields.io/badge/MCP-Compatible-green.svg)](https://modelcontextprotocol.io)

</div>

---

## 目录

- [项目简介](#-项目简介)
- [快速开始](#-快速开始)
- [一键安装](#-一键安装)
- [升级指南](#-升级指南)
- [MCP 配置](#-mcp-配置)
- [Hooks 配置](#-hooks-配置)
- [API Key 配置](#-api-key-配置)
- [守护进程配置](#-守护进程配置)
- [MCP 工具列表](#-mcp-工具列表)
- [目录结构](#-目录结构)
- [高级配置](#-高级配置)

---

## 📖 项目简介

Memory System MCP 是一个为 AI 编程工具（Claude Code、Cursor、Windsurf 等）设计的智能记忆系统，通过 MCP（Model Context Protocol）协议提供以下核心功能：

### 🧠 核心特性

| 功能 | 描述 |
|------|------|
| **对话记忆** | 自动保存对话历史，支持时间线浏览和搜索 |
| **多人格支持** | 切换不同人格获得专业领域的上下文 |
| **技能系统** | 基于经验的学习和复用，支持动态创建技能 |
| **自我演化** | 自动评估技能质量，持续优化学习代码 |
| **向量搜索** | 语义搜索快速定位相关记忆 |
| **AI 增强** | 智能摘要、关键词提取、记忆优化 |

---

## 🚀 快速开始

### 前置要求

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) (推荐) 或 pip

### 检查环境

```bash
# 检查 Python 版本
python3 --version

# 安装 uv (推荐)
curl -LsSf https://astral.sh/uv/install.sh | sh
```

---

## 📦 一键安装

### 方式一：使用安装脚本（推荐）

**Mac/Linux**：
```bash
curl -sSL https://raw.githubusercontent.com/ab123-ch/memory-system/main/install-mcp.sh | bash
```

**Windows (PowerShell 管理员模式)**：
```powershell
Set-ExecutionPolicy Bypass -Scope Process -Force; iwr -useb https://raw.githubusercontent.com/ab123-ch/memory-system/main/install-mcp.ps1 | iex
```

安装脚本会自动完成：
1. ✅ 检查并安装依赖（Python、uv）
2. ✅ 创建数据目录 `~/.memory-system/`
3. ✅ 生成配置文件 `~/.memory-system/memory_config.yaml`
4. ✅ 配置 MCP 服务器
5. ✅ 配置 Claude Code Hooks
6. ✅ 配置守护进程服务

### 方式二：手动配置

如果需要自定义配置，请参考下方的详细配置说明。

---

## 🔄 升级指南

### 升级命令

Memory System 支持两种升级方式：

#### 方式一：uvx 方式（自动升级）

uvx 每次启动都会检查并拉取最新版本，无需手动升级。

#### 方式二：pip 方式升级

如果使用 pip 安装：

```bash
# 升级到最新版本
pip install --upgrade git+https://github.com/ab123-ch/memory-system.git

# 或指定版本
pip install git+https://github.com/ab123-ch/memory-system.git@v2.0.0
```

#### 方式三：重新运行安装脚本

```bash
# Mac/Linux
curl -sSL https://raw.githubusercontent.com/ab123-ch/memory-system/main/install-mcp.sh | bash

# Windows
Set-ExecutionPolicy Bypass -Scope Process -Force; iwr -useb https://raw.githubusercontent.com/ab123-ch/memory-system/main/install-mcp.ps1 | iex
```

安装脚本会自动检测并保留现有配置，仅更新程序文件。

---

## ⚙️ MCP 配置

### 配置文件位置

| 工具 | 配置文件路径 |
|------|-------------|
| Claude Code | `~/.claude/settings.json` |
| Cursor | `~/.cursor/mcp.json` |
| Windsurf | `~/.windsurf/mcp_config.json` |

### Claude Code 配置

编辑 `~/.claude/settings.json`：

```json
{
  "mcpServers": {
    "memorySystem": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/ab123-ch/memory-system.git",
        "memory-system-mcp"
      ]
    }
  }
}
```

### Cursor 配置

编辑 `~/.cursor/mcp.json`：

```json
{
  "mcpServers": {
    "memorySystem": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/ab123-ch/memory-system.git",
        "memory-system-mcp"
      ]
    }
  }
}
```

### Windsurf 配置

编辑 `~/.windsurf/mcp_config.json`：

```json
{
  "mcpServers": {
    "memorySystem": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/ab123-ch/memory-system.git",
        "memory-system-mcp"
      ]
    }
  }
}
```

### 使用 pip 安装时的配置

如果使用 pip 安装（`pip install git+https://github.com/ab123-ch/memory-system.git`）：

```json
{
  "mcpServers": {
    "memorySystem": {
      "command": "memory-system-mcp",
      "args": []
    }
  }
}
```

### 本地开发/部署配置

如果从源码安装或本地开发，有几种配置方式：

#### 方式一：pip 本地安装后使用

```bash
# 克隆并安装
git clone https://github.com/ab123-ch/memory-system.git
cd memory-system/memory-system
pip install -e .
```

配置 `~/.claude/settings.json`：
```json
{
  "mcpServers": {
    "memorySystem": {
      "command": "memory-system-mcp",
      "args": []
    }
  }
}
```

#### 方式二：uvx 使用本地路径

```json
{
  "mcpServers": {
    "memorySystem": {
      "command": "uvx",
      "args": [
        "--from",
        "/Users/{你的用户名}/PycharmProjects/memory-system/memory-system",
        "memory-system-mcp"
      ]
    }
  }
}
```

#### 方式三：直接运行 Python 模块（开发调试推荐）

```json
{
  "mcpServers": {
    "memorySystem": {
      "command": "python3",
      "args": [
        "-m",
        "memory_system.mcp_server"
      ],
      "cwd": "/Users/{你的用户名}/PycharmProjects/memory-system/memory-system",
      "env": {
        "PYTHONPATH": "/Users/{你的用户名}/PycharmProjects/memory-system/memory-system"
      }
    }
  }
}
```

> **注意**：请将 `{你的用户名}` 和路径替换为你的实际本地路径。

---

## 🪝 Hooks 配置

Hooks 可以在会话开始/结束时自动触发记忆功能，实现自动记忆恢复和保存。

### 配置文件位置

- **Mac/Linux**: `~/.claude/hooks/hooks.json`
- **Windows**: `%USERPROFILE%\.claude\hooks\hooks.json`

### Hook 脚本类型

工程提供两套 Hook 脚本：

| 类型 | 文件 | 功能说明 |
|------|------|----------|
| **完整版（推荐）** | `session_start_context.py`<br>`auto_save_memory.py` | 完整记忆系统：人格切换、记忆恢复、智能保存、自动优化 |
| **简单版** | `session-start.sh`<br>`session-end.sh` | 基础日志记录 |

### 完整版功能

**SessionStart (`session_start_context.py`)**：
- 恢复最近使用的人格
- 加载身份、习惯、能力记忆
- 加载最近 5 条对话记录
- 加载共享记忆
- 加载优化后的经验规则

**Stop (`auto_save_memory.py`)**：
- 自动检测并保存对话
- 智能判断是否需要记忆优化
- 自动触发优化流程

### 自动配置（推荐）

安装脚本会自动复制 Hook 脚本到 `~/.claude/hooks/` 并配置 `hooks.json`。

### 手动配置

如需手动配置，请复制脚本并更新 `hooks.json`：

**Mac/Linux:**
```bash
# 复制完整版脚本（推荐）
mkdir -p ~/.claude/hooks
cp /path/to/memory-system/hooks/*.py ~/.claude/hooks/

# 或复制简单版脚本
cp /path/to/memory-system/hooks/*.sh ~/.claude/hooks/
chmod +x ~/.claude/hooks/*.sh
```

**Windows:**
```powershell
# 复制脚本
mkdir -Force "$env:USERPROFILE\.claude\hooks"
Copy-Item "C:\path\to\memory-system\hooks\*.py" "$env:USERPROFILE\.claude\hooks\"
Copy-Item "C:\path\to\memory-system\hooks\*.ps1" "$env:USERPROFILE\.claude\hooks\"
```

### hooks.json 配置

**完整版配置（推荐）** - 编辑 `~/.claude/hooks/hooks.json`：
```json
{
  "hooks": {
    "SessionStart": {
      "command": "python3 /Users/{用户名}/.claude/hooks/session_start_context.py"
    },
    "Stop": {
      "command": "python3 /Users/{用户名}/.claude/hooks/auto_save_memory.py"
    }
  }
}
```

**简单版配置** - 编辑 `~/.claude/hooks/hooks.json`：
```json
{
  "hooks": {
    "SessionStart": {
      "command": "/Users/{用户名}/.claude/hooks/session-start.sh"
    },
    "SessionEnd": {
      "command": "/Users/{用户名}/.claude/hooks/session-end.sh"
    }
  }
}
```

> **注意**：
> - 请将 `{用户名}` 替换为实际的用户名
> - 完整版需要已安装 memory_system 模块（`pip install -e .`）
> - 可通过环境变量 `MEMORY_DATA_PATH` 指定数据目录

---

## 🔑 API Key 配置

Memory System 支持多种 LLM 后端，用于 AI 增强功能：

### 智谱 AI（推荐，国内用户）

**Mac/Linux** - 添加到 `~/.zshrc` 或 `~/.bashrc`：
```bash
export ZHIPU_API_KEY="your_zhipu_api_key"
```

**Windows** - 以管理员身份运行 PowerShell：
```powershell
setx ZHIPU_API_KEY "your_zhipu_api_key" /M
```

### OpenAI

**Mac/Linux**：
```bash
export OPENAI_API_KEY="your_openai_api_key"
```

**Windows**：
```powershell
setx OPENAI_API_KEY "your_openai_api_key" /M
```

### 配置文件设置

首次运行会自动创建 `~/.memory-system/memory_config.yaml`：

```yaml
# 存储配置
storage:
  path: ~/.memory-system

# 向量搜索配置
vector:
  enabled: true
  provider: chroma
  embedding:
    provider: zhipu
    model: embedding-3

# AI 增强功能
ai:
  enabled: true
  llm:
    provider: zhipu
    model: GLM-5

# 技能系统
skill_system:
  matching:
    max_skills_per_session: 3
  learning:
    auto_learn: true
  evolution:
    enabled: true
    interval_minutes: 60
```

---

## 🔄 守护进程配置

守护进程会定时执行技能质量评估和记忆优化。

### macOS (launchd)

```bash
# 加载服务
launchctl load ~/Library/LaunchAgents/com.memory-system.daemon.plist

# 查看状态
launchctl list | grep memory-system

# 停止服务
launchctl unload ~/Library/LaunchAgents/com.memory-system.daemon.plist

# 查看日志
tail -f ~/.memory-system/logs/daemon.log
```

### Linux (systemd)

```bash
# 启用并启动
systemctl --user enable memory-system-daemon
systemctl --user start memory-system-daemon

# 查看状态
systemctl --user status memory-system-daemon

# 查看日志
journalctl --user -u memory-system-daemon -f
```

### Windows (任务计划程序)

```powershell
# 查看任务状态
Get-ScheduledTask -TaskName "MemorySystem-Daemon"

# 手动运行
Start-ScheduledTask -TaskName "MemorySystem-Daemon"

# 禁用任务
Disable-ScheduledTask -TaskName "MemorySystem-Daemon"
```

### 手动运行

```bash
# 执行一次
memory-system-daemon --once --storage ~/.memory-system

# 持续运行（每小时）
memory-system-daemon --interval 60 --storage ~/.memory-system
```

---

## 🛠️ MCP 工具列表

Memory System 提供以下 MCP 工具：

### 记忆管理

| 工具 | 描述 |
|------|------|
| `memory_save` | 保存对话到记忆 |
| `memory_recall` | 召回历史记忆 |
| `memory_recall_by_id` | 通过ID精确召回记忆 |
| `memory_recall_summary` | 摘要格式召回记忆 |
| `memory_search` | 搜索记忆内容 |
| `memory_search_summary` | 摘要格式搜索记忆 |
| `memory_get_quick_response` | 获取快速响应 |
| `memory_get_strategy` | 获取推荐策略 |
| `memory_set_shared` | 设置共享记忆 |
| `memory_optimize` | 执行记忆优化 |
| `memory_optimization_status` | 获取优化状态 |

### 多人格

| 工具 | 描述 |
|------|------|
| `persona_list` | 列出所有人格 |
| `persona_switch` | 切换人格 |
| `persona_create` | 创建新人格 |
| `persona_delete` | 删除人格 |
| `persona_set_memory` | 设置人格记忆 |
| `persona_get_context` | 获取人格上下文 |

### 学习系统

| 工具 | 描述 |
|------|------|
| `learning_recommend` | 获取知识推荐 |
| `learning_feedback_submit` | 提交学习反馈 |
| `learning_reflect` | 触发反思学习 |
| `learning_status` | 获取学习状态 |

### 技能系统

| 工具 | 描述 |
|------|------|
| `skill_create` | 创建新技能 |
| `skill_list` | 列出所有技能 |
| `skill_get` | 获取技能详情 |
| `skill_match` | 匹配相关技能 |
| `skill_update_quality` | 更新技能质量 |

### 风格学习

| 工具 | 描述 |
|------|------|
| `style_learn_article` | 学习文章风格 |
| `style_get_techniques` | 获取写作技巧 |
| `style_get_suggestions` | 获取写作建议 |
| `style_record_application` | 记录技巧应用 |
| `style_record_review` | 记录复习结果 |
| `style_get_review_list` | 获取待复习列表 |
| `style_get_stats` | 获取学习统计 |
| `style_apply_decay` | 触发记忆衰减 |

### 会话管理

| 工具 | 描述 |
|------|------|
| `session_close` | 关闭会话并保存 |
| `session_restore` | 恢复上次会话 |

---

## 📁 目录结构

```
~/.memory-system/
├── memory/                    # 记忆数据
│   ├── conversations/         # 对话记录
│   ├── personas/              # 人格数据
│   └── learning_memory.yaml   # 学习记忆
├── skills/                    # 技能系统
│   ├── skill_index.yaml       # 技能索引
│   └── {skill_id}/            # 技能目录
│       └── SKILL.md           # 技能文件（Agent Skills 格式）
├── vectors/                   # 向量数据库
├── evolution/                 # 演化数据
│   ├── evolution_state.yaml   # 演化状态
│   └── iterations_*.yaml      # 迭代记录
├── logs/                      # 日志文件
│   ├── daemon.log             # 守护进程日志
│   ├── session-start.log      # 会话开始日志
│   └── session-end.log        # 会话结束日志
└── memory_config.yaml         # 配置文件
```

---

## 🔧 高级配置

### 使用不同的 LLM 后端

编辑 `~/.memory-system/memory_config.yaml`：

```yaml
ai:
  llm:
    provider: openai  # 可选: zhipu, openai, anthropic, ollama
    model: gpt-4
    temperature: 0.3
    max_tokens: 500
```

### 禁用向量搜索

```yaml
vector:
  enabled: false
```

### 调整技能匹配参数

```yaml
skill_system:
  matching:
    max_skills_per_session: 5    # 每次最多加载 5 个技能
    min_match_score: 0.5         # 最低匹配分数
  learning:
    auto_learn: false            # 关闭自动学习
```

---

## 🧪 开发

### 从源码安装

```bash
# 克隆仓库
git clone https://github.com/ab123-ch/memory-system.git
cd memory-system/memory-system

# 安装依赖
pip install -e .

# 或使用 uv
uv sync
```

### 运行测试

```bash
# 安装开发依赖
pip install -e ".[dev]"

# 运行测试
pytest tests/ -v

# 运行覆盖率测试
pytest tests/ --cov=memory_system --cov-report=html
```

---

## 📝 更新日志

### v2.0.0 (2026-03-03)

- ✨ 新增技能驱动自我进化系统
- ✨ 支持 Agent Skills 标准格式
- ✨ LLM 驱动的经验判断
- ✨ 动态技能创建
- ✨ 演化守护服务
- 🔧 重构为分层架构
- 📝 完善文档和安装脚本

### v1.0.0

- 🎉 初始版本
- ✨ 基础记忆功能
- ✨ 多人格支持
- ✨ 向量搜索
- ✨ AI 增强

---

## 🤝 贡献

欢迎贡献代码！请查看 [CONTRIBUTING.md](CONTRIBUTING.md) 了解详情。

---

## 📄 许可证

[MIT License](LICENSE)

---

## 🙏 致谢

- [MCP](https://modelcontextprotocol.io/) - Model Context Protocol
- [Claude Code](https://claude.ai/code) - Anthropic 的 AI 编程工具
- [ChromaDB](https://www.trychroma.com/) - 向量数据库
- [智谱 AI](https://www.zhipuai.cn/) - GLM 模型