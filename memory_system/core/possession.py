"""会话初始化 - 夺舍流程"""
from datetime import datetime, date
from typing import Optional, Tuple
from dataclasses import dataclass

from ..models import SoulMemory, DailyMemory, GlobalIndex, Session
from ..storage import FileStore


@dataclass
class InitializationResult:
    """初始化结果"""
    soul: SoulMemory
    daily_memory: DailyMemory
    session: Session
    global_index: GlobalIndex
    is_new_day: bool
    recent_summary: str
    hot_keywords: list[str]
    active_events: list[dict]


class PossessionManager:
    """会话初始化管理器 - 实现"夺舍"流程"""

    def __init__(self, storage_path: str = "./data/memory"):
        self.store = FileStore(storage_path)

    async def initialize(
        self,
        user_id: str = "default_user",
        load_recent_days: int = 3
    ) -> InitializationResult:
        """
        初始化会话 - 夺舍流程

        1. 检查日期，确定是否需要创建新的记忆文件
        2. 加载本元记忆 (soul.yaml)
        3. 加载/创建每日记忆
        4. 加载全局索引
        5. 创建新会话
        6. 返回初始化结果，包含上下文信息
        """
        today = date.today()

        # 1. 加载本元记忆
        soul = self.store.load_soul()
        soul.user_id = user_id

        # 2. 加载/创建今日记忆
        daily_memory = self.store.load_daily_memory(today)
        is_new_day = len(daily_memory.sessions) == 0

        # 3. 创建新会话
        session = daily_memory.create_session()

        # 4. 加载全局索引
        global_index = self.store.load_global_index()

        # 5. 构建上下文信息
        recent_summary = self._build_recent_summary(global_index)
        hot_keywords = global_index.get_hot_keywords(limit=10)
        active_events = [e.model_dump() for e in global_index.active_events]

        return InitializationResult(
            soul=soul,
            daily_memory=daily_memory,
            session=session,
            global_index=global_index,
            is_new_day=is_new_day,
            recent_summary=recent_summary,
            hot_keywords=hot_keywords,
            active_events=active_events
        )

    def _build_recent_summary(self, index: GlobalIndex) -> str:
        """构建最近记忆摘要"""
        if not index.recent_memories:
            return ""

        summaries = []
        for memory in index.recent_memories:
            if memory.summary:
                summaries.append(f"[{memory.date}] {memory.summary}")

        return "\n".join(summaries)

    def get_memory_context(self, soul: SoulMemory, index: GlobalIndex) -> str:
        """生成记忆上下文提示（用于AI）"""
        context_parts = []

        # 本元记忆
        confirmed = soul.get_confirmed_memories()
        if confirmed["identity"]:
            context_parts.append("身份信息: " + ", ".join(confirmed["identity"]))
        if confirmed["habits"]:
            context_parts.append("习惯偏好: " + ", ".join(confirmed["habits"]))
        if confirmed["abilities"]:
            context_parts.append("能力特征: " + ", ".join(confirmed["abilities"]))

        # 热门关键词
        hot_keywords = index.get_hot_keywords(5)
        if hot_keywords:
            context_parts.append("近期话题: " + ", ".join(hot_keywords))

        # 进行中的事件
        if index.active_events:
            events = [f"{e.name}({e.status})" for e in index.active_events[:3]]
            context_parts.append("进行中的事件: " + ", ".join(events))

        return "\n".join(context_parts)

    def build_recall_prompt(
        self,
        memories: list[dict],
        topic: str
    ) -> str:
        """构建召回提示"""
        if not memories:
            return ""

        prompt_parts = [f"你想起了之前关于'{topic}'的讨论..."]

        for mem in memories[:3]:  # 最多3条
            date_str = mem.get("date", "某天")
            summary = mem.get("summary", "")
            if summary:
                prompt_parts.append(f"- [{date_str}] {summary}")

        return "\n".join(prompt_parts)
