#!/bin/bash
#
# Memory System MCP 打包脚本
# 将当前代码打包为可分发的压缩包
#
# 用法: ./build-package.sh [版本号]
#   ./build-package.sh          # 使用 pyproject.toml 中的版本
#   ./build-package.sh 2.1.0    # 指定版本号
#

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_NAME="memory-system-mcp"
DEFAULT_INSTALL_DIR="$HOME/.claude/mcp/memory-system"

# 获取版本号
if [ -n "$1" ]; then
    VERSION="$1"
else
    VERSION=$(grep -E '^version = "' "$SCRIPT_DIR/pyproject.toml" | sed 's/version = "//;s/"$//' || echo "2.0.0")
fi

PACKAGE_NAME="${PROJECT_NAME}-${VERSION}"
BUILD_DIR="$SCRIPT_DIR/dist"
PACKAGE_DIR="$BUILD_DIR/$PACKAGE_NAME"

# 颜色
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }

echo "=========================================="
echo "  Memory System MCP 打包工具"
echo "  版本: $VERSION"
echo "=========================================="

# 清理旧的构建目录
rm -rf "$BUILD_DIR"
mkdir -p "$PACKAGE_DIR"

log_info "复制源码文件..."

# 1. 复制核心模块
cp -r "$SCRIPT_DIR/memory_system" "$PACKAGE_DIR/"
find "$PACKAGE_DIR/memory_system" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

# 2. 复制 hooks 脚本（排除备份和测试文件）
mkdir -p "$PACKAGE_DIR/hooks"
for f in session_start_context.py auto_save_memory.py session_summary.py \
         experience_learning.py session-close_hook.py \
         session-start.sh session-end.sh session-start.ps1 session-end.ps1; do
    cp "$SCRIPT_DIR/hooks/$f" "$PACKAGE_DIR/hooks/" 2>/dev/null || true
done
chmod +x "$PACKAGE_DIR/hooks/"*.sh 2>/dev/null || true

# 3. 复制项目配置
cp "$SCRIPT_DIR/pyproject.toml" "$PACKAGE_DIR/"
cp "$SCRIPT_DIR/README.md" "$PACKAGE_DIR/"

# 4. 复制根目录的 Python 文件
cp "$SCRIPT_DIR/memory_mcp_server.py" "$PACKAGE_DIR/" 2>/dev/null || true
cp "$SCRIPT_DIR/memory_mcp_server_lite.py" "$PACKAGE_DIR/" 2>/dev/null || true

# 5. 复制配置模板（不含私钥）
# memory_config 模板
cp "$SCRIPT_DIR/memory_config.yaml" "$PACKAGE_DIR/memory_config.yaml.template"

# model_config 模板（如果有 .template 文件就用，否则创建空白）
if [ -f "$SCRIPT_DIR/model_config.yaml.template" ]; then
    cp "$SCRIPT_DIR/model_config.yaml.template" "$PACKAGE_DIR/"
else
    cat > "$PACKAGE_DIR/model_config.yaml.template" << 'EOF'
# 模型配置文件
# Model Configuration for Memory System

llm:
  provider: zhipu  # zhipu, openai, anthropic, ollama, mock
  model: glm-4-flash
  api_key: ""  # 填入你的 API Key，或通过环境变量设置
  base_url: ""
  temperature: 0.3
  max_tokens: 500

embedding:
  provider: zhipu
  model: embedding-3
  api_key: ""
  base_url: ""
  dimensions: 1024

fallback:
  llm_provider: mock
  embedding_provider: mock
EOF
fi

# 6. 清理模板中的敏感信息（确保安全）
# 替换 memory_config 中的路径为通用路径
sed -i 's|./data|~/.claude/mcp/memory-system/data|g' "$PACKAGE_DIR/memory_config.yaml.template" 2>/dev/null || \
    sed -i '' 's|./data|~/.claude/mcp/memory-system/data|g' "$PACKAGE_DIR/memory_config.yaml.template"

log_info "复制安装脚本..."

# 直接复制已有的 install.sh
cp "$SCRIPT_DIR/install.sh" "$PACKAGE_DIR/"
chmod +x "$PACKAGE_DIR/install.sh"

log_info "创建压缩包..."
cd "$BUILD_DIR"
tar -czf "${PACKAGE_NAME}.tar.gz" "$PACKAGE_NAME"

log_success "打包完成: $BUILD_DIR/${PACKAGE_NAME}.tar.gz"

echo ""
echo "包内容:"
tar -tzf "${PACKAGE_NAME}.tar.gz" | head -20

echo ""
echo "=========================================="
log_success "分发文件: $BUILD_DIR/${PACKAGE_NAME}.tar.gz"
echo "=========================================="
echo ""
echo "用户使用:"
echo "  tar -xzf ${PACKAGE_NAME}.tar.gz"
echo "  cd ${PACKAGE_NAME} && ./install.sh"