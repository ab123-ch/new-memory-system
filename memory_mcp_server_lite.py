"""
Memory System MCP Server - 精简版

只保留核心功能：
1. 人格管理（6个工具）
2. 会话管理（2个工具）
3. 记忆管理（4个工具）

v3.0 改进：
- 使用 OpenCode (deer-flow) 进行智能摘要和相关性判断
- 每日整体摘要
- 关键词索引 + 相关性召回
- 人格创建时询问能力
- 元记忆支持正反面案例
"""

import asyncio
import json
from datetime import datetime, date, timedelta
from typing import Any, Optional, Dict, List
from pathlib import Path
import yaml
import re

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# 导入精简后的模块
import sys
sys.path.insert(0, str(Path(__file__).parent))

from memory_system.personas import PersonaManager
from memory_system.storage import FileStore
from memory_system.models import GlobalIndex
from memory_system.opencode_client import get_opencode_client, OPENCODE_AVAILABLE


# ============== 配置 ==============

# 默认人格系统提示词 - 认知更新能力
DEFAULT_PERSONA_SYSTEM_PROMPT = """## 认知更新机制

在每次对话中，你需要主动检测用户消息中包含的、与你当前记忆/上下文认知不一致的信息。

### 触发更新的场景
1. **事实修正**：用户提供的实际信息与你记忆中的描述不同
   - 示例：你记忆中"工程B是独立服务"，但用户说"工程B只是个jar包"
2. **架构变更**：系统结构、依赖关系发生变化
3. **偏好修正**：用户的习惯、偏好与记忆记录不符
4. **知识更新**：新知识覆盖旧知识，或补充缺失信息

### 更新原则
- **准确性优先**：以用户最新表述为准，及时修正错误记忆
- **保留上下文**：更新时保留相关背景，避免信息断层
- **明确记录**：使用 persona_set_memory 工具更新记忆文件

### 更新时机
当你发现以下情况时，应立即使用相应工具更新记忆：
- 用户明确说"不是"、"其实"、"应该是"等纠正性词汇
- 用户的描述与你的上下文记忆存在明显矛盾
- 用户提供了更准确、更详细的替代信息

请始终保持记忆的准确性和时效性，这是提供高质量服务的基础。"""

app = Server("memory-system-lite")

# 全局实例
_persona_manager: Optional[PersonaManager] = None
_storage_path: Path = None
_daily_summaries: Dict[str, Dict] = {}  # 每日摘要缓存
_keyword_index: Dict[str, List[Dict]] = {}  # 关键词索引

# 当前会话追踪（用于 session_close 时更新索引）
_current_session_id: Optional[str] = None
_current_session_file: Optional[Path] = None
_current_session_date: Optional[str] = None


def get_storage_path() -> Path:
    """获取存储路径"""
    global _storage_path
    if _storage_path is None:
        _storage_path = Path(__file__).parent / "data" / "memory"
        _storage_path.mkdir(parents=True, exist_ok=True)
    return _storage_path


def get_persona_manager() -> PersonaManager:
    """获取人格管理器"""
    global _persona_manager
    if _persona_manager is None:
        _persona_manager = PersonaManager(str(get_storage_path()))
    return _persona_manager


def get_persona_storage_path(persona_id: str = None) -> Path:
    """获取人格存储路径"""
    base = get_storage_path()
    if persona_id:
        return base / "personas" / persona_id
    return base


def load_memory_file(file_path: Path) -> Dict:
    """加载记忆文件"""
    if file_path.exists():
        with open(file_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    return {}


def save_memory_file(file_path: Path, data: Dict):
    """保存记忆文件"""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, 'w', encoding='utf-8') as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)


# ============== 摘要生成 ==============
# 设计原则：不在服务端调用 LLM，而是让 AI 自己生成摘要后传入
# 这样可以复用当前对话的 AI 能力，无需额外 API 调用

def truncate_text(content: str, max_length: int = 200) -> str:
    """简单截断文本（用于未提供摘要时的降级）"""
    content = content.strip()
    if len(content) <= max_length:
        return content
    return content[:max_length] + "..."


def extract_keywords(text: str) -> List[str]:
    """
    从文本中提取关键词

    规则：
    1. 业务词汇（退舱、红冲、资费等）
    2. 技术词汇（API、接口、数据库等）
    3. 中文词组（2-4字）
    """
    keywords = set()

    # 常见业务关键词模式
    business_patterns = [
        r'[\u4e00-\u9fa5]{2,4}(?:逻辑|功能|模块|系统|流程|接口|服务)',
        r'[\u4e00-\u9fa5]{2,4}(?:修改|优化|新增|删除|调整)',
        r'(?:红冲|退舱|资费|订舱|费用|审批|合同|发票)',
    ]

    for pattern in business_patterns:
        matches = re.findall(pattern, text)
        keywords.update(matches)

    # 提取引号中的内容
    quoted = re.findall(r'[""「」『』]([^""「」『』]+)[""「」『』]', text)
    keywords.update(quoted)

    # 提取代码标识符（驼峰命名）
    code_ids = re.findall(r'\b([A-Z][a-zA-Z]+(?:[A-Z][a-zA-Z]+)+)\b', text)
    keywords.update(code_ids)

    return list(keywords)[:10]


