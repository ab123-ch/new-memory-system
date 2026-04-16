#!/bin/bash
# =============================================================================
# Memory System - Session Start Hook
# =============================================================================
# 在 Claude Code 会话开始时自动恢复记忆上下文
#
# 安装位置: ~/.claude/hooks/session-start.sh
# 配置文件: ~/.claude/hooks/hooks.json
# =============================================================================

MEMORY_DIR="${MEMORY_DIR:-$HOME/.memory-system}"
LOG_FILE="$MEMORY_DIR/logs/session-start.log"

# 确保日志目录存在
mkdir -p "$(dirname "$LOG_FILE")"

# 记录会话开始
echo "$(date '+%Y-%m-%d %H:%M:%S'): Session started" >> "$LOG_FILE"

# 可选：输出提示信息
# echo "[Memory System] Session context loaded from $MEMORY_DIR"
