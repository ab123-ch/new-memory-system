"""每日记忆模型 - 按天存储对话记忆"""
from datetime import datetime, date
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from enum import Enum


class KeywordType(str, Enum):
    """关键词类型"""
    TOPIC = "topic"
    TECHNOLOGY = "technology"
    ACTION = "action"
    ENTITY = "entity"


class EventStatus(str, Enum):
    """事件状态"""
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"


class EmotionType(str, Enum):
    """情感类型"""
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    MIXED = "mixed"


class RecalledFrom(BaseModel):
    """召回来源"""
    date: str
    summary: str


class Keyword(BaseModel):
    """关键词"""
    word: str
    type: KeywordType = KeywordType.TOPIC
    weight: float = 0.5


class ToolCall(BaseModel):
    """工具调用"""
    id: str = ""
    name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    """工具结果"""
    tool_call_id: str
    content: str
    is_error: bool = False


class Conversation(BaseModel):
    """单条对话"""
    id: str
    role: str  # "user", "assistant", "tool"
    content: str
    timestamp: datetime = Field(default_factory=datetime.now)
    recalled_from: List[RecalledFrom] = Field(default_factory=list)
    # 新增字段：支持工具调用
    tool_calls: List[ToolCall] = Field(default_factory=list)
    tool_results: List[ToolResult] = Field(default_factory=list)
    # 思考过程（如果有）
    thinking: Optional[str] = None


class Session(BaseModel):
    """单个会话"""
    session_id: str
    started_at: datetime = Field(default_factory=datetime.now)
    ended_at: Optional[datetime] = None

    # 对话内容
    conversations: List[Conversation] = Field(default_factory=list)

    # AI提取的摘要
    summary: str = ""

    # AI提取的关键词
    keywords: List[Keyword] = Field(default_factory=list)

    def add_conversation(
        self,
        role: str,
        content: str,
        recalled_from: Optional[List[RecalledFrom]] = None,
        tool_calls: Optional[List[ToolCall]] = None,
        tool_results: Optional[List[ToolResult]] = None,
        thinking: Optional[str] = None
    ) -> Conversation:
        """添加对话"""
        conv = Conversation(
            id=f"{self.session_id}_conv_{len(self.conversations):03d}",
            role=role,
            content=content,
            recalled_from=recalled_from or [],
            tool_calls=tool_calls or [],
            tool_results=tool_results or [],
            thinking=thinking
        )
        self.conversations.append(conv)
        return conv

    def end(self):
        """结束会话"""
        self.ended_at = datetime.now()


class Event(BaseModel):
    """跨会话的连续事件"""
    event_id: str
    name: str
    category: str = "general"
    status: EventStatus = EventStatus.ACTIVE
    sessions: List[str] = Field(default_factory=list)
    summary: str = ""
    started_at: datetime = Field(default_factory=datetime.now)
    last_activity: datetime = Field(default_factory=datetime.now)

    def add_session(self, session_id: str):
        """添加关联会话"""
        if session_id not in self.sessions:
            self.sessions.append(session_id)
            self.last_activity = datetime.now()


class Knowledge(BaseModel):
    """知识积累"""
    id: str
    content: str
    source: str  # session_id
    confidence: float = 0.8


class Emotion(BaseModel):
    """情感记录"""
    session_id: str
    overall: EmotionType = EmotionType.NEUTRAL
    intensity: float = 0.5
    notes: str = ""


class DailyMemory(BaseModel):
    """每日记忆文件"""
    version: str = "1.0"
    date: date
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    # 当天的会话记录
    sessions: List[Session] = Field(default_factory=list)

    # 当天的事件
    events: List[Event] = Field(default_factory=list)

    # 当天的知识积累
    knowledge: List[Knowledge] = Field(default_factory=list)

    # 当天的情感记录
    emotions: List[Emotion] = Field(default_factory=list)

    def create_session(self) -> Session:
        """创建新会话"""
        session = Session(
            session_id=f"sess_{len(self.sessions):03d}_{self.date.strftime('%Y%m%d')}"
        )
        self.sessions.append(session)
        self.updated_at = datetime.now()
        return session

    def get_current_session(self) -> Optional[Session]:
        """获取当前进行中的会话"""
        for session in reversed(self.sessions):
            if session.ended_at is None:
                return session
        return None

    def add_event(
        self,
        name: str,
        category: str = "general",
        session_id: Optional[str] = None
    ) -> Event:
        """添加事件"""
        event = Event(
            event_id=f"evt_{len(self.events):03d}_{self.date.strftime('%Y%m%d')}",
            name=name,
            category=category
        )
        if session_id:
            event.add_session(session_id)
        self.events.append(event)
        self.updated_at = datetime.now()
        return event

    def add_knowledge(
        self,
        content: str,
        source: str,
        confidence: float = 0.8
    ) -> Knowledge:
        """添加知识"""
        knowledge = Knowledge(
            id=f"kno_{len(self.knowledge):03d}",
            content=content,
            source=source,
            confidence=confidence
        )
        self.knowledge.append(knowledge)
        self.updated_at = datetime.now()
        return knowledge

    def find_event_by_name(self, name: str) -> Optional[Event]:
        """通过名称查找事件"""
        for event in self.events:
            if name in event.name or event.name in name:
                return event
        return None