def extract_date_hint(text: str) -> Optional[str]:
    """
    从查询文本中提取日期线索

    支持：
    - 相对日期：今天、昨天、前天、大前天
    - 星期：上周一、本周五
    - 绝对日期：3月22日、2026-03-22
    - 天数偏移：前天、3天前、上周

    Returns:
        ISO 日期字符串 (如 "2026-04-03") 或 None
    """
    from datetime import timedelta

    today = date.today()
    text_lower = text.lower()

    # 相对日期
    if "今天" in text or "今天" in text_lower:
        return today.isoformat()
    if "昨天" in text:
        return (today - timedelta(days=1)).isoformat()
    if "前天" in text:
        return (today - timedelta(days=2)).isoformat()
    if "大前天" in text:
        return (today - timedelta(days=3)).isoformat()

    # N天前
    m = re.search(r'(\d+)\s*天前', text)
    if m:
        days = int(m.group(1))
        return (today - timedelta(days=days)).isoformat()

    # 上周X
    weekday_map = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
    m = re.search(r'上周([一二三四五六日天])', text)
    if m:
        target_wd = weekday_map.get(m.group(1))
        if target_wd is not None:
            days_back = today.weekday() + 7 - target_wd
            if days_back <= 0:
                days_back += 7
            return (today - timedelta(days=days_back)).isoformat()

    # 本周X
    m = re.search(r'本周([一二三四五六日天])', text)
    if m:
        target_wd = weekday_map.get(m.group(1))
        if target_wd is not None:
            diff = target_wd - today.weekday()
            if diff > 0:
                diff -= 7  # 本周过去的日期
            return (today + timedelta(days=diff)).isoformat()

    # 绝对日期：M月D日
    m = re.search(r'(\d{1,2})月(\d{1,2})[日号]', text)
    if m:
        month = int(m.group(1))
        day_num = int(m.group(2))
        try:
            target = date(today.year, month, day_num)
            # 如果未来日期，取去年
            if target > today:
                target = date(today.year - 1, month, day_num)
            return target.isoformat()
        except ValueError:
            pass

    # ISO 日期格式
    m = re.search(r'(\d{4}-\d{2}-\d{2})', text)
    if m:
        return m.group(1)

    return None


# ============== 每日摘要 ==============

async def generate_daily_summary(date_str: str, persona_id: str = None) -> Dict:
    """
    生成每日整体摘要

    Args:
        date_str: 日期字符串 (2026-03-22)
        persona_id: 人格ID（可选）

    Returns:
        {
            "date": "2026-03-22",
            "summary": "今日主要工作：...",
            "topics": [...],
            "keywords": [...],
            "session_count": 3
        }
    """
    storage = get_persona_storage_path(persona_id)

    # 新版目录结构: personas/{persona_id}/{date}/sess_xxx.yaml
    date_dir = storage / date_str

    if not date_dir.exists():
        return {"date": date_str, "summary": "无记忆", "topics": [], "keywords": []}

    # 读取该日期下所有会话文件
    session_files = [f for f in date_dir.glob("sess_*.yaml")]
    if not session_files:
        return {"date": date_str, "summary": "无会话", "topics": [], "keywords": []}

    # 汇总所有会话的摘要和关键词
    all_summaries = []
    all_keywords = set()
    topics = []

    for session_file in session_files:
        data = load_memory_file(session_file)
        summary = data.get("summary", "")
        if summary:
            all_summaries.append(summary)

        keywords = data.get("keywords", [])
        all_keywords.update(keywords)

        topics.append({
            "session_id": session_file.stem,
            "summary": summary,
            "keywords": keywords[:5]
        })

    # 生成整体摘要
    if all_summaries:
        combined = "\n".join([f"- {s}" for s in all_summaries])
        daily_summary = f"今日主要工作 ({len(session_files)} 个会话):\n{combined}"
    else:
        daily_summary = f"今日有 {len(session_files)} 个会话，无摘要"

    result = {
        "date": date_str,
        "summary": daily_summary,
        "topics": topics,
        "keywords": list(all_keywords),
        "session_count": len(session_files)
    }

    # 缓存结果
    cache_key = f"{persona_id or 'default'}_{date_str}"
    _daily_summaries[cache_key] = result

    # 保存到文件（与日期目录同级）
    index_file = date_dir / "index.yaml"
    save_memory_file(index_file, result)

    return result


# ============== 关键词索引 ==============

def build_keyword_index(persona_id: str = None, recent_days: int = 30):
    """
    构建关键词索引

    支持两种目录结构：
    - 新格式 (v2.0): {date}/{session_id}.yaml
    - 旧格式 (v1.0): {month}/{date}.yaml (包含 sessions 数组)

    结构:
    {
        "红冲": [
            {"date": "2026-03-22", "session": "sess_001", "relevance": 0.95}
        ],
        ...
    }

    Args:
        persona_id: 人格ID，None 则使用当前活跃人格
        recent_days: 只索引最近 N 天的记忆，默认 30 天。设为 0 索引全部。
    """
    global _keyword_index
    _keyword_index = {}

    storage = get_persona_storage_path(persona_id)
    today = date.today()
    cutoff = (today - timedelta(days=recent_days)).isoformat() if recent_days > 0 else ""

    # 1. 新格式：遍历日期目录 (格式: 20??-??-??)
    for date_dir in storage.glob("20??-??-??"):
        if not date_dir.is_dir():
            continue

        date_str = date_dir.name

        # 日期范围过滤：跳过早于 cutoff 的目录
        if cutoff and date_str < cutoff:
            continue

        # 遍历该日期下的所有会话文件
        for session_file in date_dir.glob("*.yaml"):
            if session_file.name in ["index.yaml", "index.md"]:
                continue

            data = load_memory_file(session_file)
            if not data:
                continue

            session_id = session_file.stem  # 文件名即 session_id
            keywords = data.get("keywords", [])
            summary = data.get("summary", "")

            # 确保 keywords 是列表
            if not isinstance(keywords, list):
                continue

            # 为每个关键词建立索引
            for kw in keywords:
                if not isinstance(kw, str):
                    continue
                if kw not in _keyword_index:
                    _keyword_index[kw] = []

                _keyword_index[kw].append({
                    "date": date_str,
                    "session": session_id,
                    "summary": summary[:50] + "..." if len(summary) > 50 else summary,
                    "relevance": 1.0  # 精确匹配
                })

    # 2. 旧格式：遍历月份目录 (格式: 20??-??)
    for month_dir in storage.glob("20??-??"):
        if not month_dir.is_dir():
            continue

        # 遍历该月份下的所有日期文件
        for day_file in month_dir.glob("20??-??-??.yaml"):
            if day_file.name.endswith(".index.yaml"):
                continue

            date_str = day_file.stem

            # 日期范围过滤
            if cutoff and date_str < cutoff:
                continue

            data = load_memory_file(day_file)
            if not data:
                continue

            date_str = day_file.stem

            # 旧格式：从 sessions 数组中提取
            sessions = data.get("sessions", [])
            for session in sessions:
                session_id = session.get("session_id", "")
                keywords = session.get("keywords", [])
                summary = session.get("summary", "")

                # 确保 keywords 是列表
                if not isinstance(keywords, list):
                    continue

                for kw in keywords:
                    if not isinstance(kw, str):
                        continue
                    if kw not in _keyword_index:
                        _keyword_index[kw] = []

                    _keyword_index[kw].append({
                        "date": date_str,
                        "session": session_id,
                        "summary": summary[:50] + "..." if len(summary) > 50 else summary,
                        "relevance": 1.0
                    })


