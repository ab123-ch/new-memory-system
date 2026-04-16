"""记忆写入 - 保存对话和更新索引"""
from datetime import datetime, date
from typing import List, Optional, Dict, Any

from ..models import (
    SoulMemory, DailyMemory, GlobalIndex, DailyIndex,
    Session, Conversation, Event, Knowledge,
    RecentMemory, HotKeyword, ActiveEvent, FileInfo,
    KeywordType, Keyword, EventStatus,
    ToolCall, ToolResult
)
from ..storage import FileStore

# 统一日志
try:
    from ..logging_config import get_logger
    _logger = get_logger("writer", "mcp")
except ImportError:
    import logging
    _logger = logging.getLogger(__name__)


class MemoryWriter:
    """记忆写入器 - 处理对话保存和索引更新"""

    def __init__(self, storage_path: str = "./data/memory"):
        self.store = FileStore(storage_path)

    async def save_conversation(
        self,
        daily_memory: DailyMemory,
        session: Session,
        role: str,
        content: str,
        recalled_from: Optional[List[Dict[str, str]]] = None,
        tool_calls: Optional[List[ToolCall]] = None,
        tool_results: Optional[List[ToolResult]] = None,
        thinking: Optional[str] = None
    ) -> Conversation:
        """保存单条对话（支持工具调用）"""
        from ..models.daily_memory import RecalledFrom

        recalled = []
        if recalled_from:
            recalled = [
                RecalledFrom(date=r.get("date", ""), summary=r.get("summary", ""))
                for r in recalled_from
            ]

        conv = session.add_conversation(
            role=role,
            content=content,
            recalled_from=recalled,
            tool_calls=tool_calls or [],
            tool_results=tool_results or [],
            thinking=thinking
        )

        # 更新时间戳
        daily_memory.updated_at = datetime.now()

        # 立即持久化到文件
        self.store.save_daily_memory(daily_memory)

        return conv

    async def save_session_summary(
        self,
        daily_memory: DailyMemory,
        session: Session,
        summary: str,
        keywords: List[Dict[str, Any]]
    ):
        """保存会话摘要和关键词"""
        session.summary = summary

        # 更新关键词
        session.keywords = []
        for kw in keywords:
            keyword = Keyword(
                word=kw.get("word", ""),
                type=KeywordType(kw.get("type", "topic")),
                weight=kw.get("weight", 0.5)
            )
            session.keywords.append(keyword)

        daily_memory.updated_at = datetime.now()

    async def update_or_create_event(
        self,
        daily_memory: DailyMemory,
        event_name: str,
        category: str,
        session_id: str,
        summary: str = ""
    ) -> Event:
        """更新或创建事件"""
        # 查找现有事件
        existing_event = None
        for event in daily_memory.events:
            if event_name in event.name or event.name in event_name:
                existing_event = event
                break

        if existing_event:
            existing_event.add_session(session_id)
            if summary:
                existing_event.summary = summary
            existing_event.last_activity = datetime.now()
            return existing_event
        else:
            # 创建新事件
            return daily_memory.add_event(
                name=event_name,
                category=category,
                session_id=session_id
            )

    async def add_knowledge(
        self,
        daily_memory: DailyMemory,
        content: str,
        source_session: str,
        confidence: float = 0.8
    ) -> Knowledge:
        """添加知识"""
        return daily_memory.add_knowledge(
            content=content,
            source=source_session,
            confidence=confidence
        )

    async def update_daily_index(
        self,
        daily_memory: DailyMemory,
        daily_index: Optional[DailyIndex] = None
    ) -> DailyIndex:
        """更新每日索引"""
        if daily_index is None:
            daily_index = self.store.load_daily_index(daily_memory.date)

        # 清空旧索引
        daily_index.keyword_index = {}
        daily_index.event_index = []

        # 重建关键词索引
        for session in daily_memory.sessions:
            for kw in session.keywords:
                daily_index.add_keyword_entry(
                    keyword=kw.word,
                    session_id=session.session_id,
                    relevance=kw.weight,
                    summary=session.summary[:100] if session.summary else ""
                )

        # 重建事件索引
        for event in daily_memory.events:
            daily_index.add_event_entry(
                event_id=event.event_id,
                name=event.name,
                status=event.status.value,
                session_count=len(event.sessions)
            )

        # 更新统计
        total_conversations = sum(
            len(s.conversations) for s in daily_memory.sessions
        )
        daily_index.stats.total_sessions = len(daily_memory.sessions)
        daily_index.stats.total_conversations = total_conversations
        daily_index.stats.total_events = len(daily_memory.events)

        # 提取主要话题
        main_topics = []
        for session in daily_memory.sessions:
            for kw in session.keywords[:2]:
                if kw.word not in main_topics:
                    main_topics.append(kw.word)
        daily_index.stats.main_topics = main_topics[:5]

        return daily_index

    async def update_global_index(
        self,
        daily_memory: DailyMemory,
        global_index: GlobalIndex,
        keywords: Optional[List[str]] = None
    ) -> GlobalIndex:
        """更新全局索引"""
        today_str = str(daily_memory.date)
        file_path = f"{daily_memory.date.strftime('%Y-%m')}/{daily_memory.date.strftime('%Y-%m-%d')}.yaml"

        # 更新最近记忆
        recent_memory = RecentMemory(
            date=today_str,
            file=file_path,
            summary=daily_memory.sessions[-1].summary if daily_memory.sessions else "",
            keywords=keywords or [],
            sessions=len(daily_memory.sessions)
        )
        global_index.add_recent_memory(recent_memory)

        # 更新热门关键词
        if keywords:
            for kw in keywords:
                global_index.update_hot_keyword(kw)

        # 更新进行中的事件
        for event in daily_memory.events:
            if event.status == EventStatus.ACTIVE:
                active_event = ActiveEvent(
                    event_id=event.event_id,
                    name=event.name,
                    started_at=str(event.started_at.date()),
                    last_activity=str(event.last_activity.date()),
                    status="active",
                    related_files=[file_path]
                )
                global_index.add_active_event(active_event)
            else:
                # 移除已完成/暂停的事件
                global_index.complete_event(event.event_id)

        # 更新文件列表
        file_info = FileInfo(
            path=file_path,
            size=self.store.get_file_size(
                self.store.path_manager.get_daily_memory_path(daily_memory.date)
            ),
            sessions=len(daily_memory.sessions)
        )

        # 检查是否已存在
        for i, f in enumerate(global_index.files):
            if f.path == file_path:
                global_index.files[i] = file_info
                break
        else:
            global_index.files.append(file_info)

        return global_index

    async def save_all(
        self,
        daily_memory: DailyMemory,
        global_index: GlobalIndex,
        daily_index: Optional[DailyIndex] = None
    ) -> bool:
        """保存所有更改"""
        try:
            # 保存每日记忆
            if not self.store.save_daily_memory(daily_memory):
                return False

            # 更新并保存每日索引
            daily_index = await self.update_daily_index(daily_memory, daily_index)
            if not self.store.save_daily_index(daily_index):
                return False

            # 保存全局索引
            if not self.store.save_global_index(global_index):
                return False

            return True
        except Exception as e:
            _logger.error(f"保存失败: {e}")
            return False

    async def save_soul(self, soul: SoulMemory) -> bool:
        """保存本元记忆"""
        return self.store.save_soul(soul)

    def update_soul_from_conversation(
        self,
        soul: SoulMemory,
        content: str,
        memory_type: str = "identity"
    ):
        """从对话中提取并更新本元记忆"""
        # 简单的规则匹配（实际应使用AI提取）
        identity_patterns = [
            "我是", "我在", "我的工作是", "我从事",
            "I am", "I work", "I'm a"
        ]

        habit_patterns = [
            "我喜欢", "我习惯", "我偏好", "通常我",
            "I prefer", "I like", "usually I"
        ]

        ability_patterns = [
            "我会", "我能", "我熟悉", "我擅长",
            "I can", "I know", "I'm familiar"
        ]

        content_lower = content.lower()

        # 检测身份信息
        for pattern in identity_patterns:
            if pattern.lower() in content_lower:
                soul.add_identity(content, confirmed=False)
                return

        # 检测习惯偏好
        for pattern in habit_patterns:
            if pattern.lower() in content_lower:
                soul.add_habit(content, confirmed=False)
                return

        # 检测能力特征
        for pattern in ability_patterns:
            if pattern.lower() in content_lower:
                soul.add_ability(content, confirmed=False)
                return
