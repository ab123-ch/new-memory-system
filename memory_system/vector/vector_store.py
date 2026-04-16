"""向量存储抽象层 - 定义存储接口和数据结构"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict, Any


@dataclass
class MemoryVector:
    """记忆向量数据结构"""
    id: str  # 唯一标识
    content: str  # 原始文本内容
    embedding: List[float]  # 嵌入向量
    metadata: Dict[str, Any] = field(default_factory=dict)  # 元数据

    # 元数据字段
    date: Optional[str] = None  # 日期 YYYY-MM-DD
    session_id: Optional[str] = None  # 会话 ID
    role: Optional[str] = None  # user / assistant
    memory_type: str = "conversation"  # conversation / summary / event

    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class SearchResult:
    """搜索结果"""
    id: str
    content: str
    score: float  # 相似度分数 (0-1)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def date(self) -> Optional[str]:
        return self.metadata.get("date")

    @property
    def session_id(self) -> Optional[str]:
        return self.metadata.get("session_id")

    @property
    def role(self) -> Optional[str]:
        return self.metadata.get("role")


class VectorStore(ABC):
    """向量存储抽象基类"""

    @abstractmethod
    async def add(self, memory: MemoryVector) -> bool:
        """添加记忆向量"""
        pass

    @abstractmethod
    async def add_batch(self, memories: List[MemoryVector]) -> bool:
        """批量添加记忆向量"""
        pass

    @abstractmethod
    async def search(
        self,
        query_embedding: List[float],
        top_k: int = 5,
        filter_dict: Optional[Dict[str, Any]] = None
    ) -> List[SearchResult]:
        """
        语义搜索

        Args:
            query_embedding: 查询向量
            top_k: 返回结果数量
            filter_dict: 过滤条件 (如 {"date": "2024-01-01"})

        Returns:
            搜索结果列表
        """
        pass

    @abstractmethod
    async def delete(self, memory_id: str) -> bool:
        """删除记忆向量"""
        pass

    @abstractmethod
    async def delete_by_filter(self, filter_dict: Dict[str, Any]) -> int:
        """按条件删除，返回删除数量"""
        pass

    @abstractmethod
    async def get(self, memory_id: str) -> Optional[MemoryVector]:
        """获取单个记忆向量"""
        pass

    @abstractmethod
    async def count(self) -> int:
        """获取总数量"""
        pass

    @abstractmethod
    async def is_available(self) -> bool:
        """检查存储是否可用"""
        pass

    @abstractmethod
    async def clear(self) -> bool:
        """清空所有数据"""
        pass


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """计算余弦相似度"""
    if len(a) != len(b):
        return 0.0

    dot_product = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot_product / (norm_a * norm_b)