def search_by_keywords(keywords: List[str]) -> List[Dict]:
    """
    通过关键词搜索记忆

    Args:
        keywords: 关键词列表

    Returns:
        匹配的记忆列表
    """
    results = []
    seen = set()

    for kw in keywords:
        if kw in _keyword_index:
            for item in _keyword_index[kw]:
                key = f"{item['date']}_{item['session']}"
                if key not in seen:
                    seen.add(key)
                    results.append(item)

    # 按相关性排序
    results.sort(key=lambda x: x.get("relevance", 0), reverse=True)

    return results[:5]  # 返回前 5 个


# ============== MCP 工具定义 ==============

def get_tools() -> List[Tool]:
    """获取所有 MCP 工具"""
    return [
        # ========== 人格管理 ==========
        Tool(
            name="persona_list",
            description="列出所有可用人格。当用户询问有哪些人格、人格选项时调用。",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="persona_switch",
            description="切换人格。当用户说'切换到XX'、'用XX模式'、'换成XX'时调用。传入空字符串切换到默认状态。",
            inputSchema={
                "type": "object",
                "properties": {
                    "persona_id": {
                        "type": "string",
                        "description": "人格ID或名称，空字符串表示切换到默认状态"
                    }
                },
                "required": ["persona_id"]
            }
        ),
        Tool(
            name="persona_create",
            description="""创建新人格。当用户说'创建一个XX人格'、'新建人格'时调用。

创建流程：
1. 询问用户人格名称
2. 询问人格的主要用途/场景
3. 询问人格应该优先具备什么能力/知识
4. 根据用户回答创建人格""",
            inputSchema={
                "type": "object",
                "properties": {
                    "persona_id": {
                        "type": "string",
                        "description": "人格ID(英文,如 work, study)"
                    },
                    "name": {
                        "type": "string",
                        "description": "人格名称(如:工作助手)"
                    },
                    "description": {
                        "type": "string",
                        "description": "人格描述"
                    },
                    "abilities": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "人格应具备的能力列表"
                    },
                    "trigger_keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "触发关键词(可选)"
                    },
                    "system_prompt": {
                        "type": "string",
                        "description": "自定义系统提示词(可选，默认使用认知更新提示词)"
                    }
                },
                "required": ["persona_id", "name"]
            }
        ),
        Tool(
            name="persona_set_memory",
            description="""设置人格的元记忆。支持添加正面案例、反面案例和能力特征。

类型说明：
- identity: 身份信息（用户是XX、用户喜欢XX）
- habit: 习惯偏好（用户习惯用XX方式）
- ability: 能力特征/正面案例（正确做法、最佳实践）
- negative_case: 反面案例（错误做法、需要避免的）
- positive_case: 正面案例（成功经验、推荐做法）""",
            inputSchema={
                "type": "object",
                "properties": {
                    "memory_type": {
                        "type": "string",
                        "enum": ["identity", "habit", "ability", "positive_case", "negative_case"],
                        "description": "记忆类型"
                    },
                    "content": {
                        "type": "string",
                        "description": "记忆内容"
                    }
                },
                "required": ["memory_type", "content"]
            }
        ),
        Tool(
            name="persona_get_context",
            description="获取当前人格的完整上下文。包含人格信息、元记忆、能力等。",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="persona_delete",
            description="删除人格。当用户说'删除XX人格'时调用。",
            inputSchema={
                "type": "object",
                "properties": {
                    "persona_id": {
                        "type": "string",
                        "description": "要删除的人格ID"
                    }
                },
                "required": ["persona_id"]
            }
        ),

        # ========== 会话管理 ==========
        Tool(
            name="session_close",
            description="关闭当前会话并保存状态。下次启动时会自动恢复当前人格。",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="session_restore",
            description="手动恢复上一个会话的人格。查看上次关闭会话时使用的人格并切换过去。",
            inputSchema={"type": "object", "properties": {}}
        ),

        # ========== 记忆管理 ==========
        Tool(
            name="memory_save",
            description="""保存对话到记忆。在重要对话结束后调用。

【重要】你应该在保存前自己生成摘要:
1. 总结这次对话的主要内容(1-2句话)
2. 提取关键业务词汇和技术词汇
3. 然后调用此工具保存

示例调用:
{
    "user_message": "原始用户消息",
    "assistant_message": "原始助手响应",
    "summary": "讨论了退舱红冲资费逻辑,涉及费用计算和状态流转",
    "keywords": ["退舱", "红冲", "资费", "费用计算", "BillCreateWayEnum"],
    "session_id": "sess_abc123_20260325"
}""",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_message": {
                        "type": "string",
                        "description": "用户消息"
                    },
                    "assistant_message": {
                        "type": "string",
                        "description": "助手响应"
                    },
                    "summary": {
                        "type": "string",
                        "description": "【必填】你生成的对话摘要(1-2句话概括主要内容)"
                    },
                    "keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "【必填】你提取的关键词列表(业务词、技术词、代码标识)"
                    },
                    "session_id": {
                        "type": "string",
                        "description": "【必填】当前会话的唯一标识"
                    }
                },
                "required": ["user_message", "assistant_message", "summary", "keywords", "session_id"]
            }
        ),
        Tool(
            name="memory_daily_summary",
            description="""生成或获取每日记忆摘要。

功能：
1. 汇总当日所有会话
2. 提取主要主题和关键词
3. 生成整体摘要

当用户想了解今天/某天做了什么时调用。""",
            inputSchema={
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "日期 (如 '2026-03-22')，默认今天"
                    }
                }
            }
        ),
        Tool(
            name="memory_recall",
            description="""召回相关记忆。

召回策略：
1. 先通过关键词精确匹配
2. 如果没有匹配，加载所有每日摘要进行相关性搜索
3. 返回最相关的记忆

当用户提到之前的需求、问题、讨论时调用。""",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "查询内容（可以是关键词、问题描述或完整句子）"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回数量限制",
                        "default": 5
                    }
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="memory_recall_by_date",
            description="""按日期精确召回记忆。

当需要查看某天的完整记忆时调用。
例如：用户说'查看昨天的记忆'、'3月20日做了什么'""",
            inputSchema={
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "日期 (如 '2026-03-22')"
                    },
                    "session_id": {
                        "type": "string",
                        "description": "会话ID (可选，不提供则返回整天的记忆)"
                    }
                },
                "required": ["date"]
            }
        ),
        # ========== 经验管理 ==========
        Tool(
            name="experience_list",
            description="""列出当前人格的经验索引。

只返回经验列表的索引（ID、标题、日期），不返回具体内容。
当需要获取具体经验时，使用 experience_get 工具。

使用场景：
- 查看有哪些可用的经验
- 会话开始时了解经验概况""",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "返回数量限制",
                        "default": 10
                    }
                }
            }
        ),
        Tool(
            name="experience_get",
            description="""获取具体经验的完整内容。

根据经验ID（文件名）获取经验的完整内容。
经验ID可以从 experience_list 工具获取。

使用场景：
- 需要查看某个具体经验的详细内容
- 需要参考之前会话的经验总结""",
            inputSchema={
                "type": "object",
                "properties": {
                    "experience_id": {
                        "type": "string",
                        "description": "经验ID（文件名，如 '2026-03-24_143052_abc123'）"
                    }
                },
                "required": ["experience_id"]
            }
        ),
    ]


