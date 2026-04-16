#!/usr/bin/env python3
"""
经验学习 Hook - 在每轮对话结束后执行经验提取和记忆优化

工作流程：
1. 读取最后一轮对话
2. 检测是否包含可学习经验
3. 使用 LLM 智能分析提取经验总结、关键要点、标签
4. 保存经验为 MD 文件，按类型分类
5. 执行智能判断和记忆优化
6. 记录运行日志

日志路径: {data_path}/logs/经验学习日志/experience_learning_{date}.log
经验保存: {data_path}/experiences/{experience_type}/{id}.md
"""

# ========== 最早期调试 ==========
import sys as _sys
from datetime import datetime as _dt
from pathlib import Path as _Path
_stdin_content = None
try:
    _stdin_content = _sys.stdin.read()
except Exception as _e:
    pass
# ========== 最早期调试结束 ==========

import json
import sys
import os
import asyncio
import traceback
from datetime import datetime, date
from pathlib import Path
from typing import Optional, Dict, Any, List

# 恢复 stdin 内容
import io
if _stdin_content is not None:
    sys.stdin = io.StringIO(_stdin_content)


# 记忆系统路径检测
def _detect_memory_paths() -> tuple:
    """
    自动检测记忆系统路径

    返回: (memory_system_module_path, mcp_data_path)
    - memory_system_module_path: memory_system 模块的父目录（用于导入模块）
    - mcp_data_path: MCP 服务的 data 目录（用于存储日志和经验）
    """
    # 1. 优先使用环境变量
    data_path = os.environ.get('MEMORY_DATA_PATH')
    if data_path:
        memory_system_path = Path(data_path).parent
        return memory_system_path, Path(data_path)

    # 2. 检测 Claude Code MCP 安装路径（优先级最高）
    claude_mcp_path = Path.home() / ".claude" / "mcp" / "memory-system"
    if (claude_mcp_path / "memory_system" / "__init__.py").exists():
        # MCP 服务的 data 目录（根目录下的 data，不是 data/memory）
        mcp_data_path = claude_mcp_path / "data"
        return claude_mcp_path, mcp_data_path

    # 3. 检测项目目录
    project_path = Path(__file__).parent.parent
    if (project_path / "memory_system" / "__init__.py").exists():
        data_path = project_path / "data"
        if data_path.exists():
            return project_path, data_path
        return project_path, Path.home() / ".memory-system"

    return Path.home() / ".memory-system", Path.home() / ".memory-system"

_MEMORY_SYSTEM_PATH, MCP_DATA_PATH = _detect_memory_paths()

# 兼容性别名
MEMORY_DATA_PATH = MCP_DATA_PATH

if _MEMORY_SYSTEM_PATH and str(_MEMORY_SYSTEM_PATH) not in sys.path:
    sys.path.insert(0, str(_MEMORY_SYSTEM_PATH))


