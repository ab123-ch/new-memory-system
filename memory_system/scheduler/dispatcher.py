"""
模式调度器 - 根据场景模式返回配置并管理模式切换

核心功能：
1. 模式配置管理
2. 模式切换钩子
3. 配置加载
4. 模式状态管理
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
from pathlib import Path
import yaml


logger = logging.getLogger(__name__)


@dataclass
class KnowledgeConfig:
    """知识加载配置"""
    categories: List[str] = field(default_factory=list)
    max_items: int = 5
    min_relevance: float = 0.3


@dataclass
class MemoryConfig:
    """记忆检索配置"""
    days: int = 7
    max_items: int = 10
    use_semantic: bool = True


@dataclass
class OutputConfig:
    """输出配置"""
    style: str = "balanced"  # concise, detailed, balanced
    max_length: Optional[int] = None
    format_hints: List[str] = field(default_factory=list)


@dataclass
class ModeConfig:
    """模式配置"""
    mode_id: str
    name: str
    description: str = ""

    # 知识配置
    knowledge: KnowledgeConfig = field(default_factory=KnowledgeConfig)

    # 记忆配置
    memory: MemoryConfig = field(default_factory=MemoryConfig)

    # 输出配置
    output: OutputConfig = field(default_factory=OutputConfig)

    # 额外配置
    extra: Dict[str, Any] = field(default_factory=dict)

    # 元信息
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "mode_id": self.mode_id,
            "name": self.name,
            "description": self.description,
            "knowledge": {
                "categories": self.knowledge.categories,
                "max_items": self.knowledge.max_items,
                "min_relevance": self.knowledge.min_relevance
            },
            "memory": {
                "days": self.memory.days,
                "max_items": self.memory.max_items,
                "use_semantic": self.memory.use_semantic
            },
            "output": {
                "style": self.output.style,
                "max_length": self.output.max_length,
                "format_hints": self.output.format_hints
            },
            "extra": self.extra,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat()
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ModeConfig":
        """从字典创建"""
        knowledge_data = data.get("knowledge", {})
        memory_data = data.get("memory", {})
        output_data = data.get("output", {})

        return cls(
            mode_id=data.get("mode_id", "unknown"),
            name=data.get("name", "未知模式"),
            description=data.get("description", ""),
            knowledge=KnowledgeConfig(
                categories=knowledge_data.get("categories", []),
                max_items=knowledge_data.get("max_items", 5),
                min_relevance=knowledge_data.get("min_relevance", 0.3)
            ),
            memory=MemoryConfig(
                days=memory_data.get("days", 7),
                max_items=memory_data.get("max_items", 10),
                use_semantic=memory_data.get("use_semantic", True)
            ),
            output=OutputConfig(
                style=output_data.get("style", "balanced"),
                max_length=output_data.get("max_length"),
                format_hints=output_data.get("format_hints", [])
            ),
            extra=data.get("extra", {})
        )


# 预定义模式配置
DEFAULT_MODE_CONFIGS = {
    "writing": ModeConfig(
        mode_id="writing",
        name="写作模式",
        description="专注于创作任务的上下文",
        knowledge=KnowledgeConfig(
            categories=["narrative", "character", "dialogue", "pacing", "emotion", "description"],
            max_items=5,
            min_relevance=0.4
        ),
        memory=MemoryConfig(
            days=7,
            max_items=8,
            use_semantic=True
        ),
        output=OutputConfig(
            style="detailed",
            format_hints=["使用丰富的描写", "注重情感表达"]
        ),
        extra={
            "suggestion_types": ["technique", "example", "inspiration"]
        }
    ),
    "programming": ModeConfig(
        mode_id="programming",
        name="编程模式",
        description="专注于代码开发任务的上下文",
        knowledge=KnowledgeConfig(
            categories=["structure", "logic", "pattern"],
            max_items=3,
            min_relevance=0.5
        ),
        memory=MemoryConfig(
            days=3,
            max_items=5,
            use_semantic=True
        ),
        output=OutputConfig(
            style="concise",
            format_hints=["使用代码块", "添加注释"]
        ),
        extra={
            "code_style": "clean",
            "prefer_solutions": True
        }
    ),
    "analysis": ModeConfig(
        mode_id="analysis",
        name="分析模式",
        description="专注于分析和推理任务的上下文",
        knowledge=KnowledgeConfig(
            categories=["structure", "logic", "framework"],
            max_items=4,
            min_relevance=0.4
        ),
        memory=MemoryConfig(
            days=14,
            max_items=10,
            use_semantic=True
        ),
        output=OutputConfig(
            style="balanced",
            format_hints=["结构化输出", "使用列表"]
        ),
        extra={
            "analysis_depth": "deep",
            "include_evidence": True
        }
    ),
    "chat": ModeConfig(
        mode_id="chat",
        name="聊天模式",
        description="日常对话的轻量上下文",
        knowledge=KnowledgeConfig(
            categories=[],
            max_items=0,
            min_relevance=0.0
        ),
        memory=MemoryConfig(
            days=1,
            max_items=3,
            use_semantic=False
        ),
        output=OutputConfig(
            style="concise",
            format_hints=[]
        ),
        extra={
            "casual": True
        }
    ),
}


# 钩子类型
ModeSwitchHook = Callable[[str, str, Dict[str, Any]], None]


class ModeDispatcher:
    """
    模式调度器

    管理模式配置，处理模式切换，触发钩子。
    """

    def __init__(
        self,
        storage_path: Optional[str] = None,
        custom_configs: Optional[Dict[str, ModeConfig]] = None
    ):
        """
        初始化调度器

        Args:
            storage_path: 存储路径（用于加载自定义配置）
            custom_configs: 自定义模式配置
        """
        self.storage_path = Path(storage_path) if storage_path else None

        # 合并配置
        self._configs = {**DEFAULT_MODE_CONFIGS}
        if custom_configs:
            self._configs.update(custom_configs)

        # 当前模式
        self._current_mode: str = "chat"

        # 模式切换历史
        self._switch_history: List[Dict[str, Any]] = []

        # 钩子函数
        self._switch_hooks: List[ModeSwitchHook] = []

        # 尝试加载自定义配置
        if self.storage_path:
            self._load_custom_configs()

    def _load_custom_configs(self):
        """从存储路径加载自定义配置"""
        if not self.storage_path:
            return

        config_file = self.storage_path / "mode_configs.yaml"

        if not config_file.exists():
            return

        try:
            with open(config_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            for mode_id, config_data in data.items():
                if isinstance(config_data, dict):
                    self._configs[mode_id] = ModeConfig.from_dict(config_data)

            logger.info(f"加载了 {len(data)} 个自定义模式配置")

        except Exception as e:
            logger.warning(f"加载自定义模式配置失败: {e}")

    def save_custom_configs(self):
        """保存自定义配置"""
        if not self.storage_path:
            return

        config_file = self.storage_path / "mode_configs.yaml"

        try:
            # 只保存非默认的配置
            custom_configs = {}
            for mode_id, config in self._configs.items():
                if mode_id not in DEFAULT_MODE_CONFIGS:
                    custom_configs[mode_id] = config.to_dict()

            with open(config_file, "w", encoding="utf-8") as f:
                yaml.dump(custom_configs, f, allow_unicode=True, sort_keys=False)

        except Exception as e:
            logger.warning(f"保存自定义模式配置失败: {e}")

    def dispatch(self, mode: str) -> ModeConfig:
        """
        调度到指定模式

        Args:
            mode: 模式名称

        Returns:
            模式配置
        """
        # 验证模式
        if mode not in self._configs:
            logger.warning(f"未知模式 '{mode}'，使用默认聊天模式")
            mode = "chat"

        # 获取配置
        config = self._configs[mode]

        # 触发钩子
        old_mode = self._current_mode
        if old_mode != mode:
            self._trigger_hooks(old_mode, mode, config.to_dict())

            # 记录切换
            self._switch_history.append({
                "from": old_mode,
                "to": mode,
                "timestamp": datetime.now().isoformat()
            })

            # 更新当前模式
            self._current_mode = mode

        return config

    def get_current_mode(self) -> str:
        """获取当前模式"""
        return self._current_mode

    def get_current_config(self) -> ModeConfig:
        """获取当前模式的配置"""
        return self._configs.get(self._current_mode, DEFAULT_MODE_CONFIGS["chat"])

    def get_mode_config(self, mode: str) -> ModeConfig:
        """
        获取指定模式的配置（不切换）

        Args:
            mode: 模式名称

        Returns:
            模式配置
        """
        return self._configs.get(mode, DEFAULT_MODE_CONFIGS["chat"])

    def list_modes(self) -> List[Dict[str, Any]]:
        """
        列出所有可用模式

        Returns:
            模式列表
        """
        result = []
        for mode_id, config in self._configs.items():
            result.append({
                "id": mode_id,
                "name": config.name,
                "description": config.description,
                "is_current": mode_id == self._current_mode
            })
        return result

    def register_mode(self, config: ModeConfig) -> bool:
        """
        注册新模式

        Args:
            config: 模式配置

        Returns:
            是否成功
        """
        if not config.mode_id:
            return False

        self._configs[config.mode_id] = config
        return True

    def unregister_mode(self, mode_id: str) -> bool:
        """
        注销模式

        Args:
            mode_id: 模式ID

        Returns:
            是否成功
        """
        if mode_id in DEFAULT_MODE_CONFIGS:
            # 不允许注销默认模式
            return False

        if mode_id in self._configs:
            del self._configs[mode_id]
            return True

        return False

    def add_switch_hook(self, hook: ModeSwitchHook):
        """
        添加模式切换钩子

        钩子函数签名: (old_mode: str, new_mode: str, config: dict) -> None

        Args:
            hook: 钩子函数
        """
        self._switch_hooks.append(hook)

    def remove_switch_hook(self, hook: ModeSwitchHook):
        """移除模式切换钩子"""
        if hook in self._switch_hooks:
            self._switch_hooks.remove(hook)

    def _trigger_hooks(
        self,
        old_mode: str,
        new_mode: str,
        config: Dict[str, Any]
    ):
        """触发钩子"""
        for hook in self._switch_hooks:
            try:
                hook(old_mode, new_mode, config)
            except Exception as e:
                logger.warning(f"模式切换钩子执行失败: {e}")

    def get_switch_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        获取切换历史

        Args:
            limit: 最大返回数量

        Returns:
            切换历史列表
        """
        return self._switch_history[-limit:]

    def get_statistics(self) -> Dict[str, Any]:
        """
        获取统计信息

        Returns:
            统计信息
        """
        mode_counts: Dict[str, int] = {}
        for record in self._switch_history:
            mode = record.get("to", "unknown")
            mode_counts[mode] = mode_counts.get(mode, 0) + 1

        return {
            "current_mode": self._current_mode,
            "total_switches": len(self._switch_history),
            "mode_distribution": mode_counts,
            "available_modes": list(self._configs.keys())
        }
