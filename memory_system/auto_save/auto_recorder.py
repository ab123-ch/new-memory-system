"""自动对话记录器 - 实现每次对话自动保存"""
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
import uuid

from ..config import AutoSaveConfig, get_config
from ..vector import VectorStore, MemoryVector, create_vector_store
from ..vector.embedding import EmbeddingProvider, create_embedding_provider
from ..storage import FileStore
from ..models import DailyMemory, Session

# 统一日志
try:
    from ..logging_config import get_logger
    _logger = get_logger("auto_recorder", "mcp")
except ImportError:
    import logging
    _logger = logging.getLogger(__name__)


@dataclass
class ConversationRecord:
    """对话记录"""
    id: str
    role: str  # user / assistant
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    session_id: Optional[str] = None
    date: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class AutoRecorder:
    """
    自动对话记录器

    功能：
    1. 立即保存到 YAML 文件
    2. 异步索引到向量库（用于语义搜索）
    3. 支持防抖，避免频繁写入
    """

    def __init__(
        self,
        storage_path: str,
        config: Optional[AutoSaveConfig] = None,
        vector_store: Optional[VectorStore] = None,
        embedding_provider: Optional[EmbeddingProvider] = None
    ):
        self.storage_path = storage_path
        self.config = config or get_config().auto_save
        self.store = FileStore(storage_path)

        # 向量存储（懒加载）
        self._vector_store = vector_store
        self._embedding_provider = embedding_provider
        self._vector_available: Optional[bool] = None

        # 防抖
        self._pending_records: List[ConversationRecord] = []
        self._debounce_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

        # 会话状态
        self._current_session_id: Optional[str] = None
        self._current_daily_memory: Optional[DailyMemory] = None
        self._current_session: Optional[Session] = None

    async def initialize(self):
        """初始化（确保目录存在）"""
        from pathlib import Path
        Path(self.storage_path).mkdir(parents=True, exist_ok=True)

    async def record_conversation(
        self,
        daily_memory: DailyMemory,
        session: Session,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> ConversationRecord:
        """
        记录对话

        Args:
            daily_memory: 每日记忆对象
            session: 会话对象
            role: 角色 (user/assistant)
            content: 内容
            metadata: 额外元数据

        Returns:
            ConversationRecord: 记录对象
        """
        # 创建记录
        record = ConversationRecord(
            id=f"{session.session_id}_{uuid.uuid4().hex[:8]}",
            role=role,
            content=content,
            timestamp=datetime.now(),
            session_id=session.session_id,
            date=str(daily_memory.date),
            metadata=metadata or {}
        )

        # 保存状态
        self._current_daily_memory = daily_memory
        self._current_session = session

        # 注意：不再在这里保存到 YAML，由调用方（session.py）负责保存
        # 这样避免与 writer.save_conversation() 重复保存

        # 异步索引到向量库
        if self.config.index_to_vector and self.config.enabled:
            await self._index_to_vector(record)

        return record

    async def _save_to_memory(
        self,
        daily_memory: DailyMemory,
        session: Session,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """保存到内存模型"""
        from ..core import MemoryWriter

        writer = MemoryWriter(self.storage_path)
        await writer.save_conversation(
            daily_memory=daily_memory,
            session=session,
            role=role,
            content=content,
            recalled_from=metadata.get("recalled_from") if metadata else None
        )

        # 更新时间戳
        daily_memory.updated_at = datetime.now()

    async def _index_to_vector(self, record: ConversationRecord):
        """索引到向量库"""
        if not await self._check_vector_available():
            return

        try:
            # 生成嵌入向量
            embedding = await self._embedding_provider.embed(record.content)

            # 创建向量对象
            memory_vector = MemoryVector(
                id=record.id,
                content=record.content,
                embedding=embedding,
                metadata=record.metadata,
                date=record.date,
                session_id=record.session_id,
                role=record.role,
                memory_type="conversation"
            )

            # 添加到向量库
            await self._vector_store.add(memory_vector)
        except Exception as e:
            _logger.warning(f"向量索引失败: {e}")

    async def _check_vector_available(self) -> bool:
        """检查向量存储是否可用"""
        if self._vector_available is not None:
            return self._vector_available

        config = get_config()

        if not config.vector.enabled:
            self._vector_available = False
            return False

        try:
            # 懒加载嵌入提供者
            if self._embedding_provider is None:
                self._embedding_provider = create_embedding_provider(
                    provider=config.vector.embedding.provider,
                    api_key=config.vector.embedding.api_key,
                    model=config.vector.embedding.model,
                    dimensions=config.vector.embedding.dimensions,
                    base_url=config.vector.embedding.base_url
                )

            # 懒加载向量存储
            if self._vector_store is None:
                self._vector_store = create_vector_store(
                    provider=config.vector.provider,
                    persist_path=config.vector.persist_path,
                    embedding_provider=self._embedding_provider
                )

            self._vector_available = await self._vector_store.is_available()
        except Exception as e:
            _logger.warning(f"向量存储初始化失败: {e}")
            self._vector_available = False

        return self._vector_available

    async def flush(self):
        """刷新待写入的记录"""
        async with self._lock:
            if self._pending_records:
                # 批量写入
                pass
            self._pending_records.clear()

    async def save_session(self):
        """保存会话（在会话结束时调用）"""
        if self._current_daily_memory and self._current_session:
            from ..core import MemoryWriter
            from ..extraction import KeywordExtractor, Summarizer

            writer = MemoryWriter(self.storage_path)

            # 生成摘要
            if self._current_session.conversations:
                conversations = [
                    {"role": c.role, "content": c.content}
                    for c in self._current_session.conversations
                ]

                summarizer = Summarizer()
                summary_result = await summarizer.summarize_session(conversations)
                self._current_session.summary = summary_result.summary

                # 提取关键词
                combined_content = " ".join(
                    c.content for c in self._current_session.conversations
                )
                extractor = KeywordExtractor()
                keywords = await extractor.extract(combined_content)

                await writer.save_session_summary(
                    daily_memory=self._current_daily_memory,
                    session=self._current_session,
                    summary=summary_result.summary,
                    keywords=keywords
                )

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "storage_path": self.storage_path,
            "vector_enabled": self._vector_available,
            "current_session": self._current_session_id,
            "pending_records": len(self._pending_records)
        }
