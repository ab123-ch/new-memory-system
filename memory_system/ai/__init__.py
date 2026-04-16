"""AI 增强模块 - 提供智能摘要和关键词提取

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

    # 方式4：获取客户端（向后兼容）
    from memory_system.ai import get_llm_client

    client = get_llm_client()
"""
from .llm_client import LLMClient, ZhipuClient, OpenAIClient, MockLLMClient, LLMResponse, create_llm_client
from .llm_service import (
    LLMService,
    get_llm_client,
    get_llm_service,
    reset_llm_service,
    get_llm_stats,
    LLMStats,
    # 新增便捷函数
    llm_complete,
    llm_chat,
    llm_generate_json,
    llm_complete_sync,
    llm_chat_sync,
    llm_generate_json_sync,
)
from .ai_summarizer import AISummarizer
from .ai_extractor import AIKeywordExtractor

__all__ = [
    # LLM 客户端
    "LLMClient",
    "ZhipuClient",
    "OpenAIClient",
    "MockLLMClient",
    "LLMResponse",
    "create_llm_client",
    # LLM 服务层（推荐使用）
    "LLMService",
    "get_llm_client",
    "get_llm_service",
    "reset_llm_service",
    "get_llm_stats",
    "LLMStats",
    # 便捷函数（推荐使用）
    "llm_complete",
    "llm_chat",
    "llm_generate_json",
    "llm_complete_sync",
    "llm_chat_sync",
    "llm_generate_json_sync",
    # AI 功能
    "AISummarizer",
    "AIKeywordExtractor",
]
