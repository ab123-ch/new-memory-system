"""
Claude Code MCP Server - AI记忆系统 + 多人格支持

使用方式：
1. 安装依赖: pip install mcp pydantic pyyaml
2. 添加到 Claude Code 配置
3. Claude Code 会自动调用记忆功能

v2.0 新功能：
- 向量语义搜索
- AI 驱动的摘要和关键词提取
- 自动对话保存
- Token 统计
"""

import asyncio
import json
from datetime import datetime
from typing import Any, Optional
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# 导入记忆系统
import sys
sys.path.insert(0, str(Path(__file__).parent))

from memory_system import MemorySystem, get_config, reload_config
from memory_system.personas import PersonaManager, PersonaStyle
from memory_system.learning import LearningPipeline, LearningConfig, FeedbackType
from memory_system.skills import SkillManager


# 创建MCP服务器
app = Server("memory-system")

# 全局实例
_memory_system: Optional[MemorySystem] = None
_persona_manager: Optional[PersonaManager] = None
_learning_pipeline: Optional[LearningPipeline] = None
_skill_manager: Optional[SkillManager] = None
_user_id = "default_user"
_current_session = None  # 当前会话


def get_memory_system() -> MemorySystem:
    """获取记忆系统实例"""
    global _memory_system
    if _memory_system is None:
        # 加载配置
        config_path = Path(__file__).parent / "memory_config.yaml"
        if config_path.exists():
            config = reload_config(str(config_path))
        else:
            config = get_config()

        storage_path = Path(__file__).parent / "data" / "memory"
        _memory_system = MemorySystem(str(storage_path), config)
    return _memory_system


def get_persona_manager() -> PersonaManager:
    """获取人格管理器"""
    global _persona_manager
    if _persona_manager is None:
        storage_path = Path(__file__).parent / "data" / "memory"
        _persona_manager = PersonaManager(str(storage_path))

        # 自动恢复上一个会话的人格
        try:
            restore_result = _persona_manager.auto_restore_persona()
            if restore_result.get("restored"):
                print(f"[记忆系统] {restore_result.get('message', '')}")
        except Exception as e:
            print(f"[记忆系统] 自动恢复人格失败: {e}")

    return _persona_manager


def get_learning_pipeline() -> LearningPipeline:
    """获取学习管道实例"""
    global _learning_pipeline
    if _learning_pipeline is None:
        # 获取当前人格的存储路径
        index = get_persona_manager().load_index()
        if index.active_persona:
            storage_path = str(Path(__file__).parent / "data" / "memory" / "personas" / index.active_persona)
        else:
            storage_path = str(Path(__file__).parent / "data" / "memory")
        _learning_pipeline = LearningPipeline(storage_path)
    return _learning_pipeline


def get_skill_manager() -> SkillManager:
    """获取技能管理器实例"""
    global _skill_manager
    if _skill_manager is None:
        # 获取当前人格的存储路径
        index = get_persona_manager().load_index()
        if index.active_persona:
            storage_path = str(Path(__file__).parent / "data" / "memory" / "personas" / index.active_persona)
        else:
            storage_path = str(Path(__file__).parent / "data" / "memory")
        _skill_manager = SkillManager(storage_path)
    return _skill_manager


