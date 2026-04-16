"""统一 LLM 服务层 - 连接池模式

提供统一的 LLM 调用接口，支持：
- 单例模式：配置只加载一次，全局共享
- 连接池：管理多个 LLM 客户端实例
- 同步和异步调用方式
- 统一的错误处理和重试机制
- 统计信息：调用次数、成功率、失败率
- 向后兼容的便捷函数

使用方式:
    # 方式1：获取服务实例（推荐）
    from memory_system.ai import get_llm_service

    service = get_llm_service()
    result = await service.acomplete("你好")

    # 方式2：直接使用便捷函数
    from memory_system.ai import llm_complete, llm_chat

    result = await llm_complete("你好")

    # 方式3：同步调用
    from memory_system.ai import llm_complete_sync

    result = llm_complete_sync("你好")
"""
import logging
import threading
import time
import asyncio
from typing import Optional, List, Dict, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime
from functools import wraps

from .llm_client import LLMClient, LLMResponse, create_llm_client, MockLLMClient

logger = logging.getLogger(__name__)


# ========== 统计信息 ==========

@dataclass
class LLMStats:
    """LLM 调用统计信息"""
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    retried_calls: int = 0
    total_tokens: int = 0
    total_latency_ms: float = 0.0
    last_call_time: Optional[datetime] = None
    errors: List[str] = field(default_factory=list)

    def record_success(self, latency_ms: float = 0, tokens: int = 0):
        """记录成功调用"""
        self.total_calls += 1
        self.successful_calls += 1
        self.total_latency_ms += latency_ms
        self.total_tokens += tokens
        self.last_call_time = datetime.now()

    def record_failure(self, error: str, retried: bool = False):
        """记录失败调用"""
        self.total_calls += 1
        self.failed_calls += 1
        if retried:
            self.retried_calls += 1
        self.errors.append(f"{datetime.now().isoformat()}: {error}")
        self.last_call_time = datetime.now()

    @property
    def success_rate(self) -> float:
        """成功率"""
        if self.total_calls == 0:
            return 0.0
        return self.successful_calls / self.total_calls

    @property
    def avg_latency_ms(self) -> float:
        """平均延迟（毫秒）"""
        if self.successful_calls == 0:
            return 0.0
        return self.total_latency_ms / self.successful_calls

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "total_calls": self.total_calls,
            "successful_calls": self.successful_calls,
            "failed_calls": self.failed_calls,
            "retried_calls": self.retried_calls,
            "success_rate": f"{self.success_rate:.1%}",
            "total_tokens": self.total_tokens,
            "avg_latency_ms": f"{self.avg_latency_ms:.1f}ms",
            "last_call_time": self.last_call_time.isoformat() if self.last_call_time else None,
        }


# ========== LLM 服务类 ==========

