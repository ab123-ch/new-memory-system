#!/bin/bash
#
# Memory System MCP 安装/升级脚本
#
# 用法:
#   ./install.sh           # 自动检测：已配置则升级，未配置则全新安装
#   ./install.sh /path     # 指定安装路径（全新安装）
#

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEFAULT_INSTALL_DIR="$HOME/.claude/mcp/memory-system"
SETTINGS_FILE="$HOME/.claude/settings.json"
HOOKS_DIR="$HOME/.claude/hooks"

# 颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# 从 settings.json 获取 MCP cwd
get_mcp_cwd() {
    if [ -f "$SETTINGS_FILE" ]; then
        python3 -c "
import json
try:
    with open('$SETTINGS_FILE') as f:
        cfg = json.load(f)
    print(cfg.get('mcpServers', {}).get('memory-system', {}).get('cwd', ''))
except: pass
" 2>/dev/null
    fi
}

# 检测安装模式
detect_mode() {
    USER_PATH="$1"
    if [ -n "$USER_PATH" ]; then
        INSTALL_DIR="$USER_PATH"
        MODE="install"
        log_info "指定路径安装: $INSTALL_DIR"
        return
    fi

    EXISTING=$(get_mcp_cwd)
    if [ -n "$EXISTING" ] && [ -d "$EXISTING" ]; then
        INSTALL_DIR="$EXISTING"
        MODE="upgrade"
        log_success "检测到已安装 MCP: $INSTALL_DIR"
        log_info "升级模式"
    else
        INSTALL_DIR="$DEFAULT_INSTALL_DIR"
        MODE="install"
        log_info "全新安装: $INSTALL_DIR"
    fi
}

# 检查 Python
check_python() {
    if ! command -v python3 &> /dev/null; then
        log_error "需要 Python 3.10+"
        exit 1
    fi
    log_success "Python: $(python3 --version 2>&1 | awk '{print $2}')"
}

# 检查 uv
check_uv() {
    command -v uv &> /dev/null
}

# 备份
backup_data() {
    if [ "$MODE" != "upgrade" ]; then return; fi

    BACKUP="$INSTALL_DIR/backups/$(date +%Y%m%d_%H%M%S)"
    mkdir -p "$BACKUP"

    log_info "备份数据..."
    [ -d "$INSTALL_DIR/data" ] && cp -r "$INSTALL_DIR/data" "$BACKUP/"
    [ -f "$INSTALL_DIR/memory_config.yaml" ] && cp "$INSTALL_DIR/memory_config.yaml" "$BACKUP/"
    [ -f "$INSTALL_DIR/model_config.yaml" ] && cp "$INSTALL_DIR/model_config.yaml" "$BACKUP/"
    log_success "备份: $BACKUP"
}

# 安装
do_install() {
    mkdir -p "$INSTALL_DIR/data"/{memory,logs,vectors,personas,experiences}

    log_info "复制源码..."
    cp -r "$SCRIPT_DIR/memory_system" "$INSTALL_DIR/"
    cp "$SCRIPT_DIR/pyproject.toml" "$INSTALL_DIR/README.md" "$INSTALL_DIR/"
    [ -f "$SCRIPT_DIR/memory_mcp_server_lite.py" ] && cp "$SCRIPT_DIR/memory_mcp_server_lite.py" "$INSTALL_DIR/"
    find "$INSTALL_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

    # 配置文件
    if [ "$MODE" = "install" ] || [ ! -f "$INSTALL_DIR/memory_config.yaml" ]; then
        log_info "创建配置..."
        sed "s|~/.claude/mcp/memory-system|$INSTALL_DIR|g" "$SCRIPT_DIR/memory_config.yaml.template" > "$INSTALL_DIR/memory_config.yaml"
        cp "$SCRIPT_DIR/model_config.yaml.template" "$INSTALL_DIR/model_config.yaml"
    else
        log_warn "保留现有配置"
    fi

    log_info "安装依赖..."
    cd "$INSTALL_DIR"
    if check_uv; then
        uv venv .venv --python python3 --quiet
        source .venv/bin/activate
        uv pip install -e . --quiet
    else
        python3 -m venv .venv
        source .venv/bin/activate
        pip install -q -e .
    fi
    log_success "依赖安装完成"
}

# 配置 MCP
setup_mcp() {
    log_info "更新 MCP 配置..."

    mkdir -p "$HOME/.claude"

    python3 -c "
import json, os

file = '$SETTINGS_FILE'
data = {}

if os.path.exists(file):
    with open(file) as f:
        data = json.load(f)

data.setdefault('mcpServers', {})
data['mcpServers']['memory-system'] = {
    'command': '$INSTALL_DIR/.venv/bin/python',
    'args': ['$INSTALL_DIR/memory_mcp_server_lite.py'],
    'env': {'PYTHONPATH': '$INSTALL_DIR'},
    'cwd': '$INSTALL_DIR'
}

# 更新 hooks
data['hooks'] = {
    'SessionStart': [{'hooks': [{'type': 'command', 'command': '$INSTALL_DIR/.venv/bin/python $HOOKS_DIR/session_start_context.py', 'timeout': 15}]}],
    'Stop': [{'hooks': [{'type': 'command', 'command': '$INSTALL_DIR/.venv/bin/python $HOOKS_DIR/auto_save_memory.py', 'timeout': 30}]}]
}

with open(file, 'w') as f:
    json.dump(data, f, indent=2)

print('已更新 settings.json')
"

    # 复制 hooks
    mkdir -p "$HOOKS_DIR"
    cp "$SCRIPT_DIR/hooks/"*.py "$HOOKS_DIR/" 2>/dev/null || true
    cp "$SCRIPT_DIR/hooks/"*.sh "$HOOKS_DIR/" 2>/dev/null || true
    chmod +x "$HOOKS_DIR/"*.sh 2>/dev/null || true

    log_success "MCP 配置完成"
}

# 完成
show_done() {
    echo ""
    echo "=========================================="
    echo "  $MODE 完成!"
    echo "=========================================="
    echo ""
    echo "目录: $INSTALL_DIR"
    echo "配置: $INSTALL_DIR/memory_config.yaml"
    echo ""
    echo "API Key 配置:"
    echo "  export ZHIPU_API_KEY=\"your_key\""
    echo ""
    echo "重启 Claude Code 后使用 memory_recall 测试"
    echo ""
}

# 主流程
echo ""
echo "=========================================="
echo "  Memory System MCP 安装程序"
echo "=========================================="
echo ""

check_python
detect_mode "$@"
backup_data
do_install
setup_mcp
show_done