"""索引模型 - 用于快速检索记忆"""
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class RecentMemory(BaseModel):
    """最近记忆条目"""
    date: str
    file: str
    summary: str = ""
    keywords: List[str] = Field(default_factory=list)
    sessions: int = 0


class HotKeyword(BaseModel):
    """高热度关键词"""
    word: str
    recall_count: int = 0
    last_recalled: datetime = Field(default_factory=datetime.now)
    weight: float = 0.5


class ActiveEvent(BaseModel):
    """进行中的事件"""
    event_id: str
    name: str
    started_at: str
    last_activity: str
    status: str = "active"
    related_files: List[str] = Field(default_factory=list)


class FileInfo(BaseModel):
    """文件信息"""
    path: str
    size: int = 0
    sessions: int = 0
    created_at: datetime = Field(default_factory=datetime.now)


class KeywordIndexEntry(BaseModel):
    """关键词索引条目"""
    session_id: str
    relevance: float = 0.5
    summary: str = ""


class EventIndexEntry(BaseModel):
    """事件索引条目"""
    event_id: str
    name: str
    status: str = "active"
    session_count: int = 0


class DailyStats(BaseModel):
    """每日统计"""
    total_sessions: int = 0
    total_conversations: int = 0
    total_events: int = 0
    main_topics: List[str] = Field(default_factory=list)


class GlobalIndex(BaseModel):
    """全局记忆索引"""
    version: str = "1.0"
    updated_at: datetime = Field(default_factory=datetime.now)

    # 最近记忆（最近3天）
    recent_memories: List[RecentMemory] = Field(default_factory=list)

    # 高热度关键词
    hot_keywords: List[HotKeyword] = Field(default_factory=list)

    # 进行中的事件
    active_events: List[ActiveEvent] = Field(default_factory=list)

    # 文件列表
    files: List[FileInfo] = Field(default_factory=list)

    def add_recent_memory(self, memory: RecentMemory):
        """添加最近记忆"""
        # 移除同日期的旧记录
        self.recent_memories = [
            m for m in self.recent_memories if m.date != memory.date
        ]
        self.recent_memories.insert(0, memory)

        # 只保留最近3天
        self.recent_memories = self.recent_memories[:3]
        self.updated_at = datetime.now()

    def update_hot_keyword(self, word: str, delta: int = 1):
        """更新关键词热度"""
        for kw in self.hot_keywords:
            if kw.word == word or word in kw.word or kw.word in word:
                kw.recall_count += delta
                kw.last_recalled = datetime.now()
                kw.weight = min(1.0, kw.weight + 0.05)
                self.updated_at = datetime.now()
                return

        # 新关键词
        self.hot_keywords.append(HotKeyword(
            word=word,
            recall_count=delta,
            weight=0.5
        ))
        self.updated_at = datetime.now()

    def add_active_event(self, event: ActiveEvent):
        """添加进行中的事件"""
        # 检查是否已存在
        for i, e in enumerate(self.active_events):
            if e.event_id == event.event_id:
                self.active_events[i] = event
                self.updated_at = datetime.now()
                return

        self.active_events.append(event)
        self.updated_at = datetime.now()

    def complete_event(self, event_id: str):
        """标记事件完成"""
        self.active_events = [
            e for e in self.active_events if e.event_id != event_id
        ]
        self.updated_at = datetime.now()

    def get_hot_keywords(self, limit: int = 10) -> List[str]:
        """获取热门关键词"""
        sorted_keywords = sorted(
            self.hot_keywords,
            key=lambda x: x.weight,
            reverse=True
        )
        return [kw.word for kw in sorted_keywords[:limit]]


class DailyIndex(BaseModel):
    """每日索引文件"""
    date: str

    # 关键词索引
    keyword_index: dict[str, List[KeywordIndexEntry]] = Field(default_factory=dict)

    # 事件索引
    event_index: List[EventIndexEntry] = Field(default_factory=list)

    # 统计信息
    stats: DailyStats = Field(default_factory=DailyStats)

    def add_keyword_entry(
        self,
        keyword: str,
        session_id: str,
        relevance: float,
        summary: str
    ):
        """添加关键词索引"""
        if keyword not in self.keyword_index:
            self.keyword_index[keyword] = []

        # 检查是否已存在
        for entry in self.keyword_index[keyword]:
            if entry.session_id == session_id:
                return

        self.keyword_index[keyword].append(KeywordIndexEntry(
            session_id=session_id,
            relevance=relevance,
            summary=summary
        ))

    def add_event_entry(
        self,
        event_id: str,
        name: str,
        status: str,
        session_count: int
    ):
        """添加事件索引"""
        self.event_index.append(EventIndexEntry(
            event_id=event_id,
            name=name,
            status=status,
            session_count=session_count
        ))

    def search_by_keyword(self, keyword: str) -> List[KeywordIndexEntry]:
        """通过关键词搜索"""
        results = []

        # 精确匹配
        if keyword in self.keyword_index:
            results.extend(self.keyword_index[keyword])

        # 模糊匹配
        for kw, entries in self.keyword_index.items():
            if keyword in kw or kw in keyword:
                if entries not in results:
                    results.extend(entries)

        # 按相关性排序
        results.sort(key=lambda x: x.relevance, reverse=True)
        return results
