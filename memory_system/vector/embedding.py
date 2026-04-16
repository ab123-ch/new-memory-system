"""向量嵌入接口 - 支持多种嵌入模型"""
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
import asyncio
import os
import json
from pathlib import Path
import yaml


def _load_model_config() -> Dict[str, Any]:
    """从 model_config.yaml 读取模型配置"""
    config = {}
    possible_paths = [
        Path.cwd() / "model_config.yaml",
        Path(__file__).parent.parent.parent / "model_config.yaml",
        Path.home() / ".claude" / "mcp" / "memory" / "model_config.yaml",
        Path.home() / "model_config.yaml",
    ]
    for p in possible_paths:
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    config = yaml.safe_load(f) or {}
                break
            except (yaml.YAMLError, IOError):
                pass
    return config


_MODEL_CONFIG = _load_model_config()


def _get_api_key_from_settings(key_name: str) -> Optional[str]:
    """从 Claude settings.json 读取 API Key"""
    settings_path = Path.home() / ".claude" / "settings.json"
    if settings_path.exists():
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("env", {}).get(key_name)
        except (json.JSONDecodeError, IOError):
            pass
    return None


def _resolve_api_key(key_name: str, explicit_key: Optional[str] = None) -> Optional[str]:
    """
    获取 API Key，优先级: 显式传入 > model_config.yaml > Claude settings > 环境变量
    """
    if explicit_key:
        return explicit_key

    # 从 model_config.yaml 读取（优先 embedding，其次 llm）
    emb_config = _MODEL_CONFIG.get("embedding", {})
    api_key = emb_config.get("api_key")
    if api_key:
        return api_key

    llm_config = _MODEL_CONFIG.get("llm", {})
    api_key = llm_config.get("api_key")
    if api_key:
        return api_key

    # 从 Claude settings 读取
    key = _get_api_key_from_settings(key_name)
    if key:
        return key

    return os.environ.get(key_name)


class EmbeddingProvider(ABC):
    """嵌入模型基类"""

    @abstractmethod
    async def embed(self, text: str) -> List[float]:
        """生成文本嵌入向量"""
        pass

    @abstractmethod
    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """批量生成嵌入向量"""
        pass

    @abstractmethod
    def get_dimensions(self) -> int:
        """获取向量维度"""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """检查服务是否可用"""
        pass


