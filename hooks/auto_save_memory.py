#!/usr/bin/env python3
"""
自动保存记忆 Hook - 在每轮对话结束时自动保存到记忆系统

工作流程：
1. 检测最后一轮对话
2. 检查当日记忆文件，判断是否已经保存过
3. 如果未保存，调用 MemorySystem 保存
4. 异步执行记忆优化
"""

# ========== 最早期调试（使用统一日志） ==========
import sys as _sys
from datetime import datetime as _dt
from pathlib import Path as _Path
_stdin_content = None
_early_debug_file = _Path.home() / ".memory-system" / "logs" / "hooks" / "auto_save_debug.log"
try:
    _stdin_content = _sys.stdin.read()
    _early_debug_file.parent.mkdir(parents=True, exist_ok=True)
    with open(_early_debug_file, "a", encoding="utf-8") as _f:
        _f.write(f"\n=== {_dt.now()} ===\n")
        _f.write(f"Python started\n")
        _f.write(f"Args: {_sys.argv}\n")
        _f.write(f"Stdin content: {_stdin_content[:500] if _stdin_content else 'empty'}\n")
except Exception as _e:
    pass  # 静默失败
# ========== 最早期调试结束 ==========

import json
import sys
import os
import asyncio
import traceback
from datetime import datetime, date
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
import yaml

import importlib.util

# 导入通用 LLM 工具
from llm_utils import call_llm

# 直接导入新保存函数（同目录下）
from session_saver_v2 import save_session_to_file

# 恢复 stdin 内容供后续使用
import io
if _stdin_content is not None:
    sys.stdin = io.StringIO(_stdin_content)

# 记忆系统路径 - 支持多种安装方式
def _detect_memory_paths() -> tuple:
    """自动检测记忆系统路径

    返回: (memory_system_module_path, data_storage_path)
    - memory_system_module_path: memory_system 模块的父目录
    - data_storage_path: 记忆数据存储目录
    """
    # 1. 优先使用环境变量
    data_path = os.environ.get('MEMORY_DATA_PATH')
    if data_path:
        # 需要同时检测模块路径
        memory_system_path = Path(data_path).parent
        return memory_system_path, Path(data_path)

    # 2. 检测 Claude Code MCP 安装路径（优先级最高）
    claude_mcp_path = Path.home() / ".claude" / "mcp" / "memory-system"
    if (claude_mcp_path / "memory_system" / "__init__.py").exists():
        # 数据存储在 MCP 安装目录下的 data/memory/
        data_path = claude_mcp_path / "data" / "memory"
        return claude_mcp_path, data_path

    # 3. 检测项目目录
    project_path = Path(__file__).parent.parent
    if (project_path / "memory_system" / "__init__.py").exists():
        data_path = project_path / "data" / "memory"
        if data_path.exists():
            return project_path, data_path
        return project_path, Path.home() / ".memory-system"

    # 4. 检测全局安装（通过 pip）
    try:
        import memory_system
        module_path = Path(memory_system.__file__).parent.parent
        return module_path, Path.home() / ".memory-system"
    except ImportError:
        pass

    # 5. 默认路径
    return Path.home() / ".memory-system", Path.home() / ".memory-system"

_MEMORY_SYSTEM_PATH, MEMORY_DATA_PATH = _detect_memory_paths()

# 创建别名（兼容旧代码）
MEMORY_SYSTEM_PATH = _MEMORY_SYSTEM_PATH

# 确保 memory_system 模块可导入
if _MEMORY_SYSTEM_PATH and str(_MEMORY_SYSTEM_PATH) not in sys.path:
    sys.path.insert(0, str(_MEMORY_SYSTEM_PATH))

# 尝试导入统一日志模块
try:
    _memory_system_path = _MEMORY_SYSTEM_PATH or Path(__file__).parent.parent
    if str(_memory_system_path) not in sys.path:
        sys.path.insert(0, str(_memory_system_path))

    from memory_system.logging_config import get_logger, init_logging, get_log_path

    # 初始化日志系统
    _config_path = _memory_system_path / "data" / "memory" / "config.yaml"
    if not _config_path.exists():
        _config_path = _memory_system_path / "memory_config.yaml"
    init_logging(config_path=str(_config_path) if _config_path.exists() else None)

    _logger = get_logger("auto_save", "hooks")

    def log(message: str):
        """记录日志（使用统一日志系统）"""
        _logger.info(message)

