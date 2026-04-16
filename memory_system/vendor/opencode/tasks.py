"""OpenCode 预定义任务封装

提供常用任务的便捷方法
"""

import json
import logging
from typing import Optional

from .executor import OpenCodeExecutor

logger = logging.getLogger(__name__)


class OpenCodeTasks:
    """
    预定义的 OpenCode 任务封装

    封装常用的 LLM 任务，简化调用方式

    Example:
        >>> executor = OpenCodeExecutor()
        >>> tasks = OpenCodeTasks(executor)
        >>> result = await tasks.compact_memories(messages, layer=1)
    """

    def __init__(self, executor: OpenCodeExecutor):
        """
        初始化任务封装器

        Args:
            executor: OpenCode 执行器实例
        """
        self.exe = executor

    async def compact_memories(
        self,
        messages: list[dict],
        layer: int = 1
    ) -> dict:
        """
        记忆压缩任务

        Args:
            messages: 消息列表，每条消息包含 role 和 content
            layer: 压缩层级，1-3

        Returns:
            压缩结果字典，包含 summary, key_topics 等字段

        Example:
            >>> result = await tasks.compact_memories([
            ...     {"role": "user", "content": "帮我写小说"},
            ...     {"role": "assistant", "content": "好的..."}
            ... ])
            >>> print(result["summary"])
        """
        # 格式化消息列表
        msgs_str = "\n".join(
            f"[{m.get('role', 'unknown')}]: {m.get('content', '')}"
            for m in messages
        )

        prompt = f"""请对以下对话进行压缩和摘要（Layer {layer} 压缩）：

{msgs_str}

请输出 JSON 格式的压缩结果，包含以下字段：
- summary: 对话摘要（简洁）
- key_topics: 关键主题列表
- key_decisions: 关键决策列表
- key_entities: 关键实体（人物、地点、物品等）
- key_conclusions: 关键结论列表
- task_type: 任务类型（如：创意、大纲、写作、审查等）
- task_description: 任务简述

只输出 JSON，不要其他内容。"""

        result = await self.exe.execute(prompt)

        # 解析 JSON 结果
        try:
            # 尝试提取 JSON
            json_str = self._extract_json(result)
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.warning(f"JSON 解析失败: {e}, 返回原始结果")
            return {
                "summary": result,
                "key_topics": [],
                "key_decisions": [],
                "key_entities": [],
                "key_conclusions": [],
                "task_type": None,
                "task_description": None,
                "_raw": result
            }

    async def extract_skill(self, task_execution: dict) -> dict:
        """
        技能提取任务

        从成功执行的任务中提取可复用技能

        Args:
            task_execution: 任务执行记录，包含:
                - task: 任务描述
                - execution: 执行过程
                - result: 结果
                - score: 用户评分（可选）
                - feedback: 用户反馈（可选）

        Returns:
            技能描述字典

        Example:
            >>> skill = await tasks.extract_skill({
            ...     "task": "生成修仙小说大纲",
            ...     "execution": "...",
            ...     "result": "...",
            ...     "score": 9
            ... })
        """
        context = f"""任务描述：{task_execution.get('task', '')}
执行过程：{task_execution.get('execution', '')}
执行结果：{task_execution.get('result', '')}"""

        if task_execution.get('score'):
            context += f"\n用户评分：{task_execution['score']}/10"
        if task_execution.get('feedback'):
            context += f"\n用户反馈：{task_execution['feedback']}"

        prompt = f"""请分析以下成功完成的任务，提取可复用的技能：

{context}

请输出 JSON 格式的技能描述：
- name: 技能名称（简洁）
- description: 技能描述
- scenario: 适用场景
- steps: 执行步骤列表
- notes: 注意事项列表
- success_factors: 成功要素列表

只输出 JSON，不要其他内容。"""

        result, confirmed, rounds = await self.exe.execute_with_confirmation(
            prompt,
            context,
            ["技能描述清晰可执行", "适用场景明确", "步骤可复用"],
            max_rounds=2
        )

        try:
            json_str = self._extract_json(result)
            skill_data = json.loads(json_str)
            skill_data["_confirmed"] = confirmed
            skill_data["_rounds"] = rounds
            return skill_data
        except json.JSONDecodeError as e:
            logger.warning(f"技能 JSON 解析失败: {e}")
            return {
                "name": "提取失败",
                "description": result,
                "_raw": result,
                "_confirmed": confirmed,
                "_rounds": rounds
            }

    async def evaluate_writing(
        self,
        content: str,
        dimensions: Optional[list[dict]] = None
    ) -> dict:
        """
        写作评估任务

        Args:
            content: 待评估的内容
            dimensions: 评估维度列表，每个维度包含:
                - name: 维度名称
                - description: 维度描述
                - weight: 权重（可选）

        Returns:
            评估结果字典

        Example:
            >>> result = await tasks.evaluate_writing(
            ...     "第一章内容...",
            ...     [
            ...         {"name": "情节", "description": "情节是否吸引人", "weight": 0.3},
            ...         {"name": "文笔", "description": "文字是否流畅", "weight": 0.2}
            ...     ]
            ... )
        """
        if dimensions is None:
            dimensions = [
                {"name": "情节", "description": "情节是否吸引人、逻辑合理", "weight": 0.25},
                {"name": "文笔", "description": "文字是否流畅、修辞得当", "weight": 0.20},
                {"name": "人物", "description": "人物形象是否丰满、行为合理", "weight": 0.20},
                {"name": "世界观", "description": "世界观是否完整、自洽", "weight": 0.15},
                {"name": "节奏", "description": "叙事节奏是否合适", "weight": 0.10},
                {"name": "创新", "description": "是否有创新元素", "weight": 0.10}
            ]

        dims_str = "\n".join(
            f"- {d['name']} ({d.get('weight', 0.1)*100}%): {d['description']}"
            for d in dimensions
        )

        prompt = f"""请评估以下写作内容：

{content[:3000]}  # 限制长度

评估维度：
{dims_str}

请输出 JSON 格式的评估结果：
- scores: 各维度评分（1-10）
- total_score: 综合评分（1-10）
- strengths: 优点列表
- weaknesses: 不足列表
- suggestions: 改进建议列表

只输出 JSON，不要其他内容。"""

        result = await self.exe.execute(prompt)

        try:
            json_str = self._extract_json(result)
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.warning(f"评估 JSON 解析失败: {e}")
            return {
                "scores": {},
                "total_score": 0,
                "strengths": [],
                "weaknesses": [],
                "suggestions": [],
                "_raw": result
            }

    async def analyze_feedback(
        self,
        original: str,
        modified: str,
        comment: Optional[str] = None,
        score: Optional[int] = None
    ) -> dict:
        """
        反馈分析任务

        分析用户修改，提取改进意图

        Args:
            original: 原始内容
            modified: 修改后内容
            comment: 用户评论（可选）
            score: 用户评分（可选）

        Returns:
            分析结果字典

        Example:
            >>> analysis = await tasks.analyze_feedback(
            ...     "原文内容...",
            ...     "修改后内容...",
            ...     comment="文笔太生硬了",
            ...     score=6
            ... )
        """
        context = f"""原始内容：
{original[:2000]}

修改后内容：
{modified[:2000]}"""

        if comment:
            context += f"\n\n用户评论：{comment}"
        if score:
            context += f"\n用户评分：{score}/10"

        prompt = f"""请分析以下用户修改，提取修改意图和偏好：

{context}

请输出 JSON 格式的分析结果：
- modification_type: 修改类型（文笔/情节/人物/世界观/节奏/其他）
- intent: 修改意图描述
- changes: 具体变化列表
- preferences: 体现的用户偏好列表
- suggestions: 给 AI 的建议列表

只输出 JSON，不要其他内容。"""

        result = await self.exe.execute(prompt, context)

        try:
            json_str = self._extract_json(result)
            data = json.loads(json_str)
            data["score"] = score
            data["comment"] = comment
            return data
        except json.JSONDecodeError as e:
            logger.warning(f"反馈分析 JSON 解析失败: {e}")
            return {
                "modification_type": "unknown",
                "intent": "unknown",
                "changes": [],
                "preferences": [],
                "suggestions": [],
                "score": score,
                "comment": comment,
                "_raw": result
            }

    async def match_expert(self, query: str) -> dict:
        """
        专家匹配任务

        根据用户需求匹配合适的专家

        Args:
            query: 用户需求描述

        Returns:
            匹配结果字典

        Example:
            >>> match = await tasks.match_expert("帮我构思一个修仙小说的创意")
            >>> print(match["expert"])
        """
        prompt = f"""请分析以下用户需求，匹配最适合的专家：

用户需求：{query}

可用专家类型：
1. 创意策划师 - 负责创意孵化、点子拓展
2. 大纲规划师 - 负责整体大纲、章节规划
3. 章节细化师 - 负责章纲细化、情节设计
4. 正文写手 - 负责正文写作、内容扩展
5. 质量审查员 - 负责质量检查、问题发现
6. 世界观架构师 - 负责世界观设定、体系构建
7. 人物设计师 - 负责人物设定、角色塑造

请输出 JSON 格式的匹配结果：
- expert: 最匹配的专家类型
- score: 匹配度（0-1）
- reasoning: 匹配理由
- alternatives: 备选专家列表（按匹配度降序）
- keywords: 匹配到的关键词列表

只输出 JSON，不要其他内容。"""

        result = await self.exe.execute(prompt)

        try:
            json_str = self._extract_json(result)
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.warning(f"专家匹配 JSON 解析失败: {e}")
            return {
                "expert": "正文写手",  # 默认
                "score": 0.5,
                "reasoning": "无法解析",
                "alternatives": [],
                "keywords": [],
                "_raw": result
            }

    async def generate_outline(self, core_idea: dict) -> dict:
        """
        大纲生成任务

        Args:
            core_idea: 核心创意，包含:
                - title: 标题（可选）
                - genre: 类型（可选）
                - theme: 主题（可选）
                - idea: 核心创意描述
                - keywords: 关键词列表（可选）
                - target_chapters: 目标章节数（可选）

        Returns:
            大纲结构字典

        Example:
            >>> outline = await tasks.generate_outline({
            ...     "title": "我的修仙小说",
            ...     "genre": "玄幻",
            ...     "idea": "一个程序员穿越到修仙世界"
            ... })
        """
        idea_str = core_idea.get("idea", "")
        context_parts = []

        if core_idea.get("title"):
            context_parts.append(f"标题：{core_idea['title']}")
        if core_idea.get("genre"):
            context_parts.append(f"类型：{core_idea['genre']}")
        if core_idea.get("theme"):
            context_parts.append(f"主题：{core_idea['theme']}")
        if core_idea.get("keywords"):
            context_parts.append(f"关键词：{', '.join(core_idea['keywords'])}")

        target = core_idea.get("target_chapters", 20)

        context = "\n".join(context_parts) if context_parts else ""

        prompt = f"""请根据以下核心创意生成小说大纲：

核心创意：{idea_str}

{context}

目标章节数：{target}

请输出 JSON 格式的大纲：
- title: 小说标题
- genre: 类型
- theme: 主题
- synopsis: 故事梗概（200-500字）
- world_setting: 世界观设定概要
- main_characters: 主要人物列表（名字 + 简介）
- chapters: 章节列表，每章包含：
  - chapter: 章节号
  - title: 章节标题
  - summary: 章节梗概（50-100字）
  - key_events: 关键事件列表
  - climax: 本章高潮点

只输出 JSON，不要其他内容。"""

        result, confirmed, rounds = await self.exe.execute_with_confirmation(
            prompt,
            context,
            ["大纲结构完整", "章节之间逻辑连贯", "情节有吸引力"],
            max_rounds=2
        )

        try:
            json_str = self._extract_json(result)
            data = json.loads(json_str)
            data["_confirmed"] = confirmed
            data["_rounds"] = rounds
            return data
        except json.JSONDecodeError as e:
            logger.warning(f"大纲 JSON 解析失败: {e}")
            return {
                "title": core_idea.get("title", "未命名"),
                "synopsis": result,
                "_raw": result,
                "_confirmed": confirmed,
                "_rounds": rounds
            }

    async def expand_chapter(self, chapter_outline: dict) -> str:
        """
        章节扩展任务

        将章纲扩展为完整章节内容

        Args:
            chapter_outline: 章纲，包含:
                - chapter: 章节号
                - title: 章节标题
                - summary: 章节梗概
                - key_events: 关键事件列表
                - climax: 本章高潮点
                - context: 前文上下文（可选）
                - style: 写作风格（可选）

        Returns:
            章节正文内容

        Example:
            >>> content = await tasks.expand_chapter({
            ...     "chapter": 1,
            ...     "title": "初入修仙界",
            ...     "summary": "主角穿越到修仙世界",
            ...     "key_events": ["穿越", "发现身份", "初遇危险"]
            ... })
        """
        context = f"""章节号：第{chapter_outline.get('chapter', 1)}章
章节标题：{chapter_outline.get('title', '')}
章节梗概：{chapter_outline.get('summary', '')}
关键事件：{', '.join(chapter_outline.get('key_events', []))}
本章高潮：{chapter_outline.get('climax', '')}"""

        if chapter_outline.get('context'):
            context += f"\n\n前文上下文：\n{chapter_outline['context'][:1000]}"

        style = chapter_outline.get('style', '轻松幽默')

        prompt = f"""请根据以下章纲写作正文内容：

{context}

写作风格：{style}

要求：
1. 字数 3000-5000 字
2. 情节紧凑，有起伏
3. 人物性格鲜明
4. 对话生动自然
5. 结尾设置悬念钩子

直接输出正文内容，不要加标题。"""

        return await self.exe.execute(prompt)

    async def self_evaluate(self, stats: dict) -> dict:
        """
        自我评估任务

        评估系统表现和改进方向

        Args:
            stats: 统计数据，包含:
                - total_sessions: 总会话数
                - avg_score: 平均评分
                - success_rate: 成功率
                - skill_count: 技能数量
                - feedback_count: 反馈数量

        Returns:
            评估结果字典

        Example:
            >>> evaluation = await tasks.self_evaluate({
            ...     "total_sessions": 100,
            ...     "avg_score": 7.5,
            ...     "success_rate": 0.85
            ... })
        """
        stats_str = "\n".join(f"- {k}: {v}" for k, v in stats.items())

        prompt = f"""请根据以下统计数据评估系统表现：

{stats_str}

请输出 JSON 格式的评估结果：
- overall_rating: 整体评级（A/B/C/D）
- strengths: 优势列表
- weaknesses: 不足列表
- improvement_areas: 需改进领域列表
- action_items: 具体改进行动列表
- priority: 优先级最高的改进项

只输出 JSON，不要其他内容。"""

        result = await self.exe.execute(prompt)

        try:
            json_str = self._extract_json(result)
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.warning(f"自我评估 JSON 解析失败: {e}")
            return {
                "overall_rating": "C",
                "strengths": [],
                "weaknesses": [],
                "improvement_areas": [],
                "action_items": [],
                "priority": "数据不足，无法评估",
                "_raw": result
            }

    def _extract_json(self, text: str) -> str:
        """
        从文本中提取 JSON

        Args:
            text: 可能包含 JSON 的文本

        Returns:
            JSON 字符串
        """
        text = text.strip()

        # 尝试直接解析
        if text.startswith("{") and text.endswith("}"):
            return text
        if text.startswith("[") and text.endswith("]"):
            return text

        # 尝试提取代码块中的 JSON
        if "```json" in text:
            start = text.find("```json") + 7
            end = text.find("```", start)
            if end > start:
                return text[start:end].strip()

        if "```" in text:
            start = text.find("```") + 3
            end = text.find("```", start)
            if end > start:
                return text[start:end].strip()

        # 尝试找到第一个 { 和最后一个 }
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            return text[start:end + 1]

        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end > start:
            return text[start:end + 1]

        return text
