"""记忆召回 - 查找和加载相关记忆"""
from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Optional, Dict, Any

from ..models import (
    GlobalIndex, DailyMemory, DailyIndex,
    Conversation, Session
)
from ..storage import FileStore
from .trigger import TriggerResult

# 统一日志
try:
    from ..logging_config import get_logger
    _logger = get_logger("recall", "mcp")
except ImportError:
    import logging
    _logger = logging.getLogger(__name__)


@dataclass
class RecallResult:
    """召回结果"""
    need_recall: bool
    memories: List[Dict[str, Any]] = None
    recall_prompt: str = ""
    matched_sessions: List[str] = None
    matched_dates: List[str] = None
    semantic_results: List[Dict[str, Any]] = None  # 语义搜索结果

    def __post_init__(self):
        if self.memories is None:
            self.memories = []
        if self.matched_sessions is None:
            self.matched_sessions = []
        if self.matched_dates is None:
            self.matched_dates = []
        if self.semantic_results is None:
            self.semantic_results = []


class MemoryRecaller:
    """记忆召回器 - 基于文件索引和向量搜索的记忆检索"""

    def __init__(
        self,
        storage_path: str = "./data/memory",
        config=None
    ):
        self.store = FileStore(storage_path)
        self.config = config
        self._vector_store = None
        self._embedding_provider = None
        self._vector_available = None

    async def _init_vector_search(self):
        """初始化向量搜索组件"""
        if self._vector_available is not None:
            return self._vector_available

        if not self.config or not getattr(self.config.vector, 'enabled', False):
            self._vector_available = False
            return False

        try:
            from ..vector import create_embedding_provider, create_vector_store

            # 创建嵌入提供者
            self._embedding_provider = create_embedding_provider(
                provider=self.config.vector.embedding.provider,
                api_key=self.config.vector.embedding.api_key,
                model=self.config.vector.embedding.model,
                dimensions=self.config.vector.embedding.dimensions
            )

            if not self._embedding_provider.is_available():
                self._vector_available = False
                return False

            # 创建向量存储
            self._vector_store = create_vector_store(
                provider=self.config.vector.provider,
                persist_path=self.config.vector.persist_path,
                embedding_provider=self._embedding_provider
            )

            self._vector_available = await self._vector_store.is_available()
            return self._vector_available

        except Exception as e:
            _logger.warning(f"向量搜索初始化失败: {e}")
            self._vector_available = False
            return False

    async def recall(
        self,
        trigger_result: TriggerResult,
        global_index: GlobalIndex,
        max_memories: int = 5
    ) -> RecallResult:
        """
        召回相关记忆

        Args:
            trigger_result: 触发检测结果
            global_index: 全局索引
            max_memories: 最大返回记忆数

        Returns:
            RecallResult: 召回结果
        """
        if not trigger_result.need_recall:
            return RecallResult(need_recall=False)

        # 尝试语义搜索
        semantic_results = []
        if self.config and getattr(self.config.vector, 'enabled', False):
            semantic_results = await self._semantic_search(
                topic=trigger_result.topic,
                max_results=max_memories
            )

        # 索引搜索（传统方法）
        index_memories = []
        # 1. 通过索引定位相关文件
        relevant_files = self._find_relevant_files(
            keywords=trigger_result.search_keywords,
            global_index=global_index
        )

        # 2. 读取具体记忆
        matched_sessions = []
        matched_dates = []

        for file_info in relevant_files[:3]:  # 最多查3个文件
            daily_memory = self.store.load_daily_memory(
                date.fromisoformat(file_info["date"])
            )

            matched = self._match_conversations(
                daily_memory=daily_memory,
                keywords=trigger_result.search_keywords,
                max_results=max_memories - len(index_memories)
            )

            for match in matched:
                index_memories.append({
                    "date": str(daily_memory.date),
                    "session_id": match["session_id"],
                    "content": match["content"],
                    "role": match["role"],
                    "summary": match.get("summary", ""),
                    "relevance": match.get("relevance", 0.5),
                    "source": "index"  # 标记来源
                })
                matched_sessions.append(match["session_id"])
                if str(daily_memory.date) not in matched_dates:
                    matched_dates.append(str(daily_memory.date))

            if len(index_memories) >= max_memories:
                break

        # 合并结果（语义搜索结果优先）
        all_memories = []

        # 添加语义搜索结果
        for mem in semantic_results:
            mem["source"] = "semantic"
            all_memories.append(mem)

        # 添加索引搜索结果（去重）
        seen_keys = set()
        for mem in all_memories:
            key = f"{mem.get('date')}_{mem.get('content', '')[:50]}"
            seen_keys.add(key)

        for mem in index_memories:
            key = f"{mem.get('date')}_{mem.get('content', '')[:50]}"
            if key not in seen_keys:
                all_memories.append(mem)
                seen_keys.add(key)

        # 按相关性排序并限制数量
        all_memories.sort(key=lambda x: x.get("relevance", 0), reverse=True)
        final_memories = all_memories[:max_memories]

        # 更新匹配信息
        for mem in semantic_results:
            session_id = mem.get("session_id", "")
            date_str = mem.get("date", "")
            if session_id and session_id not in matched_sessions:
                matched_sessions.append(session_id)
            if date_str and date_str not in matched_dates:
                matched_dates.append(date_str)

        # 3. 生成召回提示
        recall_prompt = ""
        if final_memories:
            recall_prompt = self._generate_recall_prompt(
                memories=final_memories,
                topic=trigger_result.topic
            )

        return RecallResult(
            need_recall=True,
            memories=final_memories,
            recall_prompt=recall_prompt,
            matched_sessions=matched_sessions,
            matched_dates=matched_dates,
            semantic_results=semantic_results
        )

    async def _semantic_search(
        self,
        topic: str,
        max_results: int = 5
    ) -> List[Dict[str, Any]]:
        """语义搜索"""
        if not await self._init_vector_search():
            return []

        try:
            # 生成查询向量
            query_embedding = await self._embedding_provider.embed(topic)

            # 执行搜索
            results = await self._vector_store.search(
                query_embedding=query_embedding,
                top_k=max_results
            )

            # 转换结果
            memories = []
            for r in results:
                memories.append({
                    "date": r.metadata.get("date", ""),
                    "session_id": r.metadata.get("session_id", ""),
                    "content": r.content,
                    "role": r.metadata.get("role", ""),
                    "summary": "",
                    "relevance": r.score
                })

            return memories

        except Exception as e:
            _logger.warning(f"语义搜索失败: {e}")
            return []

    def _find_relevant_files(
        self,
        keywords: List[str],
        global_index: GlobalIndex
    ) -> List[Dict[str, str]]:
        """通过索引找到相关文件"""
        files = []

        # 检查最近记忆
        for recent in global_index.recent_memories:
            relevance = 0
            for kw in keywords:
                if kw in recent.keywords:
                    relevance += 1
                if kw in recent.summary:
                    relevance += 0.5

            if relevance > 0:
                files.append({
                    "date": recent.date,
                    "file": recent.file,
                    "relevance": relevance
                })

        # 按相关性排序
        files.sort(key=lambda x: x["relevance"], reverse=True)
        return files

    def _match_conversations(
        self,
        daily_memory: DailyMemory,
        keywords: List[str],
        max_results: int = 5
    ) -> List[Dict[str, Any]]:
        """在每日记忆中匹配对话"""
        results = []

        for session in daily_memory.sessions:
            # 检查会话摘要是否匹配
            session_relevance = 0
            for kw in keywords:
                if kw in session.summary:
                    session_relevance += 1

            # 检查会话关键词
            for session_kw in session.keywords:
                for kw in keywords:
                    if kw in session_kw.word or session_kw.word in kw:
                        session_relevance += session_kw.weight

            if session_relevance > 0:
                # 添加会话摘要
                results.append({
                    "session_id": session.session_id,
                    "content": session.summary or "[会话内容]",
                    "role": "summary",
                    "summary": session.summary,
                    "relevance": session_relevance
                })

                # 添加相关对话
                for conv in session.conversations:
                    conv_relevance = 0
                    for kw in keywords:
                        if kw in conv.content:
                            conv_relevance += 1

                    if conv_relevance > 0 and len(results) < max_results:
                        results.append({
                            "session_id": session.session_id,
                            "content": conv.content[:200],  # 限制长度
                            "role": conv.role,
                            "relevance": conv_relevance
                        })

        # 按相关性排序并限制数量
        results.sort(key=lambda x: x["relevance"], reverse=True)
        return results[:max_results]

    def _generate_recall_prompt(
        self,
        memories: List[Dict[str, Any]],
        topic: str
    ) -> str:
        """生成召回提示"""
        if not memories:
            return ""

        prompt_parts = [f"你想起了之前关于'{topic}'的讨论..."]

        for i, mem in enumerate(memories[:3]):
            date_str = mem.get("date", "之前")
            content = mem.get("summary") or mem.get("content", "")[:100]
            source = mem.get("source", "index")

            if content:
                source_hint = " [语义匹配]" if source == "semantic" else ""
                prompt_parts.append(f"- [{date_str}]{source_hint} {content}")

        return "\n".join(prompt_parts)

    def recall_by_event(
        self,
        event_name: str,
        global_index: GlobalIndex
    ) -> RecallResult:
        """通过事件名称召回记忆"""
        memories = []
        matched_dates = []

        # 查找事件
        for event in global_index.active_events:
            if event_name in event.name or event.name in event_name:
                # 加载相关文件
                for file_path in event.related_files:
                    try:
                        # 解析日期
                        date_str = file_path.split("/")[-1].replace(".yaml", "")
                        target_date = date.fromisoformat(date_str)

                        daily_memory = self.store.load_daily_memory(target_date)

                        # 查找相关会话
                        for session in daily_memory.sessions:
                            if session.summary:
                                memories.append({
                                    "date": str(daily_memory.date),
                                    "session_id": session.session_id,
                                    "content": session.summary,
                                    "role": "summary"
                                })
                                matched_dates.append(str(daily_memory.date))
                    except Exception:
                        continue

        recall_prompt = ""
        if memories:
            recall_prompt = f"你想起了关于'{event_name}'的讨论历程..."

        return RecallResult(
            need_recall=len(memories) > 0,
            memories=memories,
            recall_prompt=recall_prompt,
            matched_dates=matched_dates
        )

    def get_session_context(
        self,
        daily_memory: DailyMemory,
        session_id: str
    ) -> List[Dict[str, Any]]:
        """获取特定会话的上下文"""
        for session in daily_memory.sessions:
            if session.session_id == session_id:
                return [
                    {
                        "role": conv.role,
                        "content": conv.content
                    }
                    for conv in session.conversations
                ]
        return []

    def recall_by_id(
        self,
        date_str: str,
        session_id: str,
        conversation_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        通过ID精确召回记忆

        Args:
            date_str: 日期字符串 (如 "2026-02-28")
            session_id: 会话ID (如 "sess_005_20260228")
            conversation_id: 对话ID (可选，如 "conv_001")

        Returns:
            包含完整记忆内容的字典
        """
        try:
            # 解析日期
            target_date = date.fromisoformat(date_str)

            # 加载当天的记忆
            daily_memory = self.store.load_daily_memory(target_date)

            # 查找目标会话
            target_session = None
            for session in daily_memory.sessions:
                if session.session_id == session_id:
                    target_session = session
                    break

            if not target_session:
                return {
                    "success": False,
                    "error": f"未找到会话: {session_id}"
                }

            # 如果指定了对话ID，只返回该对话
            if conversation_id:
                for conv in target_session.conversations:
                    if conv.id == conversation_id or conv.id.endswith(conversation_id):
                        return {
                            "success": True,
                            "date": date_str,
                            "session_id": session_id,
                            "conversation_id": conv.id,
                            "role": conv.role,
                            "content": conv.content,
                            "timestamp": conv.timestamp,
                            "summary": target_session.summary
                        }
                return {
                    "success": False,
                    "error": f"未找到对话: {conversation_id}"
                }

            # 返回整个会话
            conversations = []
            for conv in target_session.conversations:
                conversations.append({
                    "id": conv.id,
                    "role": conv.role,
                    "content": conv.content,
                    "timestamp": conv.timestamp
                })

            return {
                "success": True,
                "date": date_str,
                "session_id": session_id,
                "summary": target_session.summary,
                "keywords": [{"word": kw.word, "type": kw.type, "weight": kw.weight}
                            for kw in target_session.keywords] if target_session.keywords else [],
                "conversations": conversations,
                "started_at": target_session.started_at,
                "ended_at": target_session.ended_at
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    def get_recent_summaries(
        self,
        days: int = 7,
        limit: int = 10,
        persona_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        获取最近的记忆摘要（用于会话开始时注入上下文）

        Args:
            days: 查询最近多少天
            limit: 返回数量限制
            persona_id: 人格ID（可选）

        Returns:
            包含可召回ID的摘要列表
        """
        from datetime import timedelta

        summaries = []
        today = date.today()

        for i in range(days):
            target_date = today - timedelta(days=i)
            try:
                daily_memory = self.store.load_daily_memory(target_date)

                for session in daily_memory.sessions:
                    if session.summary:
                        # 获取第一条用户消息作为简短描述
                        first_user_msg = ""
                        for conv in session.conversations:
                            if conv.role == "user":
                                first_user_msg = conv.content[:80]
                                break

                        summaries.append({
                            "date": str(target_date),
                            "session_id": session.session_id,
                            "summary": session.summary[:150] if session.summary else "",
                            "first_message": first_user_msg,
                            "timestamp": session.started_at,
                            "keywords": [kw.word for kw in session.keywords[:3]] if session.keywords else []
                        })

                        if len(summaries) >= limit:
                            return summaries

            except Exception:
                continue

        return summaries

    def recall_summaries(
        self,
        query: str,
        days: int = 7,
        limit: int = 10
    ) -> Dict[str, Any]:
        """
        以摘要格式召回记忆

        返回轻量级摘要（≤80字符），包含召回提示。
        推荐用于减少上下文占用。

        Args:
            query: 搜索关键词
            days: 搜索最近多少天
            limit: 返回数量限制

        Returns:
            包含摘要列表和格式化输出的字典
        """
        from ..extraction.summary_cache import get_summary_cache
        from datetime import timedelta

        cache = get_summary_cache()
        entries = cache.search(query, date_filter=None, limit=limit)

        # 如果缓存中没有数据，从原始记忆中生成
        if not entries:
            today = date.today()
            query_lower = query.lower()

            for i in range(days):
                target_date = today - timedelta(days=i)
                date_str = str(target_date)

                try:
                    daily_memory = self.store.load_daily_memory(target_date)

                    for session in daily_memory.sessions:
                        # 检查会话摘要是否匹配
                        if session.summary and query_lower in session.summary.lower():
                            entry = cache.create_summary(
                                date=date_str,
                                session_id=session.session_id,
                                role="summary",
                                content=session.summary
                            )
                            entries.append(entry)
                            continue

                        # 检查对话内容是否匹配
                        for conv in session.conversations:
                            if query_lower in conv.content.lower():
                                entry = cache.create_summary(
                                    date=date_str,
                                    session_id=session.session_id,
                                    conversation_id=conv.id,
                                    role=conv.role,
                                    content=conv.content
                                )
                                entries.append(entry)

                except Exception:
                    continue

                if len(entries) >= limit:
                    break

            # 保存新生成的缓存
            if entries:
                for entry in entries:
                    cache.add_entry(entry)
                cache.save()

        # 格式化输出
        output = cache.format_summary_output(entries[:limit], query)

        return {
            "success": True,
            "entries": [e.to_dict() for e in entries[:limit]],
            "formatted_output": output,
            "count": len(entries[:limit])
        }
