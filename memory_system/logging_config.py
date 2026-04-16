"""
统一日志配置模块 - Centralized Logging Configuration

提供统一的日志管理接口，所有模块使用相同的日志配置。

目录结构：
  logs/
  ├── mcp/                     # MCP Server 日志
  │   ├── mcp.log
  │   └── mcp-error.log
  ├── hooks/                   # 钩子日志
  │   ├── session_start.log
  │   └── auto_save.log
  ├── evolution/               # 技能演化日志
  │   ├── evolution.log
  │   └── evolution-error.log
  ├── memory_save/             # 记忆保存日志
  │   └── 2026-03-12/          # 按日期
  │       └── session.json     # 结构化日志
  └── experience/              # 经验管理日志
      └── experience.log
"""

import logging
import logging.handlers
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional, Any
from dataclasses import dataclass, field
import yaml
import json


@dataclass
class LoggingConfig:
    """日志配置"""
    base_dir: Path = field(default_factory=lambda: Path.home() / ".memory-system" / "logs")
    level: int = logging.INFO
    max_bytes: int = 10 * 1024 * 1024  # 10MB
    backup_count: int = 5
    retention_days: int = 30
    cleanup_enabled: bool = True

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LoggingConfig":
        """从字典创建配置"""
        base_dir = data.get("base_dir", "~/.memory-system/logs")
        return cls(
            base_dir=Path(os.path.expanduser(base_dir)),
            level=getattr(logging, data.get("level", "INFO").upper()),
            max_bytes=data.get("rotation", {}).get("max_bytes", 10 * 1024 * 1024),
            backup_count=data.get("rotation", {}).get("backup_count", 5),
            retention_days=data.get("cleanup", {}).get("retention_days", 30),
            cleanup_enabled=data.get("cleanup", {}).get("enabled", True),
        )


# 日志类别定义
LOG_CATEGORIES = {
    "mcp": {
        "description": "MCP Server 日志",
        "files": ["mcp.log", "mcp-error.log"],
    },
    "hooks": {
        "description": "钩子日志",
        "files": ["session_start.log", "auto_save.log"],
    },
    "evolution": {
        "description": "技能演化日志",
        "files": ["evolution.log", "evolution-error.log"],
    },
    "memory_save": {
        "description": "记忆保存日志",
        "files": ["memory_save.log"],
    },
    "experience": {
        "description": "经验管理日志",
        "files": ["experience.log"],
    },
}