# ============== 工具处理函数 ==============

async def handle_persona_list() -> List[TextContent]:
    """处理 persona_list"""
    pm = get_persona_manager()
    index = pm.load_index()
    personas = index.list_personas()

    if not personas:
        return [TextContent(type="text", text="目前没有创建任何人格。\n\n使用 persona_create 创建新人格。")]

    output = "【可用人格】\n\n"
    for p in personas:
        active_marker = " ← 当前" if p.get("is_active") else ""
        output += f"• {p['name']}{active_marker}\n"
        output += f"  ID: {p['id']}\n"
        if p.get("description"):
            output += f"  描述: {p['description']}\n"
        if p.get("trigger_keywords"):
            output += f"  触发词: {', '.join(p['trigger_keywords'])}\n"
        output += "\n"

    return [TextContent(type="text", text=output)]


async def handle_persona_switch(persona_id: str) -> List[TextContent]:
    """处理 persona_switch"""
    pm = get_persona_manager()

    if persona_id == "":
        # 切换到默认状态
        index = pm.load_index()
        index.set_active(None)
        pm.save_index(index)
        pm.save_session_persona(None)
        return [TextContent(type="text", text="已切换到默认状态（无特定人格）")]

    # 尝试切换
    index = pm.load_index()

    # 支持通过名称查找
    if persona_id not in index.personas:
        found_id = index.find_by_keyword(persona_id)
        if found_id:
            persona_id = found_id

    if index.set_active(persona_id):
        pm.save_index(index)
        pm.save_session_persona(persona_id)
        persona_info = index.personas.get(persona_id, {})
        name = persona_info.get("name", persona_id)
        return [TextContent(type="text", text=f"已切换到人格: {name}")]
    else:
        return [TextContent(type="text", text=f"人格 '{persona_id}' 不存在。\n\n使用 persona_list 查看可用人格。")]


async def handle_persona_create(
    persona_id: str,
    name: str,
    description: str = "",
    abilities: List[str] = None,
    trigger_keywords: List[str] = None,
    system_prompt: str = None
) -> List[TextContent]:
    """处理 persona_create"""
    pm = get_persona_manager()

    # 使用传入的 system_prompt 或默认的认知更新提示词
    final_system_prompt = system_prompt if system_prompt else DEFAULT_PERSONA_SYSTEM_PROMPT

    # 创建人格配置
    config = pm.create_persona(
        persona_id=persona_id,
        name=name,
        description=description,
        trigger_keywords=trigger_keywords or [],
        system_prompt=final_system_prompt
    )

    # 如果提供了能力，添加到元记忆
    if abilities:
        for ability in abilities:
            pm.set_persona_memory(
                persona_id=persona_id,
                memory_type="ability",
                content=ability
            )

    return [TextContent(
        type="text",
        text=f"人格创建成功！\n\n"
             f"名称: {name}\n"
             f"ID: {persona_id}\n"
             f"描述: {description}\n"
             f"能力: {', '.join(abilities) if abilities else '无'}\n\n"
             f"使用 persona_switch('{persona_id}') 切换到此人格。"
    )]


async def handle_persona_set_memory(
    memory_type: str,
    content: str
) -> List[TextContent]:
    """处理 persona_set_memory"""
    pm = get_persona_manager()
    index = pm.load_index()

    if not index.active_persona:
        return [TextContent(
            type="text",
            text="当前没有激活的人格。\n\n使用 persona_switch 先切换到一个人格。"
        )]

    # 映射记忆类型
    type_mapping = {
        "positive_case": "ability",  # 正面案例存为能力
        "negative_case": "habit",    # 反面案例存为习惯（待改进）
    }

    actual_type = type_mapping.get(memory_type, memory_type)

    # 如果是反面案例，添加标记
    if memory_type == "negative_case":
        content = f"【反面案例】{content}"

    pm.set_persona_memory(
        persona_id=index.active_persona,
        memory_type=actual_type,
        content=content
    )

    type_names = {
        "identity": "身份信息",
        "habit": "习惯偏好",
        "ability": "能力特征/正面案例",
        "positive_case": "正面案例",
        "negative_case": "反面案例"
    }

    return [TextContent(
        type="text",
        text=f"已添加{type_names.get(memory_type, memory_type)}到人格元记忆:\n\n{content[:100]}{'...' if len(content) > 100 else ''}"
    )]


async def handle_persona_get_context() -> List[TextContent]:
    """处理 persona_get_context"""
    pm = get_persona_manager()
    context = pm.get_memory_context()

    persona_info = context.get("persona")
    if not persona_info:
        return [TextContent(type="text", text="当前处于默认状态（无特定人格）")]

    output = f"【当前人格】{persona_info.get('name', '')}\n\n"

    if persona_info.get("description"):
        output += f"描述: {persona_info['description']}\n\n"

    soul = context.get("soul", {})

    if soul.get("identity"):
        output += "【身份信息】\n"
        for item in soul["identity"][:3]:
            output += f"• {item[:80]}\n"
        output += "\n"

    if soul.get("abilities"):
        output += "【能力特征/正面案例】\n"
        for item in soul["abilities"][:5]:
            if item.startswith("【反面案例】"):
                continue
            output += f"• {item[:80]}\n"
        output += "\n"

    # 单独显示反面案例
    negative_cases = [a for a in soul.get("abilities", [])
                     if a.startswith("【反面案例】")]
    if negative_cases:
        output += "【反面案例】\n"
        for item in negative_cases[:3]:
            output += f"• {item[7:80]}\n"
        output += "\n"

    return [TextContent(type="text", text=output)]