except ImportError:
    # 回退到基础日志
    LOG_FILE = Path.home() / ".memory-system" / "logs" / "hooks" / "auto_save.log"
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    def log(message: str):
        """记录日志（回退到文件日志）"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"[{timestamp}] {message}\n")
        except:
            pass

# ========== LLM 调用（通过 llm_utils 通用模块，支持所有 provider） ==========

def analyze_session_with_http(session: Dict) -> Dict:
    """
    通过 HTTP API 分析会话

    Args:
        session: 会话数据

    Returns:
        分析结果字典
    """
    conversations = session.get("conversations", [])
    conv_texts = []
    for conv in conversations:
        role = conv.get("role", "")
        content = conv.get("content", "")
        if content:
            prefix = "用户" if role == "user" else "助手"
            conv_texts.append(f"{prefix}: {content[:500]}")

    if not conv_texts:
        return _fallback_session_analysis(session)

    combined = "\n\n".join(conv_texts[:30])  # 最多30条
    if len(combined) > 8000:
        combined = combined[:8000] + "\n\n...(内容已截断)"

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

    result = call_llm(prompt)
    if not result:
        return _fallback_session_analysis(session)

    # 解析 JSON 结果
    import re
    json_match = re.search(r'\{.*\}', result, re.DOTALL)
    if json_match:
        try:
            parsed = json.loads(json_match.group())
            parsed["session_id"] = session.get("session_id", "")
            parsed["date"] = session.get("date", "")
            return parsed
        except json.JSONDecodeError:
            pass

    return _fallback_session_analysis(session)

def normalize_content(content: str, max_len: int = 100) -> str:
    """标准化内容用于比较"""
    # 移除多余空白，截断
    normalized = " ".join(content.split())
    return normalized[:max_len].lower()

def is_conversation_already_saved(
    storage_path: str,
    user_message: str,
    assistant_message: str,
    persona_id: str = "default",
    session_id: str = None
) -> bool:
    """
    检查对话是否已经保存过（新路径格式）

    新路径格式：{storage_path}/personas/{persona_id}/{date}/{session_id}.yaml
    """
    try:
        import yaml

        # 构建当日会话文件路径（新格式）
        today = date.today()
        date_str = today.isoformat()

        if session_id:
            # 检查指定会话文件
            session_file = Path(storage_path) / "personas" / persona_id / date_str / f"{session_id}.yaml"
        else:
            # 检查当日所有会话文件
            date_dir = Path(storage_path) / "personas" / persona_id / date_str
            if not date_dir.exists():
                log(f"今日目录不存在: {date_dir}")
                return False

            # 获取最新的会话文件
            session_files = sorted(date_dir.glob("sess_*.yaml"), key=lambda x: x.stat().st_mtime, reverse=True)
            if not session_files:
                return False
            session_file = session_files[0]

        if not session_file.exists():
            log(f"会话文件不存在: {session_file}")
            return False

        with open(session_file, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        if not data or 'conversations' not in data:
            return False

        conversations = data.get('conversations', [])
        if len(conversations) < 2:
            return False

        # 获取最后两条对话
        last_user = None
        last_assistant = None

        for conv in reversed(conversations):
            role = conv.get('role', '')
            content = conv.get('content', '')

            if role == 'assistant' and last_assistant is None:
                last_assistant = content
            elif role == 'user' and last_assistant is not None and last_user is None:
                last_user = content
                break

        if not last_user or not last_assistant:
            return False

        # 比较内容（标准化后）
        user_match = normalize_content(last_user) == normalize_content(user_message)
        assistant_match = normalize_content(last_assistant) == normalize_content(assistant_message)

        if user_match and assistant_match:
            log(f"对话已存在于会话文件中，跳过保存")
            log(f"  已保存用户: {normalize_content(last_user)[:50]}...")
            log(f"  新用户消息: {normalize_content(user_message)[:50]}...")
            return True

        return False

    except Exception as e:
        log(f"检查记忆文件失败: {e}")
        return False

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
    """从 transcript 中提取最后一轮对话（包括工具调用）

    支持两种格式：
    1. Claude Code 新格式：{"type": "user/assistant", "message": {"role": "...", "content": ...}}
    2. 旧格式：{"role": "user/assistant", "content": "..."}

    返回: {
        "user_message": str,
        "assistant_message": str,
        "tool_calls": List[Dict],
        "tool_results": List[Dict],
        "conversation_history": List[Dict]
    }
    """
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

    tool_calls = []
    tool_results = []
    conversation_history = []

    def extract_text_from_content(content, include_tool_results=True):
        """从 content 中提取文本（支持字符串、数组等格式）"""
        if isinstance(content, str):
            return content if content.strip() else None

        if isinstance(content, list):
            texts = []
            for item in content:
                if isinstance(item, dict):
                    item_type = item.get('type', '')
                    # 提取 text 类型的内容
                    if item_type == 'text':
                        texts.append(item.get('text', ''))
                    # 也提取 thinking 内容（作为上下文）
                    elif item_type == 'thinking':
                        texts.append(f"[思考] {item.get('thinking', '')}")
                    # tool_result 根据参数决定是否包含
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
        """检查 content 是否包含实际文本（非 tool_result）"""
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

    def extract_tool_calls_from_content(content):
        """从 assistant content 中提取 tool_calls"""
        calls = []
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get('type') == 'tool_use':
                    calls.append({
                        "id": item.get('id', ''),
                        "name": item.get('name', ''),
                        "arguments": item.get('input', {})
                    })
        return calls

    def extract_tool_results_from_msg(msg):
        """从消息中提取 tool_result"""
        content = msg.get('content', '')
        if not content:
            content = msg.get('message', {}).get('content', '')

        results = []
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get('type') == 'tool_result':
                    results.append({
                        "tool_call_id": item.get('tool_use_id', ''),
                        "content": item.get('content', ''),
                        "is_error": item.get('is_error', False)
                    })
        return results

    def is_only_tool_result(content):
        """检查 content 是否只包含 tool_result（没有实际文本）"""
        if isinstance(content, str):
            return False  # 纯字符串不是工具结果
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

    def get_role(msg):
        """获取消息角色"""
        role = msg.get('role', '') or msg.get('type', '')
        if role not in ['user', 'assistant']:
            role = msg.get('message', {}).get('role', '')
        return role

    def get_content(msg):
        """获取消息内容"""
        return msg.get('content', '') or msg.get('message', {}).get('content', '')

    # 找到最后一轮完整对话的索引范围
    # 策略：从最后一个 assistant 消息向前找，找到包含实际文本的用户消息
    last_assistant_idx = -1
    original_user_idx = -1

    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        role = get_role(msg)

        if role == 'assistant' and last_assistant_idx == -1:
            last_assistant_idx = i
        elif role == 'user' and last_assistant_idx != -1:
            content = get_content(msg)
            # 找到包含实际文本的用户消息（不只是 tool_result）
            if has_text_content(content) and not is_only_tool_result(content):
                original_user_idx = i
                break

    if original_user_idx == -1 or last_assistant_idx == -1:
        return None

    # 提取这一轮对话中的所有消息（包括中间的 tool 相关消息）
    for i in range(original_user_idx, min(last_assistant_idx + 1, len(messages))):
        msg = messages[i]
        role = get_role(msg)
        content = get_content(msg)

        # 构建对话历史
        history_entry = {
            "role": role,
            "content": extract_text_from_content(content) or ""
        }

        if role == 'assistant':
            # 提取工具调用
            calls = extract_tool_calls_from_content(content)
            if calls:
                history_entry["tool_calls"] = calls
                tool_calls.extend(calls)

            # 提取工具结果（可能在 assistant 消息中）
            results = extract_tool_results_from_msg(msg)
            if results:
                history_entry["tool_results"] = results
                tool_results.extend(results)

        elif role == 'user':
            # 用户消息中可能包含 tool_result
            results = extract_tool_results_from_msg(msg)
            if results:
                history_entry["tool_results"] = results
                tool_results.extend(results)

        conversation_history.append(history_entry)

    # 提取主要文本内容（不包含工具结果的纯文本）
    user_msg = extract_text_from_content(
        get_content(messages[original_user_idx]),
        include_tool_results=False
    )
    assistant_msg = extract_text_from_content(
        get_content(messages[last_assistant_idx]),
        include_tool_results=True  # 助手消息包含所有内容
    )

    if user_msg and assistant_msg:
        if len(user_msg) > 2000:
            user_msg = user_msg[:2000] + "..."
        if len(assistant_msg) > 4000:
            assistant_msg = assistant_msg[:4000] + "..."

        log(f"提取到 {len(tool_calls)} 个工具调用")
        log(f"提取到 {len(tool_results)} 个工具结果")
        log(f"提取到 {len(conversation_history)} 条对话历史")

        return {
            "user_message": user_msg,
            "assistant_message": assistant_msg,
            "tool_calls": tool_calls,
            "tool_results": tool_results,
            "conversation_history": conversation_history
        }

    return None


# ============== 会话文件存储（按会话ID隔离） ==============

def generate_session_id() -> str:
    """生成会话ID：sess_{日期}_{时间}"""
    now = datetime.now()
    return f"sess_{now.strftime('%Y%m%d_%H%M%S')}"


def get_session_file_path(storage_path: str, persona_id: str, session_id: str = None) -> Path:
    """获取会话文件路径（新格式：按日期分目录）

    存储结构：
    {storage_path}/
    └── personas/
        └── {persona_id}/
            └── 2026-03-24/
                ├── sess_143052_abc123.yaml   ← 会话A
                └── sess_160523_def456.yaml   ← 会话B
    """
    if not session_id:
        session_id = generate_session_id()

    today = date.today()
    date_str = today.isoformat()
    date_dir = Path(storage_path) / "personas" / persona_id / date_str
    date_dir.mkdir(parents=True, exist_ok=True)

    return date_dir / f"{session_id}.yaml"


def save_session_file(
    file_path: Path,
    user_message: str,
    assistant_message: str,
    tool_calls: Optional[List[Dict]] = None,
    tool_results: Optional[List[Dict]] = None,
    conversation_history: Optional[List[Dict]] = None,
    session_id: str = None
) -> Dict[str, Any]:
    """保存对话到会话文件（按会话ID隔离）

    每个会话一个独立文件，不会混淆
    """
    try:
        import yaml
        from datetime import date

        # 如果没有提供文件路径，创建新的
        if file_path is None:
            if not session_id:
                session_id = generate_session_id()
            # storage_path 需要从其他地方获取
            return {"success": False, "error": "需要提供 file_path"}

        # 构建会话数据
        today = date.today()
        now = datetime.now()

        session_data = {
            "session_id": session_id or file_path.stem,
            "date": str(today),
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "conversations": [],
            "summary": "",
            "keywords": []
        }

        # 如果有完整对话历史，使用它
        if conversation_history and len(conversation_history) > 0:
            for msg in conversation_history:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                msg_tool_calls = msg.get("tool_calls", [])
                msg_tool_results = msg.get("tool_results", [])

                conv_entry = {
                    "role": role,
                    "content": content,
                    "timestamp": now.isoformat()
                }

                if msg_tool_calls:
                    conv_entry["tool_calls"] = msg_tool_calls
                if msg_tool_results:
                    conv_entry["tool_results"] = msg_tool_results

                session_data["conversations"].append(conv_entry)
        else:
            # 简化模式：只保存当前对话
            if user_message:
                session_data["conversations"].append({
                    "role": "user",
                    "content": user_message,
                    "timestamp": now.isoformat()
                })

            if tool_calls:
                session_data["conversations"].append({
                    "role": "assistant",
                    "content": "",
                    "tool_calls": tool_calls,
                    "timestamp": now.isoformat()
                })

            if assistant_message:
                session_data["conversations"].append({
                    "role": "assistant",
                    "content": assistant_message,
                    "timestamp": now.isoformat()
                })

        # 检查文件是否已存在（追加模式）
        if file_path.exists():
            with open(file_path, 'r', encoding='utf-8') as f:
                existing_data = yaml.safe_load(f) or {}

            # 合并数据
            if "conversations" in existing_data:
                # 检查最后一条是否重复
                if existing_data["conversations"]:
                    last_conv = existing_data["conversations"][-1]
                    new_conv = session_data["conversations"][-1] if session_data["conversations"] else None

                    if new_conv and (
                        last_conv.get("content") == new_conv.get("content") and
                        last_conv.get("role") == new_conv.get("role")
                    ):
                        log("对话已存在于会话文件中，跳过")
                        return {"success": True, "mode": "duplicate"}

                # 追加新对话
                existing_data["conversations"].extend(session_data["conversations"])
                existing_data["updated_at"] = now.isoformat()
                session_data = existing_data

        # 保存文件
        with open(file_path, 'w', encoding='utf-8') as f:
            yaml.dump(
                session_data,
                f,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False
            )

        log(f"会话文件已保存: {file_path}")
        return {
            "success": True,
            "session_id": session_data.get("session_id"),
            "file_path": str(file_path),
            "conversation_count": len(session_data.get("conversations", []))
        }

    except Exception as e:
        log(f"保存会话文件失败: {e}")
        return {"success": False, "error": str(e)}


def get_or_create_session_file(storage_path: str, session_id: str = None) -> tuple:
    """获取或创建会话文件

    Returns:
        (file_path, session_id, is_new_session)
    """
    sessions_dir = Path(storage_path) / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)

    if session_id:
        # 使用指定的 session_id
        file_path = sessions_dir / f"{session_id}.yaml"
        is_new = not file_path.exists()
        return file_path, session_id, is_new
    else:
        # 创建新会话
        session_id = generate_session_id()
        file_path = sessions_dir / f"{session_id}.yaml"
        return file_path, session_id, True


def get_recent_session_files(storage_path: str, limit: int = 5) -> List[Path]:
    """获取最近的会话文件列表

    Returns:
        按修改时间倒序排列的会话文件列表
    """
    sessions_dir = Path(storage_path) / "sessions"

    if not sessions_dir.exists():
        return []

    # 获取所有会话文件，按修改时间排序
    session_files = list(sessions_dir.glob("sess_*.yaml"))
    session_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)

    return session_files[:limit]


# ============== 日期索引生成 ==============

async def generate_date_index(
    storage_path: str,
    persona_id: str,
    date_str: str
) -> Dict[str, Any]:
    """
    生成日期索引（调用 OpenCode CLI 分析会话）

    索引内容包括：
    - 会话做了哪些事？
    - 用户提出了哪些问题？
    - 模型的解决方案是什么？
    - 改了哪些地方？
    - 可复用的经验总结

    Args:
        storage_path: 存储根路径
        persona_id: 人格ID
        date_str: 日期字符串 (YYYY-MM-DD)

    Returns:
        生成的索引数据
    """
    try:
        import yaml

        # 构建日期目录路径
        date_dir = Path(storage_path) / "personas" / persona_id / date_str
        if not date_dir.exists():
            log(f"日期目录不存在: {date_dir}")
            return {"success": False, "error": "日期目录不存在"}

        # 获取当天所有会话文件
        session_files = sorted(date_dir.glob("sess_*.yaml"))
        if not session_files:
            log(f"没有找到会话文件: {date_dir}")
            return {"success": False, "error": "没有会话文件"}

        log(f"找到 {len(session_files)} 个会话文件")

        # 收集所有会话数据
        sessions_data = []
        for sf in session_files:
            try:
                with open(sf, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f) or {}
                    data["file_name"] = sf.name
                    sessions_data.append(data)
            except Exception as e:
                log(f"读取会话文件失败 {sf}: {e}")

        if not sessions_data:
            return {"success": False, "error": "无法读取任何会话文件"}

        # 使用 HTTP API 进行深度分析（替代 OpenCode CLI）
        analyzed_sessions = []
        for session in sessions_data:
            try:
                analysis = analyze_session_with_http(session)
                analyzed_sessions.append({
                    "session_id": session.get("session_id", ""),
                    "file_name": session.get("file_name", ""),
                    "time_range": _get_session_time_range(session),
                    "analysis": analysis
                })
            except Exception as e:
                log(f"分析会话失败: {e}")
                # 使用降级数据
                analyzed_sessions.append({
                    "session_id": session.get("session_id", ""),
                    "file_name": session.get("file_name", ""),
                    "time_range": _get_session_time_range(session),
                    "analysis": _fallback_session_analysis(session)
                })

        # 生成 Markdown 索引
        index_content = _build_markdown_index(date_str, analyzed_sessions)

        # 保存索引文件
        index_file = date_dir / "index.md"
        with open(index_file, 'w', encoding='utf-8') as f:
            f.write(index_content)

        log(f"日期索引已生成: {index_file}")
        return {
            "success": True,
            "index_file": str(index_file),
            "sessions_count": len(analyzed_sessions)
        }

    except Exception as e:
        log(f"生成日期索引失败: {e}")
        import traceback
        log(traceback.format_exc())
        return {"success": False, "error": str(e)}


def _get_session_time_range(session: Dict) -> str:
    """获取会话时间范围"""
    convs = session.get("conversations", [])
    if not convs:
        # 从 created_at 和 updated_at 获取
        created = session.get("created_at", "")
        updated = session.get("updated_at", "")
        start = created[11:16] if len(created) > 16 else ""
        end = updated[11:16] if len(updated) > 16 else ""
        return f"{start} - {end}" if start and end else ""

    first_ts = convs[0].get("timestamp", "")
    last_ts = convs[-1].get("timestamp", "")
    start = first_ts[11:16] if len(first_ts) > 16 else ""
    end = last_ts[11:16] if len(last_ts) > 16 else ""
    return f"{start} - {end}" if start and end else ""


def _fallback_session_analysis(session: Dict) -> Dict:
    """降级会话分析（OpenCode 不可用时）"""
    convs = session.get("conversations", [])
    user_msgs = [c.get("content", "")[:100] for c in convs if c.get("role") == "user"]
    assistant_msgs = [c.get("content", "")[:100] for c in convs if c.get("role") == "assistant"]

    return {
        "tasks_done": [session.get("summary", "无摘要")[:200]],
        "user_questions": user_msgs[:3] if user_msgs else ["无记录"],
        "solutions": assistant_msgs[:3] if assistant_msgs else ["无记录"],
        "files_modified": [],
        "reusable_experience": "需要手动总结",
        "keywords": session.get("keywords", [])
    }


def _build_markdown_index(date_str: str, analyzed_sessions: List[Dict]) -> str:
    """构建 Markdown 格式的日期索引"""
    lines = [
        f"# {date_str} 工作记录",
        "",
        f"> 共 {len(analyzed_sessions)} 个会话",
        "",
    ]

    for i, session in enumerate(analyzed_sessions, 1):
        analysis = session.get("analysis", {})
        time_range = session.get("time_range", "")
        session_id = session.get("session_id", "")
        file_name = session.get("file_name", "")

        lines.append(f"## {i}. {time_range}")
        lines.append(f"")
        lines.append(f"**会话ID**: `{session_id}`")
        lines.append(f"")

        # 完成的任务
        tasks = analysis.get("tasks_done", [])
        if tasks:
            lines.append("**完成任务**:")
            lines.append("")
            for task in tasks:
                lines.append(f"- {task}")
            lines.append("")

        # 用户问题
        questions = analysis.get("user_questions", [])
        if questions:
            lines.append("**用户问题**:")
            lines.append("")
            for q in questions[:3]:
                lines.append(f"- {q[:100]}{'...' if len(q) > 100 else ''}")
            lines.append("")

        # 解决方案
        solutions = analysis.get("solutions", [])
        if solutions:
            lines.append("**解决方案**:")
            lines.append("")
            for s in solutions[:3]:
                lines.append(f"- {s[:150]}{'...' if len(s) > 150 else ''}")
            lines.append("")

        # 修改的文件
        files = analysis.get("files_modified", [])
        if files:
            lines.append("**涉及文件**:")
            lines.append("")
            for f in files:
                lines.append(f"- `{f}`")
            lines.append("")

        # 可复用经验
        experience = analysis.get("reusable_experience", "")
        if experience and experience != "需要手动总结":
            lines.append("**💡 经验总结**:")
            lines.append("")
            lines.append(f"> {experience}")
            lines.append("")

        # 关键词
        keywords = analysis.get("keywords", [])
        if keywords:
            lines.append(f"**关键词**: {', '.join(keywords[:10])}")
            lines.append("")

        lines.append("---")
        lines.append("")

    return "\n".join(lines)


async def _generate_fallback_index(
    date_dir: Path,
    sessions_data: List[Dict],
    date_str: str
) -> Dict[str, Any]:
    """生成降级版日期索引（OpenCode 不可用时）"""
    analyzed_sessions = []

    for session in sessions_data:
        analyzed_sessions.append({
            "session_id": session.get("session_id", ""),
            "file_name": session.get("file_name", ""),
            "time_range": _get_session_time_range(session),
            "analysis": _fallback_session_analysis(session)
        })

    index_content = _build_markdown_index(date_str, analyzed_sessions)

    index_file = date_dir / "index.md"
    with open(index_file, 'w', encoding='utf-8') as f:
        f.write(index_content)

    log(f"日期索引已生成（降级模式）: {index_file}")
    return {
        "success": True,
        "index_file": str(index_file),
        "sessions_count": len(analyzed_sessions),
        "mode": "fallback"
    }


async def save_to_memory_system(
    user_message: str,
    assistant_message: str,
    storage_path: str,
    persona_id: str = "default",
    session_id: str = None,
    tool_calls: Optional[List[Dict]] = None,
    tool_results: Optional[List[Dict]] = None,
    conversation_history: Optional[List[Dict]] = None
) -> Dict[str, Any]:
    """使用新格式保存对话（按会话ID分文件）

    Args:
        user_message: 用户消息
        assistant_message: 助手响应
        storage_path: 存储根路径
        persona_id: 人格ID
        session_id: 会话ID
        tool_calls: 工具调用列表
        tool_results: 工具结果列表
        conversation_history: 完整对话历史（暂不使用）
    """
    try:
        # 生成会话ID（如果没有）
        if not session_id:
            session_id = f"sess_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        log(f"【开始保存】persona={persona_id}, session={session_id}")
        log(f"  用户消息长度: {len(user_message)}")
        log(f"  助手响应长度: {len(assistant_message)}")

        # 构建存储路径（新格式）
        today = date.today()
        date_str = today.isoformat()
        date_dir = Path(storage_path) / "personas" / persona_id / date_str
        date_dir.mkdir(parents=True, exist_ok=True)
        memory_file = date_dir / f"{session_id}.yaml"

        log(f"  文件路径: {memory_file}")

        # 加载或创建会话数据
        if memory_file.exists():
            log(f"  加载现有文件...")
            with open(memory_file, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}
        else:
            log(f"  创建新文件...")
            data = {
                "version": "2.0",
                "date": date_str,
                "session_id": session_id,
                "created_at": datetime.now().isoformat(),
                "conversations": [],
                "summary": "",
                "keywords": []
            }

        # 添加对话
        conv_id = f"{session_id}_conv_{len(data['conversations'])//2}"
        timestamp = datetime.now().isoformat()

        # 用户消息
        user_conv = {
            "id": f"{conv_id}_user",
            "role": "user",
            "content": user_message,
            "timestamp": timestamp
        }
        data["conversations"].append(user_conv)

        # 助手响应
        assistant_conv = {
            "id": f"{conv_id}_assistant",
            "role": "assistant",
            "content": assistant_message,
            "timestamp": timestamp
        }

        # 添加工具调用（如果有）
        if tool_calls:
            assistant_conv["tool_calls"] = tool_calls
            log(f"  添加 {len(tool_calls)} 个工具调用")

        # 添加工具结果（如果有）
        if tool_results:
            assistant_conv["tool_results"] = tool_results
            log(f"  添加 {len(tool_results)} 个工具结果")

        data["conversations"].append(assistant_conv)

        # 更新时间戳
        data["updated_at"] = timestamp

        # 保存到文件
        log(f"  写入文件...")
        with open(memory_file, 'w', encoding='utf-8') as f:
            yaml.dump(data, f, allow_unicode=True, sort_keys=False)

        log(f"✅ 保存成功!")
        log(f"  对话总数: {len(data['conversations'])}")
        log(f"  文件大小: {memory_file.stat().st_size} bytes")

        return {
            "success": True,
            "file_path": str(memory_file),
            "session_id": session_id,
            "conversations_count": len(data["conversations"])
        }

    except Exception as e:
        log(f"❌ 保存失败: {e}")
        log(f"详细错误:\n{traceback.format_exc()}")
        return {"success": False, "error": str(e)}

# 注意：经验学习和记忆优化逻辑已移至 experience_learning.py
# 此 hook 仅负责对话保存

def main():
    """主函数 - Hook 入口"""
    # 调试日志路径（使用统一目录）
    debug_log_file = Path.home() / ".memory-system" / "logs" / "hooks" / "auto_save_debug.log"
    debug_log_file.parent.mkdir(parents=True, exist_ok=True)

    with open(debug_log_file, "a", encoding="utf-8") as f:
        f.write(f"\n=== {datetime.now()} ===\n")
        f.write("Hook started\n")

    try:
        log("=== Hook 被触发 ===")

        # 读取 stdin 输入（先读取原始内容用于调试）
        raw_input = sys.stdin.read()
        log(f"原始输入内容: {raw_input[:500]}...")

        with open(debug_log_file, "a", encoding="utf-8") as f:
            f.write(f"Raw input: {raw_input[:1000]}\n")

        # 尝试解析 JSON
        try:
            input_data = json.loads(raw_input)
        except json.JSONDecodeError as e:
            log(f"JSON 解析失败: {e}")
            log(f"完整输入: {raw_input}")
            with open(debug_log_file, "a", encoding="utf-8") as f:
                f.write(f"JSON parse failed: {e}\n")
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

        # 从字典中提取信息
        user_message = conversation.get("user_message", "")
        assistant_message = conversation.get("assistant_message", "")
        tool_calls = conversation.get("tool_calls", [])
        tool_results = conversation.get("tool_results", [])
        conversation_history = conversation.get("conversation_history", [])

        # 过滤掉纯工具调用的响应
        if assistant_message.strip().startswith('{') and '"tool"' in assistant_message[:100]:
            log("响应主要是工具调用，跳过保存")
            print(json.dumps({}))
            sys.exit(0)

        # 确定存储路径（根据当前人格）
        sys.path.insert(0, str(MEMORY_SYSTEM_PATH))
        from memory_system.personas import PersonaManager

        persona_manager = PersonaManager(str(MEMORY_DATA_PATH))
        active_persona = persona_manager.load_session_persona()

        # 使用新格式：persona_id 为实际人格ID，没有则使用 "default"
        persona_id = active_persona if active_persona else "default"

        if active_persona:
            persona_name = persona_manager.load_persona_config(active_persona)
            persona_name = persona_name.name if persona_name else active_persona
        else:
            persona_name = None

        # 存储路径为根目录（不再拼接 personas/{persona_id}，由 get_session_file_path 处理）
        storage_path = str(MEMORY_DATA_PATH)

        log(f"存储路径: {storage_path}, 人格: {persona_name or '默认'} (ID: {persona_id})")

        # 【修复】使用 Claude Code 的 session_id，实现一个会话一个文件
        # 1. 优先使用 Claude Code 传入的 session_id（UUID）
        claude_session_id = input_data.get('session_id', '')
        if claude_session_id:
            session_id = f"sess_{claude_session_id}"
            log(f"✅ 使用 Claude Code session_id: {session_id}")
        else:
            # 2. 如果没有，生成新的 session_id
            session_id = generate_session_id()
            log(f"⚠️  Claude 未传入 session_id，生成新的: {session_id}")

        # 检查对话是否已经保存过（使用新路径格式）
        if is_conversation_already_saved(storage_path, user_message, assistant_message, persona_id, session_id):
            log("对话已保存过，跳过")
            print(json.dumps({}))
            sys.exit(0)

        log(f"保存对话: 用户消息 {len(user_message)} 字符, 助手响应 {len(assistant_message)} 字符")
        if tool_calls:
            log(f"  包含 {len(tool_calls)} 个工具调用")
        if tool_results:
            log(f"  包含 {len(tool_results)} 个工具结果")
        if conversation_history:
            log(f"  包含 {len(conversation_history)} 条对话历史")

        # 保存对话（包含工具调用，传递 persona_id 和 session_id）
        result = asyncio.run(save_to_memory_system(
            user_message=user_message,
            assistant_message=assistant_message,
            storage_path=storage_path,
            persona_id=persona_id,
            session_id=session_id,
            tool_calls=tool_calls,
            tool_results=tool_results,
            conversation_history=conversation_history
        ))

        if result.get("success"):
            log(f"保存成功! Session: {result.get('session_id', 'unknown')}")
            if persona_name:
                log(f"人格: {persona_name}")

            # 【移除】日期索引生成已移至专门的 Close Hook
            # 不再在每次对话结束时生成，改为会话关闭时生成

        else:
            log(f"保存失败: {result.get('error', 'unknown')}")

        log("=== Hook 执行完成 ===")

        # 返回空结果，不阻止 stop
        print(json.dumps({}))

    except json.JSONDecodeError as e:
        log(f"JSON 解析错误: {e}")
        print(json.dumps({}))
    except Exception as e:
        log(f"Hook 执行错误: {e}")
        log(f"详细错误: {traceback.format_exc()}")
        print(json.dumps({}))
    sys.exit(0)

if __name__ == '__main__':
    main()
