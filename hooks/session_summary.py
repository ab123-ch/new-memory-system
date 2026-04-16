#!/usr/bin/env python3
"""
会话总结 Hook - 在会话结束时生成多维度经验总结

功能：
1. 读取本次会话的所有对话内容
2. 使用 LLM 进行多维度分析总结
3. 保存到对应人格目录下的 experiences/ 文件夹

触发时机：Stop 事件（每轮对话结束）
注意：只有当会话达到一定长度（如5轮以上）时才生成总结

总结维度：
- 问题处理：遇到的问题及解决方案
- 文件路径：涉及的文件和工程位置
- 知识获取：新学到的知识或信息
- 用户反馈：用户指出的问题或偏好
- 重要决策：关键的决策和方案选择
"""

# ========== 最早期调试 ==========
import sys as _sys
from datetime import datetime as _dt
from pathlib import Path as _Path
from typing import Optional, Dict, Any, List

_stdin_content = None
try:
    _stdin_content = _sys.stdin.read()
except Exception:
    pass
# ========== 最早期调试结束 ==========

import json
import os
import asyncio
import traceback
import hashlib
from datetime import datetime, date
from pathlib import Path

# 恢复 stdin 内容
import io
if _stdin_content is not None:
    _sys.stdin = io.StringIO(_stdin_content)


# ============== 路径检测 ==============
def _detect_memory_paths() -> tuple:
    """自动检测记忆系统路径"""
    # 1. 优先使用环境变量
    data_path = os.environ.get('MEMORY_DATA_PATH')
    if data_path:
        memory_system_path = Path(data_path).parent
        return memory_system_path, Path(data_path)

    # 2. 检测 Claude Code MCP 安装路径
    claude_mcp_path = Path.home() / ".claude" / "mcp" / "memory-system"
    if (claude_mcp_path / "memory_system" / "__init__.py").exists():
        data_path = claude_mcp_path / "data" / "memory"
        return claude_mcp_path, data_path

    # 3. 检测项目目录
    project_path = Path(__file__).parent.parent
    if (project_path / "memory_system" / "__init__.py").exists():
        data_path = project_path / "data" / "memory"
        if data_path.exists():
            return project_path, data_path
        return project_path, Path.home() / ".memory-system"

    return Path.home() / ".memory-system", Path.home() / ".memory-system"

_MEMORY_SYSTEM_PATH, MEMORY_DATA_PATH = _detect_memory_paths()

if _MEMORY_SYSTEM_PATH and str(_MEMORY_SYSTEM_PATH) not in _sys.path:
    _sys.path.insert(0, str(_MEMORY_SYSTEM_PATH))


# ============== 日志 ==============
try:
    from memory_system.logging_config import get_logger, init_logging
    _config_path = _MEMORY_SYSTEM_PATH / "data" / "memory" / "config.yaml"
    if not _config_path.exists():
        _config_path = _MEMORY_SYSTEM_PATH / "memory_config.yaml"
    init_logging(config_path=str(_config_path) if _config_path.exists() else None)
    _logger = get_logger("session_summary", "hooks")

    def log(message: str):
        _logger.info(message)

except ImportError:
    LOG_FILE = MEMORY_DATA_PATH / "logs" / "hooks" / "session_summary.log"
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    def log(message: str):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"[{timestamp}] {message}\n")
        except:
            pass


# ============== 经验总结提示词 ==============
SUMMARY_PROMPT = """你是一个经验总结助手。请分析以下会话内容，提炼出可复用的经验。

## 会话内容
{conversation_content}

## 请从以下维度进行总结

### 1. 问题处理
- 遇到了什么问题？
- 是如何解决的？
- 有什么可复用的解决思路？

### 2. 文件与工程
- 涉及了哪些重要文件路径？
- 工程结构有什么特点？
- 有哪些常用的配置或入口文件？

### 3. 知识获取
- 本次会话学到了什么新知识？
- 有什么重要的技术概念或API？
- 有什么需要注意的坑点？

### 4. 用户反馈
- 用户指出了什么问题或偏好？
- 有什么需要改进的地方？
- 用户的习惯或偏好是什么？

### 5. 重要决策
- 做了哪些关键决策？
- 选择了什么方案？为什么？
- 有什么权衡考虑？

### 6. 待办事项
- 还有什么未完成的任务？
- 需要后续跟进什么？

---

请用简洁的中文输出，每个维度2-5条要点。如果某个维度没有相关内容，可以跳过。
"""