@app.list_tools()
async def list_tools() -> list[Tool]:
    """列出可用工具"""
    return [
        # ========== 人格管理工具 ==========
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
            description="创建新人格。当用户说'创建一个XX人格'、'新建人格'时调用。",
            inputSchema={
                "type": "object",
                "properties": {
                    "persona_id": {
                        "type": "string",
                        "description": "人格ID（英文，如 work, study）"
                    },
                    "name": {
                        "type": "string",
                        "description": "人格名称（如：工作助手）"
                    },
                    "description": {
                        "type": "string",
                        "description": "人格描述"
                    },
                    "trigger_keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "触发关键词（用于自然语言切换）"
                    },
                    "system_prompt": {
                        "type": "string",
                        "description": "人格专属的系统提示"
                    }
                },
                "required": ["persona_id", "name"]
            }
        ),
        Tool(
            name="persona_set_memory",
            description="设置人格的元记忆。当用户在某个人格下说'记住我是XX'、'我喜欢XX'时调用。",
            inputSchema={
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["identity", "habit", "ability"],
                        "description": "记忆类型"
                    },
                    "content": {
                        "type": "string",
                        "description": "记忆内容"
                    }
                },
                "required": ["type", "content"]
            }
        ),
        Tool(
            name="persona_get_context",
            description="获取当前人格的记忆上下文。包含人格信息、元记忆、共享记忆等。",
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
        Tool(
            name="session_close",
            description="关闭当前会话并保存状态。下次启动时会自动恢复当前人格。在对话结束或需要保存会话状态时调用。",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="session_restore",
            description="手动恢复上一个会话的人格。查看上次关闭会话时使用的人格并切换过去。",
            inputSchema={"type": "object", "properties": {}}
        ),

        # ========== 共享记忆工具 ==========
        Tool(
            name="memory_set_shared",
            description="设置共享记忆（所有人格共用）。当用户说'在所有人格中记住XX'时调用。",
            inputSchema={
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["identity", "knowledge"],
                        "description": "类型：identity(身份) 或 knowledge(知识)"
                    },
                    "content": {
                        "type": "string",
                        "description": "记忆内容"
                    }
                },
                "required": ["type", "content"]
            }
        ),

        # ========== 基础记忆工具 ==========
        Tool(
            name="memory_recall",
            description="召回历史记忆。当用户提到'上次'、'之前'、'那个项目'等需要上下文的内容时调用。默认返回摘要格式以节省上下文，使用 memory_recall_by_id 获取完整内容。",
            inputSchema={
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "要召回的话题或关键词"
                    },
                    "summary_mode": {
                        "type": "boolean",
                        "description": "是否返回摘要格式（默认true，可减少上下文占用）",
                        "default": True
                    }
                },
                "required": ["topic"]
            }
        ),
        Tool(
            name="memory_save",
            description="保存对话到记忆。在重要对话结束后调用。系统会自动保存对话内容、生成摘要和提取关键词。支持保存完整的对话历史，包括工具调用。",
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
                    "tool_calls": {
                        "type": "array",
                        "description": "工具调用列表（可选）",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "name": {"type": "string"},
                                "arguments": {"type": "object"}
                            }
                        }
                    },
                    "tool_results": {
                        "type": "array",
                        "description": "工具结果列表（可选）",
                        "items": {
                            "type": "object",
                            "properties": {
                                "tool_call_id": {"type": "string"},
                                "content": {"type": "string"},
                                "is_error": {"type": "boolean"}
                            }
                        }
                    },
                    "conversation_history": {
                        "type": "array",
                        "description": "完整对话历史（可选，优先使用）",
                        "items": {
                            "type": "object",
                            "properties": {
                                "role": {"type": "string"},
                                "content": {"type": "string"},
                                "tool_calls": {"type": "array"},
                                "tool_results": {"type": "array"}
                            }
                        }
                    }
                },
                "required": ["user_message", "assistant_message"]
            }
        ),
        Tool(
            name="memory_search",
            description="搜索历史记忆。根据关键词查找过去的对话记录。支持语义搜索（如果启用）。默认返回摘要格式以节省上下文。",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词或查询语句"
                    },
                    "days": {
                        "type": "integer",
                        "description": "搜索最近多少天的记忆",
                        "default": 7
                    },
                    "use_semantic": {
                        "type": "boolean",
                        "description": "是否使用语义搜索（需要向量库）",
                        "default": True
                    },
                    "summary_mode": {
                        "type": "boolean",
                        "description": "是否返回摘要格式（默认true，可减少上下文占用）",
                        "default": True
                    }
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="memory_recall_summary",
            description="以摘要格式召回记忆。返回轻量级摘要（≤80字符），包含召回提示。推荐优先使用此工具以减少上下文占用。",
            inputSchema={
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "要召回的话题或关键词"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回数量限制",
                        "default": 10
                    }
                },
                "required": ["topic"]
            }
        ),
        Tool(
            name="memory_search_summary",
            description="以摘要格式搜索记忆。返回轻量级摘要（≤80字符），包含召回提示。推荐优先使用此工具以减少上下文占用。",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词或查询语句"
                    },
                    "days": {
                        "type": "integer",
                        "description": "搜索最近多少天的记忆",
                        "default": 7
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回数量限制",
                        "default": 10
                    }
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="memory_recall_by_id",
            description="通过ID精确召回完整记忆。当需要查看某条记忆的完整内容时调用。使用上下文中的日期和会话ID来获取详细信息。例如：用户说'继续昨晚的bug修复'，先用此工具召回国昨晚的记忆详情，了解具体进度。",
            inputSchema={
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "日期 (如 '2026-02-28')"
                    },
                    "session_id": {
                        "type": "string",
                        "description": "会话ID (如 'sess_005_20260228')"
                    },
                    "conversation_id": {
                        "type": "string",
                        "description": "对话ID (可选，如 'conv_001')。不提供则返回整个会话。",
                        "default": ""
                    }
                },
                "required": ["date", "session_id"]
            }
        ),

        # ========== 风格学习工具 ==========
        Tool(
            name="style_learn_article",
            description="学习文章，提取写作技巧。当用户想要学习一篇文章的写作风格时调用。",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "文章标题"
                    },
                    "content": {
                        "type": "string",
                        "description": "文章内容"
                    },
                    "author": {
                        "type": "string",
                        "description": "作者名（可选）",
                        "default": ""
                    }
                },
                "required": ["title", "content"]
            }
        ),
        Tool(
            name="style_get_techniques",
            description="查询已学习的技巧。支持按类别或场景查询。",
            inputSchema={
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "技巧类别（narrative/pacing/conflict/character/dialogue/atmosphere/structure/wording/emotion/worldbuilding）",
                        "default": ""
                    },
                    "keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "关键词列表",
                        "default": []
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回数量限制",
                        "default": 10
                    }
                }
            }
        ),
        Tool(
            name="style_get_suggestions",
            description="获取写作建议。根据当前创作上下文返回相关的写作技巧建议。",
            inputSchema={
                "type": "object",
                "properties": {
                    "stage": {
                        "type": "string",
                        "description": "创作阶段（opening/development/climax/resolution/dialogue/description/action/flashback）",
                        "default": ""
                    },
                    "keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "关键词列表",
                        "default": []
                    },
                    "scene": {
                        "type": "string",
                        "description": "当前场景描述",
                        "default": ""
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回数量限制",
                        "default": 5
                    }
                }
            }
        ),
        Tool(
            name="style_record_application",
            description="记录技巧应用结果。当用户在实际创作中应用了某个技巧后调用，用于强化记忆。",
            inputSchema={
                "type": "object",
                "properties": {
                    "technique_id": {
                        "type": "string",
                        "description": "技巧ID"
                    },
                    "success_score": {
                        "type": "number",
                        "description": "成功程度（0-1）",
                        "default": 0.5
                    },
                    "context": {
                        "type": "string",
                        "description": "应用场景描述",
                        "default": ""
                    },
                    "feedback": {
                        "type": "string",
                        "description": "反馈说明",
                        "default": ""
                    }
                },
                "required": ["technique_id"]
            }
        ),
        Tool(
            name="style_get_review_list",
            description="获取待复习的技巧列表。基于间隔重复算法返回需要复习的技巧。",
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
            name="style_record_review",
            description="记录技巧复习结果。使用 SM-2 算法调整复习间隔。",
            inputSchema={
                "type": "object",
                "properties": {
                    "technique_id": {
                        "type": "string",
                        "description": "技巧ID"
                    },
                    "quality": {
                        "type": "integer",
                        "description": "复习质量（0-5：0完全不记得，5轻松回忆）",
                        "minimum": 0,
                        "maximum": 5
                    },
                    "notes": {
                        "type": "string",
                        "description": "复习笔记",
                        "default": ""
                    }
                },
                "required": ["technique_id", "quality"]
            }
        ),
        Tool(
            name="style_get_stats",
            description="获取风格学习统计信息。",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="style_apply_decay",
            description="手动触发记忆衰减。对长期未使用的技巧应用遗忘曲线。",
            inputSchema={"type": "object", "properties": {}}
        ),

        # ========== 记忆优化工具 ==========
        Tool(
            name="memory_optimize",
            description="执行记忆优化。包括：知识重组（发现隐藏关联、提取抽象规则）、技能内化（高频模式迁移）、元认知进化（评估思考过程）。当用户说'优化记忆'、'整理记忆'、'重组知识'时调用。",
            inputSchema={
                "type": "object",
                "properties": {
                    "force": {
                        "type": "boolean",
                        "description": "是否强制执行（忽略时间间隔检查）",
                        "default": False
                    },
                    "components": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "指定要执行的组件: reorganization(知识重组), internalization(技能内化), meta_cognition(元认知进化)"
                    }
                }
            }
        ),
        Tool(
            name="memory_optimization_status",
            description="获取记忆优化状态。显示上次优化时间、各组件状态、内化模式数量等。",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="memory_get_quick_response",
            description="获取快速响应。如果有匹配的内化模式（reflex级别），可以直接返回模板响应。",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "用户查询"
                    }
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="memory_get_strategy",
            description="获取推荐策略。基于元认知引擎，为问题推荐最有效的解决策略。",
            inputSchema={
                "type": "object",
                "properties": {
                    "problem": {
                        "type": "string",
                        "description": "问题描述"
                    }
                },
                "required": ["problem"]
            }
        ),

        # ========== 学习系统工具 ==========
        Tool(
            name="learning_feedback_submit",
            description="提交学习反馈。当用户对某个知识/技巧给出评价时调用。",
            inputSchema={
                "type": "object",
                "properties": {
                    "knowledge_id": {
                        "type": "string",
                        "description": "知识/技巧ID"
                    },
                    "score": {
                        "type": "number",
                        "description": "反馈分数 (0-1，0=完全无用，1=非常有用)",
                        "minimum": 0,
                        "maximum": 1
                    },
                    "feedback_type": {
                        "type": "string",
                        "description": "反馈类型",
                        "enum": ["explicit_positive", "explicit_negative", "explicit_rating"],
                        "default": "explicit_rating"
                    },
                    "context": {
                        "type": "string",
                        "description": "上下文描述",
                        "default": ""
                    }
                },
                "required": ["knowledge_id", "score"]
            }
        ),
        Tool(
            name="learning_status",
            description="获取学习系统状态。显示知识统计、反馈数量、高价值知识等。",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="learning_recommend",
            description="获取知识推荐。基于学习历史推荐最相关的知识。",
            inputSchema={
                "type": "object",
                "properties": {
                    "candidates": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "候选知识ID列表（可选，为空则推荐全局高价值知识）",
                        "default": []
                    },
                    "limit": {
                        "type": "integer",
                        "description": "推荐数量限制",
                        "default": 5
                    }
                }
            }
        ),
        Tool(
            name="learning_reflect",
            description="手动触发反思学习。分析历史反馈并生成元规则。",
            inputSchema={"type": "object", "properties": {}}
        ),

        # ========== 技能管理工具 ==========
        Tool(
            name="skill_create",
            description="创建新技能。当用户说'创建一个技能'、'记录技能'时调用。",
            inputSchema={
                "type": "object",
                "properties": {
                    "skill_id": {
                        "type": "string",
                        "description": "技能ID（英文，如 react-hooks, api-design）"
                    },
                    "name": {
                        "type": "string",
                        "description": "技能名称（如：React Hooks 使用）"
                    },
                    "description": {
                        "type": "string",
                        "description": "技能描述"
                    },
                    "trigger_keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "触发关键词"
                    },
                    "file_patterns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "文件模式（可选，如 ['*.tsx', '*.jsx']）"
                    },
                    "context_patterns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "上下文模式（可选）"
                    }
                },
                "required": ["skill_id", "name", "description", "trigger_keywords"]
            }
        ),
        Tool(
            name="skill_list",
            description="列出所有技能。当用户询问有哪些技能时调用。",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="skill_get",
            description="获取技能详情。查看特定技能的经验列表。",
            inputSchema={
                "type": "object",
                "properties": {
                    "skill_id": {
                        "type": "string",
                        "description": "技能ID"
                    }
                },
                "required": ["skill_id"]
            }
        ),
        Tool(
            name="skill_match",
            description="匹配相关技能。根据当前上下文找到相关技能。",
            inputSchema={
                "type": "object",
                "properties": {
                    "context": {
                        "type": "string",
                        "description": "上下文内容"
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "返回最多几个技能",
                        "default": 3
                    }
                },
                "required": ["context"]
            }
        ),
        Tool(
            name="skill_update_quality",
            description="更新技能质量分数。当用户评价技能效果时调用。",
            inputSchema={
                "type": "object",
                "properties": {
                    "skill_id": {
                        "type": "string",
                        "description": "技能ID"
                    },
                    "score": {
                        "type": "number",
                        "description": "质量分数（0-100）",
                        "minimum": 0,
                        "maximum": 100
                    }
                },
                "required": ["skill_id", "score"]
            }
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: Any) -> list[TextContent]:
    """处理工具调用"""
    try:
        pm = get_persona_manager()

        # ========== 人格管理 ==========

        if name == "persona_list":
            personas = pm.list_personas()

            if not personas:
                return [TextContent(
                    type="text",
                    text="当前没有创建任何人格。\n\n"
                         "你可以说：'创建一个工作助手人格' 来创建新人格。"
                )]

            output = "【可用人格】\n\n"
            for p in personas:
                status = " ✓ 当前" if p.get("is_active") else ""
                triggers = ", ".join(p.get("trigger_keywords", []))
                output += f"**{p['name']}** ({p['id']}){status}\n"
                if p.get("description"):
                    output += f"  {p['description']}\n"
                if triggers:
                    output += f"  触发词: {triggers}\n"
                output += "\n"

            output += "---\n"
            output += "切换人格：说 '切换到[人格名]' 或 '用[人格名]模式'\n"
            output += "默认状态：说 '切换到默认' 或 '重置人格'"

            return [TextContent(type="text", text=output)]

        elif name == "persona_switch":
            persona_id = arguments.get("persona_id", "")

            # 查找人格（支持通过名称或ID切换）
            if persona_id and persona_id != "__DEFAULT__":
                index = pm.load_index()

                # 检查是否是精确ID
                if persona_id not in index.personas:
                    # 尝试通过关键词匹配
                    found_id = index.find_by_keyword(persona_id)
                    if found_id:
                        persona_id = found_id
                    else:
                        return [TextContent(
                            type="text",
                            text=f"未找到人格 '{persona_id}'。\n\n"
                                 f"可用的人格：{', '.join(p['name'] for p in pm.list_personas())}"
                        )]

            result = pm.switch_persona(persona_id if persona_id else None)

            if result["success"]:
                info = result.get("persona_info", {})
                if result["current_persona"]:
                    return [TextContent(
                        type="text",
                        text=f"已切换到「{info.get('name')}」人格\n\n"
                             f"{info.get('description', '')}\n\n"
                             f"风格: {info.get('style', {})}"
                    )]
                else:
                    return [TextContent(
                        type="text",
                        text="已切换到默认状态（无人格）"
                    )]
            else:
                return [TextContent(type="text", text=f"切换失败: {result.get('error')}")]

        elif name == "persona_create":
            persona_id = arguments["persona_id"]
            name_str = arguments["name"]
            description = arguments.get("description", "")
            trigger_keywords = arguments.get("trigger_keywords", [name_str])
            system_prompt = arguments.get("system_prompt", "")

            # 检查是否已存在
            existing = pm.load_persona_config(persona_id)
            if existing:
                return [TextContent(
                    type="text",
                    text=f"人格 '{persona_id}' 已存在。请使用其他ID。"
                )]

            config = pm.create_persona(
                persona_id=persona_id,
                name=name_str,
                description=description,
                trigger_keywords=trigger_keywords,
                system_prompt=system_prompt
            )

            return [TextContent(
                type="text",
                text=f"已创建人格「{name_str}」({persona_id})\n\n"
                     f"描述: {description}\n"
                     f"触发词: {', '.join(trigger_keywords)}\n\n"
                     f"切换到此人格：说 '切换到{name_str}' 或 '用{trigger_keywords[0] if trigger_keywords else name_str}模式'"
            )]

        elif name == "persona_set_memory":
            index = pm.load_index()

            if not index.active_persona:
                return [TextContent(
                    type="text",
                    text="当前没有激活的人格。请先切换到一个人格。\n\n"
                         "说 '切换到[人格名]' 来激活一个人格。"
                )]

            memory_type = arguments["type"]
            content = arguments["content"]

            soul = pm.load_persona_soul(index.active_persona)

            memory_item = {
                "id": f"{memory_type[:3]}_{len(getattr(soul, memory_type + 's', [])):03d}",
                "content": content,
                "confirmed": True,
                "created_at": datetime.now().isoformat()
            }

            if memory_type == "identity":
                soul.identity.append(memory_item)
            elif memory_type == "habit":
                soul.habits.append(memory_item)
            elif memory_type == "ability":
                soul.abilities.append(memory_item)

            pm.save_persona_soul(soul)

            type_names = {"identity": "身份", "habit": "习惯", "ability": "能力"}
            config = pm.load_persona_config(index.active_persona)

            return [TextContent(
                type="text",
                text=f"已在「{config.name}」人格中记录{type_names.get(memory_type, memory_type)}: {content}"
            )]

        elif name == "persona_get_context":
            context = pm.get_memory_context()

            output = "【当前记忆上下文】\n\n"

            if context["persona"]:
                output += f"人格: {context['persona']['name']}\n"
                output += f"描述: {context['persona']['description']}\n\n"

                if context["soul"]:
                    if context["soul"]["identity"]:
                        output += "身份: " + ", ".join(context["soul"]["identity"]) + "\n"
                    if context["soul"]["habits"]:
                        output += "习惯: " + ", ".join(context["soul"]["habits"]) + "\n"
                    if context["soul"]["abilities"]:
                        output += "能力: " + ", ".join(context["soul"]["abilities"]) + "\n"
            else:
                output += "当前状态: 默认（无人格）\n\n"

            if context["shared"]:
                output += "\n【共享记忆】\n"
                if context["shared"]["identity"]:
                    output += "共享身份: " + ", ".join(context["shared"]["identity"]) + "\n"
                if context["shared"]["knowledge"]:
                    output += "共享知识: " + ", ".join(context["shared"]["knowledge"][:3]) + "\n"

            return [TextContent(type="text", text=output)]

        elif name == "persona_delete":
            persona_id = arguments["persona_id"]

            config = pm.load_persona_config(persona_id)
            if not config:
                return [TextContent(type="text", text=f"人格 '{persona_id}' 不存在")]

            pm.delete_persona(persona_id)

            return [TextContent(
                type="text",
                text=f"已删除人格「{config.name}」({persona_id})"
            )]

        # ========== 会话管理 ==========

        elif name == "session_close":
            # 获取当前人格信息
            index = pm.load_index()
            current_persona = index.active_persona
            persona_name = "默认状态"

            if current_persona:
                config = pm.load_persona_config(current_persona)
                if config:
                    persona_name = config.name

            # 关闭会话
            success = pm.close_session()

            if success:
                output = f"✓ 会话已关闭并保存状态\n"
                output += f"  当前人格: {persona_name}\n"
                output += f"  下次启动将自动恢复到此人格"
            else:
                output = "没有活动的会话需要关闭"

            return [TextContent(type="text", text=output)]

        elif name == "session_restore":
            # 获取上一个会话信息
            last_session = pm.get_last_session_persona()

            if not last_session:
                return [TextContent(
                    type="text",
                    text="没有找到上一个会话的记录。\n\n"
                         "这是首次使用，或者之前的会话没有保存状态。"
                )]

            persona_id = last_session.get("persona_id")
            persona_name = last_session.get("persona_name", "未知")
            closed_at = last_session.get("closed_at", "")

            if not persona_id:
                return [TextContent(
                    type="text",
                    text=f"上一个会话使用的是「默认状态」（无人格）\n"
                         f"关闭时间: {closed_at}"
                )]

            # 执行恢复
            result = pm.auto_restore_persona()

            if result.get("success") and result.get("restored"):
                output = f"✓ 已恢复到上一次会话的人格\n"
                output += f"  人格: {persona_name}\n"
                output += f"  上次关闭: {closed_at}"
            else:
                output = result.get("message", "恢复失败")

            return [TextContent(type="text", text=output)]

        # ========== 共享记忆 ==========

        elif name == "memory_set_shared":
            memory_type = arguments["type"]
            content = arguments["content"]

            shared = pm.load_shared_memory()

            if memory_type == "identity":
                shared.add_shared_identity(content)
            elif memory_type == "knowledge":
                shared.add_shared_knowledge(content)

            pm.save_shared_memory(shared)

            type_names = {"identity": "身份", "knowledge": "知识"}
            return [TextContent(
                type="text",
                text=f"已添加共享{type_names.get(memory_type, memory_type)}（所有人格可见）: {content}"
            )]

        # ========== 基础记忆 ==========

        elif name == "memory_recall":
            system = get_memory_system()
            pm_local = get_persona_manager()
            index = pm_local.load_index()
            topic = arguments["topic"]
            summary_mode = arguments.get("summary_mode", True)

            # 根据当前人格决定召回范围
            if index.active_persona:
                # 召回人格专属记忆
                memories = pm_local._load_persona_recent_memories(index.active_persona, 7)

                # 简单匹配
                matched = []
                for m in memories:
                    if topic.lower() in m.get("summary", "").lower():
                        matched.append(m)

                if matched:
                    if summary_mode:
                        # 摘要模式
                        from memory_system.extraction import get_summary_cache
                        cache = get_summary_cache()
                        entries = []
                        for m in matched[:5]:
                            entry = cache.create_summary(
                                date=m.get("date", ""),
                                session_id=m.get("session_id", ""),
                                role="summary",
                                content=m.get("summary", "")
                            )
                            entries.append(entry)
                        output = cache.format_summary_output(entries, topic)
                    else:
                        # 完整模式
                        output = f"在当前人格中找到关于 '{topic}' 的记忆：\n\n"
                        for m in matched[:5]:
                            output += f"[{m['date']}] {m['summary'][:100]}\n"
                else:
                    output = f"在当前人格中没有找到关于 '{topic}' 的记忆"
            else:
                # 默认召回 - 使用增强搜索
                results = await system.search(topic, 7, use_semantic=True)

                if results:
                    if summary_mode:
                        # 摘要模式
                        from memory_system.extraction import get_summary_cache
                        cache = get_summary_cache()
                        entries = []
                        for r in results[:5]:
                            entry = cache.create_summary(
                                date=r.get("date", ""),
                                session_id=r.get("session_id", ""),
                                role=r.get("role", ""),
                                content=r.get("content", "")
                            )
                            entries.append(entry)
                        output = cache.format_summary_output(entries, topic)
                    else:
                        # 完整模式
                        output = f"搜索 '{topic}' 的结果：\n\n"
                        for r in results[:5]:
                            source_hint = " [语义]" if r.get("type") == "semantic" else ""
                            output += f"[{r.get('date')}]{source_hint} {r.get('content', '')[:100]}...\n"
                else:
                    output = f"没有找到关于 '{topic}' 的记忆"

            return [TextContent(type="text", text=output)]

        elif name == "memory_save":
            # 实现 memory_save 的实际保存逻辑
            user_message = arguments["user_message"]
            assistant_message = arguments["assistant_message"]
            # 新增参数
            tool_calls = arguments.get("tool_calls", [])
            tool_results = arguments.get("tool_results", [])
            conversation_history = arguments.get("conversation_history", None)

            try:
                # 获取当前人格，决定存储路径
                pm_local = get_persona_manager()
                index = pm_local.load_index()
                active_persona = index.active_persona

                if active_persona:
                    # 保存到人格专属目录
                    persona_storage_path = str(Path(__file__).parent / "data" / "memory" / "personas" / active_persona)
                    persona_system = MemorySystem(persona_storage_path, get_config())

                    # 优先使用完整对话历史
                    if conversation_history:
                        result = await persona_system.save_conversation_history(
                            messages=conversation_history,
                            user_id=_user_id
                        )
                    else:
                        # 使用扩展接口保存（含工具调用）
                        result = await persona_system.save_conversation(
                            user_message=user_message,
                            assistant_message=assistant_message,
                            user_id=_user_id,
                            tool_calls=tool_calls,
                            tool_results=tool_results
                        )

                    # 获取人格名称用于显示
                    config = pm_local.load_persona_config(active_persona)
                    persona_name = config.name if config else active_persona
                    result["persona"] = persona_name
                else:
                    # 保存到全局目录
                    system = get_memory_system()

                    # 优先使用完整对话历史
                    if conversation_history:
                        result = await system.save_conversation_history(
                            messages=conversation_history,
                            user_id=_user_id
                        )
                    else:
                        # 使用扩展接口保存（含工具调用）
                        result = await system.save_conversation(
                            user_message=user_message,
                            assistant_message=assistant_message,
                            user_id=_user_id,
                            tool_calls=tool_calls,
                            tool_results=tool_results
                        )
                    result["persona"] = None

                if result.get("success"):
                    output = f"✓ 对话已保存\n"
                    output += f"  会话ID: {result.get('session_id', 'unknown')}\n"
                    output += f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"

                    # 显示人格信息
                    if result.get("persona"):
                        output += f"  人格: {result['persona']}\n"

                    # 显示配置状态
                    config = get_config()
                    features = []
                    if config.ai.enabled:
                        features.append("AI摘要")
                    if config.vector.enabled:
                        features.append("向量索引")
                    if config.auto_save.enabled:
                        features.append("自动保存")

                    if features:
                        output += f"  已启用: {', '.join(features)}"
                else:
                    output = "保存失败"

                return [TextContent(type="text", text=output)]

            except Exception as e:
                import traceback
                return [TextContent(
                    type="text",
                    text=f"保存对话时出错: {str(e)}\n\n{traceback.format_exc()}"
                )]

        elif name == "memory_search":
            query = arguments["query"]
            days = arguments.get("days", 7)
            use_semantic = arguments.get("use_semantic", True)
            summary_mode = arguments.get("summary_mode", True)

            # 获取当前人格，搜索人格专属记忆
            index = pm.load_index()
            active_persona = index.active_persona

            if active_persona:
                # 搜索人格专属记忆
                persona_storage_path = str(Path(__file__).parent / "data" / "memory" / "personas" / active_persona)
                persona_system = MemorySystem(persona_storage_path, get_config())
                results = await persona_system.search(query, days, use_semantic)
            else:
                # 搜索全局记忆
                system = get_memory_system()
                results = await system.search(query, days, use_semantic)

            if results:
                if summary_mode:
                    # 摘要模式
                    from memory_system.extraction import get_summary_cache
                    cache = get_summary_cache()
                    entries = []
                    for r in results[:10]:
                        entry = cache.create_summary(
                            date=r.get("date", ""),
                            session_id=r.get("session_id", ""),
                            role=r.get("role", ""),
                            content=r.get("content", "")
                        )
                        entries.append(entry)
                    output = cache.format_summary_output(entries, query)
                else:
                    # 完整模式
                    output = f"搜索 '{query}' 的结果 ({len(results)}条):\n\n"
                    for r in results[:10]:
                        source = r.get("type", "keyword")
                        source_hint = " [语义]" if source == "semantic" else ""
                        role = r.get("role", "")
                        role_hint = f"[{role}] " if role and role != "summary" else ""
                        output += f"[{r.get('date')}]{source_hint} {role_hint}{r.get('content', '')[:100]}...\n\n"
            else:
                output = f"没有找到 '{query}' 相关的记忆"

            return [TextContent(type="text", text=output)]

        elif name == "memory_recall_summary":
            """以摘要格式召回记忆"""
            from memory_system.extraction import get_summary_cache

            topic = arguments["topic"]
            limit = arguments.get("limit", 10)

            system = get_memory_system()
            pm_local = get_persona_manager()
            index = pm_local.load_index()

            # 根据当前人格决定召回范围
            if index.active_persona:
                memories = pm_local._load_persona_recent_memories(index.active_persona, 7)
                matched = []
                for m in memories:
                    if topic.lower() in m.get("summary", "").lower():
                        matched.append(m)
                results = matched[:limit]
            else:
                results = await system.search(topic, 7, use_semantic=True)
                results = results[:limit]

            if results:
                cache = get_summary_cache()
                entries = []
                for r in results:
                    entry = cache.create_summary(
                        date=r.get("date", ""),
                        session_id=r.get("session_id", ""),
                        role=r.get("role", "summary"),
                        content=r.get("content", "") or r.get("summary", "")
                    )
                    entries.append(entry)
                output = cache.format_summary_output(entries, topic)
            else:
                output = f"没有找到关于 '{topic}' 的记忆"

            return [TextContent(type="text", text=output)]

        elif name == "memory_search_summary":
            """以摘要格式搜索记忆"""
            from memory_system.extraction import get_summary_cache

            query = arguments["query"]
            days = arguments.get("days", 7)
            limit = arguments.get("limit", 10)

            # 获取当前人格
            index = pm.load_index()
            active_persona = index.active_persona

            if active_persona:
                persona_storage_path = str(Path(__file__).parent / "data" / "memory" / "personas" / active_persona)
                persona_system = MemorySystem(persona_storage_path, get_config())
                results = await persona_system.search(query, days, use_semantic=True)
            else:
                system = get_memory_system()
                results = await system.search(query, days, use_semantic=True)

            if results:
                cache = get_summary_cache()
                entries = []
                for r in results[:limit]:
                    entry = cache.create_summary(
                        date=r.get("date", ""),
                        session_id=r.get("session_id", ""),
                        role=r.get("role", ""),
                        content=r.get("content", "")
                    )
                    entries.append(entry)
                output = cache.format_summary_output(entries, query)
            else:
                output = f"没有找到 '{query}' 相关的记忆"

            return [TextContent(type="text", text=output)]

        elif name == "memory_recall_by_id":
            from memory_system.core import MemoryRecaller

            date_str = arguments["date"]
            session_id = arguments["session_id"]
            conversation_id = arguments.get("conversation_id", "")

            # 获取当前人格的存储路径
            index = pm.load_index()
            if index.active_persona:
                storage_path = str(Path(__file__).parent / "data" / "memory" / "personas" / index.active_persona)
            else:
                storage_path = str(Path(__file__).parent / "data" / "memory")

            # 使用 MemoryRecaller 召回
            recaller = MemoryRecaller(storage_path)
            result = recaller.recall_by_id(date_str, session_id, conversation_id if conversation_id else None)

            if not result.get("success"):
                return [TextContent(
                    type="text",
                    text=f"召回失败: {result.get('error', '未知错误')}"
                )]

            # 如果只返回单条对话
            if conversation_id and "conversation_id" in result:
                output = f"【记忆详情】\n\n"
                output += f"日期: {result['date']}\n"
                output += f"会话: {result['session_id']}\n"
                output += f"对话ID: {result['conversation_id']}\n"
                output += f"角色: {result['role']}\n"
                output += f"时间: {result.get('timestamp', '')}\n\n"
                output += f"--- 内容 ---\n{result['content']}\n"
                return [TextContent(type="text", text=output)]

            # 返回整个会话
            output = f"【会话记忆详情】\n\n"
            output += f"日期: {result['date']}\n"
            output += f"会话ID: {result['session_id']}\n"
            output += f"开始时间: {result.get('started_at', '')}\n\n"

            if result.get('summary'):
                output += f"摘要: {result['summary']}\n\n"

            if result.get('keywords'):
                kw_str = ", ".join([f"{kw['word']}({kw['weight']:.1f})" for kw in result['keywords'][:5]])
                output += f"关键词: {kw_str}\n\n"

            output += "--- 完整对话 ---\n\n"
            for conv in result.get('conversations', []):
                role_name = "用户" if conv['role'] == 'user' else "助手"
                timestamp = conv.get('timestamp', '')[11:19]  # 只取时间部分
                content = conv['content']
                # 截断过长的内容
                if len(content) > 500:
                    content = content[:500] + "..."
                output += f"[{timestamp}] {role_name}：{content}\n\n"

            output += f"\n--- 召回ID ---\n"
            output += f"日期: {result['date']}\n"
            output += f"会话: {result['session_id']}\n"

            return [TextContent(type="text", text=output)]

        # ========== 风格学习工具 ==========

        elif name == "style_learn_article":
            from memory_system.style_learning import ArticleLearner

            # 获取当前人格
            index = pm.load_index()
            if not index.active_persona:
                return [TextContent(
                    type="text",
                    text="请先切换到一个创作人格后再学习文章。\n\n"
                         "例如：'切换到滚开' 或 '用网文创作模式'"
                )]

            title = arguments["title"]
            content = arguments["content"]
            author = arguments.get("author", "")

            try:
                # 加载风格记忆
                memory = pm.load_style_memory(index.active_persona)

                # 学习文章
                learner = ArticleLearner()
                result = learner.learn_article(memory, title, content, author)

                # 保存
                if result.get("success"):
                    pm.save_style_memory(memory)

                    output = f"✓ 文章学习完成\n\n"
                    output += f"标题: {title}\n"
                    output += f"提取技巧: {result.get('techniques_count', 0)} 个\n"

                    # 安全处理 categories_covered（可能是字典或列表）
                    categories = result.get('categories_covered', {})
                    if isinstance(categories, dict):
                        output += f"覆盖类别: {', '.join(categories.keys())}\n\n"
                    elif isinstance(categories, list):
                        output += f"覆盖类别: {', '.join(categories)}\n\n"

                    if result.get("techniques"):
                        output += "【提取的技巧】\n"
                        for tech in result.get("techniques", [])[:5]:
                            output += f"- [{tech['category']}] {tech['principle'][:80]}...\n"
                else:
                    output = f"学习失败: {result.get('error', '未知错误')}"

            except Exception as e:
                import traceback
                output = f"学习失败: {str(e)}\n\n{traceback.format_exc()}"

            return [TextContent(type="text", text=output)]

        elif name == "style_get_techniques":
            from memory_system.style_learning import TechniqueRetriever, KnowledgeCategory

            # 获取当前人格
            index = pm.load_index()
            if not index.active_persona:
                return [TextContent(
                    type="text",
                    text="请先切换到一个创作人格。"
                )]

            memory = pm.load_style_memory(index.active_persona)

            if not memory.techniques:
                return [TextContent(
                    type="text",
                    text="当前人格还没有学习任何技巧。\n\n"
                         "使用 style_learn_article 学习文章来获取写作技巧。"
                )]

            # 初始化检索器
            retriever = TechniqueRetriever()
            retriever.initialize(memory)

            category = arguments.get("category", "")
            keywords = arguments.get("keywords", [])
            limit = arguments.get("limit", 10)

            if category:
                # 按类别查询
                try:
                    cat = KnowledgeCategory(category.lower())
                    suggestions = retriever.retrieve_by_category(cat, limit)
                except ValueError:
                    suggestions = []
                    output = f"无效的类别: {category}\n"
                    output += f"有效类别: narrative, pacing, conflict, character, dialogue, atmosphere, structure, wording, emotion, worldbuilding"
                    return [TextContent(type="text", text=output)]
            elif keywords:
                # 按关键词查询
                suggestions = retriever.retrieve_by_keywords(keywords, limit)
            else:
                # 返回所有
                suggestions = retriever.get_top_techniques("applications", limit)

            if suggestions:
                output = f"【写作技巧】\n\n"
                for s in suggestions:
                    output += f"**{s['category_display']}** (ID: {s['id'][:12]}...)\n"
                    output += f"  原理: {s['principle'][:100]}{'...' if len(s['principle']) > 100 else ''}\n"
                    if s['examples']:
                        output += f"  示例: {s['examples'][0][:60]}...\n"
                    output += f"  应用次数: {s['application_count']} | 相关度: {s['relevance_score']:.2f}\n\n"
            else:
                output = "没有找到匹配的技巧"

            return [TextContent(type="text", text=output)]

        elif name == "style_get_suggestions":
            from memory_system.style_learning import TechniqueRetriever

            # 获取当前人格
            index = pm.load_index()
            if not index.active_persona:
                return [TextContent(
                    type="text",
                    text="请先切换到一个创作人格。"
                )]

            memory = pm.load_style_memory(index.active_persona)

            if not memory.techniques:
                return [TextContent(
                    type="text",
                    text="当前人格还没有学习任何技巧。"
                )]

            # 初始化检索器
            retriever = TechniqueRetriever()
            retriever.initialize(memory)

            # 构建上下文
            context = {
                "stage": arguments.get("stage", ""),
                "keywords": arguments.get("keywords", []),
                "scene": arguments.get("scene", "")
            }
            limit = arguments.get("limit", 5)

            suggestions = retriever.retrieve_for_context(context, limit)

            if suggestions:
                output = "【写作建议】\n\n"

                for i, s in enumerate(suggestions, 1):
                    output += f"### 建议 {i}: {s['category_display']}\n"
                    output += f"**原理**: {s['principle']}\n"

                    if s['examples']:
                        output += f"**示例**: {s['examples'][0]}\n"

                    if s['scenarios']:
                        output += f"**适用场景**: {', '.join(s['scenarios'][:2])}\n"

                    output += f"**相关度**: {s['relevance_score']:.2f}\n\n"

                # 生成注入提示
                injection = retriever.generate_context_prompt(context, limit)
                if injection:
                    output += "---\n"
                    output += "【可直接注入的提示】\n```\n" + injection + "\n```"
            else:
                output = "没有找到相关的写作建议。\n\n"
                output += "提示: 尝试提供更多上下文信息（阶段、关键词、场景）"

            return [TextContent(type="text", text=output)]

        elif name == "style_record_application":
            from memory_system.style_learning import TechniqueApplication

            # 获取当前人格
            index = pm.load_index()
            if not index.active_persona:
                return [TextContent(
                    type="text",
                    text="请先切换到一个创作人格。"
                )]

            technique_id = arguments["technique_id"]
            success_score = arguments.get("success_score", 0.5)
            context_desc = arguments.get("context", "")
            feedback = arguments.get("feedback", "")

            memory = pm.load_style_memory(index.active_persona)

            # 创建应用记录
            application = TechniqueApplication(
                context=context_desc,
                success_score=success_score,
                feedback=feedback
            )

            # 记录应用
            success = memory.record_application(technique_id, application)

            if success:
                pm.save_style_memory(memory)

                technique = memory.get_technique(technique_id)
                output = f"✓ 已记录技巧应用\n\n"
                output += f"技巧: {technique.principle[:50]}... \n"
                output += f"成功程度: {success_score:.1f}\n"
                output += f"累计应用: {technique.application_count} 次\n"
                output += f"成功应用: {technique.successful_applications} 次"
            else:
                output = f"技巧 '{technique_id}' 不存在"

            return [TextContent(type="text", text=output)]

        elif name == "style_get_review_list":
            from memory_system.style_learning import SpacedRepetitionScheduler

            # 获取当前人格
            index = pm.load_index()
            if not index.active_persona:
                return [TextContent(
                    type="text",
                    text="请先切换到一个创作人格。"
                )]

            limit = arguments.get("limit", 10)

            memory = pm.load_style_memory(index.active_persona)

            if not memory.techniques:
                return [TextContent(
                    type="text",
                    text="当前人格还没有学习任何技巧。"
                )]

            # 获取复习列表
            scheduler = SpacedRepetitionScheduler()
            review_list = scheduler.get_review_list(memory, limit)

            if review_list:
                output = "【待复习技巧】\n\n"

                for i, item in enumerate(review_list, 1):
                    output += f"### {i}. {item['id'][:12]}...\n"
                    output += f"**类别**: {item['category']}\n"
                    output += f"**原理**: {item['principle'][:80]}...\n"
                    output += f"**可检索性**: {item['retrievability']:.2f}\n"
                    output += f"**优先级**: {item['priority']}\n\n"

                    if item.get('examples'):
                        output += f"示例: {item['examples'][0][:60]}...\n\n"

                output += "---\n"
                output += "使用 style_record_review 记录复习结果（质量 0-5）"
            else:
                output = "当前没有需要复习的技巧 🎉"

            return [TextContent(type="text", text=output)]

        elif name == "style_record_review":
            from memory_system.style_learning import SpacedRepetitionScheduler

            # 获取当前人格
            index = pm.load_index()
            if not index.active_persona:
                return [TextContent(
                    type="text",
                    text="请先切换到一个创作人格。"
                )]

            technique_id = arguments["technique_id"]
            quality = arguments["quality"]
            notes = arguments.get("notes", "")

            memory = pm.load_style_memory(index.active_persona)

            # 记录复习
            scheduler = SpacedRepetitionScheduler()
            result = scheduler.record_review(memory, technique_id, quality, notes)

            if result.get("success"):
                pm.save_style_memory(memory)

                output = f"✓ 复习已记录\n\n"
                output += f"技巧ID: {technique_id[:12]}...\n"
                output += f"复习质量: {quality}/5\n"
                output += f"新难度因子: {result['new_easiness_factor']:.2f}\n"
                output += f"下次复习: {result['new_interval_days']} 天后\n"
                output += f"当前强度: {result['strength']}"
            else:
                output = f"复习记录失败: {result.get('error', '未知错误')}"

            return [TextContent(type="text", text=output)]

        elif name == "style_get_stats":
            # 获取当前人格
            index = pm.load_index()

            if not index.active_persona:
                return [TextContent(
                    type="text",
                    text="请先切换到一个创作人格。"
                )]

            stats = pm.get_style_learning_stats(index.active_persona)

            output = "【风格学习统计】\n\n"
            output += f"学习文章: {stats.get('total_articles', 0)} 篇\n"
            output += f"总技巧数: {stats.get('total_techniques', 0)} 个\n"
            output += f"归档技巧: {stats.get('archived_techniques', 0)} 个\n"
            output += f"总应用次数: {stats.get('total_applications', 0)} 次\n"
            output += f"总复习次数: {stats.get('total_reviews', 0)} 次\n\n"

            category_dist = stats.get("category_distribution", {})
            if category_dist:
                output += "【类别分布】\n"
                for cat, count in sorted(category_dist.items(), key=lambda x: x[1], reverse=True):
                    output += f"  {cat}: {count}\n"

            recent = stats.get("recent_learning", [])
            if recent:
                output += "\n【最近学习】\n"
                for r in recent[:3]:
                    output += f"  - {r['title']} ({r['techniques_count']} 个技巧)\n"

            return [TextContent(type="text", text=output)]

        elif name == "style_apply_decay":
            # 获取当前人格
            index = pm.load_index()

            if not index.active_persona:
                return [TextContent(
                    type="text",
                    text="请先切换到一个创作人格。"
                )]

            result = pm.apply_style_memory_decay(index.active_persona, auto_save=True)
            stats = result.get("stats", {})

            output = "【记忆衰减完成】\n\n"
            output += f"处理技巧: {stats.get('techniques_processed', 0)} 个\n"
            output += f"降级技巧: {stats.get('techniques_decayed', 0)} 个\n"
            output += f"归档技巧: {stats.get('techniques_archived', 0)} 个\n"

            strength_changes = stats.get("strength_changes", {})
            if strength_changes:
                output += "\n【强度变化】\n"
                for change, count in strength_changes.items():
                    output += f"  {change}: {count} 个\n"

            archived_ids = stats.get("archived_ids", [])
            if archived_ids:
                output += f"\n已归档ID: {', '.join(archived_ids[:5])}{'...' if len(archived_ids) > 5 else ''}"

            return [TextContent(type="text", text=output)]

        # ========== 记忆优化工具 ==========

        elif name == "memory_optimize":
            from memory_system.optimization import MemoryOptimizer

            # 获取当前人格的存储路径
            index = pm.load_index()
            if index.active_persona:
                storage_path = str(Path(__file__).parent / "data" / "memory" / "personas" / index.active_persona)
            else:
                storage_path = str(Path(__file__).parent / "data" / "memory")

            optimizer = MemoryOptimizer(storage_path)

            force = arguments.get("force", False)
            components = arguments.get("components")

            result = optimizer.optimize(force=force, components=components)

            if result.get("skipped"):
                return [TextContent(
                    type="text",
                    text=f"优化已跳过: {result.get('reason')}\n\n使用 force=true 强制执行。"
                )]

            output = "【记忆优化完成】\n\n"
            output += f"执行时间: {result.get('started_at', '')}\n"
            output += f"耗时: {result.get('duration_seconds', 0):.1f}秒\n"
            output += f"执行组件: {', '.join(result.get('components_run', []))}\n\n"

            # 知识重组结果
            reorg = result.get("results", {}).get("reorganization", {})
            if reorg and not reorg.get("error"):
                output += "【知识重组】\n"
                output += f"  处理记忆: {reorg.get('memories_processed', 0)} 条\n"
                output += f"  发现聚类: {reorg.get('clusters_found', 0)} 个\n"
                output += f"  提取规则: {reorg.get('rules_extracted', 0)} 条\n\n"

            # 技能内化结果
            intern = result.get("results", {}).get("internalization", {})
            if intern and not intern.get("error"):
                output += "【技能内化】\n"
                output += f"  分析模式: {intern.get('patterns_analyzed', 0)} 个\n"
                output += f"  新增模式: {intern.get('new_patterns', 0)} 个\n"
                output += f"  反射模式: {intern.get('reflex_patterns', 0)} 个\n\n"

            # 元认知进化结果
            meta = result.get("results", {}).get("meta_cognition", {})
            if meta and not meta.get("error"):
                output += "【元认知进化】\n"
                l2 = meta.get("level_2", {})
                l3 = meta.get("level_3", {})
                output += f"  提取策略: {l2.get('strategies_extracted', 0)} 个\n"
                output += f"  有效策略: {l3.get('effective_strategies', 0)} 个\n"
                suggestions = l3.get("optimization_suggestions", [])
                if suggestions:
                    output += f"  优化建议: {len(suggestions)} 条\n"

            return [TextContent(type="text", text=output)]

        elif name == "memory_optimization_status":
            from memory_system.optimization import MemoryOptimizer

            # 获取当前人格的存储路径
            index = pm.load_index()
            if index.active_persona:
                storage_path = str(Path(__file__).parent / "data" / "memory" / "personas" / index.active_persona)
            else:
                storage_path = str(Path(__file__).parent / "data" / "memory")

            optimizer = MemoryOptimizer(storage_path)
            status = optimizer.get_optimization_status()

            output = "【记忆优化状态】\n\n"
            output += f"记忆总数: {status.get('memory_count', 0)} 条\n"
            output += f"上次优化: {status.get('last_optimization') or '从未'}\n\n"

            # 各组件状态
            components = status.get("components", {})

            # 知识重组
            reorg = components.get("reorganization", {})
            if reorg:
                output += "【知识重组】\n"
                output += f"  抽象规则: {len(reorg.get('abstract_rules', []))} 条\n"
                output += f"  聚类数量: {reorg.get('cluster_count', 0)} 个\n\n"

            # 技能内化
            intern = components.get("internalization", {})
            if intern:
                output += "【技能内化】\n"
                output += f"  总模式: {intern.get('total_patterns', 0)} 个\n"
                by_level = intern.get("by_level", {})
                output += f"  显式(explicit): {by_level.get('explicit', 0)} 个\n"
                output += f"  模式(pattern): {by_level.get('pattern', 0)} 个\n"
                output += f"  反射(reflex): {by_level.get('reflex', 0)} 个\n\n"

            # 元认知
            meta = components.get("meta_cognition", {})
            if meta:
                output += "【元认知】\n"
                output += f"  思考轨迹: {meta.get('total_traces', 0)} 条\n"
                output += f"  总策略: {meta.get('total_strategies', 0)} 个\n"
                output += f"  有效策略: {meta.get('effective_strategies', 0)} 个\n"

            return [TextContent(type="text", text=output)]

        elif name == "memory_get_quick_response":
            from memory_system.optimization import MemoryOptimizer

            query = arguments["query"]

            # 获取当前人格的存储路径
            index = pm.load_index()
            if index.active_persona:
                storage_path = str(Path(__file__).parent / "data" / "memory" / "personas" / index.active_persona)
            else:
                storage_path = str(Path(__file__).parent / "data" / "memory")

            optimizer = MemoryOptimizer(storage_path)
            result = optimizer.get_quick_response(query)

            if result:
                level_emoji = {"reflex": "⚡", "pattern": "🔄"}
                output = f"【快速响应 - {level_emoji.get(result['level'], '')}{result['level']}】\n\n"
                output += f"置信度: {result.get('confidence', 0):.0%}\n\n"
                if result["level"] == "reflex":
                    output += f"模板:\n{result.get('template', '')}\n"
                else:
                    output += f"提示: {result.get('hint', '')}\n"
                return [TextContent(type="text", text=output)]
            else:
                return [TextContent(
                    type="text",
                    text="没有找到匹配的内化模式。\n\n这可能是一个新的问题类型，需要完整推理。"
                )]

        elif name == "memory_get_strategy":
            from memory_system.optimization import MemoryOptimizer

            problem = arguments["problem"]

            # 获取当前人格的存储路径
            index = pm.load_index()
            if index.active_persona:
                storage_path = str(Path(__file__).parent / "data" / "memory" / "personas" / index.active_persona)
            else:
                storage_path = str(Path(__file__).parent / "data" / "memory")

            optimizer = MemoryOptimizer(storage_path)
            result = optimizer.get_recommended_strategy(problem)

            if result:
                output = "【推荐策略】\n\n"
                output += f"名称: {result.get('name', '')}\n"
                output += f"有效性: {result.get('effectiveness', 0):.0%}\n"
                output += f"使用次数: {result.get('usage_count', 0)} 次\n\n"
                output += f"描述:\n{result.get('description', '')}\n"
                return [TextContent(type="text", text=output)]
            else:
                return [TextContent(
                    type="text",
                    text="没有找到匹配的策略。\n\n这可能是一个新的问题类型。"
                )]

        # ========== 学习系统工具 ==========

        elif name == "learning_feedback_submit":
            pipeline = get_learning_pipeline()
            knowledge_id = arguments["knowledge_id"]
            score = arguments["score"]
            feedback_type_str = arguments.get("feedback_type", "explicit_rating")
            context = arguments.get("context", "")

            # 转换反馈类型
            feedback_type_map = {
                "explicit_positive": FeedbackType.EXPLICIT_POSITIVE,
                "explicit_negative": FeedbackType.EXPLICIT_NEGATIVE,
                "explicit_rating": FeedbackType.EXPLICIT_RATING
            }
            feedback_type = feedback_type_map.get(feedback_type_str, FeedbackType.EXPLICIT_RATING)

            result = pipeline.submit_feedback(
                knowledge_id=knowledge_id,
                score=score,
                feedback_type=feedback_type,
                context=context
            )

            output = f"✓ 反馈已提交\n\n"
            output += f"知识ID: {knowledge_id}\n"
            output += f"评分: {score:.1f}\n"
            output += f"新价值: {result['new_value']:.2f}\n"
            output += f"新权重: {result['new_weight']:.2f}"

            return [TextContent(type="text", text=output)]

        elif name == "learning_status":
            pipeline = get_learning_pipeline()
            status = pipeline.get_learning_status()

            output = "【学习系统状态】\n\n"
            output += f"知识总数: {status.get('total_knowledge', 0)}\n"
            output += f"组合总数: {status.get('total_combinations', 0)}\n"
            output += f"元规则数: {status.get('total_rules', 0)}\n"
            output += f"反馈总数: {status.get('total_feedbacks', 0)}\n"
            output += f"上次反思: {status.get('last_reflection') or '从未'}\n"
            output += f"需要反思: {'是' if status.get('should_reflect') else '否'}\n\n"

            top_knowledge = status.get("top_knowledge", [])
            if top_knowledge:
                output += "【高价值知识】\n"
                for k in top_knowledge[:5]:
                    output += f"  {k['id'][:12]}... : {k['value']:.2f}\n"

            return [TextContent(type="text", text=output)]

        elif name == "learning_recommend":
            pipeline = get_learning_pipeline()
            candidates = arguments.get("candidates", [])
            limit = arguments.get("limit", 5)

            if candidates:
                # 优化候选列表
                selected = pipeline.optimize_retrieval(candidates, limit)
                recommendations = [
                    {"knowledge_id": kid, "value": pipeline.get_knowledge_value(kid)}
                    for kid in selected
                ]
            else:
                # 获取全局推荐
                recommendations = pipeline.get_recommendations(limit=limit)

            if recommendations:
                output = "【知识推荐】\n\n"
                for i, rec in enumerate(recommendations, 1):
                    output += f"### {i}. {rec['knowledge_id'][:16]}...\n"
                    output += f"**价值**: {rec.get('value', 0):.2f}\n"
                    if rec.get("confidence"):
                        output += f"**置信度**: {rec['confidence']:.0%}\n"
                    if rec.get("reasons"):
                        output += f"**理由**: {', '.join(rec['reasons'])}\n"
                    output += "\n"
            else:
                output = "暂无推荐。请先通过 learning_feedback_submit 提交反馈。"

            return [TextContent(type="text", text=output)]

        elif name == "learning_reflect":
            pipeline = get_learning_pipeline()
            result = pipeline.trigger_reflection()

            if result.get("success"):
                output = "【反思学习完成】\n\n"
                output += f"生成规则: {result.get('rules_generated', 0)} 条\n\n"

                rules = result.get("rules", [])
                if rules:
                    output += "【新规则】\n"
                    for rule in rules:
                        output += f"- {rule['name']} (置信度: {rule['confidence']:.0%})\n"
            else:
                output = f"反思失败: {result.get('error', '未知错误')}"

            return [TextContent(type="text", text=output)]

        # ========== 技能管理工具 ==========

        elif name == "skill_create":
            skill_manager = get_skill_manager()

            skill_id = arguments["skill_id"]
            name_str = arguments["name"]
            description = arguments["description"]
            trigger_keywords = arguments["trigger_keywords"]
            file_patterns = arguments.get("file_patterns", [])
            context_patterns = arguments.get("context_patterns", [])

            # 检查是否已存在
            existing = skill_manager.get_skill(skill_id)
            if existing:
                return [TextContent(
                    type="text",
                    text=f"技能 '{skill_id}' 已存在。请使用其他ID。"
                )]

            try:
                skill = skill_manager.create_skill(
                    skill_id=skill_id,
                    name=name_str,
                    description=description,
                    trigger_keywords=trigger_keywords,
                    file_patterns=file_patterns,
                    context_patterns=context_patterns
                )

                output = f"✓ 技能创建成功\n\n"
                output += f"ID: {skill.id}\n"
                output += f"名称: {skill.name}\n"
                output += f"描述: {skill.description}\n"
                output += f"触发词: {', '.join(trigger_keywords)}\n"
                if file_patterns:
                    output += f"文件模式: {', '.join(file_patterns)}\n"

                return [TextContent(type="text", text=output)]
            except Exception as e:
                return [TextContent(type="text", text=f"创建技能失败: {str(e)}")]

        elif name == "skill_list":
            skill_manager = get_skill_manager()
            skills = skill_manager.get_all_skills_summary()

            if not skills:
                return [TextContent(
                    type="text",
                    text="当前没有创建任何技能。\n\n"
                         "你可以说：'创建一个React开发技能' 来创建新技能。"
                )]

            output = "【技能列表】\n\n"
            for s in skills:
                output += f"**{s['name']}** ({s['id']})\n"
                output += f"  {s['description']}\n"
                output += f"  质量分数: {s['quality_score']:.1f} | 经验数: {s['total_experiences']}\n\n"

            return [TextContent(type="text", text=output)]

        elif name == "skill_get":
            skill_manager = get_skill_manager()
            skill_id = arguments["skill_id"]

            skill = skill_manager.get_skill(skill_id)
            if not skill:
                return [TextContent(type="text", text=f"技能 '{skill_id}' 不存在")]

            # 读取完整技能文件
            try:
                _, experiences = skill_manager.skill_file.read(skill_id)

                output = f"【技能详情】\n\n"
                output += f"ID: {skill.id}\n"
                output += f"名称: {skill.name}\n"
                output += f"描述: {skill.description}\n"
                output += f"触发词: {', '.join(skill.trigger_keywords)}\n"
                output += f"质量分数: {skill.quality_score:.1f}\n"
                output += f"经验数: {skill.total_experiences}\n\n"

                if experiences:
                    output += "【经验列表】\n\n"
                    for i, exp in enumerate(experiences[:10], 1):
                        output += f"### 经验 {i}\n"
                        output += f"{exp.content[:300]}{'...' if len(exp.content) > 300 else ''}\n\n"
                        if exp.quality_score > 0:
                            output += f"质量分数: {exp.quality_score:.1f}\n"
                        output += f"创建时间: {exp.created_at}\n\n"

                return [TextContent(type="text", text=output)]
            except Exception as e:
                return [TextContent(type="text", text=f"读取技能详情失败: {str(e)}")]

        elif name == "skill_match":
            skill_manager = get_skill_manager()
            context = arguments["context"]
            top_k = arguments.get("top_k", 3)

            matched_skills = skill_manager.match_skills(context, top_k=top_k)

            if not matched_skills:
                return [TextContent(
                    type="text",
                    text="没有找到匹配的技能。\n\n"
                         "当前上下文没有触发任何技能关键词。"
                )]

            output = f"【匹配的技能】(共 {len(matched_skills)} 个)\n\n"

            for i, skill in enumerate(matched_skills, 1):
                output += f"### {i}. {skill.name} ({skill.id})\n"
                output += f"描述: {skill.description}\n"
                output += f"匹配关键词: {', '.join(skill.trigger_keywords)}\n"
                output += f"质量分数: {skill.quality_score:.1f}\n\n"

            return [TextContent(type="text", text=output)]

        elif name == "skill_update_quality":
            skill_manager = get_skill_manager()
            skill_id = arguments["skill_id"]
            score = arguments["score"]

            try:
                skill_manager.update_skill_quality(skill_id, score)

                output = f"✓ 技能质量分数已更新\n\n"
                output += f"技能ID: {skill_id}\n"
                output += f"新分数: {score:.1f}"

                return [TextContent(type="text", text=output)]
            except ValueError as e:
                return [TextContent(type="text", text=str(e))]
            except Exception as e:
                return [TextContent(type="text", text=f"更新失败: {str(e)}")]

        else:
            return [TextContent(type="text", text=f"未知工具: {name}")]

    except Exception as e:
        import traceback
        return [TextContent(type="text", text=f"错误: {str(e)}\n\n{traceback.format_exc()}")]


async def main():
    """启动MCP服务器"""
    # 自动恢复上次会话的人格状态
    try:
        persona_manager = get_persona_manager()
        if persona_manager:
            # 尝试恢复上次会话
            restore_result = persona_manager.auto_restore_persona()
            if restore_result.get("restored"):
                # 获取恢复后的人格上下文
                persona_info = restore_result.get("persona_info", {})
                print(f"[MCP] 已自动恢复人格: {persona_info.get('name', 'unknown')}", file=__import__('sys').stderr)
    except Exception as e:
        print(f"[MCP] 恢复人格失败: {e}", file=__import__('sys').stderr)

    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