async def handle_persona_delete(persona_id: str) -> List[TextContent]:
    """处理 persona_delete"""
    pm = get_persona_manager()

    if pm.delete_persona(persona_id):
        return [TextContent(type="text", text=f"人格 '{persona_id}' 已删除")]
    else:
        return [TextContent(type="text", text=f"人格 '{persona_id}' 不存在")]


async def generate_date_index(
    storage: Path,
    date_str: str,
    session_id: str = None,
    session_file: Path = None
) -> bool:
    """
    生成或更新日期索引文件（分析当天所有会话）

    Args:
        storage: 人格存储路径
        date_str: 日期字符串 (YYYY-MM-DD)
        session_id: 会话ID（可选，用于标记更新）
        session_file: 会话文件路径（可选）

    Returns:
        是否成功
    """
    try:
        date_dir = storage / date_str
        index_file = date_dir / "index.md"

        # 获取当天所有会话文件
        session_files = sorted(date_dir.glob("sess_*.yaml"))
        if not session_files:
            print(f"[generate_date_index] 没有找到会话文件: {date_dir}")
            return False

        print(f"[generate_date_index] 找到 {len(session_files)} 个会话文件")

        # 分析所有会话
        all_sessions = []
        for idx, sf in enumerate(session_files, 1):
            session_data = load_memory_file(sf)
            if not session_data:
                continue

            current_session_id = session_data.get("session_id", sf.stem)

            # 使用 OpenCode 生成会话摘要
            if OPENCODE_AVAILABLE:
                client = get_opencode_client()
                summary_result = await client.generate_session_summary(session_data)
                session_summary = summary_result.get("summary", session_data.get("summary", "无摘要"))
                keywords = summary_result.get("keywords", session_data.get("keywords", []))
                time_range = summary_result.get("time_range", "")
            else:
                # 降级：使用现有摘要
                session_summary = session_data.get("summary", "无摘要")
                keywords = session_data.get("keywords", [])
                # 计算时间范围
                convs = session_data.get("conversations", [])
                start_time = convs[0].get("timestamp", "")[11:16] if convs else ""
                end_time = convs[-1].get("timestamp", "")[11:16] if convs else ""
                time_range = f"{start_time} - {end_time}"

            all_sessions.append({
                "session_id": current_session_id,
                "summary": session_summary,
                "keywords": keywords,
                "time_range": time_range
            })

            print(f"[generate_date_index] 分析会话 {idx}/{len(session_files)}: {current_session_id}")

        if not all_sessions:
            return False

        # 构建索引内容（所有会话）
        sessions_content = ""
        for idx, sess in enumerate(all_sessions, 1):
            sessions_content += f"""## {idx}. {sess['time_range']}

**会话ID**: `{sess['session_id']}`

**摘要**:
{sess['summary']}

**关键词**: {', '.join(sess['keywords'][:5]) if sess['keywords'] else '无'}

---

"""

        # 完整索引内容
        index_content = f"""# {date_str} 工作记录

> 共 {len(all_sessions)} 个会话

{sessions_content}"""

        # 保存索引文件
        with open(index_file, 'w', encoding='utf-8') as f:
            f.write(index_content)

        print(f"[generate_date_index] 日期索引已生成: {index_file} (包含 {len(all_sessions)} 个会话)")
        return True

    except Exception as e:
        print(f"[generate_date_index] 生成索引失败: {e}")
        import traceback
        traceback.print_exc()
        return False



async def handle_session_close() -> List[TextContent]:
    """处理 session_close"""
    global _current_session_id, _current_session_file, _current_session_date

    pm = get_persona_manager()
    index = pm.load_index()

    # 更新日期索引（如果有活动会话）
    if _current_session_id and _current_session_file and _current_session_date:
        storage = get_persona_storage_path(index.active_persona)

        # 异步生成索引
        try:
            success = await generate_date_index(
                storage=storage,
                date_str=_current_session_date,
                session_id=_current_session_id,
                session_file=_current_session_file
            )
            if success:
                print(f"[session_close] 日期索引已更新: {_current_session_date}/{_current_session_id}")
        except Exception as e:
            print(f"[session_close] 更新索引失败: {e}")

    # 关闭会话
    result = pm.close_session()

    # 清理全局状态
    _current_session_id = None
    _current_session_file = None
    _current_session_date = None

    if result.get("closed"):
        return [TextContent(type="text", text=f"会话已关闭。人格 '{result.get('persona_name')}' 已保存，日期索引已更新。")]
    else:
        return [TextContent(type="text", text="会话已关闭。")]


async def handle_session_restore() -> List[TextContent]:
    """处理 session_restore"""
    pm = get_persona_manager()
    result = pm.auto_restore_persona()

    if result.get("restored"):
        return [TextContent(type="text", text=f"已恢复人格: {result.get('persona_name')}")]
    else:
        return [TextContent(type="text", text=result.get("message", "没有可恢复的人格"))]


