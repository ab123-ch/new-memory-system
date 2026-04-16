"""ChromaDB 向量存储实现"""
from typing import List, Optional, Dict, Any
from pathlib import Path
import asyncio

from .vector_store import VectorStore, MemoryVector, SearchResult, cosine_similarity
from .embedding import EmbeddingProvider, MockEmbedding

# 统一日志
try:
    from ..logging_config import get_logger
    _logger = get_logger("chroma_store", "mcp")
except ImportError:
    import logging
    _logger = logging.getLogger(__name__)


class ChromaVectorStore(VectorStore):
    """
    ChromaDB 向量存储实现

    特点：
    - 持久化存储
    - 支持元数据过滤
    - 高性能 ANN 搜索
    """

    def __init__(
        self,
        persist_path: str = "./data/vectors",
        collection_name: str = "memories",
        embedding_provider: Optional[EmbeddingProvider] = None
    ):
        self.persist_path = persist_path
        self.collection_name = collection_name
        self.embedding_provider = embedding_provider or MockEmbedding()
        self._client = None
        self._collection = None
        self._available = None

    def _get_client(self):
        """懒加载 ChromaDB 客户端"""
        if self._client is None:
            try:
                import chromadb
                from chromadb.config import Settings

                # 确保目录存在
                Path(self.persist_path).mkdir(parents=True, exist_ok=True)

                self._client = chromadb.PersistentClient(
                    path=self.persist_path,
                    settings=Settings(anonymized_telemetry=False)
                )
            except ImportError:
                raise ImportError(
                    "chromadb not installed. Run: pip install chromadb"
                )
        return self._client

    def _get_collection(self):
        """获取或创建集合"""
        if self._collection is None:
            client = self._get_client()
            self._collection = client.get_or_create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": "cosine"}
            )
        return self._collection

    async def add(self, memory: MemoryVector) -> bool:
        """添加记忆向量"""
        try:
            collection = self._get_collection()

            # 如果没有嵌入向量，生成一个
            embedding = memory.embedding
            if not embedding:
                embedding = await self.embedding_provider.embed(memory.content)

            def _add():
                collection.add(
                    ids=[memory.id],
                    embeddings=[embedding],
                    documents=[memory.content],
                    metadatas=[self._build_metadata(memory)]
                )

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, _add)
            return True
        except Exception as e:
            _logger.error(f"添加向量失败: {e}")
            return False

    async def add_batch(self, memories: List[MemoryVector]) -> bool:
        """批量添加记忆向量"""
        if not memories:
            return True

        try:
            collection = self._get_collection()

            ids = [m.id for m in memories]
            documents = [m.content for m in memories]
            metadatas = [self._build_metadata(m) for m in memories]

            # 生成嵌入向量
            embeddings = []
            for m in memories:
                if m.embedding:
                    embeddings.append(m.embedding)
                else:
                    emb = await self.embedding_provider.embed(m.content)
                    embeddings.append(emb)

            def _add():
                collection.add(
                    ids=ids,
                    embeddings=embeddings,
                    documents=documents,
                    metadatas=metadatas
                )

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, _add)
            return True
        except Exception as e:
            _logger.error(f"批量添加向量失败: {e}")
            return False

    async def search(
        self,
        query_embedding: List[float],
        top_k: int = 5,
        filter_dict: Optional[Dict[str, Any]] = None
    ) -> List[SearchResult]:
        """语义搜索"""
        try:
            collection = self._get_collection()

            # 构建过滤条件
            where = None
            if filter_dict:
                conditions = []
                for key, value in filter_dict.items():
                    conditions.append({key: value})
                if len(conditions) == 1:
                    where = conditions[0]
                elif conditions:
                    where = {"$and": conditions}

            def _query():
                return collection.query(
                    query_embeddings=[query_embedding],
                    n_results=top_k,
                    where=where,
                    include=["documents", "metadatas", "distances"]
                )

            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(None, _query)

            # 转换结果
            search_results = []
            if results and results["ids"] and results["ids"][0]:
                for i, id_ in enumerate(results["ids"][0]):
                    distance = results["distances"][0][i] if results.get("distances") else 0
                    # ChromaDB 返回的是距离，转换为相似度 (1 - distance for cosine)
                    score = 1 - distance if distance is not None else 0

                    search_results.append(SearchResult(
                        id=id_,
                        content=results["documents"][0][i] if results.get("documents") else "",
                        score=score,
                        metadata=results["metadatas"][0][i] if results.get("metadatas") else {}
                    ))

            return search_results
        except Exception as e:
            _logger.error(f"搜索失败: {e}")
            return []

    async def delete(self, memory_id: str) -> bool:
        """删除记忆向量"""
        try:
            collection = self._get_collection()

            def _delete():
                collection.delete(ids=[memory_id])

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, _delete)
            return True
        except Exception as e:
            _logger.error(f"删除向量失败: {e}")
            return False

    async def delete_by_filter(self, filter_dict: Dict[str, Any]) -> int:
        """按条件删除"""
        try:
            collection = self._get_collection()

            # 构建过滤条件
            where = None
            conditions = []
            for key, value in filter_dict.items():
                conditions.append({key: value})
            if len(conditions) == 1:
                where = conditions[0]
            elif conditions:
                where = {"$and": conditions}

            if not where:
                return 0

            def _delete():
                collection.delete(where=where)

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, _delete)
            return 1  # ChromaDB 不返回删除数量
        except Exception as e:
            _logger.error(f"按条件删除失败: {e}")
            return 0

    async def get(self, memory_id: str) -> Optional[MemoryVector]:
        """获取单个记忆向量"""
        try:
            collection = self._get_collection()

            def _get():
                return collection.get(ids=[memory_id])

            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(None, _get)

            if results and results["ids"]:
                return MemoryVector(
                    id=results["ids"][0],
                    content=results["documents"][0] if results.get("documents") else "",
                    embedding=[],  # ChromaDB 默认不返回嵌入向量
                    metadata=results["metadatas"][0] if results.get("metadatas") else {}
                )
            return None
        except Exception as e:
            _logger.error(f"获取向量失败: {e}")
            return None

    async def count(self) -> int:
        """获取总数量"""
        try:
            collection = self._get_collection()
            return collection.count()
        except Exception:
            return 0

    async def is_available(self) -> bool:
        """检查是否可用"""
        if self._available is not None:
            return self._available

        try:
            import chromadb  # noqa: F401
            # 尝试初始化
            self._get_client()
            self._available = True
        except ImportError:
            self._available = False
        except Exception as e:
            _logger.warning(f"ChromaDB 不可用: {e}")
            self._available = False

        return self._available

    async def clear(self) -> bool:
        """清空所有数据"""
        try:
            client = self._get_client()
            client.delete_collection(self.collection_name)
            self._collection = None
            return True
        except Exception as e:
            _logger.error(f"清空失败: {e}")
            return False

    def _build_metadata(self, memory: MemoryVector) -> Dict[str, Any]:
        """构建元数据"""
        metadata = dict(memory.metadata)
        if memory.date:
            metadata["date"] = memory.date
        if memory.session_id:
            metadata["session_id"] = memory.session_id
        if memory.role:
            metadata["role"] = memory.role
        metadata["memory_type"] = memory.memory_type
        metadata["created_at"] = memory.created_at.isoformat()
        return metadata


