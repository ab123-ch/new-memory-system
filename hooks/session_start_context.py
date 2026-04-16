#!/usr/bin/env python3
"""
SessionStart Hook - 会话开始时加载人格和记忆上下文

功能：
1. 恢复最近使用的人格
2. 加载该人格的 5 条最近记忆到上下文中
3. 输出会被自动注入到 Claude 的上下文

触发时机：会话开始或恢复时
"""

import sys
import os
import logging
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Any
import json
import yaml

# 记忆系统路径 - 支持多种安装方式
def _detect_memory_data_path() -> Path:
    """自动检测记忆数据路径"""
    # 1. 优先使用环境变量
    env_path = os.environ.get('MEMORY_DATA_PATH')
    if env_path:
        return Path(env_path)

    # 2. 检查 Claude Code 安装路径
    claude_path = Path.home() / ".claude" / "mcp" / "memory-system" / "data" / "memory"
    if claude_path.exists():
        return claude_path

    # 3. 默认路径
    return Path.home() / ".memory-system"

MEMORY_DATA_PATH = _detect_memory_data_path()

# 尝试导入统一日志模块，失败则使用基础日志
try:
    # 添加记忆系统路径
    memory_system_path = Path(__file__).parent.parent
    if str(memory_system_path) not in sys.path:
        sys.path.insert(0, str(memory_system_path))

    from memory_system.logging_config import get_logger, init_logging

    # 初始化日志系统
    config_path = memory_system_path / "data" / "memory" / "config.yaml"
    if not config_path.exists():
        config_path = memory_system_path / "memory_config.yaml"
    init_logging(config_path=str(config_path) if config_path.exists() else None)

    _logger = get_logger("session_start", "hooks")

    def log(message: str):
        """记录日志（使用统一日志系统）"""
        _logger.info(message)