class LLMService:
    """LLM 服务封装"""

    def __init__(self):
        self._service = None

    def _get_service(self):
        """获取 LLM 服务（懒加载）"""
        if self._service is None:
            try:
                from memory_system.ai import get_llm_service
                self._service = get_llm_service()
                log("LLM 服务已连接")
            except Exception as e:
                log(f"获取 LLM 服务失败: {e}")
                return None
        return self._service

    async def analyze(self, prompt: str) -> Optional[str]:
        """调用 LLM 分析"""
        service = self._get_service()
        if service is None:
            return None

        try:
            response = await service.acomplete(
                prompt=prompt,
                temperature=0.3,
                max_tokens=2000
            )
            return response.content.strip()
        except Exception as e:
            log(f"LLM 调用失败: {e}")
            return None


class TranscriptParser:
    """对话历史解析器"""

    @staticmethod
    def parse(transcript: str) -> List[Dict[str, Any]]:
        """解析 transcript 文件，返回对话列表"""
        if not transcript:
            return []

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

        # 如果 JSONL 解析失败，尝试整体 JSON
        if not messages:
            try:
                data = json.loads(transcript)
                if isinstance(data, list):
                    messages = data
                elif isinstance(data, dict) and 'messages' in data:
                    messages = data['messages']
            except json.JSONDecodeError:
                pass

        return messages

    @staticmethod
    def extract_conversations(messages: List[Dict]) -> List[Dict[str, str]]:
        """从消息列表中提取对话对（user + assistant）"""
        conversations = []

        def get_role(msg):
            role = msg.get('role', '') or msg.get('type', '')
            if role not in ['user', 'assistant']:
                role = msg.get('message', {}).get('role', '')
            return role

        def get_text_content(content):
            """提取文本内容"""
            if isinstance(content, str):
                return content.strip() if content.strip() else None

            if isinstance(content, list):
                texts = []
                for item in content:
                    if isinstance(item, dict):
                        item_type = item.get('type', '')
                        if item_type == 'text':
                            texts.append(item.get('text', ''))
                        elif item_type == 'thinking':
                            texts.append(f"[思考] {item.get('thinking', '')[:200]}")
                    elif isinstance(item, str):
                        texts.append(item)
                result = '\n'.join(texts).strip()
                return result if result else None
            return None

        # 配对 user 和 assistant
        i = 0
        while i < len(messages):
            msg = messages[i]
            role = get_role(msg)
            content = msg.get('content', '') or msg.get('message', {}).get('content', '')
            text = get_text_content(content)

            if role == 'user' and text:
                # 找下一个 assistant 回复
                assistant_text = ""
                for j in range(i + 1, len(messages)):
                    next_msg = messages[j]
                    next_role = get_role(next_msg)
                    next_content = next_msg.get('content', '') or next_msg.get('message', {}).get('content', '')
                    next_text = get_text_content(next_content)

                    if next_role == 'assistant' and next_text:
                        assistant_text = next_text
                        i = j  # 跳到 assistant
                        break

                if text or assistant_text:
                    conversations.append({
                        "user": text[:2000] if text else "",
                        "assistant": assistant_text[:3000] if assistant_text else ""
                    })

            i += 1

        return conversations


class ExperienceManager:
    """经验管理器 - 保存经验到人格目录"""

    def __init__(self, persona_id: Optional[str], data_path: Path):
        self.persona_id = persona_id
        self.data_path = data_path

        # 确定存储路径
        if persona_id:
            self.storage_path = data_path / "personas" / persona_id / "experiences"
        else:
            self.storage_path = data_path / "experiences"

        # 确保目录存在
        self.storage_path.mkdir(parents=True, exist_ok=True)

        log(f"经验存储路径: {self.storage_path}")

    def save(self, summary_content: str, conversation_count: int) -> Optional[Path]:
        """保存经验总结"""
        try:
            # 生成文件名
            today = date.today()
            timestamp = datetime.now().strftime("%H%M%S")
            date_str = today.strftime("%Y-%m-%d")

            # 使用内容哈希作为唯一标识
            content_hash = hashlib.md5(summary_content.encode()).hexdigest()[:8]
            filename = f"{date_str}_{timestamp}_{content_hash}.md"
            file_path = self.storage_path / filename

            # 构建 MD 内容
            md_content = f"""# 会话经验总结

> **日期**: {date_str}
> **时间**: {datetime.now().strftime('%H:%M:%S')}
> **对话轮数**: {conversation_count}
> **人格**: {self.persona_id or '默认'}

---

{summary_content}

---

*此经验由 session_summary hook 自动生成*
"""

            # 写入文件
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(md_content)

            log(f"经验已保存: {file_path}")
            return file_path

        except Exception as e:
            log(f"保存经验失败: {e}")
            return None