class ZhipuEmbedding(EmbeddingProvider):
    """
    智谱 GLM 嵌入实现

    使用 zhipuai SDK，模型: embedding-3
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "embedding-3",
        dimensions: int = 1024
    ):
        self.api_key = _resolve_api_key("ZHIPU_API_KEY", api_key)
        self.model = model
        self.dimensions = dimensions
        self._client = None
        self._available = None

    def _get_client(self):
        """懒加载客户端"""
        if self._client is None:
            try:
                from zhipuai import ZhipuAI
                if not self.api_key:
                    raise ValueError("ZHIPU_API_KEY not set")
                self._client = ZhipuAI(api_key=self.api_key)
            except ImportError:
                raise ImportError(
                    "zhipuai not installed. Run: pip install zhipuai"
                )
        return self._client

    async def embed(self, text: str) -> List[float]:
        """生成单个文本的嵌入向量"""
        client = self._get_client()

        def _call():
            response = client.embeddings.create(
                model=self.model,
                input=text,
                dimensions=self.dimensions
            )
            return response.data[0].embedding

        # 在线程池中执行同步调用
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _call)

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """批量生成嵌入向量"""
        # 智谱 API 支持批量，但这里简单逐个处理
        results = []
        for text in texts:
            embedding = await self.embed(text)
            results.append(embedding)
        return results

    def get_dimensions(self) -> int:
        return self.dimensions

    def is_available(self) -> bool:
        """检查是否可用"""
        if self._available is not None:
            return self._available

        if not self.api_key:
            self._available = False
            return False

        try:
            # 尝试加载 zhipuai
            import zhipuai  # noqa: F401
            self._available = True
        except ImportError:
            self._available = False

        return self._available


class OpenAIEmbedding(EmbeddingProvider):
    """
    OpenAI 嵌入实现

    模型: text-embedding-3-small / text-embedding-3-large
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "text-embedding-3-small",
        dimensions: int = 1536,
        base_url: Optional[str] = None
    ):
        self.api_key = _resolve_api_key("OPENAI_API_KEY", api_key)
        self.model = model
        self.dimensions = dimensions
        self.base_url = base_url
        self._client = None
        self._available = None

    def _get_client(self):
        """懒加载客户端"""
        if self._client is None:
            try:
                from openai import OpenAI
                if not self.api_key:
                    raise ValueError("OPENAI_API_KEY not set")
                kwargs = {"api_key": self.api_key}
                if self.base_url:
                    kwargs["base_url"] = self.base_url
                self._client = OpenAI(**kwargs)
            except ImportError:
                raise ImportError(
                    "openai not installed. Run: pip install openai"
                )
        return self._client

    async def embed(self, text: str) -> List[float]:
        """生成单个文本的嵌入向量"""
        client = self._get_client()

        def _call():
            response = client.embeddings.create(
                model=self.model,
                input=text,
                dimensions=self.dimensions
            )
            return response.data[0].embedding

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _call)

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """批量生成嵌入向量"""
        client = self._get_client()

        def _call():
            response = client.embeddings.create(
                model=self.model,
                input=texts,
                dimensions=self.dimensions
            )
            return [item.embedding for item in response.data]

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _call)

    def get_dimensions(self) -> int:
        return self.dimensions

    def is_available(self) -> bool:
        if self._available is not None:
            return self._available

        if not self.api_key:
            self._available = False
            return False

        try:
            import openai  # noqa: F401
            self._available = True
        except ImportError:
            self._available = False

        return self._available


class MockEmbedding(EmbeddingProvider):
    """
    模拟嵌入（用于测试或无 API 时回退）

    生成随机向量，不推荐生产使用
    """

    def __init__(self, dimensions: int = 128):
        self.dimensions = dimensions

    async def embed(self, text: str) -> List[float]:
        """基于文本哈希生成伪向量"""
        import hashlib

        # 使用文本哈希作为种子
        hash_bytes = hashlib.md5(text.encode()).digest()
        seed = int.from_bytes(hash_bytes[:4], "big")

        import random
        random.seed(seed)

        # 生成归一化向量
        vec = [random.gauss(0, 1) for _ in range(self.dimensions)]
        norm = sum(x * x for x in vec) ** 0.5
        return [x / norm for x in vec]

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        return [await self.embed(t) for t in texts]

    def get_dimensions(self) -> int:
        return self.dimensions

    def is_available(self) -> bool:
        return True


def create_embedding_provider(
    provider: str = "zhipu",
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    dimensions: int = 1024,
    base_url: Optional[str] = None
) -> EmbeddingProvider:
    """
    创建嵌入提供者

    Args:
        provider: 提供者类型 (zhipu, openai, mock)
        api_key: API 密钥
        model: 模型名称
        dimensions: 向量维度
        base_url: API 基础 URL

    Returns:
        EmbeddingProvider: 嵌入提供者实例
    """
    provider = provider.lower()

    if provider == "zhipu":
        return ZhipuEmbedding(
            api_key=api_key,
            model=model or "embedding-3",
            dimensions=dimensions
        )
    elif provider == "openai":
        return OpenAIEmbedding(
            api_key=api_key,
            model=model or "text-embedding-3-small",
            dimensions=dimensions,
            base_url=base_url
        )
    elif provider == "mock" or provider == "none":
        return MockEmbedding(dimensions=dimensions)
    else:
        raise ValueError(f"Unknown embedding provider: {provider}")