class LLMService:
    """统一 LLM 服务层 - 单例 + 连接池模式

    所有模块通过此服务获取 LLM 客户端和调用 LLM。
    """

    _instance: Optional['LLMService'] = None
    _lock = threading.Lock()

    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """初始化服务（只执行一次）"""
        if self._initialized:
            return

        self._client: Optional[LLMClient] = None
        self._config: Dict[str, Any] = {}
        self._stats = LLMStats()
        self._call_lock = threading.Lock()  # 调用锁
        self._initialized = True

    @classmethod
    def get_instance(cls) -> 'LLMService':
        """获取单例实例"""
        return cls()

    @classmethod
    def reset_instance(cls):
        """重置单例（用于测试）"""
        with cls._lock:
            cls._instance = None

    @property
    def client(self) -> LLMClient:
        """获取 LLM 客户端（懒加载）"""
        if self._client is None:
            self._client = self._create_client()
        return self._client

    @property
    def stats(self) -> LLMStats:
        """获取统计信息"""
        return self._stats

    def _create_client(self) -> LLMClient:
        """创建 LLM 客户端"""
        try:
            config = self._load_config()

            if config.get("enabled", True):
                client = create_llm_client(
                    provider=config.get("provider", "zhipu"),
                    api_key=config.get("api_key"),
                    model=config.get("model"),
                    base_url=config.get("base_url")
                )
                logger.info(f"LLM 客户端创建成功: provider={config.get('provider', 'zhipu')}")
                return client
            else:
                logger.info("AI 功能已禁用，使用 Mock 客户端")
                return MockLLMClient()

        except Exception as e:
            logger.warning(f"创建 LLM 客户端失败: {e}，使用 Mock 客户端")
            return MockLLMClient()

    def _load_config(self) -> Dict[str, Any]:
        """加载配置"""
        if self._config:
            return self._config

        config = {}

        # 1. 尝试从全局配置加载
        try:
            from ..config import get_config
            global_config = get_config()
            if hasattr(global_config, 'ai') and global_config.ai:
                ai_config = global_config.ai
                config = {
                    "enabled": getattr(ai_config, 'enabled', True),
                    "provider": getattr(ai_config.llm, 'provider', 'zhipu') if hasattr(ai_config, 'llm') else 'zhipu',
                    "api_key": getattr(ai_config.llm, 'api_key', None) if hasattr(ai_config, 'llm') else None,
                    "model": getattr(ai_config.llm, 'model', None) if hasattr(ai_config, 'llm') else None,
                    "base_url": getattr(ai_config.llm, 'base_url', None) if hasattr(ai_config, 'llm') else None,
                }
                self._config = config
                return config
        except Exception:
            pass

        # 2. 尝试从 model_config.yaml 加载
        try:
            import yaml
            from pathlib import Path

            possible_paths = [
                Path.cwd() / "model_config.yaml",
                Path(__file__).parent.parent.parent / "model_config.yaml",  # 项目根目录
                Path(__file__).parent.parent / "model_config.yaml",  # memory_system 目录
                Path.home() / ".claude" / "mcp" / "memory" / "model_config.yaml",
                Path.home() / "model_config.yaml",
            ]

            for p in possible_paths:
                if p.exists():
                    with open(p, "r", encoding="utf-8") as f:
                        yaml_config = yaml.safe_load(f) or {}

                    llm_config = yaml_config.get("llm", {})
                    config = {
                        "enabled": yaml_config.get("ai", {}).get("enabled", True),
                        "provider": llm_config.get("provider", "zhipu"),
                        "api_key": llm_config.get("api_key"),
                        "model": llm_config.get("model"),
                        "base_url": llm_config.get("base_url"),
                    }
                    self._config = config
                    logger.info(f"从 {p} 加载 LLM 配置")
                    return config
        except Exception as e:
            logger.debug(f"加载 model_config.yaml 失败: {e}")

        # 3. 默认配置
        config = {
            "enabled": True,
            "provider": "zhipu",
        }
        self._config = config
        return config

    def configure(self, **kwargs):
        """手动配置服务

        Args:
            provider: 提供者类型
            api_key: API 密钥
            model: 模型名称
            base_url: API 基础 URL
            enabled: 是否启用
        """
        self._config.update(kwargs)
        # 强制重新创建客户端
        self._client = None
        logger.info(f"LLM 服务已重新配置: {kwargs}")

    # ========== 带统计的调用方法 ==========

    async def _call_with_stats(
        self,
        call_func: Callable,
        *args,
        **kwargs
    ) -> LLMResponse:
        """带统计的调用"""
        start_time = time.time()

        try:
            with self._call_lock:
                result = await call_func(*args, **kwargs)

            latency_ms = (time.time() - start_time) * 1000
            # 从 usage 字典中获取 total_tokens
            usage = getattr(result, 'usage', {}) or {}
            tokens = usage.get('total_tokens', 0)
            self._stats.record_success(latency_ms, tokens)

            return result

        except Exception as e:
            self._stats.record_failure(str(e))
            raise

    async def acomplete(
        self,
        prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 500,
        retry: int = 2
    ) -> LLMResponse:
        """异步补全（带重试）

        Args:
            prompt: 提示文本
            temperature: 温度参数
            max_tokens: 最大 token 数
            retry: 重试次数

        Returns:
            LLMResponse: 响应结果
        """
        last_error = None

        for attempt in range(retry + 1):
            try:
                return await self._call_with_stats(
                    self.client.complete,
                    prompt, temperature, max_tokens
                )
            except Exception as e:
                last_error = e
                if attempt < retry:
                    logger.warning(f"LLM 调用失败 (尝试 {attempt + 1}/{retry + 1}): {e}，正在重试...")
                    await asyncio.sleep(1)  # 等待 1 秒后重试
                else:
                    logger.error(f"LLM 调用失败 (已重试 {retry} 次): {e}")

        # 所有重试都失败，使用 Mock 客户端
        logger.warning("所有 LLM 调用都失败，回退到 Mock 客户端")
        mock = MockLLMClient()
        return await mock.complete(prompt, temperature, max_tokens)

    async def achat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 500,
        retry: int = 2
    ) -> LLMResponse:
        """异步聊天（带重试）

        Args:
            messages: 消息列表
            temperature: 温度参数
            max_tokens: 最大 token 数
            retry: 重试次数

        Returns:
            LLMResponse: 响应结果
        """
        last_error = None

        for attempt in range(retry + 1):
            try:
                return await self._call_with_stats(
                    self.client.chat,
                    messages, temperature, max_tokens
                )
            except Exception as e:
                last_error = e
                if attempt < retry:
                    logger.warning(f"LLM 调用失败 (尝试 {attempt + 1}/{retry + 1}): {e}，正在重试...")
                    await asyncio.sleep(1)
                else:
                    logger.error(f"LLM 调用失败 (已重试 {retry} 次): {e}")

        # 所有重试都失败，使用 Mock 客户端
        logger.warning("所有 LLM 调用都失败，回退到 Mock 客户端")
        mock = MockLLMClient()
        return await mock.chat(messages, temperature, max_tokens)

    # ========== 同步接口 ==========

    def complete_sync(
        self,
        prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 500,
        retry: int = 2
    ) -> LLMResponse:
        """同步补全"""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(
                        asyncio.run,
                        self.acomplete(prompt, temperature, max_tokens, retry)
                    )
                    return future.result()
            else:
                return loop.run_until_complete(
                    self.acomplete(prompt, temperature, max_tokens, retry)
                )
        except RuntimeError:
            return asyncio.run(self.acomplete(prompt, temperature, max_tokens, retry))

    def chat_sync(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 500,
        retry: int = 2
    ) -> LLMResponse:
        """同步聊天"""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(
                        asyncio.run,
                        self.achat(messages, temperature, max_tokens, retry)
                    )
                    return future.result()
            else:
                return loop.run_until_complete(
                    self.achat(messages, temperature, max_tokens, retry)
                )
        except RuntimeError:
            return asyncio.run(self.achat(messages, temperature, max_tokens, retry))

    # ========== JSON 生成接口 ==========

    async def agenerate_json(
        self,
        prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 1000,
        retry: int = 2
    ) -> Dict[str, Any]:
        """异步生成 JSON（带重试）

        Args:
            prompt: 提示文本（要求返回 JSON）
            temperature: 温度参数
            max_tokens: 最大 token 数
            retry: 重试次数

        Returns:
            Dict: 解析后的 JSON 对象
        """
        import json
        import re

        response = await self.acomplete(prompt, temperature, max_tokens, retry)
        content = response.content

        # 尝试解析 JSON
        try:
            # 尝试直接解析
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        # 尝试提取 JSON 块
        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        # 尝试提取 ```json 块
        code_block = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', content)
        if code_block:
            try:
                return json.loads(code_block.group(1))
            except json.JSONDecodeError:
                pass

        logger.warning(f"无法解析 JSON 响应: {content[:200]}...")
        return {}

    def generate_json_sync(
        self,
        prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 1000,
        retry: int = 2
    ) -> Dict[str, Any]:
        """同步生成 JSON"""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(
                        asyncio.run,
                        self.agenerate_json(prompt, temperature, max_tokens, retry)
                    )
                    return future.result()
            else:
                return loop.run_until_complete(
                    self.agenerate_json(prompt, temperature, max_tokens, retry)
                )
        except RuntimeError:
            return asyncio.run(self.agenerate_json(prompt, temperature, max_tokens, retry))

    # ========== 类方法快捷接口 ==========

    @classmethod
    async def acomplete_cls(cls, prompt: str, **kwargs) -> LLMResponse:
        """类方法异步补全"""
        return await cls.get_instance().acomplete(prompt, **kwargs)

    @classmethod
    async def achat_cls(cls, messages: List[Dict[str, str]], **kwargs) -> LLMResponse:
        """类方法异步聊天"""
        return await cls.get_instance().achat(messages, **kwargs)

    @classmethod
    def complete_sync_cls(cls, prompt: str, **kwargs) -> LLMResponse:
        """类方法同步补全"""
        return cls.get_instance().complete_sync(prompt, **kwargs)

    @classmethod
    def chat_sync_cls(cls, messages: List[Dict[str, str]], **kwargs) -> LLMResponse:
        """类方法同步聊天"""
        return cls.get_instance().chat_sync(messages, **kwargs)