except ImportError:
    # 回退到基础日志
    LOG_FILE = Path.home() / ".memory-system" / "logs" / "hooks" / "session_start.log"
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    def log(message: str):
        """记录日志（回退到文件日志）"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"[{timestamp}] {message}\n")
        except:
            pass


def get_last_active_persona() -> Optional[str]:
    """获取上次活跃的人格"""
    try:
        from memory_system.personas import PersonaManager

        pm = PersonaManager(str(MEMORY_DATA_PATH))
        index = pm.load_index()

        return index.active_persona
    except ImportError:
        # 模块未安装，返回 None
        return None
    except Exception as e:
        log(f"获取人格失败: {e}")
        return None


def get_soul_memories(storage_path: str, limit: int = 5) -> Dict[str, List[str]]:
    """获取元记忆（身份、习惯、能力）"""
    soul_memories = {
        "identity": [],
        "habits": [],
        "abilities": []
    }

    try:
        soul_file = Path(storage_path) / "soul.yaml"
        if soul_file.exists():
            with open(soul_file, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}

            # 获取各类记忆，限制数量
            identity = data.get("identity", [])
            habits = data.get("habits", [])
            abilities = data.get("abilities", [])

            # 每类最多 limit 条
            soul_memories["identity"] = identity[:limit]
            soul_memories["habits"] = habits[:limit]
            soul_memories["abilities"] = abilities[:limit]

            log(f"元记忆: 身份 {len(identity)} 条, 习惯 {len(habits)} 条, 能力 {len(abilities)} 条")

    except Exception as e:
        log(f"获取元记忆失败: {e}")

    return soul_memories


def get_recent_conversations(storage_path: str, limit: int = 5) -> List[Dict[str, Any]]:
    """获取最近的对话记录（原始对话内容）

    逻辑：
    1. 优先从新格式目录读取（{storage_path}/YYYY-MM-DD/sess_xxx.yaml）
    2. 如果没有新格式，则从旧格式读取（{storage_path}/YYYY-MM/YYYY-MM-DD.yaml）
    3. 从最近几天按时间倒序收集对话
    4. 取最新的 limit 条
    5. 返回时正序排列（时间线从早到晚）
    """
    all_conversations = []
    today = date.today()

    try:
        # 从今天开始往前搜索
        for i in range(7):
            target_date = today - timedelta(days=i)
            date_str = target_date.strftime("%Y-%m-%d")

            # === 新格式：{storage_path}/YYYY-MM-DD/sess_xxx.yaml ===
            new_format_dir = Path(storage_path) / date_str
            if new_format_dir.exists() and new_format_dir.is_dir():
                # 遍历该日期下的所有 session 文件
                for session_file in new_format_dir.glob("sess_*.yaml"):
                    try:
                        with open(session_file, 'r', encoding='utf-8') as f:
                            data = yaml.safe_load(f) or {}

                        # 新格式：conversations 直接在顶层
                        convs = data.get("conversations", [])
                        _extract_conversations(convs, all_conversations)
                    except Exception as e:
                        log(f"读取新格式文件失败 {session_file}: {e}")
                continue  # 新格式存在，跳过旧格式检查

            # === 旧格式：{storage_path}/YYYY-MM/YYYY-MM-DD.yaml ===
            month_dir = Path(storage_path) / target_date.strftime("%Y-%m")
            memory_file = month_dir / f"{date_str}.yaml"

            if memory_file.exists():
                try:
                    with open(memory_file, 'r', encoding='utf-8') as f:
                        data = yaml.safe_load(f) or {}

                    # 旧格式：sessions -> conversations 嵌套
                    for session in data.get("sessions", []):
                        convs = session.get("conversations", [])
                        _extract_conversations(convs, all_conversations)
                except Exception as e:
                    log(f"读取旧格式文件失败 {memory_file}: {e}")

        # 按时间戳排序（倒序，获取最新的）
        all_conversations.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

        # 取最新的 limit 条
        recent = all_conversations[:limit]

        # 返回时正序排列（时间线从早到晚）
        recent.reverse()

        log(f"获取到 {len(recent)} 条对话记录")
        return recent

    except Exception as e:
        log(f"获取对话记录失败: {e}")
        return []


def _extract_conversations(convs: List[Dict], all_conversations: List[Dict]) -> None:
    """从对话列表中提取 user-assistant 配对

    Args:
        convs: 对话列表
        all_conversations: 结果收集列表
    """
    idx = 0
    while idx < len(convs):
        user_conv = convs[idx]

        # 确保是 user 开始
        if user_conv.get("role") == "user":
            user_content = user_conv.get("content", "")
            user_time = user_conv.get("timestamp", "")

            # 找下一个 assistant 回复
            assistant_content = ""
            assistant_time = ""
            for j in range(idx + 1, len(convs)):
                if convs[j].get("role") == "assistant":
                    assistant_content = convs[j].get("content", "")
                    assistant_time = convs[j].get("timestamp", "")
                    idx = j  # 跳到 assistant
                    break

            if user_content or assistant_content:
                all_conversations.append({
                    "timestamp": user_time,
                    "user": user_content,
                    "assistant": assistant_content
                })

        idx += 1


def get_available_personas() -> List[Dict[str, str]]:
    """获取所有可用的人格列表"""
    personas = []

    try:
        personas_dir = MEMORY_DATA_PATH / "personas"
        if personas_dir.exists():
            for persona_dir in personas_dir.iterdir():
                if persona_dir.is_dir():
                    persona_config_file = persona_dir / "persona.yaml"
                    if persona_config_file.exists():
                        with open(persona_config_file, 'r', encoding='utf-8') as f:
                            config = yaml.safe_load(f) or {}
                            personas.append({
                                "id": persona_dir.name,
                                "name": config.get("name", persona_dir.name),
                                "description": config.get("description", "")[:50]
                            })
    except Exception as e:
        log(f"获取人格列表失败: {e}")

    return personas


def get_shared_memories(limit: int = 3) -> Dict[str, List[str]]:
    """获取共享记忆（所有人格共用）"""
    shared = {
        "identity": [],
        "knowledge": []
    }

    try:
        shared_file = MEMORY_DATA_PATH / "shared" / "soul.yaml"
        if shared_file.exists():
            with open(shared_file, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}

            shared["identity"] = data.get("identity", [])[:limit]
            shared["knowledge"] = data.get("knowledge", [])[:limit]

    except Exception as e:
        log(f"获取共享记忆失败: {e}")

    return shared


def get_optimized_rules(storage_path: str, limit: int = 3) -> List[Dict[str, Any]]:
    """获取优化后的规则"""
    rules = []
    rules_file = Path(storage_path) / "reorganization_results.yaml"

    try:
        if rules_file.exists():
            with open(rules_file, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}
                rules = data.get("abstract_rules", [])[:limit]
    except Exception as e:
        log(f"获取规则失败: {e}")

    return rules


def get_persona_experiences_index(storage_path: str, limit: int = 10) -> List[Dict[str, Any]]:
    """获取人格的经验索引（只返回文件名和标题，不加载内容）

    设计原则：类似 skill，只加载索引，按需获取内容
    """
    experiences = []
    experiences_dir = Path(storage_path) / "experiences"

    try:
        if not experiences_dir.exists():
            log(f"经验目录不存在: {experiences_dir}")
            return experiences

        # 获取所有 MD 文件，按修改时间排序
        md_files = list(experiences_dir.glob("*.md"))
        if not md_files:
            return experiences

        # 按修改时间倒序
        md_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)

        for md_file in md_files[:limit]:
            try:
                # 只读取前 20 行获取元数据（标题、日期）
                with open(md_file, 'r', encoding='utf-8') as f:
                    first_lines = [f.readline() for _ in range(20)]

                # 提取标题（第一个 # 开头的行）
                title = ""
                for line in first_lines:
                    if line.startswith('# '):
                        title = line[2:].strip()
                        break

                # 提取日期
                date_str = ""
                for line in first_lines:
                    if line.startswith('> **日期**:'):
                        date_str = line.split(':', 1)[1].strip()
                        break

                experiences.append({
                    "id": md_file.stem,  # 文件名作为 ID
                    "title": title or md_file.stem,
                    "date": date_str,
                    "file": md_file.name
                })

            except Exception as e:
                log(f"读取经验索引失败 {md_file}: {e}")
                continue

        log(f"获取到 {len(experiences)} 条经验索引")

    except Exception as e:
        log(f"获取经验索引失败: {e}")

    return experiences


def format_context_output(
    persona_name: Optional[str],
    persona_description: Optional[str],
    soul_memories: Dict[str, List[str]],
    recent_conversations: List[Dict[str, Any]],
    shared_memories: Dict[str, List[str]],
    rules: List[Dict[str, Any]],
    experiences: List[Dict[str, Any]],
    available_personas: List[Dict[str, str]] = None
) -> str:
    """格式化上下文输出"""
    lines = []
    lines.append("=" * 50)
    lines.append("【会话上下文 - 自动加载】")
    lines.append("=" * 50)

    # 人格信息
    if persona_name:
        lines.append(f"\n【当前人格】{persona_name}")
        if persona_description:
            lines.append(f"描述: {persona_description}")
    else:
        lines.append("\n【当前人格】默认人格")

    # 显示可用人格列表
    if available_personas:
        lines.append("\n【可用人格】")
        for p in available_personas:
            marker = " ← 当前" if p["name"] == persona_name else ""
            lines.append(f"  • {p['name']}{marker}: {p['description']}")
        lines.append("\n")
        lines.append("🔄 " + "=" * 40)
        lines.append("=" * 40)
        lines.append("")
        lines.append("⚠️ 在用户发送第一条消息时，请执行以下判断：")
        lines.append("")
        lines.append("┌─ 检查用户消息是否包含人格切换关键词：")
        lines.append("│   关键词：\"切换到\"、\"用XX模式\"、\"换成\"、\"切换人格\"")
        lines.append("│")
        lines.append("├─ 情况1: 用户消息包含切换意图")
        lines.append("│   → 直接调用 persona_switch 工具切换人格（无需确认）")
        lines.append("│")
        lines.append("└─ 情况2: 用户消息不包含切换意图")
        lines.append("│   → 告知用户当前人格")
        lines.append("│   → 询问：\"是否需要切换到其他人格开展工作？\"")
        lines.append("│   → 根据用户回答决定下一步操作")
        lines.append("")
        lines.append("可用人格列表： ")
        for p in available_personas:
            marker = " ← 当前" if p["name"] == persona_name else ""
            lines.append(f"  • {p['name']}{marker}: {p['description']}")
        lines.append("")
        lines.append("=" * 40)

    # 元记忆 - 身份
    identity = soul_memories.get("identity", [])
    if identity:
        lines.append("\n【身份认知】")
        for i, item in enumerate(identity[:5], 1):
            lines.append(f"{i}. {item}")

    # 元记忆 - 习惯
    habits = soul_memories.get("habits", [])
    if habits:
        lines.append("\n【偏好习惯】")
        for i, item in enumerate(habits[:5], 1):
            lines.append(f"{i}. {item}")

    # 元记忆 - 能力
    abilities = soul_memories.get("abilities", [])
    if abilities:
        lines.append("\n【能力特征】")
        for i, item in enumerate(abilities[:5], 1):
            lines.append(f"{i}. {item}")

    # 最近对话记录
    if recent_conversations:
        lines.append("\n【最近对话】")
        for i, conv in enumerate(recent_conversations[:5], 1):
            timestamp = conv.get("timestamp", "")
            # 解析时间戳，格式：2026-02-28T12:04:00.216754
            time_str = timestamp
            if timestamp:
                try:
                    dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
                except:
                    pass

            user_msg = conv.get("user", "")
            assistant_msg = conv.get("assistant", "")

            # 截断过长的内容
            if len(user_msg) > 150:
                user_msg = user_msg[:150] + "..."
            if len(assistant_msg) > 150:
                assistant_msg = assistant_msg[:150] + "..."

            lines.append(f"\n--- 对话 {i} [{time_str}] ---")
            lines.append(f"用户：{user_msg}")
            lines.append(f"助手：{assistant_msg}")

    # 共享记忆
    shared_identity = shared_memories.get("identity", [])
    shared_knowledge = shared_memories.get("knowledge", [])

    if shared_identity or shared_knowledge:
        lines.append("\n【共享记忆】")
        if shared_identity:
            lines.append("身份: " + ", ".join(shared_identity[:3]))
        if shared_knowledge:
            lines.append("知识: " + ", ".join(shared_knowledge[:3]))

    # 优化规则
    if rules:
        lines.append("\n【经验规则】")
        for i, rule in enumerate(rules, 1):
            rule_text = rule.get("rule", "")
            source_count = rule.get("source_count", 0)
            lines.append(f"{i}. {rule_text[:80]}")
            if source_count > 0:
                lines[-1] += f" (基于 {source_count} 次对话)"
            if len(rule_text) > 80:
                lines[-1] += "..."

    # 会话经验索引（只显示索引，按需获取内容）
    if experiences:
        lines.append("\n【会话经验索引】")
        lines.append("使用 experience_get 工具获取具体经验内容")
        lines.append("")
        for i, exp in enumerate(experiences, 1):
            exp_id = exp.get("id", str(i))
            title = exp.get("title", "未命名")
            exp_date = exp.get("date", "")

            line = f"  {i}. [{exp_id}] {title}"
            if exp_date:
                line += f" ({exp_date})"
            lines.append(line)

    lines.append("\n" + "=" * 50)
    return "\n".join(lines)


def main():
    """主函数"""
    log("=== SessionStart Hook 触发 ===")

    try:
        # 读取 stdin（可能有会话信息）
        raw_input = ""
        try:
            raw_input = sys.stdin.read()
            log(f"输入: {raw_input[:200] if raw_input else '空'}...")
        except:
            pass

        # 1. 获取上次活跃的人格
        persona_id = get_last_active_persona()
        persona_name = None
        persona_description = None
        storage_path = str(MEMORY_DATA_PATH)

        if persona_id:
            storage_path = str(MEMORY_DATA_PATH / "personas" / persona_id)
            log(f"人格: {persona_id}, 存储路径: {storage_path}")

            # 获取人格配置
            try:
                persona_file = Path(storage_path) / "persona.yaml"
                if persona_file.exists():
                    with open(persona_file, 'r', encoding='utf-8') as f:
                        persona_config = yaml.safe_load(f) or {}
                        persona_name = persona_config.get("name", persona_id)
                        persona_description = persona_config.get("description", "")
            except Exception as e:
                log(f"读取人格配置失败: {e}")
                persona_name = persona_id

        # 2. 获取元记忆（身份、习惯、能力）
        soul_memories = get_soul_memories(storage_path, limit=5)
        log(f"元记忆: 身份 {len(soul_memories['identity'])} 条, 习惯 {len(soul_memories['habits'])} 条, 能力 {len(soul_memories['abilities'])} 条")

        # 3. 获取最近 5 条对话记录
        recent_conversations = get_recent_conversations(storage_path, limit=5)
        log(f"最近对话: {len(recent_conversations)} 条")

        # 4. 获取共享记忆
        shared_memories = get_shared_memories(limit=3)
        log(f"共享记忆: 身份 {len(shared_memories['identity'])} 条, 知识 {len(shared_memories['knowledge'])} 条")

        # 5. 获取优化后的规则
        rules = get_optimized_rules(storage_path, limit=3)
        log(f"获取到 {len(rules)} 条规则")

        # 6. 获取人格经验索引（只加载索引，不加载内容）
        experiences = get_persona_experiences_index(storage_path, limit=10)
        log(f"获取到 {len(experiences)} 条经验索引")

        # 7. 获取可用人格列表
        available_personas = get_available_personas()
        log(f"可用人格: {len(available_personas)} 个")

        # 8. 格式化输出（会自动注入到上下文）
        output = format_context_output(
            persona_name,
            persona_description,
            soul_memories,
            recent_conversations,
            shared_memories,
            rules,
            experiences,
            available_personas
        )
        print(output)

        log("=== SessionStart Hook 完成 ===")

    except Exception as e:
        log(f"Hook 执行错误: {e}")
        import traceback
        log(traceback.format_exc())
        # 即使出错也返回空，不阻止会话启动
        print("")

    sys.exit(0)


if __name__ == "__main__":
    main()
