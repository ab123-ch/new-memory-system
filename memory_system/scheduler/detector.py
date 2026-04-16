"""
场景识别器 - 自动识别用户输入的场景模式

核心功能：
1. 关键词匹配
2. 置信度计算
3. 混合场景检测
4. 场景连续性追踪
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from enum import Enum


logger = logging.getLogger(__name__)


class SceneMode(Enum):
    """场景模式"""
    WRITING = "writing"
    PROGRAMMING = "programming"
    ANALYSIS = "analysis"
    CHAT = "chat"


@dataclass
class DetectionResult:
    """识别结果"""
    mode: str
    confidence: float
    matched_keywords: List[str] = field(default_factory=list)
    is_mixed: bool = False
    secondary_modes: List[Tuple[str, float]] = field(default_factory=list)
    detection_time: datetime = field(default_factory=datetime.now)

    @property
    def is_confident(self) -> bool:
        """是否足够置信"""
        return self.confidence >= 0.6

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "confidence": self.confidence,
            "matched_keywords": self.matched_keywords,
            "is_mixed": self.is_mixed,
            "secondary_modes": self.secondary_modes,
            "detection_time": self.detection_time.isoformat()
        }


# 场景关键词映射表
SCENE_KEYWORDS = {
    SceneMode.WRITING: {
        "strong": [
            "写小说", "创作", "故事", "写作", "小说", "文章",
            "角色", "情节", "开头", "结尾", "章节",
            "描写", "对话", "叙述", "场景描写",
            "write a story", "novel", "fiction", "creative writing"
        ],
        "medium": [
            "人物", "主角", "配角", "反派", "世界观",
            "铺垫", "高潮", "转折", "悬念", "伏笔",
            "文笔", "风格", "修辞", "比喻",
            "narrative", "plot", "character", "scene"
        ],
        "weak": [
            "文", "说", "讲", "编", "想一个",
            "情节", "结局", "发展"
        ]
    },
    SceneMode.PROGRAMMING: {
        "strong": [
            "写代码", "编程", "函数", "类", "方法",
            "bug", "调试", "重构", "优化代码",
            "python", "java", "javascript", "typescript",
            "api", "接口", "数据库", "算法",
            "write code", "function", "class", "debug"
        ],
        "medium": [
            "程序", "脚本", "模块", "变量", "循环",
            "实现", "逻辑", "语法", "编译",
            "测试", "单元测试", "git", "commit",
            "programming", "code", "implementation"
        ],
        "weak": [
            "运行", "执行", "调用", "参数", "配置",
            "文件", "目录", "路径"
        ]
    },
    SceneMode.ANALYSIS: {
        "strong": [
            "分析", "研究", "调查", "评估", "诊断",
            "原因", "因素", "影响", "关联", "规律",
            "比较", "对比", "优缺点", "利弊",
            "analyze", "analysis", "research", "investigate"
        ],
        "medium": [
            "为什么", "怎么", "如何", "什么原因",
            "总结", "归纳", "推断", "预测",
            "数据", "统计", "趋势", "模式",
            "examine", "evaluate", "assess"
        ],
        "weak": [
            "看", "检查", "看看", "了解一下",
            "问题", "情况", "现象"
        ]
    },
    SceneMode.CHAT: {
        "strong": [
            "你好", "嗨", "哈喽", "早上好", "晚安",
            "聊天", "聊聊", "说话", "陪我",
            "hello", "hi", "hey", "good morning"
        ],
        "medium": [
            "怎么样", "好吗", "是什么", "能不能",
            "谢谢", "感谢", "不好意思", "抱歉",
            "觉得", "认为", "想问", "请问",
            "thanks", "sorry", "please"
        ],
        "weak": [
            "嗯", "哦", "好", "行", "可以",
            "ok", "yes", "no"
        ]
    }
}

# 权重配置
KEYWORD_WEIGHTS = {
    "strong": 1.0,
    "medium": 0.6,
    "weak": 0.3
}

# 模式切换关键词
MODE_SWITCH_KEYWORDS = {
    "writing": ["切换到写作", "写作模式", "创作模式", "用写作"],
    "programming": ["切换到编程", "编程模式", "代码模式", "用编程"],
    "analysis": ["切换到分析", "分析模式", "用分析"],
    "chat": ["切换到聊天", "聊天模式", "普通模式", "默认模式"]
}


class ModeDetector:
    """
    场景识别器

    根据用户输入自动识别当前场景模式。
    """

    def __init__(
        self,
        history_size: int = 5,
        stability_threshold: float = 0.3
    ):
        """
        初始化识别器

        Args:
            history_size: 历史记录大小（用于连续性判断）
            stability_threshold: 稳定性阈值（避免频繁切换）
        """
        self.history_size = history_size
        self.stability_threshold = stability_threshold

        # 识别历史
        self._detection_history: List[DetectionResult] = []

        # 上一次的识别结果
        self._last_result: Optional[DetectionResult] = None

    def detect(self, user_input: str) -> DetectionResult:
        """
        识别用户输入的场景模式

        Args:
            user_input: 用户输入

        Returns:
            识别结果
        """
        if not user_input or not user_input.strip():
            return self._get_default_result()

        input_lower = user_input.lower()

        # 1. 检查显式模式切换
        explicit_mode = self._check_explicit_switch(input_lower)
        if explicit_mode:
            result = DetectionResult(
                mode=explicit_mode,
                confidence=1.0,
                matched_keywords=[f"显式切换: {explicit_mode}"]
            )
            self._update_history(result)
            return result

        # 2. 计算各模式的得分
        mode_scores = self._calculate_mode_scores(input_lower)

        # 3. 确定主模式
        primary_mode, primary_confidence = self._get_primary_mode(mode_scores)

        # 4. 检测混合场景
        secondary_modes = self._get_secondary_modes(mode_scores, primary_mode)
        is_mixed = len(secondary_modes) > 0

        # 5. 应用稳定性调整
        adjusted_confidence = self._apply_stability(
            primary_mode,
            primary_confidence
        )

        # 6. 收集匹配的关键词
        matched_keywords = self._get_matched_keywords(input_lower, primary_mode)

        # 构建结果
        result = DetectionResult(
            mode=primary_mode,
            confidence=adjusted_confidence,
            matched_keywords=matched_keywords,
            is_mixed=is_mixed,
            secondary_modes=secondary_modes
        )

        # 更新历史
        self._update_history(result)

        return result

    def _check_explicit_switch(self, input_lower: str) -> Optional[str]:
        """检查显式模式切换"""
        for mode, keywords in MODE_SWITCH_KEYWORDS.items():
            for keyword in keywords:
                if keyword.lower() in input_lower:
                    return mode
        return None

    def _calculate_mode_scores(
        self,
        input_lower: str
    ) -> Dict[SceneMode, Dict[str, Any]]:
        """
        计算各模式的得分

        Args:
            input_lower: 小写的用户输入

        Returns:
            各模式的得分详情
        """
        scores = {}

        for mode in SceneMode:
            keywords = SCENE_KEYWORDS.get(mode, {})

            total_score = 0.0
            matched = {
                "strong": [],
                "medium": [],
                "weak": []
            }

            for strength, words in keywords.items():
                weight = KEYWORD_WEIGHTS.get(strength, 0.3)

                for word in words:
                    if word.lower() in input_lower:
                        total_score += weight
                        matched[strength].append(word)

            # 归一化分数
            normalized_score = min(total_score / 3.0, 1.0)

            scores[mode] = {
                "score": normalized_score,
                "raw_score": total_score,
                "matched": matched
            }

        return scores

    def _get_primary_mode(
        self,
        mode_scores: Dict[SceneMode, Dict[str, Any]]
    ) -> Tuple[str, float]:
        """
        获取主模式

        Args:
            mode_scores: 各模式得分

        Returns:
            (模式名, 置信度)
        """
        # 找出得分最高的模式
        sorted_modes = sorted(
            mode_scores.items(),
            key=lambda x: x[1]["score"],
            reverse=True
        )

        if not sorted_modes:
            return "chat", 0.5

        top_mode, top_info = sorted_modes[0]

        # 如果最高分太低，默认为聊天
        if top_info["score"] < 0.1:
            return "chat", 0.5

        return top_mode.value, top_info["score"]

    def _get_secondary_modes(
        self,
        mode_scores: Dict[SceneMode, Dict[str, Any]],
        primary_mode: str
    ) -> List[Tuple[str, float]]:
        """
        获取次要模式（用于混合场景）

        Args:
            mode_scores: 各模式得分
            primary_mode: 主模式

        Returns:
            次要模式列表 [(模式名, 得分), ...]
        """
        secondary = []

        for mode, info in mode_scores.items():
            if mode.value == primary_mode:
                continue

            # 如果得分超过主模式的 60%，认为是混合场景
            if info["score"] >= 0.3:
                secondary.append((mode.value, info["score"]))

        return sorted(secondary, key=lambda x: x[1], reverse=True)[:2]

    def _apply_stability(
        self,
        new_mode: str,
        new_confidence: float
    ) -> float:
        """
        应用稳定性调整

        避免模式频繁切换

        Args:
            new_mode: 新检测到的模式
            new_confidence: 新的置信度

        Returns:
            调整后的置信度
        """
        if not self._last_result:
            return new_confidence

        last_mode = self._last_result.mode

        # 如果和上次一样，增加置信度
        if new_mode == last_mode:
            return min(new_confidence + 0.1, 1.0)

        # 如果和上次不一样，降低置信度
        history_modes = [r.mode for r in self._detection_history[-3:]]
        last_mode_count = history_modes.count(last_mode)

        if last_mode_count >= 2:
            # 之前连续使用同一模式，需要更高的置信度才能切换
            if new_confidence < 0.7:
                return new_confidence * 0.8

        return new_confidence

    def _get_matched_keywords(
        self,
        input_lower: str,
        mode: str
    ) -> List[str]:
        """获取匹配的关键词"""
        matched = []

        try:
            scene_mode = SceneMode(mode)
            keywords = SCENE_KEYWORDS.get(scene_mode, {})

            for strength, words in keywords.items():
                for word in words:
                    if word.lower() in input_lower:
                        matched.append(word)
        except ValueError:
            pass

        return matched[:10]  # 最多返回 10 个

    def _update_history(self, result: DetectionResult):
        """更新识别历史"""
        self._last_result = result
        self._detection_history.append(result)

        # 保持历史记录大小
        if len(self._detection_history) > self.history_size:
            self._detection_history = self._detection_history[-self.history_size:]

    def _get_default_result(self) -> DetectionResult:
        """获取默认结果"""
        return DetectionResult(
            mode="chat",
            confidence=0.5,
            matched_keywords=[]
        )

    def get_mode_statistics(self) -> Dict[str, Any]:
        """
        获取模式统计信息

        Returns:
            统计信息
        """
        if not self._detection_history:
            return {
                "total_detections": 0,
                "mode_distribution": {},
                "average_confidence": 0.0
            }

        mode_counts: Dict[str, int] = {}
        total_confidence = 0.0

        for result in self._detection_history:
            mode_counts[result.mode] = mode_counts.get(result.mode, 0) + 1
            total_confidence += result.confidence

        return {
            "total_detections": len(self._detection_history),
            "mode_distribution": mode_counts,
            "average_confidence": total_confidence / len(self._detection_history),
            "last_mode": self._last_result.mode if self._last_result else None
        }

    def reset(self):
        """重置识别器状态"""
        self._detection_history.clear()
        self._last_result = None
