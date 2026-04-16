#!/bin/bash
# =============================================================================
# Memory System - Session End Hook
# =============================================================================
# 在 Claude Code 会话结束时自动保存对话并触发记忆优化
#
# 安装位置: ~/.claude/hooks/session-end.sh
# 配置文件: ~/.claude/hooks/hooks.json
# =============================================================================

MEMORY_DIR="${MEMORY_DIR:-$HOME/.memory-system}"
LOG_FILE="$MEMORY_DIR/logs/session-end.log"

# 确保日志目录存在
mkdir -p "$(dirname "$LOG_FILE")"

# 记录会话结束
echo "$(date '+%Y-%m-%d %H:%M:%S'): Session ended" >> "$LOG_FILE"

# 触发记忆优化（如果守护进程可用）
if command -v memory-system-daemon &> /dev/null; then
    echo "$(date '+%Y-%m-%d %H:%M:%S'): Triggering memory optimization..." >> "$LOG_FILE"
    memory-system-daemon --once --storage "$MEMORY_DIR" 2>&1 >> "$LOG_FILE" || true
    echo "$(date '+%Y-%m-%d %H:%M:%S'): Memory optimization completed" >> "$LOG_FILE"
fi
