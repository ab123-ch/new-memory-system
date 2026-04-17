#!/usr/bin/env python3
"""
会话关闭 Hook - SessionEnd 事件处理

功能：
1. 接收 Claude Code SessionEnd Hook 的 JSON 输入
2. 根据 session_id 查找记忆文件
3. 读取文件内容，调用 LLM API 分析总结
4. 在日期目录下生成/更新 index.md

通过 hooks/llm_utils.py 调用 LLM，支持所有 OpenAI 兼容 API 的提供商。
"""

import sys
import os
import json
import re
import yaml
import traceback
import importlib.util
from pathlib import Path
from datetime import datetime

# 导入通用 LLM 工具
from llm_utils import call_llm


# ============== 路径检测 ==============

def _detect_paths():
    """检测记忆系统路径"""
    data_path = os.environ.get('MEMORY_DATA_PATH')
    if data_path:
        return Path(data_path).parent, Path(data_path)

    claude_mcp_path = Path.home() / ".claude" / "mcp" / "memory-system"
    if (claude_mcp_path / "memory_system" / "__init__.py").exists():
        return claude_mcp_path, claude_mcp_path / "data" / "memory"

    project_path = Path(__file__).parent.parent
    if (project_path / "memory_system" / "__init__.py").exists():
        data_path = project_path / "data" / "memory"
        if data_path.exists():
            return project_path, data_path

    return Path.home() / ".memory-system", Path.home() / ".memory-system" / "data" / "memory"


SYSTEM_PATH, DATA_PATH = _detect_paths()


# ============== 日志 ==============

LOG_FILE = DATA_PATH / "logs" / "session_close_hook.log"


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except:
        pass
    print(f"[session_close_hook] {msg}", file=sys.stderr)


# ============== 查找会话文件 ==============

