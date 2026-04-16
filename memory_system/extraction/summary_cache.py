"""
对话摘要缓存模块

功能：
1. 生成和存储对话摘要
2. 提供 key-value 查询接口
3. 生成召回提示
4. 持久化到 summary_cache.yaml

设计目标：
- 减少上下文占用（每条摘要 ≤80 字符）
- 保留获取完整内容的能力
- 支持快速检索
"""
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
import yaml
import threading

# 统一日志
try:
    from ..logging_config import get_logger
    _logger = get_logger("summary_cache", "mcp")
except ImportError:
    import logging
    _logger = logging.getLogger(__name__)


@dataclass
class ConversationSummaryEntry:
    """
    对话摘要条目

    Attributes:
        key: 唯一标识符，格式：date|session_id|conversation_id
        date: 日期 (YYYY-MM-DD)
        session_id: 会话ID
        conversation_id: 对话ID（可选）
        role: 角色 (user/assistant)
        summary: 摘要内容（≤80字符）
        recall_hint: 召回提示命令
        timestamp: 创建时间戳
    """
    key: str
    date: str
    session_id: str
    role: str
    summary: str
    recall_hint: str
    conversation_id: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    note: str = "使用 memory_recall_by_id 工具获取完整内容"

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConversationSummaryEntry":
        """从字典创建"""
        return cls(**data)


