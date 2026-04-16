"""OpenCode 执行器连接池

管理多个执行器实例，支持按模型区分
"""

import logging
from typing import Optional

from .config import OpenCodeConfig
from .executor import OpenCodeExecutor

logger = logging.getLogger(__name__)


class OpenCodePool:
    """
    执行器连接池

    按模型管理执行器实例，避免重复创建

    Example:
        >>> pool = OpenCodePool(OpenCodeConfig())
        >>> executor = pool.get_executor("glm-4.7")
        >>> result = await executor.execute("任务")
    """

    _instance: Optional["OpenCodePool"] = None
    _executors: dict[str, OpenCodeExecutor]
    _initialized: bool  # 初始化标志

    def __new__(cls, config: Optional[OpenCodeConfig] = None) -> "OpenCodePool":
        """
        单例模式

        Args:
            config: 配置对象

        Returns:
            OpenCodePool 实例
        """
        if cls._instance is None:
            instance = super().__new__(cls)
            instance._initialized = False  # 初始化标志
            cls._instance = instance
        return cls._instance

    def __init__(self, config: Optional[OpenCodeConfig] = None):
        """
        初始化连接池

        Args:
            config: 配置对象，仅首次创建时使用
        """
        # 使用 _initialized 标志避免重复初始化
        if self._initialized:
            return

        self._executors = {}
        self._config = config or OpenCodeConfig()
        self._initialized = True
        logger.info("[OpenCodePool] 初始化连接池")

    def get_executor(
        self,
        model: Optional[str] = None,
        config: Optional[OpenCodeConfig] = None
    ) -> OpenCodeExecutor:
        """
        获取执行器

        如果对应模型的执行器不存在，则创建新实例

        Args:
            model: 模型名称，为空则使用默认模型
            config: 自定义配置，为空则使用池配置

        Returns:
            OpenCodeExecutor 实例

        Example:
            >>> executor = pool.get_executor("glm-5")
        """
        mdl = model or self._config.model
        cfg = config or self._config

        if mdl not in self._executors:
            # 创建新的执行器配置
            executor_cfg = OpenCodeConfig(
                model=mdl,
                timeout=cfg.timeout,
                max_retries=cfg.max_retries,
                models=cfg.models,
                working_dir=cfg.working_dir,
                compaction_threshold=cfg.compaction_threshold,
                warning_tokens=cfg.warning_tokens
            )
            self._executors[mdl] = OpenCodeExecutor(executor_cfg)
            logger.info(f"[OpenCodePool] 创建新执行器: model={mdl}")

        return self._executors[mdl]

    def clear(self) -> None:
        """
        清空连接池

        清除所有缓存的执行器实例
        """
        self._executors.clear()
        logger.info("[OpenCodePool] 连接池已清空")

    def list_models(self) -> list[str]:
        """
        列出已缓存的模型

        Returns:
            模型名称列表
        """
        return list(self._executors.keys())

    @classmethod
    def reset(cls) -> None:
        """
        重置单例

        用于测试场景
        """
        if cls._instance is not None:
            cls._instance._executors.clear()
            cls._instance = None
            logger.info("[OpenCodePool] 单例已重置")