def _get_active_persona():
    """获取当前会话的人格 ID（按进程 PPID 查找）"""
    try:
        import importlib
        spec = importlib.util.spec_from_file_location(
            "personas",
            SYSTEM_PATH / "memory_system" / "personas" / "manager.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        pm = mod.PersonaManager(str(DATA_PATH))
        # 使用 load_session_persona() 获取当前进程的人格
        return pm.load_session_persona()
    except Exception as e:
        log(f"获取人格失败: {e}")
        return None


def find_session_file(session_id):
    """
    根据 session_id 查找会话文件

    Returns:
        dict with file_path, date, persona_id  or  None
    """
    persona_id = _get_active_persona()

    if persona_id:
        # 在特定人格目录下查找
        persona_dir = DATA_PATH / "personas" / persona_id

        if persona_dir.exists():
            # 精确匹配: sess_{session_id}.yaml
            for date_dir in sorted(persona_dir.iterdir(), reverse=True):
                if not date_dir.is_dir() or not re.match(r'\d{4}-\d{2}-\d{2}', date_dir.name):
                    continue
                f = date_dir / f"sess_{session_id}.yaml"
                if f.exists():
                    log(f"精确匹配: {f}")
                    return {"file_path": f, "date": date_dir.name, "persona_id": persona_id}

            # 模糊匹配: 找当天最近修改的文件
            today = datetime.now().strftime("%Y-%m-%d")
            today_dir = persona_dir / today
            if today_dir.exists():
                files = sorted(today_dir.glob("sess_*.yaml"), key=lambda f: f.stat().st_mtime, reverse=True)
                if files:
                    log(f"模糊匹配（最近文件）: {files[0]}")
                    return {"file_path": files[0], "date": today, "persona_id": persona_id}

    # 如果没有人格或找不到，全局搜索所有人格目录
    log(f"在特定人格目录未找到，全局搜索: {session_id}")
    personas_dir = DATA_PATH / "personas"
    if personas_dir.exists():
        for p_dir in personas_dir.iterdir():
            if not p_dir.is_dir():
                continue
            for date_dir in sorted(p_dir.iterdir(), reverse=True):
                if not date_dir.is_dir() or not re.match(r'\d{4}-\d{2}-\d{2}', date_dir.name):
                    continue
                f = date_dir / f"sess_{session_id}.yaml"
                if f.exists():
                    log(f"全局搜索找到: {f}")
                    return {"file_path": f, "date": date_dir.name, "persona_id": p_dir.name}

    log(f"未找到会话文件: {session_id}")
    return None


# ============== LLM 调用 ==============
# 使用 hooks/llm_utils.py 中的 call_llm 函数，支持所有 OpenAI 兼容 API 提供商


# ============== 分析会话 ==============

ANALYSIS_PROMPT = """请分析以下会话内容，直接输出 Markdown 格式的总结。不要输出 JSON。

会话时间: {time_range}

会话内容:
{content}

请按以下格式输出（纯 Markdown）:

**完成任务**:
- 1. 具体完成了什么
- 2. ...

**用户问题**:
- 用户提出的核心问题

**解决方案**:
- 解决方案要点

**涉及文件**:
- 涉及修改的文件/类/方法

**经验总结**:
> 提炼可复用的经验，比如"遇到X情况时，可以Y方式处理"

**关键词**: 关键词1, 关键词2, 关键词3, ...

要求:
1. 总结要具体，不要泛泛而谈
2. 如果是测试/闲聊会话，简单标注即可
3. 经验总结要突出"下次遇到类似问题的处理方式"
4. 关键词提取5-8个技术和业务词汇"""


def analyze_session(conversations, time_range):
    """
    分析会话内容，返回 Markdown 格式的分析结果

    Args:
        conversations: 对话列表 [{"role": "user/assistant", "content": "...", "timestamp": "..."}]
        time_range: 时间范围字符串

    Returns:
        Markdown 格式的分析文本
    """
    # 提取对话文本
    conv_texts = []
    for conv in conversations:
        role = conv.get("role", "user")
        content = conv.get("content", "")
        if not content:
            continue
        prefix = "用户" if role == "user" else "助手"
        conv_texts.append(f"{prefix}: {content[:500]}")

    if not conv_texts:
        return "**摘要**: 无对话内容\n\n**关键词**: 无"

    # 控制总长度
    combined = "\n\n".join(conv_texts[:30])
    if len(combined) > 8000:
        combined = combined[:8000] + "\n\n...(内容已截断)"

    prompt = ANALYSIS_PROMPT.format(time_range=time_range, content=combined)

    # 调 LLM API（通过 llm_utils 通用模块，支持所有 provider）
    result = call_llm(prompt)
    if result:
        return result

    # 降级: 简单提取
    log("API 失败，使用降级摘要")
    user_msgs = [c["content"][:100] for c in conversations if c.get("role") == "user" and c.get("content")]
    return f"**摘要**: {user_msgs[0] if user_msgs else '无摘要'}\n\n**关键词**: 无"


# ============== 索引更新 ==============

def update_index(date_dir, session_id, time_range, analysis_md):
    """
    更新日期索引文件 index.md

    Args:
        date_dir: 日期目录 Path
        session_id: 会话 ID
        time_range: 时间范围
        analysis_md: Markdown 格式的分析结果
    """
    index_file = date_dir / "index.md"

    # 统一前缀
    sid = f"sess_{session_id}" if not session_id.startswith("sess_") else session_id

    # 构建条目
    entry = f"""## {sid} ({time_range})

{analysis_md}

---

"""

    # 读取或创建索引
    if index_file.exists():
        content = index_file.read_text(encoding="utf-8")
    else:
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        content = f"# {date_dir.name} 工作记录\n\n> 自动生成于 {now}\n\n"

    # 更新或追加
    marker = f"## {sid}"
    if marker in content:
        pattern = rf"## {re.escape(sid)}.*?---\n"
        content = re.sub(pattern, entry, content, flags=re.DOTALL)
        log(f"更新已有条目: {session_id}")
    else:
        content += entry
        log(f"追加新条目: {session_id}")

    index_file.write_text(content, encoding="utf-8")
    log(f"索引文件已更新: {index_file}")


# ============== 主流程 ==============

def main():
    try:
        raw_input = sys.stdin.read()
        if not raw_input:
            log("无输入，跳过")
            return

        try:
            input_data = json.loads(raw_input)
        except json.JSONDecodeError:
            log("JSON 解析失败")
            return

        session_id = input_data.get("session_id", "")
        reason = input_data.get("reason", "")
        log(f"=== 开始处理: session_id={session_id}, reason={reason} ===")

        if not session_id:
            log("无 session_id，跳过")
            return

        # 1. 查找文件
        file_info = find_session_file(session_id)
        if not file_info:
            return

        file_path = file_info["file_path"]
        date = file_info["date"]

        # 2. 读取 yaml
        with open(file_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        conversations = data.get("conversations", [])
        if not conversations:
            log("无对话内容，跳过")
            return

        # 计算时间范围
        first_ts = conversations[0].get("timestamp", "")
        last_ts = conversations[-1].get("timestamp", "")
        start = first_ts[11:16] if len(first_ts) >= 16 else ""
        end = last_ts[11:16] if len(last_ts) >= 16 else ""
        time_range = f"{start} - {end}" if start and end else ""

        # 3. 调用 API 分析
        analysis_md = analyze_session(conversations, time_range)

        # 4. 更新 index.md
        update_index(file_path.parent, session_id, time_range, analysis_md)

        log(f"=== 处理完成: {session_id} ===")

    except Exception as e:
        log(f"错误: {e}")
        traceback.print_exc(file=sys.stderr)


if __name__ == "__main__":
    main()