async def handle_memory_save(
    user_message: str,
    assistant_message: str,
    summary: Optional[str] = None,
    keywords: Optional[List[str]] = None,
    session_id: Optional[str] = None
) -> List[TextContent]:
    """
    处理 memory_save

    Args:
        user_message: 用户消息
        assistant_message: 助手响应
        summary: AI 提供的摘要（如果没提供，使用 OpenCode 生成）
        keywords: AI 提供的关键词（如果没提供，使用规则提取）
        session_id: 会话ID（必填，由调用方传入）
    """
    # 验证 session_id
    if not session_id:
        return [TextContent(
            type="text",
            text="错误: session_id 参数是必填的，请传入当前会话的ID"
        )]

    pm = get_persona_manager()
    index = pm.load_index()

    # 确定存储路径（按日期+会话隔离）
    storage = get_persona_storage_path(index.active_persona)
    today = date.today()
    date_str = today.isoformat()
    date_dir = storage / date_str  # 按日期分目录
    date_dir.mkdir(parents=True, exist_ok=True)
    memory_file = date_dir / f"{session_id}.yaml"  # 按会话ID命名

    # 加载或创建会话文件（单会话单文件）
    data = load_memory_file(memory_file)
    if not data:
        data = {
            "version": "2.0",  # 新版本标识
            "date": date_str,
            "session_id": session_id,
            "created_at": datetime.now().isoformat(),
            "conversations": [],
            "summary": "",
            "keywords": []
        }

    current_session = data  # 直接使用 data 作为会话数据

    # 生成对话摘要（AI 提供 > OpenCode 生成 > 规则降级）
    combined_text = f"用户: {user_message}\n助手: {assistant_message}"

    if summary:
        # AI 已提供摘要
        conv_summary = summary
        source = "AI"
    elif OPENCODE_AVAILABLE:
        # 使用 OpenCode 生成
        client = get_opencode_client()
        result = await client.generate_summary(user_message, assistant_message)
        conv_summary = result["summary"]
        source = "OpenCode"
    else:
        # 降级：规则提取
        conv_summary = truncate_text(combined_text, 100)
        source = "规则"

    # 提取关键词（AI 提供 > OpenCode 提取 > 规则提取）
    if keywords:
        final_keywords = keywords
    elif OPENCODE_AVAILABLE:
        client = get_opencode_client()
        result = await client.generate_summary(user_message, assistant_message)
        final_keywords = result.get("keywords", extract_keywords(combined_text))
    else:
        final_keywords = extract_keywords(combined_text)

    # 添加对话
    conv_id = f"{session_id}_conv_{len(data['conversations'])}"
    data["conversations"].extend([
        {
            "id": f"{conv_id}_user",
            "role": "user",
            "content": user_message,
            "summary": truncate_text(user_message, 50),
            "timestamp": datetime.now().isoformat()
        },
        {
            "id": f"{conv_id}_assistant",
            "role": "assistant",
            "content": assistant_message,
            "summary": truncate_text(assistant_message, 50),
            "timestamp": datetime.now().isoformat()
        }
    ])

    # 更新会话摘要和关键词
    data["summary"] = conv_summary
    data["keywords"] = list(set(data.get("keywords", []) + final_keywords))

    # 更新文件
    data["updated_at"] = datetime.now().isoformat()
    save_memory_file(memory_file, data)

    # 更新全局会话追踪（用于 session_close 时更新索引）
    global _current_session_id, _current_session_file, _current_session_date
    _current_session_id = session_id
    _current_session_file = memory_file
    _current_session_date = date_str

    # 更新关键词索引
    for kw in final_keywords:
        if kw not in _keyword_index:
            _keyword_index[kw] = []
        _keyword_index[kw].append({
            "date": date_str,
            "session": session_id,
            "summary": data["summary"][:50],
            "relevance": 1.0
        })

    return [TextContent(
        type="text",
        text=f"记忆已保存\n"
             f"日期: {date_str}\n"
             f"会话: {session_id}\n"
             f"文件: {memory_file.name}\n"
             f"摘要来源: {source}\n"
             f"摘要: {conv_summary[:100]}...\n"
             f"关键词: {', '.join(final_keywords[:5])}"
    )]


async def handle_memory_daily_summary(date_str: str = None) -> List[TextContent]:
    """处理 memory_daily_summary"""
    pm = get_persona_manager()
    index = pm.load_index()

    if not date_str:
        date_str = date.today().isoformat()

    summary = await generate_daily_summary(date_str, index.active_persona)

    output = f"【{date_str} 记忆摘要】\n\n"
    output += summary.get("summary", "无摘要") + "\n\n"

    if summary.get("keywords"):
        output += f"关键词: {', '.join(summary['keywords'][:10])}\n\n"

    if summary.get("topics"):
        output += "会话列表:\n"
        for topic in summary["topics"]:
            output += f"• {topic.get('session_id')}: {topic.get('summary', '')[:50]}...\n"

    return [TextContent(type="text", text=output)]


