"""摘要生成器 - 为会话和事件生成摘要"""
from dataclasses import dataclass
from typing import List, Dict, Any, Optional


@dataclass
class SummaryResult:
    """摘要结果"""
    summary: str
    main_points: List[str]
    sentiment: str  # positive, negative, neutral
    confidence: float


class Summarizer:
    """
    摘要生成器

    功能：
    1. 会话摘要生成
    2. 事件摘要更新
    3. 情感分析
    4. 要点提取
    """

    # 情感词汇
    POSITIVE_WORDS = {
        "好", "棒", "优秀", "成功", "解决", "完成", "喜欢", "满意",
        "不错", "很棒", "很好", "完美", "顺利", "感谢", "谢谢",
        "great", "good", "excellent", "perfect", "success", "thanks",
        "awesome", "nice", "wonderful", "fantastic",
    }

    NEGATIVE_WORDS = {
        "不好", "问题", "错误", "失败", "困难", "麻烦", "不喜欢",
        "不满意", "糟糕", "崩溃", "bug", "error", "fail", "issue",
        "problem", "bad", "terrible", "awful", "difficult",
    }

    def __init__(self):
        pass

    async def summarize_session(
        self,
        conversations: List[Dict[str, Any]],
        max_length: int = 200
    ) -> SummaryResult:
        """
        为会话生成摘要

        Args:
            conversations: 对话列表，每项包含 role 和 content
            max_length: 摘要最大长度

        Returns:
            SummaryResult: 摘要结果
        """
        if not conversations:
            return SummaryResult(
                summary="",
                main_points=[],
                sentiment="neutral",
                confidence=0.0
            )

        # 提取用户消息
        user_messages = [
            c["content"] for c in conversations
            if c.get("role") == "user"
        ]

        # 提取助手消息
        assistant_messages = [
            c["content"] for c in conversations
            if c.get("role") == "assistant"
        ]

        # 生成摘要
        summary = self._generate_summary(
            user_messages,
            assistant_messages,
            max_length
        )

        # 提取要点
        main_points = self._extract_main_points(conversations)

        # 分析情感
        sentiment, confidence = self._analyze_sentiment(
            user_messages + assistant_messages
        )

        return SummaryResult(
            summary=summary,
            main_points=main_points,
            sentiment=sentiment,
            confidence=confidence
        )

    def _generate_summary(
        self,
        user_messages: List[str],
        assistant_messages: List[str],
        max_length: int
    ) -> str:
        """生成摘要"""
        # 简单实现：提取关键句子
        # 实际应用中应使用AI生成

        # 提取用户意图
        user_intent = ""
        if user_messages:
            first_msg = user_messages[0]
            # 提取第一句作为意图
            sentences = first_msg.replace("。", ".").replace("！", "!").replace("？", "?").split(".")
            if sentences:
                user_intent = sentences[0].strip()[:100]

        # 提取助手响应要点
        assistant_key = ""
        if assistant_messages:
            # 取最后一条助手消息的关键部分
            last_msg = assistant_messages[-1]
            if len(last_msg) > 100:
                assistant_key = last_msg[:100] + "..."
            else:
                assistant_key = last_msg

        # 组合摘要
        if user_intent and assistant_key:
            summary = f"用户询问：{user_intent}。讨论结果：{assistant_key}"
        elif user_intent:
            summary = f"讨论了关于：{user_intent}"
        else:
            summary = "进行了一次对话"

        return summary[:max_length]

    def _extract_main_points(
        self,
        conversations: List[Dict[str, Any]]
    ) -> List[str]:
        """提取主要观点"""
        points = []

        # 提取包含关键词的句子
        keywords = ["决定", "确定", "选择", "使用", "实现", "问题", "方案"]

        for conv in conversations:
            content = conv.get("content", "")
            for kw in keywords:
                if kw in content:
                    # 提取包含关键词的句子
                    sentences = content.replace("。", ".").split(".")
                    for sentence in sentences:
                        if kw in sentence and len(sentence) < 100:
                            points.append(sentence.strip())
                            break
                    break

        return points[:5]  # 最多5个要点

    def _analyze_sentiment(
        self,
        messages: List[str]
    ) -> tuple[str, float]:
        """分析情感"""
        combined = " ".join(messages).lower()

        positive_count = sum(1 for w in self.POSITIVE_WORDS if w in combined)
        negative_count = sum(1 for w in self.NEGATIVE_WORDS if w in combined)

        total = positive_count + negative_count
        if total == 0:
            return "neutral", 0.5

        if positive_count > negative_count:
            confidence = positive_count / total
            return "positive", confidence
        elif negative_count > positive_count:
            confidence = negative_count / total
            return "negative", confidence
        else:
            return "neutral", 0.5

    async def update_event_summary(
        self,
        existing_summary: str,
        new_content: str
    ) -> str:
        """更新事件摘要"""
        if not existing_summary:
            return new_content[:200]

        # 简单合并（实际应使用AI生成）
        if len(existing_summary) > 150:
            return existing_summary[:150] + "..." + new_content[:50]
        else:
            return existing_summary + "；" + new_content[:100]

    def generate_daily_summary(
        self,
        sessions: List[Dict[str, Any]]
    ) -> str:
        """生成每日摘要"""
        if not sessions:
            return ""

        summaries = []
        for i, session in enumerate(sessions, 1):
            summary = session.get("summary", "")
            if summary:
                summaries.append(f"{i}. {summary}")

        return "\n".join(summaries[:5])
