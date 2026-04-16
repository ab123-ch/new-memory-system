#!/usr/bin/env python3
"""
会话保存器 - V2 (新格式：按会话ID分文件)

功能：
1. 按 {date}/{session_id}.yaml 格式保存会话
2. 与 MCP 服务的 memory_save 工具保持一致
"""
from datetime import datetime, date
from pathlib import Path
from typing import Dict, Any, List, Optional
import yaml


def save_session_to_file(
    storage_path: str,
    persona_id: str,
    session_id: str,
    user_message: str,
    assistant_message: str,
    summary: Optional[str] = None,
    keywords: Optional[List[str]] = None,
    tool_calls: Optional[List[Dict]] = None,
    tool_results: Optional[List[Dict]] = None,
    conversation_history: Optional[List[Dict]] = None
) -> Dict[str, Any]:
    """
    保存会话到文件（新格式：{date}/{session_id}.yaml）

    Args:
        storage_path: 存储根路径
        persona_id: 人格ID
        session_id: 会话ID
        user_message: 用户消息
        assistant_message: 助手响应
        summary: 摘要（可选）
        keywords: 关键词列表（可选）
        tool_calls: 工具调用列表（可选）
        tool_results: 工具结果列表（可选）
        conversation_history: 完整对话历史（可选）

    Returns:
        {"success": bool, "file_path": str, "session_id": str}
    """
    try:
        # 1. 构建存储路径
        today = date.today()
        date_str = today.isoformat()

        # 人格存储路径
        persona_path = Path(storage_path) / "personas" / persona_id
        date_dir = persona_path / date_str
        date_dir.mkdir(parents=True, exist_ok=True)

        # 会话文件路径
        session_file = date_dir / f"{session_id}.yaml"

        # 2. 加载或创建会话数据
        if session_file.exists():
            with open(session_file, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}
        else:
            data = {
                "version": "2.0",
                "date": date_str,
                "session_id": session_id,
                "created_at": datetime.now().isoformat(),
                "conversations": [],
                "summary": "",
                "keywords": []
            }

        # 3. 添加对话
        conv_id = f"{session_id}_conv_{len(data['conversations'])}"

        # 用户消息
        user_conv = {
            "id": f"{conv_id}_user",
            "role": "user",
            "content": user_message,
            "timestamp": datetime.now().isoformat()
        }
        data["conversations"].append(user_conv)

        # 助手响应
        assistant_conv = {
            "id": f"{conv_id}_assistant",
            "role": "assistant",
            "content": assistant_message,
            "timestamp": datetime.now().isoformat()
        }

        # 添加工具调用（如果有）
        if tool_calls:
            assistant_conv["tool_calls"] = tool_calls

        data["conversations"].append(assistant_conv)

        # 4. 更新摘要和关键词
        if summary:
            data["summary"] = summary
        if keywords:
            existing_keywords = set(data.get("keywords", []))
            data["keywords"] = list(existing_keywords | set(keywords))

        # 5. 保存到文件
        data["updated_at"] = datetime.now().isoformat()

        with open(session_file, 'w', encoding='utf-8') as f:
            yaml.dump(data, f, allow_unicode=True, sort_keys=False)

        return {
            "success": True,
            "file_path": str(session_file),
            "session_id": session_id,
            "conversations_count": len(data["conversations"])
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "session_id": session_id
        }


def is_conversation_already_saved_v2(
    storage_path: str,
    persona_id: str,
    session_id: str,
    user_message: str
) -> bool:
    """
    检查对话是否已经保存（新格式）

    Args:
        storage_path: 存储根路径
        persona_id: 人格ID
        session_id: 会话ID
        user_message: 用户消息

    Returns:
        是否已保存
    """
    try:
        today = date.today()
        date_str = today.isoformat()

        # 查找会话文件
        session_file = Path(storage_path) / "personas" / persona_id / date_str / f"{session_id}.yaml"

        if not session_file.exists():
            return False

        # 读取会话数据
        with open(session_file, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}

        # 检查是否有相同的用户消息
        for conv in data.get("conversations", []):
            if conv.get("role") == "user" and conv.get("content", "") == user_message:
                return True

        return False

    except Exception:
        return False
