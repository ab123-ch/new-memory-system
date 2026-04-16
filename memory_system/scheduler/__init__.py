"""
场景调度模块

负责场景识别和模式调度，根据用户输入自动识别当前场景，
并返回相应的模式配置。
"""

from .detector import ModeDetector, DetectionResult
from .dispatcher import ModeDispatcher, ModeConfig

__all__ = [
    "ModeDetector",
    "DetectionResult",
    "ModeDispatcher",
    "ModeConfig",
]
