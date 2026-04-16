"""向量存储模块 - 提供语义搜索能力"""
from .embedding import (
    EmbeddingProvider, ZhipuEmbedding, OpenAIEmbedding, MockEmbedding,
    create_embedding_provider
)
from .vector_store import VectorStore, MemoryVector, SearchResult
from .chroma_store import ChromaVectorStore, NoVectorStore, create_vector_store

__all__ = [
    "EmbeddingProvider",
    "ZhipuEmbedding",
    "OpenAIEmbedding",
    "MockEmbedding",
    "create_embedding_provider",
    "VectorStore",
    "MemoryVector",
    "SearchResult",
    "ChromaVectorStore",
    "NoVectorStore",
    "create_vector_store",
]
