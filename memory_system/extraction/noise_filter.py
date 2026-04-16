"""噪点过滤器 - 过滤低价值或重复内容"""
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Set
import re
from difflib import SequenceMatcher


@dataclass
class FilterResult:
    """过滤结果"""
    passed: bool
    reason: str = ""
    cleaned_content: str = ""
    similarity_score: float = 0.0


class NoiseFilter:
    """
    噪点过滤器

    功能：
    1. 重复内容检测
    2. 低价值内容过滤
    3. 敏感信息检测
    4. 内容清洗
    """

    # 低价值模式（问候、简单确认等）
    LOW_VALUE_PATTERNS = [
        r'^[好的嗯]+[！!。\.]?$',  # "好的", "嗯", "好"
        r'^(ok|okay|yes|no|好|是|不是|对|不对)[！!。\.]?$',
        r'^(谢谢|感谢|thanks|thank you)[！!。\.]?$',
        r'^(你好|hello|hi)[！!。\.]?$',
        r'^\s*$',  # 空白
    ]

    # 敏感信息模式
    SENSITIVE_PATTERNS = [
        r'\b\d{16,19}\b',  # 信用卡号
        r'\b\d{6,}\b',  # 长数字（可能是密码）
        r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',  # 邮箱
        r'password\s*[=:：]\s*\S+',  # 密码
        r'密码\s*[=:：]\s*\S+',
        r'api[_-]?key\s*[=:：]\s*\S+',  # API密钥
        r'secret\s*[=:：]\s*\S+',
    ]

    # 要过滤的词汇（脏话、广告等）
    SPAM_INDICATORS = [
        "点击链接", "免费领取", "限时优惠", "加微信",
        "click here", "free gift", "limited offer",
    ]

    def __init__(self, similarity_threshold: float = 0.8):
        self.similarity_threshold = similarity_threshold
        self._low_value_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.LOW_VALUE_PATTERNS
        ]
        self._sensitive_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.SENSITIVE_PATTERNS
        ]
        self._recent_contents: Set[str] = set()

    def filter(
        self,
        content: str,
        check_duplicate: bool = True,
        check_sensitive: bool = True,
        check_low_value: bool = True
    ) -> FilterResult:
        """
        过滤内容

        Args:
            content: 要过滤的内容
            check_duplicate: 是否检查重复
            check_sensitive: 是否检查敏感信息
            check_low_value: 是否检查低价值内容

        Returns:
            FilterResult: 过滤结果
        """
        # 清理内容
        cleaned = self._clean_content(content)

        # 1. 检查低价值
        if check_low_value:
            for pattern in self._low_value_patterns:
                if pattern.match(cleaned):
                    return FilterResult(
                        passed=False,
                        reason="low_value",
                        cleaned_content=cleaned
                    )

        # 2. 检查重复
        if check_duplicate:
            is_duplicate, similarity = self._check_duplicate(cleaned)
            if is_duplicate:
                return FilterResult(
                    passed=False,
                    reason="duplicate",
                    cleaned_content=cleaned,
                    similarity_score=similarity
                )

        # 3. 检查敏感信息
        if check_sensitive:
            has_sensitive, masked = self._check_sensitive(cleaned)
            if has_sensitive:
                cleaned = masked

        # 4. 检查垃圾信息
        if self._is_spam(cleaned):
            return FilterResult(
                passed=False,
                reason="spam",
                cleaned_content=cleaned
            )

        # 记录最近内容
        self._recent_contents.add(cleaned[:100])

        # 限制最近内容集合大小
        if len(self._recent_contents) > 1000:
            self._recent_contents = set(list(self._recent_contents)[-500:])

        return FilterResult(
            passed=True,
            cleaned_content=cleaned
        )

    def _clean_content(self, content: str) -> str:
        """清理内容"""
        # 移除多余空白
        cleaned = re.sub(r'\s+', ' ', content).strip()

        # 移除控制字符
        cleaned = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', cleaned)

        return cleaned

    def _check_duplicate(self, content: str) -> tuple[bool, float]:
        """检查是否重复"""
        content_key = content[:100]

        # 精确匹配
        if content_key in self._recent_contents:
            return True, 1.0

        # 相似度匹配
        for recent in self._recent_contents:
            similarity = SequenceMatcher(None, content_key, recent).ratio()
            if similarity >= self.similarity_threshold:
                return True, similarity

        return False, 0.0

    def _check_sensitive(self, content: str) -> tuple[bool, str]:
        """检查并脱敏敏感信息"""
        has_sensitive = False
        masked = content

        for pattern in self._sensitive_patterns:
            matches = pattern.findall(masked)
            if matches:
                has_sensitive = True
                for match in matches:
                    if isinstance(match, str):
                        masked = masked.replace(match, self._mask_string(match))

        return has_sensitive, masked

    def _mask_string(self, s: str) -> str:
        """脱敏字符串"""
        if len(s) <= 4:
            return '*' * len(s)
        return s[:2] + '*' * (len(s) - 4) + s[-2:]

    def _is_spam(self, content: str) -> bool:
        """检查是否是垃圾信息"""
        content_lower = content.lower()

        for indicator in self.SPAM_INDICATORS:
            if indicator.lower() in content_lower:
                return True

        return False

    def is_worth_remembering(
        self,
        conversation: Dict[str, Any],
        min_content_length: int = 10
    ) -> bool:
        """
        判断对话是否值得记忆

        Args:
            conversation: 对话内容
            min_content_length: 最小内容长度

        Returns:
            bool: 是否值得记忆
        """
        content = conversation.get("content", "")

        # 长度检查
        if len(content) < min_content_length:
            return False

        # 过滤检查
        result = self.filter(content)
        return result.passed

    def filter_conversations(
        self,
        conversations: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """批量过滤对话"""
        return [
            conv for conv in conversations
            if self.is_worth_remembering(conv)
        ]

    def clear_cache(self):
        """清除缓存"""
        self._recent_contents.clear()
