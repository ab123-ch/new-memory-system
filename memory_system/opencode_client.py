"""
OpenCode 客户端 - 调用 deer-flow 的 OpenCode 进行 LLM 推理

用途：
1. 生成对话摘要
2. 提取关键词
3. 相关性判断
4. 会话记忆深度分析
"""

import sys
import os
import logging
from pathlib import Path
from typing import Optional, Dict, List, Any
from datetime import datetime

# ============== 日志配置 ==============
# 日志文件路径
LOG_DIR = Path(__file__).parent.parent / "data" / "memory" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "opencode_client.log"

# 配置日志
def _setup_logging():
    """配置 OpenCode 相关的日志输出"""
    # 创建文件处理器
    file_handler = logging.FileHandler(LOG_FILE, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))

    # 配置 opencode 模块的日志
    opencode_logger = logging.getLogger('opencode')
    opencode_logger.setLevel(logging.DEBUG)
    opencode_logger.addHandler(file_handler)

    # 配置当前模块的日志
    client_logger = logging.getLogger('opencode_client')
    client_logger.setLevel(logging.DEBUG)
    client_logger.addHandler(file_handler)

    return client_logger

_logger = _setup_logging()

# 只使用本地 vendor 目录中的 opencode 模块（不使用 deer-flow，避免加载旧代码）
VENDOR_PATH = Path(__file__).parent / "vendor"
if VENDOR_PATH.exists():
    sys.path.insert(0, str(VENDOR_PATH))

try:
    from opencode import OpenCodeExecutor, OpenCodeConfig, OpenCodeTasks
    OPENCODE_AVAILABLE = True
except ImportError:
    OPENCODE_AVAILABLE = False
    OpenCodeExecutor = None
    OpenCodeConfig = None
    OpenCodeTasks = None