class NoVectorStore(VectorStore):
    """
    无向量存储的回退实现

    用于没有安装向量数据库时，仅使用内存存储（重启丢失）
    """

    def __init__(self):
        self._memories: Dict[str, MemoryVector] = {}

    async def add(self, memory: MemoryVector) -> bool:
        self._memories[memory.id] = memory
        return True

    async def add_batch(self, memories: List[MemoryVector]) -> bool:
        for m in memories:
            self._memories[m.id] = m
        return True

    async def search(
        self,
        query_embedding: List[float],
        top_k: int = 5,
        filter_dict: Optional[Dict[str, Any]] = None
    ) -> List[SearchResult]:
        """暴力搜索（性能差，仅用于回退）"""
        results = []

        for memory in self._memories.values():
            # 过滤条件
            if filter_dict:
                match = True
                for key, value in filter_dict.items():
                    if memory.metadata.get(key) != value:
                        match = False
                        break
                if not match:
                    continue

            # 计算相似度
            if memory.embedding:
                score = cosine_similarity(query_embedding, memory.embedding)
            else:
                score = 0

            results.append(SearchResult(
                id=memory.id,
                content=memory.content,
                score=score,
                metadata=memory.metadata
            ))

        # 排序并返回 top_k
        results.sort(key=lambda x: x.score, reverse=True)
        return results[:top_k]

    async def delete(self, memory_id: str) -> bool:
        if memory_id in self._memories:
            del self._memories[memory_id]
            return True
        return False

    async def delete_by_filter(self, filter_dict: Dict[str, Any]) -> int:
        count = 0
        to_delete = []

        for id_, memory in self._memories.items():
            match = True
            for key, value in filter_dict.items():
                if memory.metadata.get(key) != value:
                    match = False
                    break
            if match:
                to_delete.append(id_)
                count += 1

        for id_ in to_delete:
            del self._memories[id_]

        return count

    async def get(self, memory_id: str) -> Optional[MemoryVector]:
        return self._memories.get(memory_id)

    async def count(self) -> int:
        return len(self._memories)

    async def is_available(self) -> bool:
        return True

    async def clear(self) -> bool:
        self._memories.clear()
        return True


def create_vector_store(
    provider: str = "chroma",
    persist_path: str = "./data/vectors",
    embedding_provider: Optional[EmbeddingProvider] = None
) -> VectorStore:
    """
    创建向量存储实例

    Args:
        provider: 存储类型 (chroma, none)
        persist_path: 持久化路径
        embedding_provider: 嵌入提供者

    Returns:
        VectorStore: 向量存储实例
    """
    provider = provider.lower()

    if provider == "chroma":
        store = ChromaVectorStore(
            persist_path=persist_path,
            embedding_provider=embedding_provider
        )
        # 检查是否真正可用
        import asyncio
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # 异步检查
            return store
        else:
            # 同步检查
            if store.is_available():
                return store
            else:
                return NoVectorStore()
    else:
        return NoVectorStore()
