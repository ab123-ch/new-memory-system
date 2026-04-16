"""
容量控制器 - 控制 Token 容量和智能压缩

核心功能：
1. Token 估算
2. 自适应阈值计算
3. 优先级压缩
4. 核心层保护
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from enum import Enum


logger = logging.getLogger(__name__)


class ContentPriority(Enum):
    """内容优先级"""
    CRITICAL = 100      # 核心基础层，不可压缩
    HIGH = 75           # 模式知识层，尽量保留
    MEDIUM = 50         # 相关记忆，可压缩
    LOW = 25            # 辅助信息，优先压缩
    DISPOSABLE = 0      # 可丢弃


@dataclass
class ContentItem:
    """内容项"""
    content: str
    priority: ContentPriority
    source: str  # 来源标识
    metadata: Dict[str, Any] = field(default_factory=dict)
    estimated_tokens: int = 0

    def __post_init__(self):
        if self.estimated_tokens == 0:
            self.estimated_tokens = self._estimate_tokens()

    def _estimate_tokens(self) -> int:
        """估算 Token 数量"""
        # 简单估算：中文约 1.5 字/token，英文约 4 字符/token
        # 使用混合估算
        text = self.content

        # 统计中文字符
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
        # 统计英文单词（粗略）
        english_words = len(re.findall(r'[a-zA-Z]+', text))
        # 其他字符
        other_chars = len(text) - chinese_chars - sum(len(w) for w in re.findall(r'[a-zA-Z]+', text))

        # 估算 tokens
        tokens = int(chinese_chars / 1.5) + english_words + int(other_chars / 4)
        return max(tokens, 1)


@dataclass
class CompressionResult:
    """压缩结果"""
    items: List[ContentItem]
    total_tokens: int
    max_tokens: int
    compressed_count: int
    removed_count: int
    compression_ratio: float

    @property
    def is_within_limit(self) -> bool:
        """是否在限制内"""
        return self.total_tokens <= self.max_tokens


class CapacityController:
    """
    容量控制器

    负责控制上下文的 Token 容量，实现智能压缩策略。
    """

    # 默认配置
    DEFAULT_MAX_TOKENS = 8000
    DEFAULT_RESERVE_RATIO = 0.2  # 预留 20% 给响应

    def __init__(
        self,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        reserve_ratio: float = DEFAULT_RESERVE_RATIO
    ):
        """
        初始化容量控制器

        Args:
            max_tokens: 最大 Token 数
            reserve_ratio: 预留比例
        """
        self.max_tokens = max_tokens
        self.reserve_ratio = reserve_ratio
        self._adaptive_threshold = 1.0  # 自适应阈值因子

    @property
    def effective_max_tokens(self) -> int:
        """有效最大 Token 数（扣除预留）"""
        return int(self.max_tokens * (1 - self.reserve_ratio))

    def calculate_tokens(self, text: str) -> int:
        """
        计算文本的 Token 数

        Args:
            text: 输入文本

        Returns:
            估算的 Token 数
        """
        if not text:
            return 0

        item = ContentItem(
            content=text,
            priority=ContentPriority.DISPOSABLE,
            source="calculator"
        )
        return item.estimated_tokens

    def get_adaptive_threshold(self, context_pressure: float) -> float:
        """
        获取自适应阈值

        当上下文压力大时，提高压缩阈值

        Args:
            context_pressure: 上下文压力 (0-1, 1 表示满了)

        Returns:
            自适应阈值因子
        """
        if context_pressure > 0.9:
            # 压力很大，激进压缩
            self._adaptive_threshold = 1.5
        elif context_pressure > 0.7:
            # 中等压力，适度压缩
            self._adaptive_threshold = 1.2
        else:
            # 压力小，保守压缩
            self._adaptive_threshold = 1.0

        return self._adaptive_threshold

    def compress_context(
        self,
        items: List[ContentItem],
        target_tokens: Optional[int] = None
    ) -> CompressionResult:
        """
        压缩上下文以适应容量限制

        压缩策略：
        1. 保护 CRITICAL 优先级内容
        2. 按优先级排序
        3. 从低优先级开始压缩/移除
        4. 对可压缩内容进行摘要

        Args:
            items: 内容项列表
            target_tokens: 目标 Token 数，默认使用 effective_max_tokens

        Returns:
            压缩结果
        """
        if target_tokens is None:
            target_tokens = self.effective_max_tokens

        if not items:
            return CompressionResult(
                items=[],
                total_tokens=0,
                max_tokens=target_tokens,
                compressed_count=0,
                removed_count=0,
                compression_ratio=1.0
            )

        # 计算当前总 Token
        current_tokens = sum(item.estimated_tokens for item in items)

        # 如果已经在限制内，直接返回
        if current_tokens <= target_tokens:
            return CompressionResult(
                items=items,
                total_tokens=current_tokens,
                max_tokens=target_tokens,
                compressed_count=0,
                removed_count=0,
                compression_ratio=1.0
            )

        # 计算上下文压力
        context_pressure = current_tokens / target_tokens
        self.get_adaptive_threshold(context_pressure)

        # 分离不可压缩内容
        critical_items = [i for i in items if i.priority == ContentPriority.CRITICAL]
        compressible_items = [i for i in items if i.priority != ContentPriority.CRITICAL]

        # 计算核心层占用的 Token
        critical_tokens = sum(i.estimated_tokens for i in critical_items)

        # 剩余可用 Token
        remaining_tokens = target_tokens - critical_tokens

        if remaining_tokens <= 0:
            # 核心层已经超出限制，警告并只返回核心层
            logger.warning(
                f"核心层内容 ({critical_tokens} tokens) 超出限制 ({target_tokens} tokens)"
            )
            return CompressionResult(
                items=critical_items,
                total_tokens=critical_tokens,
                max_tokens=target_tokens,
                compressed_count=0,
                removed_count=len(items) - len(critical_items),
                compression_ratio=len(critical_items) / len(items) if items else 0
            )

        # 按优先级排序（高优先级在前）
        compressible_items.sort(key=lambda x: x.priority.value, reverse=True)

        # 选择要保留的项目
        selected_items: List[ContentItem] = []
        selected_tokens = 0
        compressed_count = 0
        removed_count = 0

        for item in compressible_items:
            if selected_tokens + item.estimated_tokens <= remaining_tokens:
                # 可以完整保留
                selected_items.append(item)
                selected_tokens += item.estimated_tokens
            else:
                # 尝试压缩
                compressed = self._compress_item(item, remaining_tokens - selected_tokens)

                if compressed:
                    selected_items.append(compressed)
                    selected_tokens += compressed.estimated_tokens
                    compressed_count += 1
                else:
                    # 无法压缩，移除
                    removed_count += 1

        # 合并结果
        final_items = critical_items + selected_items
        final_tokens = sum(i.estimated_tokens for i in final_items)

        return CompressionResult(
            items=final_items,
            total_tokens=final_tokens,
            max_tokens=target_tokens,
            compressed_count=compressed_count,
            removed_count=removed_count,
            compression_ratio=len(final_items) / len(items) if items else 0
        )

    def _compress_item(
        self,
        item: ContentItem,
        available_tokens: int
    ) -> Optional[ContentItem]:
        """
        压缩单个内容项

        Args:
            item: 原始内容项
            available_tokens: 可用 Token 数

        Returns:
            压缩后的内容项，如果无法压缩则返回 None
        """
        if available_tokens < 50:
            # 太小的空间不值得压缩
            return None

        # 简单截断策略
        if item.estimated_tokens > available_tokens:
            # 计算目标长度
            ratio = available_tokens / item.estimated_tokens
            target_length = int(len(item.content) * ratio * 0.9)  # 留点余量

            if target_length < 50:
                # 太短了，不如不要
                return None

            truncated_content = item.content[:target_length]

            # 尝试在句子边界截断
            last_period = max(
                truncated_content.rfind('。'),
                truncated_content.rfind('.'),
                truncated_content.rfind('！'),
                truncated_content.rfind('？')
            )

            if last_period > target_length * 0.5:
                truncated_content = truncated_content[:last_period + 1]

            return ContentItem(
                content=truncated_content + "\n[...已压缩...]",
                priority=item.priority,
                source=item.source,
                metadata={
                    **item.metadata,
                    "compressed": True,
                    "original_tokens": item.estimated_tokens
                }
            )

        return item

    def optimize_selection(
        self,
        candidates: List[ContentItem],
        max_items: int,
        diversity_weight: float = 0.3
    ) -> List[ContentItem]:
        """
        优化选择，考虑多样性

        Args:
            candidates: 候选内容项
            max_items: 最大数量
            diversity_weight: 多样性权重 (0-1)

        Returns:
            优化后的选择列表
        """
        if len(candidates) <= max_items:
            return candidates

        # 按优先级和相关性排序
        sorted_candidates = sorted(
            candidates,
            key=lambda x: (x.priority.value, x.metadata.get("relevance", 0)),
            reverse=True
        )

        # 选择高优先级项目
        selected = []
        sources = set()

        for item in sorted_candidates:
            if len(selected) >= max_items:
                break

            # 检查来源多样性
            source = item.source.split(":")[0]  # 取主要来源

            if source in sources and len(selected) < max_items * 0.7:
                # 已有同来源的，跳过（除非已经选够了）
                continue

            selected.append(item)
            sources.add(source)

        # 如果还不够，补充剩余高优先级的
        for item in sorted_candidates:
            if len(selected) >= max_items:
                break
            if item not in selected:
                selected.append(item)

        return selected
