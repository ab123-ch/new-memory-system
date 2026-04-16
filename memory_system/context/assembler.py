"""
上下文组装器 - 统一的上下文组装逻辑

核心功能：
1. 加载核心基础层（人格信息、用户画像）
2. 加载模式知识层（场景相关技巧）
3. 检索相关记忆
4. 格式化输出
5. Token 容量控制
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from pathlib import Path

from .capacity_controller import (
    CapacityController,
    ContentItem,
    ContentPriority,
    CompressionResult
)


logger = logging.getLogger(__name__)


@dataclass
class ModeConfig:
    """模式配置"""
    mode_id: str
    name: str
    description: str = ""

    # 知识加载配置
    knowledge_categories: List[str] = field(default_factory=list)
    max_techniques: int = 5

    # 记忆检索配置
    memory_days: int = 7
    max_memories: int = 10

    # 上下文配置
    style: str = "balanced"  # concise, detailed, balanced

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode_id": self.mode_id,
            "name": self.name,
            "description": self.description,
            "knowledge_categories": self.knowledge_categories,
            "max_techniques": self.max_techniques,
            "memory_days": self.memory_days,
            "max_memories": self.max_memories,
            "style": self.style
        }


# 预定义模式配置
DEFAULT_MODES = {
    "writing": ModeConfig(
        mode_id="writing",
        name="写作模式",
        description="专注于创作任务的上下文",
        knowledge_categories=["narrative", "character", "dialogue", "pacing", "emotion"],
        max_techniques=5,
        memory_days=7,
        max_memories=8,
        style="detailed"
    ),
    "programming": ModeConfig(
        mode_id="programming",
        name="编程模式",
        description="专注于代码开发任务的上下文",
        knowledge_categories=["structure", "logic"],
        max_techniques=3,
        memory_days=3,
        max_memories=5,
        style="concise"
    ),
    "analysis": ModeConfig(
        mode_id="analysis",
        name="分析模式",
        description="专注于分析和推理任务的上下文",
        knowledge_categories=["structure", "logic"],
        max_techniques=3,
        memory_days=14,
        max_memories=10,
        style="balanced"
    ),
    "chat": ModeConfig(
        mode_id="chat",
        name="聊天模式",
        description="日常对话的轻量上下文",
        knowledge_categories=[],
        max_techniques=0,
        memory_days=1,
        max_memories=3,
        style="concise"
    ),
}


@dataclass
class AssembledContext:
    """组装后的上下文"""
    # 原始内容
    raw_content: str

    # 结构化内容
    persona_info: Optional[Dict[str, Any]] = None
    soul_info: Optional[Dict[str, Any]] = None
    shared_info: Optional[Dict[str, Any]] = None
    mode_knowledge: List[Dict[str, Any]] = field(default_factory=list)
    optimized_rules: List[Dict[str, Any]] = field(default_factory=list)
    relevant_memories: List[Dict[str, Any]] = field(default_factory=list)

    # 元信息
    mode: str = "chat"
    total_tokens: int = 0
    compression_applied: bool = False
    compression_stats: Optional[Dict[str, Any]] = None

    # 格式化输出
    formatted_output: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "raw_content": self.raw_content,
            "persona_info": self.persona_info,
            "soul_info": self.soul_info,
            "shared_info": self.shared_info,
            "mode_knowledge": self.mode_knowledge,
            "optimized_rules": self.optimized_rules,
            "relevant_memories": self.relevant_memories,
            "mode": self.mode,
            "total_tokens": self.total_tokens,
            "compression_applied": self.compression_applied,
            "compression_stats": self.compression_stats,
            "formatted_output": self.formatted_output
        }


class ContextAssembler:
    """
    上下文组装器

    负责将各种记忆、知识、配置组装成完整的上下文。
    """

    def __init__(
        self,
        storage_path: str,
        max_tokens: int = 8000,
        mode_configs: Optional[Dict[str, ModeConfig]] = None
    ):
        """
        初始化上下文组装器

        Args:
            storage_path: 存储路径
            max_tokens: 最大 Token 数
            mode_configs: 自定义模式配置
        """
        self.storage_path = Path(storage_path)
        self.max_tokens = max_tokens
        self.mode_configs = {**DEFAULT_MODES, **(mode_configs or {})}

        # 初始化容量控制器
        self.capacity_controller = CapacityController(max_tokens=max_tokens)

        # 懒加载的管理器
        self._persona_manager = None
        self._memory_system = None
        self._optimized_rules = None  # 缓存优化规则

    @property
    def persona_manager(self):
        """懒加载人格管理器"""
        if self._persona_manager is None:
            from ..personas import PersonaManager
            self._persona_manager = PersonaManager(str(self.storage_path))
        return self._persona_manager

    @property
    def memory_system(self):
        """懒加载记忆系统"""
        if self._memory_system is None:
            from .. import MemorySystem
            from ..config import get_config
            self._memory_system = MemorySystem(str(self.storage_path), get_config())
        return self._memory_system

    def get_mode_config(self, mode: str) -> ModeConfig:
        """
        获取模式配置

        Args:
            mode: 模式名称

        Returns:
            模式配置
        """
        return self.mode_configs.get(mode, DEFAULT_MODES["chat"])

    def assemble(
        self,
        mode: str,
        user_input: str,
        context_hints: Optional[Dict[str, Any]] = None
    ) -> AssembledContext:
        """
        组装上下文

        这是主入口方法，按照以下顺序组装：
        1. 加载核心基础层
        2. 加载模式知识层
        3. 检索相关记忆
        4. 容量控制
        5. 格式化输出

        Args:
            mode: 模式名称 (writing/programming/analysis/chat)
            user_input: 用户输入
            context_hints: 上下文提示（如场景、关键词等）

        Returns:
            组装后的上下文
        """
        mode_config = self.get_mode_config(mode)
        context_hints = context_hints or {}

        # 1. 加载核心基础层
        core_items = self._load_core_layer()

        # 2. 加载模式知识层
        knowledge_items = self._load_mode_knowledge(mode_config, context_hints)

        # 3. 加载优化后的抽象规则
        rule_items = self._load_optimized_rules(user_input, context_hints)

        # 4. 检索相关记忆
        memory_items = self._get_relevant_memories(
            user_input,
            mode_config,
            context_hints
        )

        # 合并所有内容项
        all_items = core_items + knowledge_items + rule_items + memory_items

        # 4. 容量控制
        compression_result = self.capacity_controller.compress_context(all_items)

        # 5. 格式化输出
        formatted_output = self._format_output(
            compression_result.items,
            mode_config,
            user_input
        )

        # 构建结果
        result = AssembledContext(
            raw_content=user_input,
            mode=mode,
            total_tokens=compression_result.total_tokens,
            compression_applied=compression_result.compressed_count > 0 or compression_result.removed_count > 0,
            formatted_output=formatted_output
        )

        # 填充分类信息
        for item in compression_result.items:
            if item.source == "persona":
                result.persona_info = item.metadata.get("data")
            elif item.source == "soul":
                result.soul_info = item.metadata.get("data")
            elif item.source == "shared":
                result.shared_info = item.metadata.get("data")
            elif item.source.startswith("knowledge"):
                result.mode_knowledge.append(item.metadata.get("data", {}))
            elif item.source.startswith("rule"):
                result.optimized_rules.append(item.metadata.get("data", {}))
            elif item.source.startswith("memory"):
                result.relevant_memories.append(item.metadata.get("data", {}))

        # 压缩统计
        if result.compression_applied:
            result.compression_stats = {
                "compressed_count": compression_result.compressed_count,
                "removed_count": compression_result.removed_count,
                "compression_ratio": compression_result.compression_ratio
            }

        return result

    def _load_core_layer(self) -> List[ContentItem]:
        """
        加载核心基础层

        包括：人格信息、元记忆、共享记忆

        Returns:
            核心层内容项列表
        """
        items = []

        try:
            # 获取人格上下文
            context = self.persona_manager.get_memory_context(include_shared=True)

            # 人格信息（CRITICAL - 不可压缩）
            if context.get("persona"):
                persona_data = context["persona"]
                persona_content = self._format_persona(persona_data)
                items.append(ContentItem(
                    content=persona_content,
                    priority=ContentPriority.CRITICAL,
                    source="persona",
                    metadata={"data": persona_data}
                ))

            # 元记忆（HIGH - 尽量保留）
            if context.get("soul"):
                soul_data = context["soul"]
                soul_content = self._format_soul(soul_data)
                items.append(ContentItem(
                    content=soul_content,
                    priority=ContentPriority.HIGH,
                    source="soul",
                    metadata={"data": soul_data}
                ))

            # 共享记忆（MEDIUM - 可压缩）
            if context.get("shared"):
                shared_data = context["shared"]
                shared_content = self._format_shared(shared_data)
                if shared_content:
                    items.append(ContentItem(
                        content=shared_content,
                        priority=ContentPriority.MEDIUM,
                        source="shared",
                        metadata={"data": shared_data}
                    ))

        except Exception as e:
            logger.warning(f"加载核心层失败: {e}")

        return items

    def _load_mode_knowledge(
        self,
        mode_config: ModeConfig,
        context_hints: Dict[str, Any]
    ) -> List[ContentItem]:
        """
        加载模式知识层

        根据模式配置加载相关的技巧和知识

        Args:
            mode_config: 模式配置
            context_hints: 上下文提示

        Returns:
            知识层内容项列表
        """
        items = []

        if not mode_config.knowledge_categories:
            return items

        try:
            # 获取当前人格的风格记忆上下文
            index = self.persona_manager.load_index()
            if not index.active_persona:
                return items

            style_context = self.persona_manager.get_style_memory_context(
                index.active_persona,
                context={
                    "stage": context_hints.get("stage", ""),
                    "keywords": context_hints.get("keywords", []),
                    "scene": context_hints.get("scene", "")
                },
                max_techniques=mode_config.max_techniques
            )

            if not style_context.get("has_style_memory"):
                return items

            # 添加技巧建议
            suggestions = style_context.get("suggestions", [])
            for i, suggestion in enumerate(suggestions[:mode_config.max_techniques]):
                content = self._format_technique(suggestion)
                items.append(ContentItem(
                    content=content,
                    priority=ContentPriority.HIGH,
                    source=f"knowledge:{suggestion.get('category', 'unknown')}",
                    metadata={
                        "data": suggestion,
                        "relevance": suggestion.get("relevance_score", 0)
                    }
                ))

        except Exception as e:
            logger.warning(f"加载模式知识失败: {e}")

        return items

    def _load_optimized_rules(
        self,
        user_input: str,
        context_hints: Dict[str, Any]
    ) -> List[ContentItem]:
        """
        加载优化后的抽象规则

        从 reorganization_results.yaml 中加载与当前输入相关的规则。
        这些规则是从历史对话中提取的经验总结。

        Args:
            user_input: 用户输入
            context_hints: 上下文提示

        Returns:
            规则内容项列表
        """
        items = []

        try:
            # 加载或获取缓存的规则
            rules = self._get_optimized_rules()

            if not rules:
                return items

            # 根据用户输入匹配相关规则
            relevant_rules = self._match_relevant_rules(rules, user_input, context_hints)

            for rule in relevant_rules[:5]:  # 最多5条规则
                content = self._format_rule(rule)
                items.append(ContentItem(
                    content=content,
                    priority=ContentPriority.HIGH,  # 规则优先级较高
                    source=f"rule:{rule.get('id', 'unknown')}",
                    metadata={
                        "data": rule,
                        "relevance": rule.get("relevance", 0)
                    }
                ))

        except Exception as e:
            logger.warning(f"加载优化规则失败: {e}")

        return items

    def _get_optimized_rules(self) -> List[Dict[str, Any]]:
        """
        获取优化规则（带缓存）

        Returns:
            规则列表
        """
        if self._optimized_rules is not None:
            return self._optimized_rules

        rules = []
        rules_file = self.storage_path / "reorganization_results.yaml"

        if rules_file.exists():
            try:
                import yaml
                with open(rules_file, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f) or {}
                    rules = data.get("abstract_rules", [])
            except Exception as e:
                logger.warning(f"读取规则文件失败: {e}")

        self._optimized_rules = rules
        return rules

    def _match_relevant_rules(
        self,
        rules: List[Dict[str, Any]],
        user_input: str,
        context_hints: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        匹配与当前输入相关的规则

        Args:
            rules: 所有规则
            user_input: 用户输入
            context_hints: 上下文提示

        Returns:
            相关规则列表（按相关度排序）
        """
        import re

        # 提取用户输入的关键词
        input_lower = user_input.lower()
        input_keywords = set(re.findall(r'[a-zA-Z]{3,}', input_lower))
        input_keywords.update(re.findall(r'[\u4e00-\u9fff]{2,4}', input_lower))

        # 上下文关键词
        context_keywords = set()
        if context_hints.get("keywords"):
            context_keywords.update(kw.lower() for kw in context_hints["keywords"] if isinstance(kw, str))

        all_keywords = input_keywords | context_keywords

        # 计算每条规则的相关度
        scored_rules = []
        for rule in rules:
            rule_text = rule.get("rule", "").lower()
            topic = rule.get("topic", rule.get("source_cluster", "")).lower()

            score = 0

            # 检查关键词匹配
            for kw in all_keywords:
                if kw in rule_text or kw in topic:
                    score += 1

            # 检查主题词匹配（规则开头的「xxx」部分）
            topic_match = re.search(r'关于「(.+?)」', rule_text)
            if topic_match:
                rule_topic = topic_match.group(1).lower()
                if rule_topic in input_lower:
                    score += 3  # 主题匹配权重更高

            rule["relevance"] = score
            if score > 0:
                scored_rules.append(rule)

        # 按相关度排序，然后按来源数量排序（更多来源的规则更可靠）
        scored_rules.sort(key=lambda x: (x.get("relevance", 0), x.get("source_count", 0)), reverse=True)

        return scored_rules

    def _format_rule(self, data: Dict[str, Any]) -> str:
        """格式化规则"""
        rule_text = data.get("rule", "")
        source_count = data.get("source_count", 0)

        parts = [f"【经验规则】{rule_text}"]

        if source_count > 0:
            parts.append(f"  (基于 {source_count} 次对话总结)")

        return "\n".join(parts)

    def _get_relevant_memories(
        self,
        user_input: str,
        mode_config: ModeConfig,
        context_hints: Dict[str, Any]
    ) -> List[ContentItem]:
        """
        检索相关记忆

        Args:
            user_input: 用户输入
            mode_config: 模式配置
            context_hints: 上下文提示

        Returns:
            相关记忆内容项列表
        """
        items = []

        if not user_input or mode_config.max_memories <= 0:
            return items

        try:
            # 使用语义搜索检索相关记忆
            import asyncio

            # 检查是否在异步环境中
            try:
                loop = asyncio.get_running_loop()
                # 在异步环境中，创建任务
                results = asyncio.create_task(
                    self.memory_system.search(
                        user_input,
                        mode_config.memory_days,
                        use_semantic=True
                    )
                )
                # 我们不能在这里等待，所以返回空
                # 实际使用时应该在外部调用异步版本
                return items
            except RuntimeError:
                # 没有运行的事件循环，创建新的
                results = asyncio.run(
                    self.memory_system.search(
                        user_input,
                        mode_config.memory_days,
                        use_semantic=True
                    )
                )

            for i, result in enumerate(results[:mode_config.max_memories]):
                content = self._format_memory(result)
                priority = ContentPriority.MEDIUM if i < 3 else ContentPriority.LOW
                items.append(ContentItem(
                    content=content,
                    priority=priority,
                    source=f"memory:{result.get('date', 'unknown')}",
                    metadata={
                        "data": result,
                        "relevance": result.get("score", 0)
                    }
                ))

        except Exception as e:
            logger.warning(f"检索相关记忆失败: {e}")

        return items

    async def _get_relevant_memories_async(
        self,
        user_input: str,
        mode_config: ModeConfig
    ) -> List[ContentItem]:
        """
        异步检索相关记忆

        Args:
            user_input: 用户输入
            mode_config: 模式配置

        Returns:
            相关记忆内容项列表
        """
        items = []

        if not user_input or mode_config.max_memories <= 0:
            return items

        try:
            results = await self.memory_system.search(
                user_input,
                mode_config.memory_days,
                use_semantic=True
            )

            for i, result in enumerate(results[:mode_config.max_memories]):
                content = self._format_memory(result)
                priority = ContentPriority.MEDIUM if i < 3 else ContentPriority.LOW
                items.append(ContentItem(
                    content=content,
                    priority=priority,
                    source=f"memory:{result.get('date', 'unknown')}",
                    metadata={
                        "data": result,
                        "relevance": result.get("score", 0)
                    }
                ))

        except Exception as e:
            logger.warning(f"异步检索记忆失败: {e}")

        return items

    async def assemble_async(
        self,
        mode: str,
        user_input: str,
        context_hints: Optional[Dict[str, Any]] = None
    ) -> AssembledContext:
        """
        异步组装上下文

        Args:
            mode: 模式名称
            user_input: 用户输入
            context_hints: 上下文提示

        Returns:
            组装后的上下文
        """
        mode_config = self.get_mode_config(mode)
        context_hints = context_hints or {}

        # 1. 加载核心基础层
        core_items = self._load_core_layer()

        # 2. 加载模式知识层
        knowledge_items = self._load_mode_knowledge(mode_config, context_hints)

        # 3. 加载优化后的抽象规则
        rule_items = self._load_optimized_rules(user_input, context_hints)

        # 4. 异步检索相关记忆
        memory_items = await self._get_relevant_memories_async(user_input, mode_config)

        # 合并所有内容项
        all_items = core_items + knowledge_items + rule_items + memory_items

        # 4. 容量控制
        compression_result = self.capacity_controller.compress_context(all_items)

        # 5. 格式化输出
        formatted_output = self._format_output(
            compression_result.items,
            mode_config,
            user_input
        )

        # 构建结果
        result = AssembledContext(
            raw_content=user_input,
            mode=mode,
            total_tokens=compression_result.total_tokens,
            compression_applied=compression_result.compressed_count > 0,
            formatted_output=formatted_output
        )

        return result

    def _format_persona(self, data: Dict[str, Any]) -> str:
        """格式化人格信息"""
        parts = [f"【当前人格】{data.get('name', '未知')}"]

        if data.get("description"):
            parts.append(f"描述: {data['description']}")

        if data.get("system_prompt"):
            parts.append(f"角色设定: {data['system_prompt']}")

        return "\n".join(parts)

    def _format_soul(self, data: Dict[str, Any]) -> str:
        """格式化元记忆"""
        parts = ["【元记忆】"]

        if data.get("identity"):
            parts.append("身份: " + ", ".join(data["identity"][:5]))

        if data.get("habits"):
            parts.append("偏好: " + ", ".join(data["habits"][:5]))

        if data.get("abilities"):
            parts.append("能力: " + ", ".join(data["abilities"][:5]))

        return "\n".join(parts)

    def _format_shared(self, data: Dict[str, Any]) -> str:
        """格式化共享记忆"""
        parts = []

        if data.get("identity"):
            parts.append("【共享身份】" + ", ".join(data["identity"][:3]))

        if data.get("knowledge"):
            parts.append("【共享知识】" + ", ".join(data["knowledge"][:3]))

        return "\n".join(parts) if parts else ""

    def _format_technique(self, data: Dict[str, Any]) -> str:
        """格式化技巧"""
        parts = [f"【{data.get('category_display', '技巧')}】"]

        principle = data.get("principle", "")
        if principle:
            parts.append(f"原理: {principle[:150]}")

        examples = data.get("examples", [])
        if examples:
            parts.append(f"示例: {examples[0][:100]}")

        return "\n".join(parts)

    def _format_memory(self, data: Dict[str, Any]) -> str:
        """格式化记忆"""
        date = data.get("date", "未知日期")
        content = data.get("content", "")
        source = data.get("type", "")

        source_hint = " [语义]" if source == "semantic" else ""
        return f"[{date}]{source_hint} {content[:200]}"

    def _format_output(
        self,
        items: List[ContentItem],
        mode_config: ModeConfig,
        user_input: str
    ) -> str:
        """
        格式化最终输出

        Args:
            items: 内容项列表
            mode_config: 模式配置
            user_input: 用户输入

        Returns:
            格式化后的上下文字符串
        """
        sections = []

        # 按 source 分组
        grouped: Dict[str, List[ContentItem]] = {}
        for item in items:
            source_key = item.source.split(":")[0]
            if source_key not in grouped:
                grouped[source_key] = []
            grouped[source_key].append(item)

        # 按顺序添加各部分
        order = ["persona", "soul", "shared", "knowledge", "rule", "memory"]

        for source in order:
            if source in grouped:
                for item in grouped[source]:
                    if item.content.strip():
                        sections.append(item.content)

        # 添加用户输入提示
        if mode_config.style == "detailed":
            sections.append(f"\n【用户输入】{user_input[:200]}")

        return "\n\n".join(sections)

    def get_quick_context(
        self,
        mode: str = "chat"
    ) -> str:
        """
        获取快速上下文（仅核心层）

        用于轻量级场景

        Args:
            mode: 模式名称

        Returns:
            格式化的上下文字符串
        """
        core_items = self._load_core_layer()

        if not core_items:
            return ""

        mode_config = self.get_mode_config(mode)
        return self._format_output(core_items, mode_config, "")