class ExperienceLearningLogger:
    """经验学习专用日志记录器"""

    def __init__(self, mcp_data_path: Path):
        """
        初始化日志记录器

        Args:
            mcp_data_path: MCP 服务的 data 目录（例如 ~/.claude/mcp/memory-system/data/）
        """
        self.mcp_data_path = mcp_data_path
        # 日志保存到 data/logs/ 目录下
        self.log_dir = mcp_data_path / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)

        today = date.today().strftime('%Y-%m-%d')
        self.log_file = self.log_dir / f"experience_learning_{today}.log"

        self._current_session_log = []
        self._session_start = datetime.now()

    def _write(self, message: str):
        """写入日志文件"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_line = f"[{timestamp}] {message}"
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(log_line + "\n")
        except:
            pass

    def info(self, message: str):
        """记录信息日志"""
        self._write(f"[INFO] {message}")
        self._current_session_log.append(f"[INFO] {message}")

    def success(self, message: str):
        """记录成功日志"""
        self._write(f"[SUCCESS] {message}")
        self._current_session_log.append(f"[SUCCESS] {message}")

    def warn(self, message: str):
        """记录警告日志"""
        self._write(f"[WARN] {message}")
        self._current_session_log.append(f"[WARN] {message}")

    def error(self, message: str):
        """记录错误日志"""
        self._write(f"[ERROR] {message}")
        self._current_session_log.append(f"[ERROR] {message}")

    def debug(self, message: str):
        """记录调试日志"""
        self._write(f"[DEBUG] {message}")

    def start_session(self):
        """开始会话日志"""
        self._write("")
        self._write("=" * 60)
        self._write(f"[SESSION START] {self._session_start.strftime('%Y-%m-%d %H:%M:%S')}")
        self._write("=" * 60)

    def end_session(self):
        """结束会话日志"""
        duration = (datetime.now() - self._session_start).total_seconds()
        self._write(f"[SESSION END] 总耗时: {duration:.2f}秒")
        self._write("=" * 60)
        self._write("")

    def log_experience_detected(self, exp_type: str, confidence: float, reason: str):
        """记录经验检测结果"""
        self.info(f"检测到可学习经验")
        self.info(f"  类型: {exp_type}")
        self.info(f"  置信度: {confidence:.0%}")
        self.info(f"  原因: {reason}")

    def log_llm_analysis(self, summary: str, key_points: List[str], tags: List[str]):
        """记录 LLM 分析结果"""
        self.info(f"LLM 分析完成")
        self.info(f"  总结: {summary[:100]}...")
        self.info(f"  关键要点: {len(key_points)} 条")
        self.info(f"  标签: {tags}")

    def log_experience_saved(self, exp_id: str, exp_type: str, title: str, file_path: str):
        """记录经验保存结果"""
        self.success(f"经验已保存")
        self.success(f"  ID: {exp_id}")
        self.success(f"  类型: {exp_type}")
        self.success(f"  标题: {title}")
        self.success(f"  文件: {file_path}")

    def log_optimization_result(self, should_optimize: bool, trigger_type: str = "",
                                reason: str = "", components: List[str] = None):
        """记录优化结果"""
        if should_optimize:
            self.info(f"触发记忆优化: {trigger_type}")
            self.info(f"  原因: {reason}")
            if components:
                self.info(f"  建议组件: {', '.join(components)}")
        else:
            self.info(f"无需优化: {reason}")


class LLMExperienceAnalyzer:
    """使用 LLM 进行智能经验分析"""

    # 经验类型中文名映射
    TYPE_NAMES = {
        "question": "提问求解",
        "suggestion": "改进建议",
        "correction": "纠正反馈",
        "feedback": "评价反馈",
        "clarification": "澄清说明",
        "command": "执行指令",
        "preference": "偏好设置",
        "error_report": "错误报告",
        "other": "其他类型",
        "unknown": "未知类型"
    }

    ANALYSIS_PROMPT = """你是一个经验学习分析助手。请分析以下对话，提炼出可复用的经验和规则。

## 用户消息
{user_message}

## 助手回复
{assistant_message}

## 经验类型
{experience_type}

请根据对话内容，提炼出以下内容：

### 核心经验总结
用一两句话总结这次对话中最重要的经验教训。

### 具体规则/准则
列出从这次对话中学到的具体规则或最佳实践，每条规则要：
- 具有可操作性（知道怎么做）
- 具有通用性（可以应用到其他类似场景）
- 说明为什么要这样做

### 适用场景
描述这些经验/规则适用的场景。

### 注意事项
列出应用这些经验时需要注意的点。

