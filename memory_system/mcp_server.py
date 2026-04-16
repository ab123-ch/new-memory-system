"""
Memory System MCP Server Entry Point

用于 pip/uvx 安装后的入口点
"""

import asyncio
import sys
from pathlib import Path

# 确保当前目录在路径中
sys.path.insert(0, str(Path(__file__).parent.parent))

from memory_mcp_server import main

if __name__ == "__main__":
    asyncio.run(main())
