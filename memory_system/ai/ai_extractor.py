"""AI 关键词提取器 - 使用 LLM 智能提取关键词"""
from typing import List, Dict, Any, Optional
import json

from .llm_service import LLMService, get_llm_service
from .llm_client import LLMClient
from ..config import get_config, AIConfig
from ..extraction.keyword_extractor import KeywordExtractor, ExtractedKeyword

# 统一日志
try:
    from ..logging_config import get_logger
    _logger = get_logger("ai_extractor", "mcp")
except ImportError:
    import logging
    _logger = logging.getLogger(__name__)


class AIKeywordExtractor(KeywordExtractor):
    """
    AI 增强关键词提取器

    优先使用 LLM 提取关键词，失败时回退到规则方法
    """

    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        config: Optional[AIConfig] = None,
        llm_service: Optional[LLMService] = None
    ):
        super().__init__()
        self.config = config or get_config().ai
        self._llm_service = llm_service or get_llm_service()
        self._llm_client = llm_client  # 向后兼容
        self._fallback_extractor = KeywordExtractor()  # 规则方法回退

    def _get_llm_client(self) -> Optional[LLMClient]:
        """获取 LLM 客户端（优先使用统一服务层）"""
        if self._llm_client is not None:
            return self._llm_client
        return self._llm_service.client

    async def extract(
        self,
        content: str,
        max_keywords: int = 10,
        existing_keywords: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        从内容中提取关键词

        优先使用 AI，失败时回退到规则方法
        """
        # 尝试 AI 提取
        if self.config.enabled and self.config.keyword_extraction_enabled:
            try:
                result = await self._ai_extract(content, max_keywords, existing_keywords)
                if result:
                    return result
            except Exception as e:
                _logger.warning(f"AI 关键词提取失败，回退到规则方法: {e}")

        # 回退到规则方法
        return await self._fallback_extractor.extract(
            content, max_keywords, existing_keywords
        )

    async def _ai_extract(
        self,
        content: str,
        max_keywords: int,
        existing_keywords: Optional[List[str]]
    ) -> Optional[List[Dict[str, Any]]]:
        """使用 AI 提取关键词"""
        client = self._get_llm_client()
        if not client or not client.is_available():
            return None

        # 构建提示词
        existing_text = ""
        if existing_keywords:
            existing_text = f"\n优先关注这些已有关键词: {', '.join(existing_keywords)}"

        prompt = f"""请从以下文本中提取{max_keywords}个最重要的关键词。

文本内容:
{content[:1000]}{existing_text}

请按以下 JSON 格式返回（不要包含其他内容）:
[
  {{"word": "关键词1", "type": "technology|topic|action|entity", "weight": 0.9}},
  {{"word": "关键词2", "type": "technology|topic|action|entity", "weight": 0.8}}
]

类型说明:
- technology: 技术词汇（编程语言、框架、工具）
- topic: 话题词汇（项目名、功能名）
- action: 动作词汇（实现、优化、解决）
- entity: 实体词汇（人名、地名、组织）

weight 范围: 0.5-1.0，越重要越高"""

        try:
            response = await client.complete(
                prompt,
                temperature=0.3,
                max_tokens=500
            )

            # 解析 JSON
            keywords = self._parse_json_response(response.content, max_keywords)
            return keywords
        except Exception as e:
            _logger.error(f"AI 关键词提取调用失败: {e}")
            return None

    def _parse_json_response(
        self,
        content: str,
        max_keywords: int
    ) -> List[Dict[str, Any]]:
        """解析 JSON 响应"""
        # 尝试提取 JSON 部分
        json_str = content.strip()

        # 如果包含 ```json ``` 代码块，提取内容
        if "```json" in json_str:
            start = json_str.find("```json") + 7
            end = json_str.find("```", start)
            json_str = json_str[start:end].strip()
        elif "```" in json_str:
            start = json_str.find("```") + 3
            end = json_str.find("```", start)
            json_str = json_str[start:end].strip()

        # 尝试找到 JSON 数组
        if "[" in json_str and "]" in json_str:
            start = json_str.find("[")
            end = json_str.rfind("]") + 1
            json_str = json_str[start:end]

        try:
            keywords = json.loads(json_str)
            if isinstance(keywords, list):
                # 验证并清理
                result = []
                for kw in keywords[:max_keywords]:
                    if isinstance(kw, dict) and "word" in kw:
                        result.append({
                            "word": str(kw.get("word", "")),
                            "type": kw.get("type", "topic"),
                            "weight": float(kw.get("weight", 0.7))
                        })
                return result
        except json.JSONDecodeError:
            pass

        # JSON 解析失败，尝试简单提取
        return self._fallback_parse(content, max_keywords)

    def _fallback_parse(self, content: str, max_keywords: int) -> List[Dict[str, Any]]:
        """回退解析（当 JSON 解析失败时）"""
        import re

        keywords = []

        # 尝试提取带引号的词
        quoted = re.findall(r'["\']([^"\']+)["\']', content)
        for word in quoted[:max_keywords]:
            if len(word) >= 2 and len(word) <= 20:
                keywords.append({
                    "word": word,
                    "type": "topic",
                    "weight": 0.7
                })

        return keywords

    def extract_from_conversation(
        self,
        user_message: str,
        assistant_message: str
    ) -> List[Dict[str, Any]]:
        """从对话中提取关键词（同步版本，用于兼容）"""
        combined = f"{user_message} {assistant_message}"

        try:
            # 使用 LLMService 的同步接口
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                # 如果有运行中的事件循环，使用线程池
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, self.extract(combined))
                    return future.result()
            except RuntimeError:
                # 没有运行中的事件循环
                return asyncio.run(self.extract(combined))
        except Exception:
            # 回退到同步方法
            return self._fallback_extractor.extract_from_conversation(
                user_message, assistant_message
            )