async def handle_memory_recall(query: str, limit: int = 5) -> List[TextContent]:
    """
    处理 memory_recall - 三级优先召回策略

    P0: 人格 + 日期精确匹配（从查询中提取日期线索）
    P1: 人格 + 关键词索引匹配（使用 _keyword_index）
    P2: 人格 + 最近N天降级搜索（不遍历全部历史）
    """
    pm = get_persona_manager()
    index = pm.load_index()

    if not index.active_persona:
        return [TextContent(type="text", text="没有活跃人格")]

    storage = get_persona_storage_path(index.active_persona)

    # ========== P0: 日期精确匹配 ==========
    date_hint = extract_date_hint(query)
    if date_hint:
        output = f"【记忆召回 - 日期精确匹配】\n\n"
        output += f"查询: {query}\n"
        output += f"提取日期: {date_hint}\n\n"

        # 直接定位到该日期目录
        date_dir = storage / date_hint
        if date_dir.exists() and date_dir.is_dir():
            # 读取该日期下所有 session
            session_results = []
            for session_file in date_dir.glob("*.yaml"):
                if session_file.name in ["index.yaml", "index.md"]:
                    continue
                data = load_memory_file(session_file)
                if data:
                    session_results.append({
                        "session_id": session_file.stem,
                        "summary": data.get("summary", ""),
                        "keywords": data.get("keywords", []),
                        "relevance": 1.0
                    })

            # 如果有多个 session，用关键词过滤排序
            if session_results:
                query_keywords = extract_keywords(query)
                if query_keywords:
                    for sr in session_results:
                        score = 0
                        for qk in query_keywords:
                            if qk in sr["summary"]:
                                score += 2
                            for kw in sr.get("keywords", []):
                                if qk in kw or kw in qk:
                                    score += 1
                        sr["relevance"] = score
                    session_results.sort(key=lambda x: x["relevance"], reverse=True)

                output += f"找到 {len(session_results)} 个会话:\n"
                for sr in session_results[:limit]:
                    output += f"\n📅 {date_hint} / {sr['session_id']}\n"
                    output += f"   {sr['summary'][:100]}\n"
                    if sr.get("keywords"):
                        output += f"   关键词: {', '.join(sr['keywords'][:5])}\n"

                output += f"\n💡 使用 memory_recall_by_date 获取完整内容"
                return [TextContent(type="text", text=output)]

        # 尝试旧格式：月份目录
        month_str = date_hint[:7]
        month_dir = storage / month_str
        day_file = month_dir / f"{date_hint}.yaml"

        if day_file.exists():
            data = load_memory_file(day_file)
            sessions = data.get("sessions", [])

            if sessions:
                output += f"找到 {len(sessions)} 个会话:\n"
                for session in sessions[:limit]:
                    output += f"\n📅 {date_hint} / {session.get('session_id', '')}\n"
                    output += f"   {session.get('summary', '')[:100]}\n"

                output += f"\n💡 使用 memory_recall_by_date 获取完整内容"
                return [TextContent(type="text", text=output)]

        output += f"日期 {date_hint} 没有记忆记录。\n"
        output += "继续使用关键词搜索...\n\n"
        # 日期没找到，继续 P1

    # ========== P1: 关键词索引匹配 ==========
    if not _keyword_index:
        build_keyword_index(index.active_persona, recent_days=30)

    query_keywords = extract_keywords(query)
    results = search_by_keywords(query_keywords) if query_keywords else []

    if results:
        output = f"【记忆召回 - 关键词匹配】\n\n" if not date_hint else output
        output += f"查询: {query}\n"
        output += f"匹配关键词: {', '.join(query_keywords)}\n\n"
        output += "相关记忆:\n"

        for r in results[:limit]:
            output += f"\n📅 {r['date']} / {r['session']}\n"
            output += f"   {r['summary']}\n"
            output += f"   相关性: {r.get('relevance', 0):.0%}\n"

        output += f"\n💡 使用 memory_recall_by_date 获取完整内容"
        return [TextContent(type="text", text=output)]

    # ========== P2: 最近N天降级搜索 ==========
    recent_days = 7
    output = f"【记忆召回 - 最近{recent_days}天搜索】\n\n"
    output += f"查询: {query}\n"
    output += f"未找到关键词精确匹配，搜索最近 {recent_days} 天记忆...\n\n"

    all_summaries = []
    today = date.today()

    for i in range(recent_days):
        target_date = today - timedelta(days=i)
        date_str = target_date.isoformat()

        # 新格式：日期目录
        date_dir = storage / date_str
        if date_dir.exists() and date_dir.is_dir():
            index_file = date_dir / "index.yaml"
            if index_file.exists():
                data = load_memory_file(index_file)
                if data.get("summary"):
                    all_summaries.append({
                        "date": date_str,
                        "summary": data.get("summary"),
                        "keywords": data.get("keywords", [])
                    })
                continue

        # 旧格式：月份目录
        month_str = date_str[:7]
        month_dir = storage / month_str
        day_file = month_dir / f"{date_str}.yaml"
        if day_file.exists():
            data = load_memory_file(day_file)
            sessions = data.get("sessions", [])
            if sessions:
                combined = "; ".join(
                    s.get("summary", "") for s in sessions if s.get("summary")
                )
                kws = []
                for s in sessions:
                    kws.extend(s.get("keywords", []))
                if combined:
                    all_summaries.append({
                        "date": date_str,
                        "summary": combined,
                        "keywords": kws
                    })

    if all_summaries:
        # 使用 OpenCode 进行相关性判断（如果可用）
        client = get_opencode_client()
        if client.available:
            try:
                results = await client.judge_relevance(query, all_summaries, top_k=limit)
                output += "【智能相关性搜索结果】\n"
                for r in results:
                    output += f"\n📅 {r.get('date', '')}\n"
                    output += f"   {r.get('summary', '')[:100]}...\n"
                    if r.get('relevance'):
                        output += f"   相关性: {r.get('relevance', 0):.0%}\n"
            except Exception as e:
                output += f"相关性判断失败 ({e})，返回最近的记忆:\n"
                for s in sorted(all_summaries, key=lambda x: x["date"], reverse=True)[:limit]:
                    output += f"\n📅 {s['date']}\n"
                    output += f"   {s['summary'][:100]}...\n"
        else:
            output += "最近的记忆摘要:\n"
            for s in sorted(all_summaries, key=lambda x: x["date"], reverse=True)[:limit]:
                output += f"\n📅 {s['date']}\n"
                output += f"   {s['summary'][:100]}...\n"
    else:
        output += "没有找到任何记忆。\n\n使用 memory_save 保存对话记忆。"

    return [TextContent(type="text", text=output)]


async def handle_memory_recall_by_date(
    date_str: str,
    session_id: str = None
) -> List[TextContent]:
    """处理 memory_recall_by_date - 适配新目录结构 {date}/{session_id}.yaml"""
    pm = get_persona_manager()
    index = pm.load_index()

    if not index.active_persona:
        return [TextContent(type="text", text="没有活跃人格")]

    storage = get_persona_storage_path(index.active_persona)
    date_dir = storage / date_str

    if not date_dir.exists():
        return [TextContent(type="text", text=f"没有找到 {date_str} 的记忆")]

    if session_id:
        # 返回指定会话
        session_file = date_dir / f"{session_id}.yaml"
        if not session_file.exists():
            return [TextContent(type="text", text=f"会话 {session_id} 不存在")]

        data = load_memory_file(session_file)
        output = f"【{date_str} / {session_id}】\n\n"
        output += f"摘要: {data.get('summary', '无')}\n"
        output += f"关键词: {', '.join(data.get('keywords', []))}\n\n"
        output += "对话内容:\n"

        for conv in data.get("conversations", []):
            role = "用户" if conv.get("role") == "user" else "助手"
            content = conv.get("content", "")
            output += f"\n{role}:\n{content[:500]}{'...' if len(content) > 500 else ''}\n"

        return [TextContent(type="text", text=output)]

    # 返回整天记忆 - 列出该日期下所有会话文件
    session_files = [f for f in date_dir.glob("*.yaml") if f.name != "index.yaml"]

    # 加载每日摘要（如果存在）
    index_file = date_dir / "index.yaml"
    daily_summary = ""
    daily_keywords = []
    if index_file.exists():
        index_data = load_memory_file(index_file)
        daily_summary = index_data.get("summary", "")
        daily_keywords = index_data.get("keywords", [])

    output = f"【{date_str} 记忆】\n\n"
    output += f"共 {len(session_files)} 个会话\n"

    if daily_summary:
        output += f"\n每日摘要: {daily_summary}\n"
    if daily_keywords:
        output += f"每日关键词: {', '.join(daily_keywords)}\n"

    output += "\n--- 会话列表 ---\n"

    for session_file in sorted(session_files):
        session_id_local = session_file.stem
        data = load_memory_file(session_file)
        summary = data.get("summary", "无")[:100]
        conv_count = len(data.get("conversations", []))
        output += f"\n[{session_id_local}]\n"
        output += f"  摘要: {summary}...\n"
        output += f"  对话数: {conv_count}\n"

    output += f"\n使用 memory_recall_by_date(date='{date_str}', session_id='xxx') 查看具体会话"

    return [TextContent(type="text", text=output)]


