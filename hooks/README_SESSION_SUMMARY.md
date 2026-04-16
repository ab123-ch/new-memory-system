# 会话总结 Hook 配置说明

## 功能概述

`session_summary.py` 是一个在会话结束时触发的 Hook，用于：

1. 读取本次会话的所有对话内容
2. 使用 LLM 进行多维度分析总结
3. 保存经验到对应人格目录下的 `experiences/` 文件夹

## 总结维度

- **问题处理**：遇到的问题及解决方案
- **文件与工程**：涉及的文件路径和工程结构
- **知识获取**：新学到的知识或信息
- **用户反馈**：用户指出的问题或偏好
- **重要决策**：关键的决策和方案选择
- **待办事项**：未完成的任务和后续跟进

## 配置方法

在 `~/.claude/settings.json` 中添加 Hook 配置：

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "/Users/chenh/.claude/mcp/memory-system/.venv/bin/python /Users/chenh/.claude/mcp/memory-system/hooks/auto_save_memory.py",
            "timeout": 30
          },
          {
            "type": "command",
            "command": "/Users/chenh/.claude/mcp/memory-system/.venv/bin/python /Users/chenh/.claude/mcp/memory-system/hooks/session_summary.py",
            "timeout": 60
          }
        ]
      }
    ]
  }
}
```

## 存储结构

```
data/memory/
├── personas/
│   ├── memory_optimizer/
│   │   ├── experiences/
│   │   │   ├── 2026-03-24_143052_abcd1234.md
│   │   │   └── ...
│   │   └── persona.yaml
│   ├── plot_creator/
│   │   ├── experiences/
│   │   │   └── ...
│   │   └── persona.yaml
│   └── ...
└── shared.yaml
```

## 触发条件

- 对话轮数 >= 3 轮时才会生成总结
- 每轮对话结束时会检查是否满足条件

## 经验文件格式

```markdown
# 会话经验总结

> **日期**: 2026-03-24
> **时间**: 14:30:52
> **对话轮数**: 5
> **人格**: memory_optimizer

---

### 1. 问题处理
- 遇到经验模块被删除的问题，需要重新设计
- 使用 hook 机制实现会话总结

### 2. 文件与工程
- 经验存储路径: data/memory/personas/{persona_id}/experiences/
- Hook 路径: hooks/session_summary.py

...

---

*此经验由 session_summary hook 自动生成*
```

## 会话启动时加载

`session_start_context.py` 已更新，会自动加载人格的最近 5 条经验总结，并在上下文中显示：

```
【会话经验】
1. 解决经验模块重构问题
   日期: 2026-03-24
   遇到经验模块被删除的问题，需要重新设计经验系统...

2. ...
```

## 依赖

- LLM 服务：需要正确配置 LLM API（在 `model_config.yaml` 或环境变量中配置）
- 日志系统：使用 `memory_system.logging_config`