class SessionSummaryHook:
    """会话总结 Hook 主类"""

    # 最小对话轮数（少于此数量不生成总结）
    MIN_CONVERSATIONS = 3

    def __init__(self):
        self.llm = LLMService()
        self.parser = TranscriptParser()

    def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """执行 Hook"""
        log("=== 会话总结 Hook 触发 ===")

        try:
            # 1. 获取 transcript 路径
            transcript_path = input_data.get('transcript_path', '')
            reason = input_data.get('reason', '')

            log(f"触发原因: {reason}")

            if not transcript_path:
                log("没有 transcript_path，跳过")
                return {}

            # 2. 读取 transcript
            try:
                with open(transcript_path, 'r', encoding='utf-8') as f:
                    transcript = f.read()
            except Exception as e:
                log(f"读取 transcript 失败: {e}")
                return {}

            # 3. 解析对话
            messages = self.parser.parse(transcript)
            conversations = self.parser.extract_conversations(messages)

            log(f"解析到 {len(conversations)} 轮对话")

            # 4. 检查对话数量
            if len(conversations) < self.MIN_CONVERSATIONS:
                log(f"对话轮数 {len(conversations)} 少于最小值 {self.MIN_CONVERSATIONS}，跳过总结")
                return {}

            # 5. 构建对话内容
            conversation_content = self._build_conversation_content(conversations)

            # 6. 获取当前人格
            persona_id = self._get_active_persona()
            log(f"当前人格: {persona_id or '默认'}")

            # 7. 调用 LLM 生成总结
            prompt = SUMMARY_PROMPT.format(conversation_content=conversation_content)
            log("调用 LLM 生成总结...")

            summary = asyncio.run(self.llm.analyze(prompt))

            if not summary:
                log("LLM 未返回有效内容")
                return {}

            # 8. 保存经验
            manager = ExperienceManager(persona_id, MEMORY_DATA_PATH)
            file_path = manager.save(summary, len(conversations))

            if file_path:
                log(f"=== 会话总结完成: {file_path} ===")
                return {
                    "success": True,
                    "file_path": str(file_path),
                    "conversation_count": len(conversations)
                }

            return {}

        except Exception as e:
            log(f"Hook 执行错误: {e}")
            log(traceback.format_exc())
            return {}

    def _build_conversation_content(self, conversations: List[Dict[str, str]], max_pairs: int = 10) -> str:
        """构建对话内容字符串"""
        # 只取最近的 N 轮对话
        recent = conversations[-max_pairs:] if len(conversations) > max_pairs else conversations

        parts = []
        for i, conv in enumerate(recent, 1):
            user_msg = conv.get('user', '')
            assistant_msg = conv.get('assistant', '')

            # 截断过长的内容
            if len(user_msg) > 500:
                user_msg = user_msg[:500] + "..."
            if len(assistant_msg) > 800:
                assistant_msg = assistant_msg[:800] + "..."

            parts.append(f"### 第 {i} 轮对话")
            parts.append(f"**用户**: {user_msg}")
            parts.append(f"**助手**: {assistant_msg}")
            parts.append("")

        return "\n".join(parts)

    def _get_active_persona(self) -> Optional[str]:
        """获取当前激活的人格"""
        try:
            from memory_system.personas import PersonaManager
            pm = PersonaManager(str(MEMORY_DATA_PATH))
            index = pm.load_index()
            return index.active_persona
        except Exception as e:
            log(f"获取人格失败: {e}")
            return None


def main():
    """主函数 - Hook 入口"""
    try:
        # 读取 stdin
        raw_input = _sys.stdin.read()
        if not raw_input:
            print(json.dumps({}))
            return

        # 解析输入
        try:
            input_data = json.loads(raw_input)
        except json.JSONDecodeError:
            print(json.dumps({}))
            return

        # 执行 Hook
        hook = SessionSummaryHook()
        result = hook.run(input_data)

        # 返回结果
        print(json.dumps(result, ensure_ascii=False))

    except Exception as e:
        log(f"主函数错误: {e}")
        print(json.dumps({}))

    _sys.exit(0)


if __name__ == '__main__':
    main()