# ============== 经验管理 ==============

async def handle_experience_list(limit: int = 10) -> List[TextContent]:
    """处理 experience_list - 返回经验索引"""
    pm = get_persona_manager()
    index = pm.load_index()
    active_persona = index.active_persona

    if not active_persona:
        return [TextContent(type="text", text="当前没有激活的人格，无法查看经验。")]

    # 经验存储路径
    storage = get_persona_storage_path(active_persona)
    experiences_dir = storage / "experiences"

    if not experiences_dir.exists():
        return [TextContent(type="text", text=f"人格 '{active_persona}' 暂无经验记录。\n\n经验会在会话结束时自动生成。")]

    # 获取所有 MD 文件
    md_files = list(experiences_dir.glob("*.md"))
    if not md_files:
        return [TextContent(type="text", text=f"人格 '{active_persona}' 暂无经验记录。")]

    # 按修改时间排序
    md_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    md_files = md_files[:limit]

    output = f"【经验索引 - {active_persona}】\n\n"
    output += "使用 experience_get 获取具体内容\n\n"

    for i, md_file in enumerate(md_files, 1):
        # 只读取前 20 行获取元数据
        try:
            with open(md_file, 'r', encoding='utf-8') as f:
                first_lines = [f.readline() for _ in range(20)]

            title = ""
            date_str = ""
            for line in first_lines:
                if line.startswith('# '):
                    title = line[2:].strip()
                elif line.startswith('> **日期**:'):
                    date_str = line.split(':', 1)[1].strip()

            exp_id = md_file.stem
            output += f"{i}. [{exp_id}] {title or '未命名'}"
            if date_str:
                output += f" ({date_str})"
            output += "\n"
        except Exception as e:
            output += f"{i}. [{md_file.stem}] 读取失败\n"

    output += f"\n共 {len(md_files)} 条经验"
    return [TextContent(type="text", text=output)]


async def handle_experience_get(experience_id: str) -> List[TextContent]:
    """处理 experience_get - 获取经验完整内容"""
    pm = get_persona_manager()
    index = pm.load_index()
    active_persona = index.active_persona

    if not active_persona:
        return [TextContent(type="text", text="当前没有激活的人格。")]

    storage = get_persona_storage_path(active_persona)
    experiences_dir = storage / "experiences"

    # 查找经验文件
    exp_file = experiences_dir / f"{experience_id}.md"

    if not exp_file.exists():
        # 尝试模糊匹配
        matches = list(experiences_dir.glob(f"*{experience_id}*.md"))
        if matches:
            exp_file = matches[0]
        else:
            return [TextContent(type="text", text=f"经验 '{experience_id}' 不存在。\n\n使用 experience_list 查看可用经验。")]

    try:
        with open(exp_file, 'r', encoding='utf-8') as f:
            content = f.read()

        return [TextContent(type="text", text=content)]
    except Exception as e:
        return [TextContent(type="text", text=f"读取经验失败: {e}")]


# ============== 路由处理 ==============

async def handle_tool_call(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
    """路由工具调用"""

    # 人格管理
    if name == "persona_list":
        return await handle_persona_list()
    elif name == "persona_switch":
        return await handle_persona_switch(arguments["persona_id"])
    elif name == "persona_create":
        return await handle_persona_create(
            persona_id=arguments["persona_id"],
            name=arguments["name"],
            description=arguments.get("description", ""),
            abilities=arguments.get("abilities"),
            trigger_keywords=arguments.get("trigger_keywords"),
            system_prompt=arguments.get("system_prompt")
        )
    elif name == "persona_set_memory":
        return await handle_persona_set_memory(
            memory_type=arguments["memory_type"],
            content=arguments["content"]
        )
    elif name == "persona_get_context":
        return await handle_persona_get_context()
    elif name == "persona_delete":
        return await handle_persona_delete(arguments["persona_id"])

    # 会话管理
    elif name == "session_close":
        return await handle_session_close()
    elif name == "session_restore":
        return await handle_session_restore()

    # 记忆管理
    elif name == "memory_save":
        return await handle_memory_save(
            user_message=arguments["user_message"],
            assistant_message=arguments["assistant_message"],
            summary=arguments.get("summary"),
            keywords=arguments.get("keywords"),
            session_id=arguments.get("session_id")
        )
    elif name == "memory_daily_summary":
        return await handle_memory_daily_summary(arguments.get("date"))
    elif name == "memory_recall":
        return await handle_memory_recall(
            query=arguments["query"],
            limit=arguments.get("limit", 5)
        )
    elif name == "memory_recall_by_date":
        return await handle_memory_recall_by_date(
            date_str=arguments["date"],
            session_id=arguments.get("session_id")
        )

    # 经验管理
    elif name == "experience_list":
        return await handle_experience_list(
            limit=arguments.get("limit", 10)
        )
    elif name == "experience_get":
        return await handle_experience_get(
            experience_id=arguments["experience_id"]
        )

    else:
        return [TextContent(type="text", text=f"未知工具: {name}")]


# ============== MCP 服务器入口 ==============

@app.list_tools()
async def list_tools() -> List[Tool]:
    """列出所有可用工具"""
    return get_tools()


@app.call_tool()
async def call_tool(name: str, arguments: Any) -> List[TextContent]:
    """处理工具调用"""
    try:
        return await handle_tool_call(name, arguments or {})
    except Exception as e:
        import traceback
        return [TextContent(
            type="text",
            text=f"工具调用错误: {str(e)}\n\n{traceback.format_exc()}"
        )]


async def main():
    """主入口"""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