class SummaryCache:
    """
    摘要缓存管理器

    功能：
    1. 生成对话摘要（复用现有 Summarizer）
    2. key-value 查询接口
    3. 生成召回提示
    4. 持久化到 summary_cache.yaml
    """

    # 摘要最大长度
    MAX_SUMMARY_LENGTH = 80

    def __init__(self, cache_path: Optional[str] = None):
        """
        初始化摘要缓存

        Args:
            cache_path: 缓存文件路径，默认为 data/memory/summary_cache.yaml
        """
        if cache_path is None:
            # 默认路径
            base_path = os.environ.get("MEMORY_DATA_PATH", "./data/memory")
            cache_path = os.path.join(base_path, "summary_cache.yaml")

        self.cache_path = Path(cache_path)
        self._cache: Dict[str, ConversationSummaryEntry] = {}
        self._lock = threading.RLock()
        self._loaded = False

    def _ensure_loaded(self):
        """确保缓存已加载"""
        if not self._loaded:
            self.load()
            self._loaded = True

    def load(self) -> bool:
        """
        从文件加载缓存

        Returns:
            是否加载成功
        """
        with self._lock:
            if not self.cache_path.exists():
                return False

            try:
                with open(self.cache_path, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f) or {}

                self._cache = {}
                for key, entry_data in data.get("entries", {}).items():
                    self._cache[key] = ConversationSummaryEntry.from_dict(entry_data)

                return True
            except Exception as e:
                _logger.error(f"加载摘要缓存失败: {e}")
                return False

    def save(self) -> bool:
        """
        保存缓存到文件

        Returns:
            是否保存成功
        """
        with self._lock:
            try:
                # 确保目录存在
                self.cache_path.parent.mkdir(parents=True, exist_ok=True)

                data = {
                    "version": "1.0",
                    "updated_at": datetime.now().isoformat(),
                    "entries": {
                        key: entry.to_dict()
                        for key, entry in self._cache.items()
                    }
                }

                with open(self.cache_path, 'w', encoding='utf-8') as f:
                    yaml.dump(data, f, allow_unicode=True, default_flow_style=False)

                return True
            except Exception as e:
                _logger.error(f"保存摘要缓存失败: {e}")
                return False

    def generate_key(
        self,
        date: str,
        session_id: str,
        conversation_id: str = ""
    ) -> str:
        """
        生成缓存键

        Args:
            date: 日期 (YYYY-MM-DD)
            session_id: 会话ID
            conversation_id: 对话ID（可选）

        Returns:
            缓存键，格式：date|session_id|conversation_id
        """
        if conversation_id:
            return f"{date}|{session_id}|{conversation_id}"
        return f"{date}|{session_id}"

    def generate_recall_hint(
        self,
        date: str,
        session_id: str,
        conversation_id: str = ""
    ) -> str:
        """
        生成召回提示

        Args:
            date: 日期
            session_id: 会话ID
            conversation_id: 对话ID（可选）

        Returns:
            召回提示命令
        """
        if conversation_id:
            return f"memory_recall_by_id(date='{date}', session_id='{session_id}', conversation_id='{conversation_id}')"
        return f"memory_recall_by_id(date='{date}', session_id='{session_id}')"

    def truncate_summary(self, text: str, max_length: int = None) -> str:
        """
        截断摘要到指定长度

        Args:
            text: 原始文本
            max_length: 最大长度，默认使用 MAX_SUMMARY_LENGTH

        Returns:
            截断后的文本
        """
        if max_length is None:
            max_length = self.MAX_SUMMARY_LENGTH

        if len(text) <= max_length:
            return text

        return text[:max_length - 3] + "..."

    def create_summary(
        self,
        date: str,
        session_id: str,
        role: str,
        content: str,
        conversation_id: str = ""
    ) -> ConversationSummaryEntry:
        """
        创建摘要条目

        Args:
            date: 日期
            session_id: 会话ID
            role: 角色 (user/assistant)
            content: 原始内容
            conversation_id: 对话ID（可选）

        Returns:
            摘要条目
        """
        key = self.generate_key(date, session_id, conversation_id)
        recall_hint = self.generate_recall_hint(date, session_id, conversation_id)
        summary = self.truncate_summary(content)

        entry = ConversationSummaryEntry(
            key=key,
            date=date,
            session_id=session_id,
            conversation_id=conversation_id,
            role=role,
            summary=summary,
            recall_hint=recall_hint
        )

        return entry

    def add_entry(self, entry: ConversationSummaryEntry) -> bool:
        """
        添加摘要条目

        Args:
            entry: 摘要条目

        Returns:
            是否添加成功
        """
        with self._lock:
            self._ensure_loaded()
            self._cache[entry.key] = entry
            return True

    def add(
        self,
        date: str,
        session_id: str,
        role: str,
        content: str,
        conversation_id: str = ""
    ) -> ConversationSummaryEntry:
        """
        添加摘要（便捷方法）

        Args:
            date: 日期
            session_id: 会话ID
            role: 角色
            content: 原始内容
            conversation_id: 对话ID（可选）

        Returns:
            创建的摘要条目
        """
        entry = self.create_summary(date, session_id, role, content, conversation_id)
        self.add_entry(entry)
        return entry

    def get(self, key: str) -> Optional[ConversationSummaryEntry]:
        """
        获取摘要

        Args:
            key: 缓存键

        Returns:
            摘要条目，不存在返回 None
        """
        with self._lock:
            self._ensure_loaded()
            return self._cache.get(key)

    def get_by_session(self, date: str, session_id: str) -> List[ConversationSummaryEntry]:
        """
        按会话获取摘要

        Args:
            date: 日期
            session_id: 会话ID

        Returns:
            摘要条目列表
        """
        with self._lock:
            self._ensure_loaded()
            prefix = f"{date}|{session_id}"
            return [
                entry for key, entry in self._cache.items()
                if key.startswith(prefix)
            ]

    def search(
        self,
        query: str,
        date_filter: Optional[str] = None,
        limit: int = 10
    ) -> List[ConversationSummaryEntry]:
        """
        搜索摘要

        Args:
            query: 搜索关键词
            date_filter: 日期过滤（可选）
            limit: 返回数量限制

        Returns:
            匹配的摘要条目列表
        """
        with self._lock:
            self._ensure_loaded()

            query_lower = query.lower()
            results = []

            for entry in self._cache.values():
                # 日期过滤
                if date_filter and not entry.date.startswith(date_filter):
                    continue

                # 关键词匹配
                if query_lower in entry.summary.lower():
                    results.append(entry)

            # 按时间倒序排序
            results.sort(key=lambda x: x.timestamp, reverse=True)

            return results[:limit]

    def delete(self, key: str) -> bool:
        """
        删除摘要

        Args:
            key: 缓存键

        Returns:
            是否删除成功
        """
        with self._lock:
            self._ensure_loaded()
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    def clear(self):
        """清空缓存"""
        with self._lock:
            self._cache.clear()

    def get_all(self) -> Dict[str, ConversationSummaryEntry]:
        """获取所有摘要"""
        with self._lock:
            self._ensure_loaded()
            return dict(self._cache)

    def format_summary_output(
        self,
        entries: List[ConversationSummaryEntry],
        query: str = ""
    ) -> str:
        """
        格式化摘要输出

        Args:
            entries: 摘要条目列表
            query: 搜索查询（用于标题）

        Returns:
            格式化的输出字符串
        """
        if not entries:
            return "未找到匹配的记忆"

        # 构建输出
        lines = []

        # 标题
        if query:
            lines.append(f"【记忆摘要】搜索 '{query}' ({len(entries)} 条)")
        else:
            lines.append(f"【记忆摘要】共 {len(entries)} 条")

        lines.append("")
        lines.append("提示: 使用 memory_recall_by_id 获取完整内容")
        lines.append("")

        # 按日期分组
        by_date: Dict[str, List[ConversationSummaryEntry]] = {}
        for entry in entries:
            if entry.date not in by_date:
                by_date[entry.date] = []
            by_date[entry.date].append(entry)

        # 输出
        for date in sorted(by_date.keys(), reverse=True):
            date_entries = by_date[date]
            lines.append(f"[{date}]")

            for entry in date_entries:
                role_label = "用户" if entry.role == "user" else "助手"
                lines.append(f"  {entry.session_id} ({role_label})")
                lines.append(f"    摘要: {entry.summary}")
                lines.append(f"    召回: {entry.recall_hint}")
                lines.append("")

        return "\n".join(lines)


# 全局单例
_summary_cache: Optional[SummaryCache] = None


def get_summary_cache() -> SummaryCache:
    """获取全局摘要缓存实例"""
    global _summary_cache
    if _summary_cache is None:
        _summary_cache = SummaryCache()
    return _summary_cache


def reset_summary_cache():
    """重置全局摘要缓存"""
    global _summary_cache
    _summary_cache = None
