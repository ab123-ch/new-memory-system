# =============================================================================
# Memory System - Session End Hook (Windows)
# =============================================================================
# 在 Claude Code 会话结束时自动保存对话并触发记忆优化
#
# 安装位置: %USERPROFILE%\.claude\hooks\session-end.ps1
# 配置文件: %USERPROFILE%\.claude\hooks\hooks.json
# =============================================================================

$env:MEMORY_DIR = if ($env:MEMORY_DIR) { $env:MEMORY_DIR } else { Join-Path $env:USERPROFILE ".memory-system" }
$logFile = Join-Path $env:MEMORY_DIR "logs\session-end.log"

# 确保日志目录存在
$logDir = Split-Path $logFile -Parent
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}

# 记录会话结束
$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -Path $logFile -Value "$timestamp`: Session ended"

# 触发记忆优化（如果守护进程可用）
$daemon = Get-Command memory-system-daemon -ErrorAction SilentlyContinue
if ($daemon) {
    Add-Content -Path $logFile -Value "$timestamp`: Triggering memory optimization..."
    try {
        & memory-system-daemon --once --storage $env:MEMORY_DIR 2>&1 | Add-Content -Path $logFile
        Add-Content -Path $logFile -Value "$timestamp`: Memory optimization completed"
    } catch {
        Add-Content -Path $logFile -Value "$timestamp`: Memory optimization failed: $_"
    }
}

Write-Host "[Memory System] Session ended"