直接输出内容，不需要 JSON 格式。"""

    def __init__(self, logger: ExperienceLearningLogger = None):
        self.logger = logger
        self._llm_service = None

    def _log(self, level: str, message: str):
        """安全日志记录"""
        if self.logger:
            getattr(self.logger, level)(message)
        else:
            print(f"[{level.upper()}] {message}")

    def _get_llm_service(self):
        """获取 LLM 服务（懒加载）"""
        if self._llm_service is None:
            try:
                from memory_system.ai.llm_service import get_llm_service
                self._llm_service = get_llm_service()
                self._log("info", "LLM 服务已连接")
            except Exception as e:
                self._log("warn", f"获取 LLM 服务失败: {e}")
                return None
        return self._llm_service

    async def analyze(
        self,
        user_message: str,
        assistant_message: str,
        experience_type: str
    ) -> Dict[str, Any]:
        """
        使用 LLM 分析对话，提取经验

        Returns:
            {
                "summary": str,
                "key_points": List[str],
                "tags": List[str],
                "importance": float,
                "confidence": float
            }
        """
        llm_service = self._get_llm_service()

        if llm_service is None:
            self._log("warn", "LLM 服务不可用，使用规则提取")
            return self._fallback_analysis(user_message, assistant_message)

        try:
            # 构建提示
            type_name = self.TYPE_NAMES.get(experience_type, "未知类型")
            prompt = self.ANALYSIS_PROMPT.format(
                user_message=user_message[:1500],
                assistant_message=assistant_message[:2000],
                experience_type=type_name
            )

            self._log("info", "调用 LLM 进行经验分析...")

            # 调用 LLM
            response = await llm_service.acomplete(
                prompt=prompt,
                temperature=0.3,
                max_tokens=800
            )

            content = response.content.strip()

            # 直接使用 LLM 返回的自然语言内容
            # 提取标题（第一行通常是核心经验）
            lines = content.split('\n')
            summary = lines[0].replace('#', '').strip()[:100] if lines else "经验总结"

            # 从内容中提取关键词作为标签
            tags = self._extract_tags_from_content(content)

            result = {
                "summary": summary,
                "content": content,  # 完整的 LLM 输出
                "key_points": [],    # 不再强制提取
                "tags": tags,
                "importance": 0.8,
                "confidence": 0.85
            }

            if self.logger:
                self.logger.log_llm_analysis(
                    summary=summary,
                    key_points=[],
                    tags=tags
                )

            return result

        except Exception as e:
            self._log("error", f"LLM 分析失败: {e}")
            return self._fallback_analysis(user_message, assistant_message)

    def _extract_tags_from_content(self, content: str) -> List[str]:
        """从内容中提取关键词作为标签"""
        import re

        # 常见经验关键词
        keywords = []

        # 提取中文关键词（2-4字）
        chinese = re.findall(r'[\u4e00-\u9fff]{2,4}', content)
        keywords.extend(chinese[:5])

        # 提取英文关键词
        english = re.findall(r'[a-zA-Z]{3,}', content)
        keywords.extend(english[:3])

        # 去重并返回
        return list(set(keywords))[:8]

    def _parse_llm_response(self, content: str) -> Dict[str, Any]:
        """解析 LLM 响应"""
        import re

        # 尝试直接解析
        try:
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

        # 返回默认值
        return {
            "summary": "LLM 响应解析失败",
            "key_points": [],
            "tags": [],
            "importance": 0.5,
            "confidence": 0.5
        }

    def _fallback_analysis(self, user_message: str, assistant_message: str) -> Dict[str, Any]:
        """回退到规则分析"""
        # 简单的总结
        user_first_sentence = user_message.split('。')[0].split('\n')[0][:100]
        summary = f"用户反馈：{user_first_sentence}"

        # 提取关键要点
        key_points = []
        suggest_keywords = ["建议", "应该", "改进", "修正", "不对", "错误"]
        text = user_message + " " + assistant_message
        for kw in suggest_keywords:
            if kw in text:
                key_points.append(f"包含{kw}相关反馈")
                if len(key_points) >= 3:
                    break

        # 提取标签
        tags = []
        if "代码" in text or "bug" in text.lower():
            tags.append("编程")
        if "优化" in text:
            tags.append("优化")

        return {
            "summary": summary,
            "key_points": key_points or ["待进一步分析"],
            "tags": tags or ["待分类"],
            "importance": 0.5,
            "confidence": 0.5
        }


class ExperienceFileManager:
    """经验文件管理器 - 负责将经验保存为 MD 文件"""

    # 经验类型中文名映射
    TYPE_NAMES = {
        "question": "提问求解",
        "suggestion": "改进建议",
        "correction": "纠正反馈",
        "feedback": "评价反馈",
        "clarification": "澄清说明",
        "command": "执行指令",
        "preference": "偏好设置",
        "error_report": "错误报告",
        "other": "其他类型",
        "unknown": "未知类型"
    }

    # 类别中文名映射
    CATEGORY_NAMES = {
        "coding": "编码相关",
        "writing": "写作相关",
        "analysis": "分析相关",
        "general": "通用经验",
        "system": "系统配置"
    }

    def __init__(self, data_path: Path, logger: ExperienceLearningLogger):
        self.data_path = data_path
        self.experiences_dir = data_path / "experiences"
        self.logger = logger

        # 确保经验目录存在
        self.experiences_dir.mkdir(parents=True, exist_ok=True)

        # 为每种类型创建子目录
        for exp_type in self.TYPE_NAMES.keys():
            type_dir = self.experiences_dir / exp_type
            type_dir.mkdir(parents=True, exist_ok=True)

    def save_experience_as_md(
        self,
        exp_id: str,
        exp_type: str,
        category: str,
        user_message: str,
        assistant_message: str,
        summary: str,
        key_points: List[str],
        tags: List[str],
        confidence: float,
        importance: float,
        session_id: str = "",
        date_str: str = "",
        conversation_id: str = "",
        content: str = ""  # LLM 完整输出
    ) -> Optional[Path]:
        """
        将经验保存为 MD 文件

        Returns:
            保存的文件路径，失败返回 None
        """
        try:
            type_dir = self.experiences_dir / exp_type

            # 生成文件名
            date_compact = (date_str or date.today().strftime('%Y-%m-%d')).replace('-', '')
            file_name = f"{date_compact}_{exp_id[:8]}.md"
            file_path = type_dir / file_name

            # 构建 MD 内容
            md_content = self._generate_md_content(
                exp_id=exp_id,
                exp_type=exp_type,
                category=category,
                user_message=user_message,
                assistant_message=assistant_message,
                summary=summary,
                key_points=key_points,
                tags=tags,
                confidence=confidence,
                importance=importance,
                session_id=session_id,
                date_str=date_str,
                conversation_id=conversation_id,
                content=content
            )

            # 写入文件
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(md_content)

            return file_path

        except Exception as e:
            self.logger.error(f"保存经验文件失败: {e}")
            return None

    def _generate_md_content(
        self,
        exp_id: str,
        exp_type: str,
        category: str,
        user_message: str,
        assistant_message: str,
        summary: str,
        key_points: List[str],
        tags: List[str],
        confidence: float,
        importance: float,
        session_id: str,
        date_str: str,
        conversation_id: str,
        content: str = ""  # LLM 完整输出
    ) -> str:
        """生成经验的 Markdown 内容"""
        type_name = self.TYPE_NAMES.get(exp_type, "未知类型")
        category_name = self.CATEGORY_NAMES.get(category, "未知类别")

        # 格式化时间
        created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # 构建 key_points 列表
        key_points_md = ""
        if key_points:
            key_points_md = "\n".join([f"- {point}" for point in key_points])

        # 构建标签
        tags_str = ", ".join(tags) if tags else "无"

        # 截取消息
        user_msg = user_message
        if len(user_msg) > 1000:
            user_msg = user_msg[:1000] + "...(已截断)"

        assistant_msg = assistant_message
        if len(assistant_msg) > 2000:
            assistant_msg = assistant_msg[:2000] + "...(已截断)"

        # 生成标题
        title = summary if summary else f"{type_name} - {created_at}"
        if len(title) > 50:
            title = title[:50] + "..."

        # LLM 分析内容（如果有）
        llm_analysis_section = ""
        if content:
            llm_analysis_section = f"""
