# =============================================================================
# Memory System - Session Start Hook (Windows)
# =============================================================================
# 在 Claude Code 会话开始时自动恢复记忆上下文
#
# 安装位置: %USERPROFILE%\.claude\hooks\session-start.ps1
# 配置文件: %USERPROFILE%\.claude\hooks\hooks.json
# =============================================================================

$env:MEMORY_DIR = if ($env:MEMORY_DIR) { $env:MEMORY_DIR } else { Join-Path $env:USERPROFILE ".memory-system" }
$logFile = Join-Path $env:MEMORY_DIR "logs\session-start.log"

# 确保日志目录存在
$logDir = Split-Path $logFile -Parent
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}

# 记录会话开始
$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -Path $logFile -Value "$timestamp`: Session started"

# 可选：输出提示信息
# Write-Host "[Memory System] Session context loaded from $env:MEMORY_DIR"