class UnifiedLogger:
    """统一日志管理器"""

    _instance: Optional["UnifiedLogger"] = None
    _config: Optional[LoggingConfig] = None
    _loggers: Dict[str, logging.Logger] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._config is None:
            self._config = LoggingConfig()

    @classmethod
    def initialize(cls, config: Optional[Dict[str, Any]] = None, config_path: Optional[str] = None):
        """
        初始化日志系统

        Args:
            config: 配置字典
            config_path: 配置文件路径
        """
        instance = cls()

        if config_path and Path(config_path).exists():
            with open(config_path, "r", encoding="utf-8") as f:
                yaml_config = yaml.safe_load(f) or {}
                logging_config = yaml_config.get("logging", {})
                if logging_config:
                    instance._config = LoggingConfig.from_dict(logging_config)
        elif config:
            instance._config = LoggingConfig.from_dict(config)

        # 确保基础目录存在
        instance._config.base_dir.mkdir(parents=True, exist_ok=True)

        # 为每个类别创建目录
        for category in LOG_CATEGORIES:
            category_dir = instance._config.base_dir / category
            category_dir.mkdir(parents=True, exist_ok=True)

        return instance

    def get_logger(
        self,
        name: str,
        category: str = "mcp",
        level: Optional[int] = None
    ) -> logging.Logger:
        """
        获取日志记录器

        Args:
            name: 日志器名称（通常使用 __name__）
            category: 日志类别 (mcp/hooks/evolution/memory_save/experience)
            level: 日志级别，默认使用配置的级别

        Returns:
            配置好的 Logger 实例
        """
        logger_key = f"{category}:{name}"

        if logger_key in self._loggers:
            return self._loggers[logger_key]

        # 创建 logger
        logger = logging.getLogger(f"{category}.{name}")
        logger.setLevel(level or self._config.level)

        # 清除已有的处理器（避免重复）
        logger.handlers = []
        logger.propagate = False

        # 获取类别目录并确保存在
        category_dir = self._config.base_dir / category
        category_dir.mkdir(parents=True, exist_ok=True)

        # 添加主日志文件处理器
        main_log_file = category_dir / f"{category}.log"
        file_handler = logging.handlers.RotatingFileHandler(
            main_log_file,
            maxBytes=self._config.max_bytes,
            backupCount=self._config.backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

        # 添加错误日志文件处理器
        error_log_file = category_dir / f"{category}-error.log"
        error_handler = logging.handlers.RotatingFileHandler(
            error_log_file,
            maxBytes=self._config.max_bytes,
            backupCount=self._config.backup_count,
            encoding="utf-8",
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(file_formatter)
        logger.addHandler(error_handler)

        # 缓存
        self._loggers[logger_key] = logger

        return logger

    def cleanup_old_logs(self, days: Optional[int] = None):
        """
        清理过期日志

        Args:
            days: 保留天数，默认使用配置的天数
        """
        if not self._config.cleanup_enabled:
            return

        retention_days = days or self._config.retention_days
        cutoff_date = datetime.now() - timedelta(days=retention_days)

        for category in LOG_CATEGORIES:
            category_dir = self._config.base_dir / category
            if not category_dir.exists():
                continue

            for log_file in category_dir.rglob("*.log*"):
                try:
                    # 检查文件修改时间
                    mtime = datetime.fromtimestamp(log_file.stat().st_mtime)
                    if mtime < cutoff_date:
                        log_file.unlink()
                except Exception as e:
                    logging.warning(f"清理日志文件失败 {log_file}: {e}")

    def get_log_path(self, category: str, filename: Optional[str] = None) -> Path:
        """
        获取日志文件路径

        Args:
            category: 日志类别
            filename: 文件名，默认为 {category}.log

        Returns:
            日志文件路径
        """
        category_dir = self._config.base_dir / category
        filename = filename or f"{category}.log"
        return category_dir / filename

    def get_stats(self) -> Dict[str, Any]:
        """获取日志统计信息"""
        stats = {
            "base_dir": str(self._config.base_dir),
            "level": logging.getLevelName(self._config.level),
            "categories": {},
            "total_size": 0,
        }

        for category in LOG_CATEGORIES:
            category_dir = self._config.base_dir / category
            category_stats = {
                "exists": category_dir.exists(),
                "files": [],
                "total_size": 0,
            }

            if category_dir.exists():
                for log_file in category_dir.glob("*.log*"):
                    size = log_file.stat().st_size
                    category_stats["files"].append({
                        "name": log_file.name,
                        "size": size,
                    })
                    category_stats["total_size"] += size

            stats["categories"][category] = category_stats
            stats["total_size"] += category_stats["total_size"]

        return stats


# 全局实例
_unified_logger: Optional[UnifiedLogger] = None


def init_logging(config: Optional[Dict[str, Any]] = None, config_path: Optional[str] = None) -> UnifiedLogger:
    """
    初始化统一日志系统

    Args:
        config: 配置字典
        config_path: 配置文件路径

    Returns:
        UnifiedLogger 实例
    """
    global _unified_logger
    _unified_logger = UnifiedLogger.initialize(config, config_path)
    return _unified_logger


def get_logger(name: str, category: str = "mcp") -> logging.Logger:
    """
    获取日志记录器（便捷函数）

    Args:
        name: 日志器名称（通常使用 __name__）
        category: 日志类别 (mcp/hooks/evolution/memory_save/experience)

    Returns:
        配置好的 Logger 实例
    """
    global _unified_logger

    if _unified_logger is None:
        _unified_logger = UnifiedLogger()

    return _unified_logger.get_logger(name, category)


def get_log_path(category: str, filename: Optional[str] = None) -> Path:
    """
    获取日志文件路径

    Args:
        category: 日志类别
        filename: 文件名

    Returns:
        日志文件路径
    """
    global _unified_logger

    if _unified_logger is None:
        _unified_logger = UnifiedLogger()

    return _unified_logger.get_log_path(category, filename)


def cleanup_logs(days: Optional[int] = None):
    """
    清理过期日志

    Args:
        days: 保留天数
    """
    global _unified_logger

    if _unified_logger is None:
        _unified_logger = UnifiedLogger()

    _unified_logger.cleanup_old_logs(days)


def get_logging_stats() -> Dict[str, Any]:
    """获取日志统计信息"""
    global _unified_logger

    if _unified_logger is None:
        _unified_logger = UnifiedLogger()

    return _unified_logger.get_stats()
