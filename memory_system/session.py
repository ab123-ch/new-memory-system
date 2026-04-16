"""会话管理 - MemorySession 和 MemorySystem"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from contextlib import asynccontextmanager

from .models import (
    SoulMemory, DailyMemory, GlobalIndex, DailyIndex, Session
)
from .storage import FileStore
from .core import PossessionManager, TriggerDetector, MemoryRecaller, MemoryWriter
from .extraction import KeywordExtractor, Summarizer, NoiseFilter
from .extraction.summary_cache import get_summary_cache
from .core.trigger import TriggerResult
from .core.recall import RecallResult
from .config import get_config, MemorySystemConfig

# 统一日志
try:
    from .logging_config import get_logger
    _logger = get_logger("session", "mcp")
except ImportError:
    import logging
    _logger = logging.getLogger(__name__)

# 经验学习模块 (已移除)
# from .experience import ExperienceManager
ExperienceManager = None


@dataclass
class ChatResult:
    """对话处理结果"""
    response: str
    recalled: bool = False
    recall_prompt: str = ""
    recalled_memories: List[Dict[str, Any]] = field(default_factory=list)
    session_id: str = ""
    saved: bool = False  # 是否已自动保存


class MemorySession:
    """
    记忆会话 - 管理单次对话会话

    使用方式:
        async with memory_system.start_session() as session:
            result = await session.chat("你好")
            # ...

    v2.0 新功能:
    - 自动保存对话到文件
    - AI 增强的摘要和关键词提取
    - 向量索引支持
    """

    def __init__(
        self,
        storage_path: str,
        user_id: str = "default_user",
        config: Optional[MemorySystemConfig] = None
    ):
        self.storage_path = storage_path
        self.user_id = user_id
        self.config = config or get_config()

        # 基础组件初始化
        self.store = FileStore(storage_path)
        self.possession = PossessionManager(storage_path)
        self.trigger_detector = TriggerDetector()
        self.recaller = MemoryRecaller(
            storage_path,
            config=self.config  # 传递配置以支持向量搜索
        )
        self.writer = MemoryWriter(storage_path)
        self.noise_filter = NoiseFilter()

        # 摘要器和关键词提取器（优先使用 AI 增强版）
        self._init_extraction_components()

        # 自动保存组件
        self._auto_recorder = None
        self._init_auto_save()

        # 经验管理器
        self._experience_manager: Optional[ExperienceManager] = None
        self._init_experience_manager()

        # 状态
        self._initialized = False
        self._soul: Optional[SoulMemory] = None
        self._daily_memory: Optional[DailyMemory] = None
        self._session: Optional[Session] = None
        self._global_index: Optional[GlobalIndex] = None
        self._daily_index: Optional[DailyIndex] = None
        self._context_info: Dict[str, Any] = {}
        self._last_user_message: str = ""  # 存储最后一条用户消息，用于经验提取

    def _init_extraction_components(self):
        """初始化提取组件（优先 AI 增强版）"""
        try:
            from .ai import AISummarizer, AIKeywordExtractor
            self.summarizer = AISummarizer(config=self.config.ai)
            self.keyword_extractor = AIKeywordExtractor(config=self.config.ai)
        except ImportError:
            # 回退到规则版本
            self.summarizer = Summarizer()
            self.keyword_extractor = KeywordExtractor()

    def _init_auto_save(self):
        """初始化自动保存组件"""
        if not self.config.auto_save.enabled:
            return

        try:
            from .auto_save import AutoRecorder
            self._auto_recorder = AutoRecorder(
                storage_path=self.storage_path,
                config=self.config.auto_save
            )
        except ImportError:
            self._auto_recorder = None

    def _init_experience_manager(self):
        """初始化经验管理器（已禁用）"""
        # ExperienceManager 已移除
        self._experience_manager = None

    async def initialize(self) -> Dict[str, Any]:
        """初始化会话 - 夺舍流程"""
        if self._initialized:
            return self._context_info

        # 执行初始化
        result = await self.possession.initialize(self.user_id)

        self._soul = result.soul
        self._daily_memory = result.daily_memory
        self._session = result.session
        self._global_index = result.global_index

        # 加载每日索引
        from datetime import date
        self._daily_index = self.store.load_daily_index(
            self._daily_memory.date
        )

        # 保存上下文信息
        self._context_info = {
            "is_new_day": result.is_new_day,
            "recent_summary": result.recent_summary,
            "hot_keywords": result.hot_keywords,
            "active_events": result.active_events,
            "soul_memory": result.soul.get_confirmed_memories()
        }

        # 初始化自动记录器
        if self._auto_recorder:
            await self._auto_recorder.initialize()

        self._initialized = True
        return self._context_info

    async def chat(
        self,
        user_message: str,
        auto_recall: bool = True
    ) -> ChatResult:
        """
        处理用户消息

        Args:
            user_message: 用户消息
            auto_recall: 是否自动检测并召回记忆

        Returns:
            ChatResult: 处理结果
        """
        if not self._initialized:
            await self.initialize()

        recall_result = RecallResult(need_recall=False)
        recall_prompt = ""

        # 1. 检测是否需要召回
        if auto_recall:
            trigger_result = self.trigger_detector.detect(
                user_message,
                self._global_index
            )

            if trigger_result.need_recall:
                recall_result = await self.recaller.recall(
                    trigger_result,
                    self._global_index
                )
                recall_prompt = recall_result.recall_prompt

        # 2. 保存用户消息
        recalled_from = []
        if recall_result.need_recall and recall_result.memories:
            recalled_from = [
                {"date": m.get("date", ""), "summary": m.get("summary", "")}
                for m in recall_result.memories[:3]
            ]

        # 保存用户消息用于经验提取
        self._last_user_message = user_message

        # 使用 writer 保存到内存
        await self.writer.save_conversation(
            daily_memory=self._daily_memory,
            session=self._session,
            role="user",
            content=user_message,
            recalled_from=recalled_from
        )

        # 3. 自动记录到向量库
        saved = False
        if self._auto_recorder:
            try:
                await self._auto_recorder.record_conversation(
                    daily_memory=self._daily_memory,
                    session=self._session,
                    role="user",
                    content=user_message,
                    metadata={"recalled_from": recalled_from}
                )
                saved = True
            except Exception as e:
                _logger.warning(f"自动记录失败: {e}")

        # 4. 更新热门关键词（如果召回）
        if recall_result.need_recall:
            for date_str in recall_result.matched_dates:
                self._global_index.update_hot_keyword(date_str)

        return ChatResult(
            response="",  # 由外部AI填充
            recalled=recall_result.need_recall,
            recall_prompt=recall_prompt,
            recalled_memories=recall_result.memories,
            session_id=self._session.session_id,
            saved=saved
        )

    async def save_assistant_response(
        self,
        content: str,
        tool_calls: Optional[List[Dict[str, Any]]] = None
    ) -> bool:
        """保存助手响应"""
        if not self._initialized:
            return False

        # 转换工具调用为模型对象
        tool_call_objs = []
        if tool_calls:
            from .models.daily_memory import ToolCall
            for tc in tool_calls:
                tool_call_objs.append(ToolCall(
                    id=tc.get("id", ""),
                    name=tc.get("name", ""),
                    arguments=tc.get("arguments", {})
                ))

        # 保存到内存
        await self.writer.save_conversation(
            daily_memory=self._daily_memory,
            session=self._session,
            role="assistant",
            content=content,
            tool_calls=tool_call_objs
        )

        # 自动记录到向量库
        if self._auto_recorder:
            try:
                await self._auto_recorder.record_conversation(
                    daily_memory=self._daily_memory,
                    session=self._session,
                    role="assistant",
                    content=content
                )
            except Exception as e:
                _logger.warning(f"自动记录助手响应失败: {e}")

        # 自动提取经验（如果有用户消息上下文）
        if self._experience_manager and self._last_user_message:
            try:
                date_str = str(self._daily_memory.date) if self._daily_memory else ""
                experience = await self._experience_manager.extract_and_save_experience(
                    user_message=self._last_user_message,
                    assistant_message=content,
                    session_id=self._session.session_id if self._session else "",
                    date=date_str
                )
                if experience:
                    _logger.info(f"[经验学习] 已自动提取经验: {experience.id} | 类型: {experience.experience_type.display_name}")
            except Exception as e:
                _logger.warning(f"自动提取经验失败: {e}")

        return True

    async def save_tool_call(self, tool_call: Dict[str, Any]) -> bool:
        """
        保存工具调用

        Args:
            tool_call: 工具调用信息，包含 id, name, arguments
        """
        if not self._initialized:
            return False

        from .models.daily_memory import ToolCall

        tool_call_obj = ToolCall(
            id=tool_call.get("id", ""),
            name=tool_call.get("name", ""),
            arguments=tool_call.get("arguments", {})
        )

        # 保存到内存（role 为 assistant，内容为空，但有 tool_calls）
        await self.writer.save_conversation(
            daily_memory=self._daily_memory,
            session=self._session,
            role="assistant",
            content="",
            tool_calls=[tool_call_obj]
        )

        return True

    async def save_tool_result(self, tool_result: Dict[str, Any]) -> bool:
        """
        保存工具结果

        Args:
            tool_result: 工具结果信息，包含 tool_call_id, content, is_error
        """
        if not self._initialized:
            return False

        from .models.daily_memory import ToolResult

        tool_result_obj = ToolResult(
            tool_call_id=tool_result.get("tool_call_id", ""),
            content=tool_result.get("content", ""),
            is_error=tool_result.get("is_error", False)
        )

        # 保存到内存（role 为 tool）
        await self.writer.save_conversation(
            daily_memory=self._daily_memory,
            session=self._session,
            role="tool",
            content=tool_result.get("content", ""),
            tool_results=[tool_result_obj]
        )

        return True

    async def recall(self, topic: str) -> RecallResult:
        """主动召回关于特定话题的记忆"""
        if not self._initialized:
            await self.initialize()

        # 构造触发结果
        trigger_result = TriggerResult(
            need_recall=True,
            topic=topic,
            search_keywords=[topic],
            confidence=1.0
        )

        return await self.recaller.recall(
            trigger_result,
            self._global_index
        )

    async def set_soul_memory(
        self,
        type: str,
        content: str,
        confirmed: bool = True
    ):
        """
        设置本元记忆

        Args:
            type: 类型 - "identity", "habit", "ability"
            content: 内容
            confirmed: 是否已确认
        """
        if not self._initialized:
            await self.initialize()

        if type == "identity":
            self._soul.add_identity(content, confirmed)
        elif type == "habit":
            self._soul.add_habit(content, confirmed)
        elif type == "ability":
            self._soul.add_ability(content, confirmed)

        await self.writer.save_soul(self._soul)

    async def confirm_pending_memory(
        self,
        pending_id: str,
        memory_type: str = "identity"
    ) -> bool:
        """确认待确认的记忆"""
        if not self._initialized:
            await self.initialize()

        result = self._soul.confirm_pending(pending_id, memory_type)
        if result:
            await self.writer.save_soul(self._soul)
        return result

    async def update_event(
        self,
        event_name: str,
        category: str = "general",
        summary: str = ""
    ):
        """更新或创建事件"""
        if not self._initialized:
            await self.initialize()

        await self.writer.update_or_create_event(
            daily_memory=self._daily_memory,
            event_name=event_name,
            category=category,
            session_id=self._session.session_id,
            summary=summary
        )

    def get_context(self) -> Dict[str, Any]:
        """获取当前上下文"""
        if not self._initialized:
            return {}

        context = self.possession.get_memory_context(
            self._soul,
            self._global_index
        )

        return {
            "memory_context": context,
            "session_id": self._session.session_id,
            "date": str(self._daily_memory.date),
            **self._context_info
        }

    async def update_summary(self):
        """更新会话摘要和关键词（不结束会话）"""
        if not self._initialized or not self._session.conversations:
            return

        # 生成会话摘要（使用 AI 增强版）
        conversations = [
            {"role": c.role, "content": c.content}
            for c in self._session.conversations
        ]

        try:
            summary_result = await self.summarizer.summarize_session(conversations)
            self._session.summary = summary_result.summary

            # 提取关键词（使用 AI 增强版）
            combined_content = " ".join(
                c.content for c in self._session.conversations
            )
            keywords = await self.keyword_extractor.extract(combined_content)

            await self.writer.save_session_summary(
                daily_memory=self._daily_memory,
                session=self._session,
                summary=summary_result.summary,
                keywords=keywords
            )

            # 更新索引
            await self.writer.save_all(
                daily_memory=self._daily_memory,
                global_index=self._global_index,
                daily_index=self._daily_index
            )

            # 更新摘要缓存
            try:
                cache = get_summary_cache()
                date_str = self._daily_memory.date.isoformat()
                session_id = self._session.session_id

                # 为每条对话创建摘要
                for conv in self._session.conversations:
                    cache.add(
                        date=date_str,
                        session_id=session_id,
                        conversation_id=conv.id,
                        role=conv.role,
                        content=conv.content
                    )

                # 保存缓存
                cache.save()
            except Exception as e:
                _logger.warning(f"更新摘要缓存失败: {e}")

        except Exception as e:
            _logger.warning(f"更新摘要失败: {e}")

    async def end(self):
        """结束会话并保存"""
        if not self._initialized:
            return

        # 结束会话
        self._session.end()

        # 更新摘要和关键词
        await self.update_summary()

        self._initialized = False

    async def __aenter__(self):
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.end()
        return False


class MemorySystem:
    """
    记忆系统主入口

    使用方式:
        memory_system = MemorySystem("./data/memory")
        async with memory_system.start_session() as session:
            result = await session.chat("你好")
            _logger.debug(f"召回提示: {result.recall_prompt[:100]}...")

    v2.0 新功能:
    - 支持配置文件
    - 语义搜索
    - 自动保存
    """

    def __init__(
        self,
        storage_path: str = "./data/memory",
        config: Optional[MemorySystemConfig] = None
    ):
        self.storage_path = storage_path
        self.config = config or get_config()
        self._sessions: Dict[str, MemorySession] = {}

    def start_session(
        self,
        user_id: str = "default_user"
    ) -> MemorySession:
        """
        开始新会话

        Args:
            user_id: 用户ID

        Returns:
            MemorySession: 会话实例
        """
        session = MemorySession(
            storage_path=self.storage_path,
            user_id=user_id,
            config=self.config
        )

        # 记录会话
        self._sessions[user_id] = session

        return session

    async def get_or_create_session(
        self,
        user_id: str = "default_user"
    ) -> MemorySession:
        """获取或创建会话"""
        if user_id in self._sessions:
            return self._sessions[user_id]

        return self.start_session(user_id)

    async def end_session(self, user_id: str = "default_user"):
        """结束会话"""
        if user_id in self._sessions:
            await self._sessions[user_id].end()
            del self._sessions[user_id]

    @asynccontextmanager
    async def session(self, user_id: str = "default_user"):
        """上下文管理器方式使用会话"""
        sess = self.start_session(user_id)
        try:
            await sess.initialize()
            yield sess
        finally:
            await sess.end()

    def get_soul(self, user_id: str = "default_user") -> SoulMemory:
        """获取本元记忆"""
        store = FileStore(self.storage_path)
        return store.load_soul()

    def get_recent_memories(
        self,
        days: int = 3
    ) -> List[DailyMemory]:
        """获取最近几天的记忆"""
        store = FileStore(self.storage_path)
        return store.load_recent_memories(days)

    def get_global_index(self) -> GlobalIndex:
        """获取全局索引"""
        store = FileStore(self.storage_path)
        return store.load_global_index()

    async def search(
        self,
        query: str,
        days: int = 7,
        use_semantic: bool = True
    ) -> List[Dict[str, Any]]:
        """
        搜索记忆

        Args:
            query: 搜索关键词或查询语句
            days: 搜索最近几天的记忆
            use_semantic: 是否使用语义搜索（需要向量库）

        Returns:
            匹配的记忆列表
        """
        results = []

        # 尝试语义搜索
        if use_semantic and self.config.vector.enabled:
            try:
                semantic_results = await self._semantic_search(query, days)
                if semantic_results:
                    results.extend(semantic_results)
            except Exception as e:
                _logger.warning(f"语义搜索失败，回退到关键词搜索: {e}")

        # 关键词搜索
        keyword_results = await self._keyword_search(query, days)

        # 合并结果（去重）
        seen = set()
        for r in results + keyword_results:
            key = f"{r.get('date')}_{r.get('session_id')}_{r.get('content', '')[:50]}"
            if key not in seen:
                seen.add(key)
                results.append(r)

        # 按相关性排序
        results.sort(key=lambda x: x.get("relevance", 0), reverse=True)
        return results[:20]

    async def _semantic_search(
        self,
        query: str,
        days: int
    ) -> List[Dict[str, Any]]:
        """语义搜索"""
        try:
            from .vector import create_embedding_provider, create_vector_store

            # 创建嵌入提供者
            embedding = create_embedding_provider(
                provider=self.config.vector.embedding.provider,
                api_key=self.config.vector.embedding.api_key,
                model=self.config.vector.embedding.model,
                dimensions=self.config.vector.embedding.dimensions
            )

            if not embedding.is_available():
                return []

            # 生成查询向量
            query_embedding = await embedding.embed(query)

            # 创建向量存储
            store = create_vector_store(
                provider=self.config.vector.provider,
                persist_path=self.config.vector.persist_path,
                embedding_provider=embedding
            )

            if not await store.is_available():
                return []

            # 执行搜索
            from datetime import date, timedelta
            min_date = str(date.today() - timedelta(days=days))

            search_results = await store.search(
                query_embedding=query_embedding,
                top_k=10,
                filter_dict={"date": {"$gte": min_date}}  # ChromaDB 语法可能不同
            )

            # 转换结果
            results = []
            for r in search_results:
                results.append({
                    "date": r.metadata.get("date", ""),
                    "session_id": r.metadata.get("session_id", ""),
                    "type": "semantic",
                    "role": r.metadata.get("role", ""),
                    "content": r.content[:200],
                    "relevance": r.score
                })

            return results
        except Exception as e:
            _logger.error(f"语义搜索错误: {e}")
            return []

    async def _keyword_search(
        self,
        query: str,
        days: int
    ) -> List[Dict[str, Any]]:
        """关键词搜索"""
        store = FileStore(self.storage_path)
        memories = store.load_recent_memories(days)

        results = []
        query_lower = query.lower()

        for daily in memories:
            for session in daily.sessions:
                # 检查会话摘要
                if query_lower in session.summary.lower():
                    results.append({
                        "date": str(daily.date),
                        "session_id": session.session_id,
                        "type": "session_summary",
                        "content": session.summary,
                        "relevance": 1.0
                    })

                # 检查对话内容
                for conv in session.conversations:
                    if query_lower in conv.content.lower():
                        results.append({
                            "date": str(daily.date),
                            "session_id": session.session_id,
                            "type": "conversation",
                            "role": conv.role,
                            "content": conv.content[:200],
                            "relevance": 0.8
                        })

        return results

    async def save_conversation(
        self,
        user_message: str,
        assistant_message: str,
        user_id: str = "default_user",
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        tool_results: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        保存对话（用于 MCP 工具调用）

        Args:
            user_message: 用户消息
            assistant_message: 助手响应
            user_id: 用户 ID
            tool_calls: 工具调用列表（可选）
            tool_results: 工具结果列表（可选）

        Returns:
            保存结果
        """
        # 获取或创建会话
        session = await self.get_or_create_session(user_id)

        # 保存用户消息
        user_result = await session.chat(user_message, auto_recall=False)

        # 保存工具调用（如果有）
        if tool_calls:
            for tc in tool_calls:
                await session.save_tool_call(tc)

        # 保存工具结果（如果有）
        if tool_results:
            for tr in tool_results:
                await session.save_tool_result(tr)

        # 保存助手响应
        await session.save_assistant_response(assistant_message)

        # 更新摘要和关键词（触发 AI 整理）
        # 注意：即使失败也不影响对话保存
        try:
            await session.update_summary()
        except Exception as e:
            _logger.warning(f"更新摘要失败（对话已保存）: {e}")

        # 自动提取经验（如果可用）
        experience_saved = False
        if session._experience_manager:
            try:
                date_str = str(session._daily_memory.date) if session._daily_memory else ""
                experience = await session._experience_manager.extract_and_save_experience(
                    user_message=user_message,
                    assistant_message=assistant_message,
                    session_id=user_result.session_id,
                    date=date_str
                )
                if experience:
                    experience_saved = True
                    _logger.info(f"已自动提取经验: {experience.id}")
            except Exception as e:
                _logger.warning(f"自动提取经验失败: {e}")

        return {
            "success": True,
            "session_id": user_result.session_id,
            "message": "对话已保存",
            "experience_saved": experience_saved
        }

    async def save_conversation_history(
        self,
        messages: List[Dict[str, Any]],
        user_id: str = "default_user"
    ) -> Dict[str, Any]:
        """
        保存完整对话历史（用于 MCP 工具调用）

        Args:
            messages: 对话消息列表，每条消息包含 role, content, 可选的 tool_calls, tool_results
            user_id: 用户 ID

        Returns:
            保存结果
        """
        # 获取或创建会话
        session = await self.get_or_create_session(user_id)

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            tool_calls = msg.get("tool_calls", [])
            tool_results = msg.get("tool_results", [])

            if role == "user":
                await session.chat(content, auto_recall=False)
            elif role == "assistant":
                # 先保存工具调用
                for tc in tool_calls:
                    await session.save_tool_call(tc)
                # 保存助手响应
                await session.save_assistant_response(content)
            elif role == "tool":
                # 保存工具结果
                for tr in tool_results:
                    await session.save_tool_result(tr)

        # 更新摘要
        try:
            await session.update_summary()
        except Exception as e:
            _logger.warning(f"更新摘要失败（对话已保存）: {e}")

        return {
            "success": True,
            "session_id": session._session.session_id if session._session else "unknown",
            "message": "对话历史已保存"
        }
