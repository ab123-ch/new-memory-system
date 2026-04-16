"""AI 摘要器 - 使用 LLM 生成智能摘要"""
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from .llm_service import LLMService, get_llm_service
from .llm_client import LLMClient
from ..config import get_config, AIConfig
from ..extraction.summarizer import Summarizer, SummaryResult

# 统一日志
try:
    from ..logging_config import get_logger
    _logger = get_logger("ai_summarizer", "mcp")
except ImportError:
    import logging
    _logger = logging.getLogger(__name__)


@dataclass
class AISummaryResult(SummaryResult):
    """AI 摘要结果（继承基础结果）"""
    ai_generated: bool = False  # 是否由 AI 生成
    model: str = ""  # 使用的模型


class AISummarizer(Summarizer):
    """
    AI 增强摘要器

    优先使用 LLM 生成摘要，失败时回退到规则方法
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
        self._fallback_summarizer = Summarizer()  # 规则方法回退

    def _get_llm_client(self) -> Optional[LLMClient]:
        """获取 LLM 客户端（优先使用统一服务层）"""
        if self._llm_client is not None:
            return self._llm_client
        return self._llm_service.client

    async def summarize_session(
        self,
        conversations: List[Dict[str, Any]],
        max_length: int = 200
    ) -> SummaryResult:
        """
        为会话生成摘要

        优先使用 AI，失败时回退到规则方法
        """
        if not conversations:
            return AISummaryResult(
                summary="",
                main_points=[],
                sentiment="neutral",
                confidence=0.0,
                ai_generated=False
            )

        # 尝试 AI 摘要
        if self.config.enabled and self.config.summarization_enabled:
            try:
                result = await self._ai_summarize(conversations, max_length)
                if result:
                    return result
            except Exception as e:
                _logger.warning(f"AI 摘要失败，回退到规则方法: {e}")

        # 回退到规则方法
        fallback_result = await self._fallback_summarizer.summarize_session(
            conversations, max_length
        )
        return AISummaryResult(
            summary=fallback_result.summary,
            main_points=fallback_result.main_points,
            sentiment=fallback_result.sentiment,
            confidence=fallback_result.confidence,
            ai_generated=False
        )

    async def _ai_summarize(
        self,
        conversations: List[Dict[str, Any]],
        max_length: int
    ) -> Optional[AISummaryResult]:
        """使用 AI 生成摘要"""
        client = self._get_llm_client()
        if not client or not client.is_available():
            return None

        # 构建提示词
        conversation_text = self._format_conversations(conversations)

        prompt = f"""请为以下对话生成一个简洁的摘要，不超过{max_length}字。

对话内容:
{conversation_text}

请按以下格式返回:
摘要: [一句话概括对话主要内容]
要点: [用分号分隔的2-3个要点]
情感: [positive/negative/neutral]"""

        try:
            response = await client.complete(
                prompt,
                temperature=self.config.llm.temperature,
                max_tokens=self.config.llm.max_tokens
            )

            # 解析响应
            content = response.content
            summary, main_points, sentiment = self._parse_ai_response(content)

            return AISummaryResult(
                summary=summary[:max_length],
                main_points=main_points,
                sentiment=sentiment,
                confidence=0.9,  # AI 生成的高置信度
                ai_generated=True,
                model=response.model
            )
        except Exception as e:
            _logger.error(f"AI 摘要调用失败: {e}")
            return None

    def _format_conversations(self, conversations: List[Dict[str, Any]]) -> str:
        """格式化对话文本"""
        lines = []
        for conv in conversations:
            role = "用户" if conv.get("role") == "user" else "助手"
            content = conv.get("content", "")[:200]  # 限制长度
            lines.append(f"{role}: {content}")
        return "\n".join(lines)

    def _parse_ai_response(self, content: str) -> tuple:
        """解析 AI 响应"""
        summary = ""
        main_points = []
        sentiment = "neutral"

        lines = content.strip().split("\n")
        for line in lines:
            line = line.strip()
            if line.startswith("摘要:") or line.startswith("摘要："):
                summary = line.split(":", 1)[-1].split("：", 1)[-1].strip()
            elif line.startswith("要点:") or line.startswith("要点："):
                points_text = line.split(":", 1)[-1].split("：", 1)[-1].strip()
                main_points = [p.strip() for p in points_text.split(";") if p.strip()]
            elif line.startswith("情感:") or line.startswith("情感："):
                sentiment_text = line.split(":", 1)[-1].split("：", 1)[-1].strip().lower()
                if "positive" in sentiment_text or "积极" in sentiment_text:
                    sentiment = "positive"
                elif "negative" in sentiment_text or "消极" in sentiment_text:
                    sentiment = "negative"

        # 如果解析失败，使用整段作为摘要
        if not summary:
            summary = content[:200]

        return summary, main_points, sentiment

    async def update_event_summary(
        self,
        existing_summary: str,
        new_content: str
    ) -> str:
        """使用 AI 更新事件摘要"""
        if not self.config.enabled:
            return await self._fallback_summarizer.update_event_summary(
                existing_summary, new_content
            )

        client = self._get_llm_client()
        if not client or not client.is_available():
            return await self._fallback_summarizer.update_event_summary(
                existing_summary, new_content
            )

        prompt = f"""请合并以下两段事件摘要，生成一个连贯的总结:

已有摘要: {existing_summary}
新内容: {new_content}

请直接输出合并后的摘要（不超过200字）:"""

        try:
            response = await client.complete(
                prompt,
                temperature=0.3,
                max_tokens=200
            )
            return response.content.strip()
        except Exception:
            return await self._fallback_summarizer.update_event_summary(
                existing_summary, new_content
            )