# ========== 便捷函数（向后兼容） ==========

def get_llm_client() -> LLMClient:
    """获取 LLM 客户端实例

    这是向后兼容的便捷函数，推荐使用 get_llm_service() 获取完整服务。

    Returns:
        LLMClient: LLM 客户端实例
    """
    return LLMService.get_instance().client


def get_llm_service() -> LLMService:
    """获取 LLM 服务实例

    Returns:
        LLMService: LLM 服务实例
    """
    return LLMService.get_instance()


def reset_llm_service():
    """重置 LLM 服务（用于测试）"""
    LLMService.reset_instance()


# ========== 新增：直接调用便捷函数 ==========

async def llm_complete(
    prompt: str,
    temperature: float = 0.3,
    max_tokens: int = 500,
    retry: int = 2
) -> LLMResponse:
    """异步补全便捷函数"""
    return await get_llm_service().acomplete(prompt, temperature, max_tokens, retry)


async def llm_chat(
    messages: List[Dict[str, str]],
    temperature: float = 0.3,
    max_tokens: int = 500,
    retry: int = 2
) -> LLMResponse:
    """异步聊天便捷函数"""
    return await get_llm_service().achat(messages, temperature, max_tokens, retry)


async def llm_generate_json(
    prompt: str,
    temperature: float = 0.3,
    max_tokens: int = 1000,
    retry: int = 2
) -> Dict[str, Any]:
    """异步生成 JSON 便捷函数"""
    return await get_llm_service().agenerate_json(prompt, temperature, max_tokens, retry)


def llm_complete_sync(
    prompt: str,
    temperature: float = 0.3,
    max_tokens: int = 500,
    retry: int = 2
) -> LLMResponse:
    """同步补全便捷函数"""
    return get_llm_service().complete_sync(prompt, temperature, max_tokens, retry)


def llm_chat_sync(
    messages: List[Dict[str, str]],
    temperature: float = 0.3,
    max_tokens: int = 500,
    retry: int = 2
) -> LLMResponse:
    """同步聊天便捷函数"""
    return get_llm_service().chat_sync(messages, temperature, max_tokens, retry)


def llm_generate_json_sync(
    prompt: str,
    temperature: float = 0.3,
    max_tokens: int = 1000,
    retry: int = 2
) -> Dict[str, Any]:
    """同步生成 JSON 便捷函数"""
    return get_llm_service().generate_json_sync(prompt, temperature, max_tokens, retry)


def get_llm_stats() -> LLMStats:
    """获取 LLM 调用统计信息"""
    return get_llm_service().stats
