"""触发检测 - 判断是否需要召回记忆"""
from dataclasses import dataclass
from typing import List, Optional
import re

from ..models import GlobalIndex


@dataclass
class TriggerResult:
    """触发检测结果"""
    need_recall: bool
    topic: str = ""
    search_keywords: List[str] = None
    confidence: float = 0.0
    reason: str = ""

    def __post_init__(self):
        if self.search_keywords is None:
            self.search_keywords = []


class TriggerDetector:
    """
    触发检测器 - 判断用户消息是否需要召回历史记忆

    检测策略：
    1. 时间指涉词检测（上次、昨天、之前等）
    2. 话题延续检测（匹配热门关键词）
    3. 事件引用检测（匹配进行中的事件）
    4. 上下文引用检测（那个、它、这个等）
    """

    # 时间指涉词模式
    TIME_REFERENCE_PATTERNS = [
        r"上次",
        r"昨天",
        r"前天",
        r"之前",
        r"之前说",
        r"刚才",
        r"上次提到",
        r"上次讨论",
        r"上次我们",
        r"之前讨论",
        r"之前提到",
        r"last time",
        r"yesterday",
        r"before",
        r"previously",
        r"earlier",
    ]

    # 上下文引用模式
    CONTEXT_REFERENCE_PATTERNS = [
        r"那个\s*(\S+)",
        r"那个项目",
        r"那个问题",
        r"那个功能",
        r"它[怎么样如何]",
        r"这个[怎么样如何]",
        r"接着[说聊]",
        r"继续[说聊做]",
    ]

    # 疑问词模式（可能需要上下文）
    QUESTION_PATTERNS = [
        r"怎么样了",
        r"进展如何",
        r"有什么[结果更新]",
        r"还记得",
        r"记得吗",
    ]

    def __init__(self):
        # 编译正则表达式
        self.time_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.TIME_REFERENCE_PATTERNS
        ]
        self.context_patterns = [
            re.compile(p) for p in self.CONTEXT_REFERENCE_PATTERNS
        ]
        self.question_patterns = [
            re.compile(p) for p in self.QUESTION_PATTERNS
        ]

    def detect(
        self,
        user_message: str,
        global_index: GlobalIndex
    ) -> TriggerResult:
        """
        检测是否需要召回记忆

        Args:
            user_message: 用户消息
            global_index: 全局索引

        Returns:
            TriggerResult: 检测结果
        """
        # 1. 检测时间指涉词
        for pattern in self.time_patterns:
            if pattern.search(user_message):
                # 提取可能的话题关键词
                keywords = self._extract_keywords(
                    user_message,
                    global_index.get_hot_keywords()
                )
                return TriggerResult(
                    need_recall=True,
                    topic="之前的讨论",
                    search_keywords=keywords,
                    confidence=0.9,
                    reason="检测到时间指涉词"
                )

        # 2. 检测上下文引用
        for pattern in self.context_patterns:
            match = pattern.search(user_message)
            if match:
                keywords = self._extract_keywords(
                    user_message,
                    global_index.get_hot_keywords()
                )
                topic = match.group(0) if match else "相关话题"
                return TriggerResult(
                    need_recall=True,
                    topic=topic,
                    search_keywords=keywords,
                    confidence=0.85,
                    reason="检测到上下文引用"
                )

        # 3. 检测疑问模式
        for pattern in self.question_patterns:
            if pattern.search(user_message):
                keywords = self._extract_keywords(
                    user_message,
                    global_index.get_hot_keywords()
                )
                return TriggerResult(
                    need_recall=True,
                    topic="相关内容",
                    search_keywords=keywords,
                    confidence=0.7,
                    reason="检测到需要上下文的疑问"
                )

        # 4. 匹配热门关键词或进行中的事件
        matched_keywords = []
        hot_keywords = [kw.word for kw in global_index.hot_keywords]

        for kw in hot_keywords:
            if kw in user_message:
                matched_keywords.append(kw)

        if matched_keywords:
            return TriggerResult(
                need_recall=True,
                topic=matched_keywords[0],
                search_keywords=matched_keywords,
                confidence=0.6,
                reason="匹配到热门话题关键词"
            )

        # 5. 匹配进行中的事件
        for event in global_index.active_events:
            if event.name in user_message:
                return TriggerResult(
                    need_recall=True,
                    topic=event.name,
                    search_keywords=[event.name],
                    confidence=0.8,
                    reason="匹配到进行中的事件"
                )

        # 不需要召回
        return TriggerResult(
            need_recall=False,
            reason="未检测到需要召回的触发条件"
        )

    def _extract_keywords(
        self,
        message: str,
        known_keywords: List[str]
    ) -> List[str]:
        """从消息中提取关键词"""
        keywords = []

        # 首先匹配已知的关键词
        for kw in known_keywords:
            if kw in message:
                keywords.append(kw)

        # 简单的关键词提取（基于常见模式）
        # 提取引号中的内容
        quoted = re.findall(r'[""「」『』]([^""「」『』]+)[""「」『』]', message)
        keywords.extend(quoted)

        # 提取"XX项目"、"XX功能"等模式
        project_pattern = re.compile(r'(\S+)(?:项目|功能|模块|系统|问题)')
        for match in project_pattern.finditer(message):
            keywords.append(match.group(0))

        return list(set(keywords))[:5]  # 去重并限制数量

    def should_summarize_session(
        self,
        conversation_count: int,
        session_duration_minutes: float
    ) -> bool:
        """判断是否应该对当前会话进行摘要"""
        # 超过10轮对话或超过30分钟
        return conversation_count >= 10 or session_duration_minutes >= 30