## 🧠 LLM 分析

{content}

"""

        md_content = f"""# {title}

> **经验类型**: {type_name}
> **经验类别**: {category_name}
> **创建时间**: {created_at}
> **置信度**: {confidence:.0%}
> **重要性**: {importance:.0%}

## 📝 经验总结

{summary or '暂无总结'}
{llm_analysis_section}## 🏷️ 标签

{tags_str}

## 💬 原始对话

### 用户消息

{user_msg}

### 助手回复

{assistant_msg}

---

**元数据**
- ID: `{exp_id}`
- 会话ID: `{session_id}`
- 对话ID: `{conversation_id}`
- 日期: `{date_str}`
"""
        return md_content


# 全局日志记录器
_logger: Optional[ExperienceLearningLogger] = None

def get_logger(data_path: Path = None) -> ExperienceLearningLogger:
    """获取日志记录器"""
    global _logger
    if _logger is None and data_path:
        _logger = ExperienceLearningLogger(data_path)
    return _logger


def log(message: str):
    """日志记录辅助函数"""
    global _logger
    if _logger:
        _logger.info(message)
    else:
        print(f"[LOG] {message}")


def read_transcript(transcript_path: str) -> Optional[str]:
    """读取对话历史文件"""
    try:
        with open(transcript_path, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        log(f"Transcript 文件未找到: {transcript_path}")
        return None
    except Exception as e:
        log(f"读取 Transcript 失败: {e}")
        return None


def extract_last_conversation(transcript: str) -> Optional[Dict]:
    """从 transcript 中提取最后一轮对话"""
    if not transcript:
        return None

    messages = []

    # 尝试按 JSONL 格式解析
    for line in transcript.strip().split('\n'):
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            messages.append(msg)
        except json.JSONDecodeError:
            continue

    if not messages:
        try:
            data = json.loads(transcript)
            if isinstance(data, list):
                messages = data
            elif isinstance(data, dict) and 'messages' in data:
                messages = data['messages']
        except json.JSONDecodeError:
            pass

    if not messages:
        return None

    def extract_text_from_content(content, include_tool_results=True):
        """从 content 中提取文本"""
        if isinstance(content, str):
            return content if content.strip() else None

        if isinstance(content, list):
            texts = []
            for item in content:
                if isinstance(item, dict):
                    item_type = item.get('type', '')
                    if item_type == 'text':
                        texts.append(item.get('text', ''))
                    elif item_type == 'thinking':
                        texts.append(f"[思考] {item.get('thinking', '')}")
                    elif item_type == 'tool_result' and include_tool_results:
                        tool_content = item.get('content', '')
                        if isinstance(tool_content, str) and len(tool_content) < 500:
                            texts.append(f"[工具结果] {tool_content}")
                elif isinstance(item, str):
                    texts.append(item)
            result = '\n'.join(texts).strip()
            return result if result else None
        return None

    def has_text_content(content):
        """检查 content 是否包含实际文本"""
        if isinstance(content, str):
            return bool(content.strip())
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    item_type = item.get('type', '')
                    if item_type in ['text', 'thinking']:
                        return True
                elif isinstance(item, str) and item.strip():
                    return True
        return False

    def get_role(msg):
        role = msg.get('role', '') or msg.get('type', '')
        if role not in ['user', 'assistant']:
            role = msg.get('message', {}).get('role', '')
        return role

    def get_content(msg):
        return msg.get('content', '') or msg.get('message', {}).get('content', '')

    def is_only_tool_result(content):
        if isinstance(content, str):
            return False
        if isinstance(content, list):
            has_tool_result = False
            has_other_content = False
            for item in content:
                if isinstance(item, dict):
                    item_type = item.get('type', '')
                    if item_type == 'tool_result':
                        has_tool_result = True
                    elif item_type in ['text', 'thinking']:
                        has_other_content = True
                elif isinstance(item, str) and item.strip():
                    has_other_content = True
            return has_tool_result and not has_other_content
        return False

    # 找到最后一轮完整对话
    last_assistant_idx = -1
    original_user_idx = -1

    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        role = get_role(msg)

        if role == 'assistant' and last_assistant_idx == -1:
            last_assistant_idx = i
        elif role == 'user' and last_assistant_idx != -1:
            content = get_content(msg)
            if has_text_content(content) and not is_only_tool_result(content):
                original_user_idx = i
                break

    if original_user_idx == -1 or last_assistant_idx == -1:
        return None

    # 提取主要文本内容
    user_msg = extract_text_from_content(
        get_content(messages[original_user_idx]),
        include_tool_results=False
    )
    assistant_msg = extract_text_from_content(
        get_content(messages[last_assistant_idx]),
        include_tool_results=True
    )

    if user_msg and assistant_msg:
        if len(user_msg) > 2000:
            user_msg = user_msg[:2000] + "..."
        if len(assistant_msg) > 4000:
            assistant_msg = assistant_msg[:4000] + "..."

        return {
            "user_message": user_msg,
            "assistant_message": assistant_msg,
        }

    return None


def _detect_category(user_message: str, assistant_message: str) -> str:
    """检测经验类别"""
    text = (user_message + " " + assistant_message).lower()

    coding_keywords = ["代码", "函数", "类", "方法", "bug", "错误", "调试", "实现", "变量", "import", "api"]
    for kw in coding_keywords:
        if kw in text:
            return "coding"

    writing_keywords = ["写", "小说", "文章", "故事", "段落", "句子", "角色", "对话"]
    for kw in writing_keywords:
        if kw in text:
            return "writing"

    analysis_keywords = ["分析", "研究", "调查", "评估", "比较", "总结", "数据"]
    for kw in analysis_keywords:
        if kw in text:
            return "analysis"

    system_keywords = ["配置", "设置", "环境", "部署", "服务器", "数据库"]
    for kw in system_keywords:
        if kw in text:
            return "system"

    return "general"


async def run_experience_learning_with_llm(
    storage_path: str,
    user_message: str,
    assistant_message: str,
    session_id: str = "",
    date_str: str = "",
    conversation_id: str = ""
):
    """
    使用 LLM 执行经验学习流程

    1. 检测对话是否包含可学习经验
    2. 使用 LLM 智能分析
    3. 保存为 MD 文件
    """
    global _logger

    try:
        from memory_system.experience import ExperienceDetector
        import hashlib

        log("开始经验检测...")

        # 1. 检测经验类型
        detector = ExperienceDetector()
        detection_result = detector.detect(user_message, assistant_message)

        if not detection_result.is_experience:
            log("未检测到可学习经验")
            return None

        # 记录检测结果
        if _logger:
            _logger.log_experience_detected(
                exp_type=detection_result.experience_type.display_name,
                confidence=detection_result.confidence,
                reason=detection_result.reason
            )

        # 2. 使用 LLM 分析
        analyzer = LLMExperienceAnalyzer(_logger)
        analysis = await analyzer.analyze(
            user_message=user_message,
            assistant_message=assistant_message,
            experience_type=detection_result.experience_type.value
        )

        # 3. 检测类别
        category = _detect_category(user_message, assistant_message)

        # 4. 生成经验 ID
        content = user_message + assistant_message
        exp_id = f"exp_{hashlib.md5((content + datetime.now().isoformat()).encode()).hexdigest()[:8]}"

        # 5. 保存为 MD 文件到 MCP data/experiences/ 目录
        # 使用全局 MCP_DATA_PATH（指向 ~/.claude/mcp/memory-system/data/）
        file_manager = ExperienceFileManager(MCP_DATA_PATH, _logger)

        file_path = file_manager.save_experience_as_md(
            exp_id=exp_id,
            exp_type=detection_result.experience_type.value,
            category=category,
            user_message=user_message,
            assistant_message=assistant_message,
            summary=analysis.get("summary", ""),
            key_points=analysis.get("key_points", []),
            tags=analysis.get("tags", []),
            confidence=analysis.get("confidence", detection_result.confidence),
            importance=analysis.get("importance", 0.5),
            session_id=session_id,
            date_str=date_str,
            conversation_id=conversation_id,
            content=analysis.get("content", "")  # LLM 完整分析内容
        )

        # 记录保存结果
        if _logger and file_path:
            _logger.log_experience_saved(
                exp_id=exp_id,
                exp_type=detection_result.experience_type.display_name,
                title=analysis.get("summary", "无标题")[:50],
                file_path=str(file_path)
            )

        # 6. 同时保存到 YAML（兼容现有系统）
        try:
            from memory_system.experience import Experience, ExperienceManager
            from memory_system.experience.models import ExperienceType, ExperienceCategory

            manager = ExperienceManager(storage_path)
            experience = Experience(
                id=exp_id,
                experience_type=detection_result.experience_type,
                category=ExperienceCategory(category),
                user_message=user_message,
                assistant_message=assistant_message,
                summary=analysis.get("summary", ""),
                key_points=analysis.get("key_points", []),
                confidence=analysis.get("confidence", detection_result.confidence),
                importance=analysis.get("importance", 0.5),
                tags=analysis.get("tags", []),
                session_id=session_id,
                date=date_str,
                conversation_id=conversation_id
            )
            manager.add_experience(experience)
            log("经验已同步到 YAML 存储")
        except Exception as e:
            log(f"同步到 YAML 失败: {e}")

        return {
            "id": exp_id,
            "type": detection_result.experience_type.value,
            "file_path": str(file_path) if file_path else None
        }

    except Exception as e:
        log(f"经验学习失败: {e}")
        log(traceback.format_exc())
        return None


async def run_memory_optimization(storage_path: str, user_message: str, assistant_message: str):
    """
    执行智能判断和记忆优化
    """
    global _logger

    try:
        from memory_system.optimization import MemoryOptimizer

        log("开始记忆优化判断...")

        optimizer = MemoryOptimizer(storage_path, enable_intelligent_judge=True)

        decision = optimizer.judge_after_conversation(
            user_message=user_message,
            assistant_response=assistant_message,
            auto_trigger=True
        )

        if _logger:
            _logger.log_optimization_result(
                should_optimize=decision.should_optimize,
                trigger_type=decision.trigger_type if decision.should_optimize else "",
                reason=decision.reason,
                components=decision.suggested_components if decision.should_optimize else None
            )

        return decision

    except Exception as e:
        log(f"记忆优化失败: {e}")
        log(traceback.format_exc())
        return None


def main():
    """主函数 - Hook 入口"""
    global _logger

    # 初始化日志记录器
    _logger = ExperienceLearningLogger(MEMORY_DATA_PATH)
    _logger.start_session()

    try:
        log("经验学习 Hook 被触发")

        # 读取 stdin 输入
        raw_input = sys.stdin.read()
        _logger.debug(f"原始输入: {raw_input[:500]}...")

        # 尝试解析 JSON
        try:
            input_data = json.loads(raw_input)
        except json.JSONDecodeError as e:
            log(f"JSON 解析失败: {e}")
            print(json.dumps({}))
            sys.exit(0)

        # 获取 transcript 路径
        transcript_path = input_data.get('transcript_path', '')
        reason = input_data.get('reason', '')

        log(f"Stop 事件触发, reason: {reason}")

        if not transcript_path:
            log("没有 transcript_path，跳过")
            print(json.dumps({}))
            sys.exit(0)

        # 读取 transcript
        transcript = read_transcript(transcript_path)
        if not transcript:
            log("无法读取 transcript，跳过")
            print(json.dumps({}))
            sys.exit(0)

        # 提取最后一轮对话
        conversation = extract_last_conversation(transcript)
        if not conversation:
            log("无法提取对话内容，跳过")
            print(json.dumps({}))
            sys.exit(0)

        user_message = conversation.get("user_message", "")
        assistant_message = conversation.get("assistant_message", "")

        # 过滤掉太短或无意义的对话
        if len(user_message) < 5 or len(assistant_message) < 10:
            log("对话内容太短，跳过")
            print(json.dumps({}))
            sys.exit(0)

        # 确定存储路径（根据当前人格）
        sys.path.insert(0, str(_MEMORY_SYSTEM_PATH))
        from memory_system.personas import PersonaManager

        persona_manager = PersonaManager(str(MEMORY_DATA_PATH))
        index = persona_manager.load_index()
        active_persona = index.active_persona

        if active_persona:
            storage_path = str(MEMORY_DATA_PATH / "personas" / active_persona)
            persona_name = persona_manager.load_persona_config(active_persona)
            persona_name = persona_name.name if persona_name else active_persona
            log(f"当前人格: {persona_name}")
        else:
            storage_path = str(MEMORY_DATA_PATH)
            log("使用默认存储路径")

        log(f"存储路径: {storage_path}")

        # 生成会话信息
        today = date.today()
        session_id = f"sess_{today.strftime('%Y%m%d')}"
        date_str = today.strftime('%Y-%m-%d')
        conversation_id = f"conv_{datetime.now().strftime('%H%M%S')}"

        log(f"会话ID: {session_id}, 对话ID: {conversation_id}")

        # 1. 执行经验学习（使用 LLM）
        log("执行经验学习（LLM 增强）...")
        try:
            result = asyncio.run(run_experience_learning_with_llm(
                storage_path=storage_path,
                user_message=user_message,
                assistant_message=assistant_message,
                session_id=session_id,
                date_str=date_str,
                conversation_id=conversation_id
            ))
            if result:
                log(f"经验学习完成: {result}")
        except Exception as e:
            _logger.error(f"经验学习异常: {e}")
            _logger.error(traceback.format_exc())

        # 2. 执行记忆优化
        log("执行记忆优化判断...")
        try:
            asyncio.run(run_memory_optimization(
                storage_path=storage_path,
                user_message=user_message,
                assistant_message=assistant_message
            ))
        except Exception as e:
            _logger.error(f"记忆优化异常: {e}")
            _logger.error(traceback.format_exc())

        log("Hook 执行完成")

        # 返回空结果
        print(json.dumps({}))

    except Exception as e:
        _logger.error(f"Hook 执行错误: {e}")
        _logger.error(traceback.format_exc())
        print(json.dumps({}))
    finally:
        _logger.end_session()
    sys.exit(0)


if __name__ == '__main__':
    main()