class OpenCodeClient:
    """
    OpenCode 客户端

    封装对 deer-flow opencode 模块的调用
    """

    # 模型名称映射（简写 -> 完整格式）
    MODEL_ALIASES = {
        "glm-4.5": "zhipuai-coding-plan/glm-4.5",
        "glm-4.5-air": "zhipuai-coding-plan/glm-4.5-air",
        "glm-4.5-flash": "zhipuai-coding-plan/glm-4.5-flash",
        "glm-4.5v": "zhipuai-coding-plan/glm-4.5v",
        "glm-4.6": "zhipuai-coding-plan/glm-4.6",
        "glm-4.6v": "zhipuai-coding-plan/glm-4.6v",
        "glm-4.6v-flash": "zhipuai-coding-plan/glm-4.6v-flash",
        "glm-4.7": "zhipuai-coding-plan/glm-4.7",
        "glm-5": "zhipuai-coding-plan/glm-5",
    }

    def __init__(self, model: str = "zhipuai-coding-plan/glm-4.7"):
        """
        初始化客户端

        Args:
            model: 使用的模型，默认 zhipuai-coding-plan/glm-4.7
                   支持简写如 "glm-4.7"，会自动转换为完整格式
        """
        self._executor = None
        self._tasks = None
        self._model = self._resolve_model(model)
        self._available = OPENCODE_AVAILABLE

        if self._available:
            try:
                config = OpenCodeConfig(model=self._model)
                self._executor = OpenCodeExecutor(config)
                self._tasks = OpenCodeTasks(self._executor)
            except Exception as e:
                print(f"[OpenCodeClient] 初始化失败: {e}")
                self._available = False

    def _resolve_model(self, model: str) -> str:
        """解析模型名称，支持简写"""
        if "/" in model:
            return model
        return self.MODEL_ALIASES.get(model, model)

    @property
    def available(self) -> bool:
        """是否可用"""
        return self._available

    async def generate_summary(
        self,
        user_message: str,
        assistant_message: str,
        max_length: int = 100
    ) -> Dict[str, Any]:
        """
        生成对话摘要

        Args:
            user_message: 用户消息
            assistant_message: 助手响应
            max_length: 摘要最大长度

        Returns:
            {
                "summary": "对话摘要",
                "keywords": ["关键词1", "关键词2"],
                "topic": "主题"
            }
        """
        if not self._available:
            # 降级：简单截断
            combined = f"{user_message}\n{assistant_message}"
            return {
                "summary": combined[:max_length] + "..." if len(combined) > max_length else combined,
                "keywords": [],
                "topic": None
            }

        try:
            messages = [
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": assistant_message}
            ]

            result = await self._tasks.compact_memories(messages, layer=1)

            return {
                "summary": result.get("summary", ""),
                "keywords": result.get("key_topics", []) + result.get("key_entities", []),
                "topic": result.get("task_description")
            }

        except Exception as e:
            print(f"[OpenCodeClient] 生成摘要失败: {e}")
            combined = f"{user_message}\n{assistant_message}"
            return {
                "summary": combined[:max_length],
                "keywords": [],
                "topic": None
            }

    async def judge_relevance(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """
        判断相关性

        Args:
            query: 查询内容
            candidates: 候选记忆列表
            top_k: 返回最相关的 k 个

        Returns:
            排序后的相关记忆列表
        """
        if not self._available or not candidates:
            # 降级：返回所有
            return candidates[:top_k]

        try:
            # 构建候选列表描述
            candidates_str = "\n".join([
                f"{i+1}. [{c.get('date')}] {c.get('summary', '')[:80]}"
                for i, c in enumerate(candidates[:20])  # 最多20个
            ])

            prompt = f"""请判断以下记忆与查询的相关性，返回最相关的 {top_k} 个序号。

查询: {query}

候选记忆:
{candidates_str}

请输出 JSON 数组，包含最相关的 {top_k} 个记忆的序号和相关性分数:
[{{"index": 1, "score": 0.95}}, {{"index": 3, "score": 0.8}}, ...]

只输出 JSON，不要其他内容。"""

            result = await self._executor.execute(prompt)

            # 解析结果
            import json
            import re

            json_match = re.search(r'\[.*\]', result, re.DOTALL)
            if json_match:
                scores = json.loads(json_match.group())
                scored_candidates = []

                for item in scores:
                    idx = item.get("index", 0) - 1
                    if 0 <= idx < len(candidates):
                        candidates[idx]["relevance"] = item.get("score", 0.5)
                        scored_candidates.append(candidates[idx])

                return scored_candidates[:top_k]

            return candidates[:top_k]

        except Exception as e:
            print(f"[OpenCodeClient] 相关性判断失败: {e}")
            return candidates[:top_k]

    async def extract_daily_summary(
        self,
        sessions: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        生成每日整体摘要

        Args:
            sessions: 当日所有会话

        Returns:
            {
                "summary": "每日摘要",
                "main_topics": ["主题1", "主题2"],
                "keywords": ["关键词"]
            }
        """
        if not self._available or not sessions:
            return {
                "summary": "无会话",
                "main_topics": [],
                "keywords": []
            }

        try:
            # 汇总所有会话
            all_summaries = [s.get("summary", "") for s in sessions if s.get("summary")]
            all_keywords = []
            for s in sessions:
                all_keywords.extend(s.get("keywords", []))

            if not all_summaries:
                return {
                    "summary": "无有效摘要",
                    "main_topics": [],
                    "keywords": list(set(all_keywords))
                }

            combined = "\n".join([f"- {s}" for s in all_summaries])

            prompt = f"""请对以下会话摘要进行汇总，生成每日总结：

{combined}

请输出 JSON 格式:
{{
    "summary": "今日主要工作总结（2-3句话）",
    "main_topics": ["主题1", "主题2"],
    "keywords": ["关键词1", "关键词2"]
}}

只输出 JSON，不要其他内容。"""

            result = await self._executor.execute(prompt)

            # 解析结果
            import json
            import re

            json_match = re.search(r'\{.*\}', result, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group())
                # 合并关键词
                parsed["keywords"] = list(set(parsed.get("keywords", []) + all_keywords))
                return parsed

            return {
                "summary": combined[:200],
                "main_topics": [],
                "keywords": list(set(all_keywords))
            }

        except Exception as e:
            print(f"[OpenCodeClient] 生成每日摘要失败: {e}")
            return {
                "summary": "生成失败",
                "main_topics": [],
                "keywords": []
            }

    async def generate_session_summary_from_file(
        self,
        session_file_path: Optional[Path],
        session_id: Optional[str],
        time_range: str = ""
    ) -> Dict[str, Any]:
        """
        从文件生成会话摘要（让 opencode 读取文件）

        注意：需要在项目根目录下创建 .opencode 配置文件，        授权 opencode 读取记忆文件目录

        Args:
            session_file_path: 会话文件路径
            session_id: 会话 ID
            time_range: 时间范围（已计算好的）

        Returns:
            {
                "tasks_done": ["1. 完成了xxx"],
                "user_questions": ["问题1"],
                "solutions": ["方案1"],
                "files_involved": ["文件1"],
                "experience_summary": "经验总结",
                "mistakes_lessons": [...],
                "user_suggestions": [...],
                "keywords": ["关键词"],
                "time_range": "09:30 - 11:45"
            }
        """
        if not self._available:
            return {
                "summary": "OpenCode 不可用",
                "keywords": [],
                "time_range": time_range
            }

        try:
            _logger.info("=" * 60)
            _logger.info("【开始生成会话摘要 - 从文件】")
            _logger.info(f"会话ID: {session_id}")
            _logger.info(f"文件路径: {session_file_path}")

            # 确定工作目录：使用记忆文件所在目录，让 opencode 能读取文件
            # opencode 会在 cwd 下找 .opencode/opencode.jsonc 配置
            # 全局配置在 ~/.config/opencode/opencode.json 中已有 provider 设置
            # 通过 --dir 参数指定工作目录即可
            memory_data_dir = MEMORY_DATA_PATH if 'MEMORY_DATA_PATH' in dir() else Path(__file__).parent.parent / "data" / "memory"
            _logger.info(f"  - 记忆数据目录: {memory_data_dir}")

            # 构建提示词（不包含文件内容，只包含路径）
            prompt = f"""请读取并分析以下会话记忆文件，提取关键信息用于记忆索引。

文件路径: {session_file_path}

请按以下步骤操作：
1. 使用 Read 工具读取文件内容
2. 分析文件中的 conversations 字段
3. 提取关键信息并输出 JSON

请输出 JSON 格式:
{{
    "tasks_done": ["1. 完成了xxx功能/需求", "2. 解决了xxx问题", "3. 根据用户提问做了xxx操作"],
    "user_questions": ["用户提出的核心问题1", "用户提出的核心问题2"],
    "solutions": ["解决方案要点1", "解决方案要点2"],
    "files_involved": ["涉及的文件路径、类名、方法名等"],
    "experience_summary": "遇到xxx问题时，可以xxx方式处理，关键点是xxx",
    "mistakes_lessons": [
        {{
            "mistake": "模型在排查xxx问题时走了弯路/遗漏了xxx",
            "lesson": "下次遇到类似问题，应该先xxx，再xxx"
        }}
    ],
    "user_suggestions": ["用户纠正/告知的知识点，如：xxx实际上是xxx"],
    "keywords": ["技术关键词1", "业务关键词2", "领域关键词3"]
}}

要求:
1. tasks_done: 总结会话完成的主要任务（修复的问题、开发的需求、执行的操作等）
2. user_questions: 用户提出的核心问题或需求
3. solutions: 模型给出的解决方案要点
4. files_involved: 涉及修改或查看的文件路径、类名、函数名等
5. experience_summary: 提炼可复用的经验总结（1-2句话），格式为"遇到X问题时，可以Y方式处理"
6. mistakes_lessons: 分析模型在会话中犯的错误或走的弯路，以及对应的教训
7. user_suggestions: 提取用户对模型的纠正、告知的知识点等
8. keywords: 提取5-10个关键的技术和业务词汇
9. 如果某项没有内容，使用空数组 []
10. 只输出 JSON，不要其他内容"""

            # 调用 OpenCode 执行
            _logger.info("[调用 OpenCode 执行分析...]")
            _logger.info(f"  - 模型: {self._model}")
            _logger.info(f"  - 文件: {session_file_path}")

            # 记录完整命令（方便手动调试）
            _logger.info("=" * 60)
            _logger.info("【完整命令】(可复制手动执行):")
            _logger.info(f"opencode run -m {self._model} --non-interactive '{prompt[:200]}...'")
            _logger.info("")
            _logger.info("【完整提示词】:")
            _logger.info(prompt)
            _logger.info("=" * 60)

            import time
            exec_start = time.time()
            result = await self._executor.execute(prompt)
            exec_elapsed = time.time() - exec_start

            _logger.info(f"  - OpenCode 返回成功，耗时: {exec_elapsed:.2f}s")
            _logger.info(f"  - 返回内容长度: {len(result)} 字符")

            # 解析 JSON 结果
            _logger.info("[解析 JSON 结果...]")
            import json
            import re

            json_match = re.search(r'\{.*\}', result, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group())
                parsed["time_range"] = time_range
                _logger.info(f"  - 解析成功!")
                _logger.info(f"  - 提取到:")
                _logger.info(f"    * tasks_done: {len(parsed.get('tasks_done', []))} 条")
                _logger.info(f"    * user_questions: {len(parsed.get('user_questions', []))} 条")
                _logger.info(f"    * solutions: {len(parsed.get('solutions', []))} 条")
                _logger.info(f"    * files_involved: {len(parsed.get('files_involved', []))} 条")
                _logger.info(f"    * mistakes_lessons: {len(parsed.get('mistakes_lessons', []))} 条")
                _logger.info(f"    * user_suggestions: {len(parsed.get('user_suggestions', []))} 条")
                _logger.info(f"    * keywords: {len(parsed.get('keywords', []))} 条")
                _logger.info("【会话摘要生成完成】")
                _logger.info("=" * 60)
                return parsed

            _logger.warning("  - JSON 解析失败")
            _logger.info("【会话摘要生成完成(解析失败)】")
            _logger.info("=" * 60)
            return {
                "summary": "JSON 解析失败",
                "keywords": [],
                "time_range": time_range
            }

        except Exception as e:
            _logger.error(f"[OpenCodeClient] 生成会话摘要失败: {e}")
            return {
                "summary": f"生成失败: {str(e)}",
                "keywords": [],
                "time_range": time_range
            }

    async def generate_session_summary(
        self,
        session_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        生成会话摘要（用于日期索引）- 保留作为备用方法

        Args:
            session_data: 会话数据，包含 conversations, summary, keywords 等

        Returns:
            {
                "summary": "会话摘要（Markdown格式，编号列表）",
                "keywords": ["关键词1", "关键词2"],
                "time_range": "09:30 - 11:45"
            }
        """
        # 直接使用旧方法作为降级方案
        convs = session_data.get("conversations", [])
        start_time = convs[0].get("timestamp", "")[11:16] if convs else ""
        end_time = convs[-1].get("timestamp", "")[11:16] if convs else ""

        return {
            "summary": session_data.get("summary", "无摘要"),
            "keywords": session_data.get("keywords", []),
            "time_range": f"{start_time} - {end_time}"
        }

    async def analyze_session_memory(
        self,
        session_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        深度分析会话记忆（用于生成索引）

        分析维度：
        1. 会话做了哪些事？
        2. 用户提出了哪些问题？
        3. 模型的解决方案是什么？
        4. 改了哪些地方（文件、代码位置）？
        5. 能不能总结出下次遇到类似问题的处理经验？

        Args:
            session_data: 会话数据，包含 conversations 等

        Returns:
            {
                "tasks_done": ["完成了xxx", "解决了xxx"],
                "user_questions": ["问题1", "问题2"],
                "solutions": ["解决方案1", "解决方案2"],
                "files_modified": ["文件路径1", "文件路径2"],
                "reusable_experience": "可复用的经验总结",
                "keywords": ["关键词1", "关键词2"]
            }
        """
        if not self._available:
            return self._fallback_analyze(session_data)

        try:
            # 提取对话内容
            conversations = session_data.get("conversations", [])
            conv_texts = []
            for conv in conversations:
                role = conv.get("role", "user")
                content = conv.get("content", "")
                if content:
                    prefix = "用户" if role == "user" else "助手"
                    # 截取更长的内容以便分析
                    conv_texts.append(f"{prefix}: {content[:500]}")

            if not conv_texts:
                return self._fallback_analyze(session_data)

            combined = "\n\n".join(conv_texts[:30])  # 最多30条

            prompt = f"""请深度分析以下会话内容，提取关键信息用于记忆索引。

会话内容:
{combined}

请输出 JSON 格式:
{{
    "tasks_done": ["1. 完成了xxx功能", "2. 解决了xxx问题"],
    "user_questions": ["用户提出的核心问题1", "用户提出的核心问题2"],
    "solutions": ["解决方案要点1", "解决方案要点2"],
    "files_modified": ["涉及的文件或代码位置"],
    "reusable_experience": "总结可复用的经验，下次遇到类似问题的处理建议",
    "keywords": ["技术关键词", "业务关键词"]
}}

要求:
1. tasks_done: 具体完成了哪些任务，用简洁的编号列表
2. user_questions: 用户提出的核心问题或需求
3. solutions: 模型给出的解决方案要点
4. files_modified: 涉及修改的文件路径、类名、函数名等
5. reusable_experience: 提炼可复用的经验，格式为"遇到X情况时，可以Y方式处理"
6. keywords: 提取5-10个关键的技术和业务词汇
7. 只输出 JSON，不要其他内容"""

            result = await self._executor.execute(prompt)

            # 解析结果
            import json
            import re

            json_match = re.search(r'\{.*\}', result, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group())
                # 添加时间信息
                parsed["session_id"] = session_data.get("session_id", "")
                parsed["date"] = session_data.get("date", "")
                return parsed

            return self._fallback_analyze(session_data)

        except Exception as e:
            print(f"[OpenCodeClient] 分析会话记忆失败: {e}")
            return self._fallback_analyze(session_data)

    def _fallback_analyze(self, session_data: Dict[str, Any]) -> Dict[str, Any]:
        """降级分析（当 OpenCode 不可用时）"""
        conversations = session_data.get("conversations", [])

        # 简单提取
        user_msgs = [c.get("content", "")[:100] for c in conversations if c.get("role") == "user"]
        assistant_msgs = [c.get("content", "")[:100] for c in conversations if c.get("role") == "assistant"]

        return {
            "tasks_done": [session_data.get("summary", "无摘要")[:100]],
            "user_questions": user_msgs[:3] if user_msgs else ["无问题记录"],
            "solutions": assistant_msgs[:3] if assistant_msgs else ["无解决方案记录"],
            "files_modified": [],
            "reusable_experience": "需要手动总结",
            "keywords": session_data.get("keywords", []),
            "session_id": session_data.get("session_id", ""),
            "date": session_data.get("date", "")
        }


# 全局实例
_client: Optional[OpenCodeClient] = None


def get_opencode_client(model: str = "glm-4.7") -> OpenCodeClient:
    """获取 OpenCode 客户端单例"""
    global _client
    if _client is None:
        _client = OpenCodeClient(model=model)
    return _client


# ============== 测试 ==============

async def test_opencode_client():
    """测试 OpenCode 客户端"""
    client = get_opencode_client()

    print("=" * 50)
    print(" OpenCode 客户端测试")
    print("=" * 50)

    print(f"\n可用性: {client.available}")

    if client.available:
        # 测试摘要生成
        print("\n【测试1】生成摘要")
        result = await client.generate_summary(
            user_message="退舱逻辑下红冲资费逻辑修改，第一点是需要检查费用状态",
            assistant_message="好的，我来分析退舱红冲资费的逻辑。首先需要..."
        )
        print(f"摘要: {result['summary']}")
        print(f"关键词: {result['keywords']}")

        # 测试相关性判断
        print("\n【测试2】相关性判断")
        candidates = [
            {"date": "2026-03-22", "summary": "退舱红冲资费逻辑修改"},
            {"date": "2026-03-21", "summary": "邮件发送功能优化"},
            {"date": "2026-03-20", "summary": "订舱审批流程调整"},
        ]
        results = await client.judge_relevance("红冲费用", candidates, top_k=2)
        for r in results:
            print(f"  {r['date']}: {r['summary']} (相关性: {r.get('relevance', 0):.2f})")

    print("\n" + "=" * 50)


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_opencode_client())
