"""
上下文组装模块

负责将记忆、人格信息、模式知识等组装成完整的上下文，
并控制 Token 容量，实现智能压缩。
"""

from .assembler import ContextAssembler, AssembledContext
from .capacity_controller import CapacityController, CompressionResult

__all__ = [
    "ContextAssembler",
    "AssembledContext",
    "CapacityController",
    "CompressionResult",
]
