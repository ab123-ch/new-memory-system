"""多人格系统模型"""
from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from enum import Enum


class CommunicationStyle(Enum):
    """沟通风格"""
    CONCISE = "concise"      # 简洁
    DETAILED = "detailed"    # 详细
    BALANCED = "balanced"    # 平衡


class ExpertiseLevel(Enum):
    """专业水平"""
    NOVICE = 1       # 新手
    INTERMEDIATE = 2 # 中级
    ADVANCED = 3     # 高级
    EXPERT = 4       # 专家


class PersonaStyle(BaseModel):
    """人格风格配置"""
    tone: str = "neutral"  # 语气：neutral, formal, casual, friendly, professional
    language_style: str = "balanced"  # 语言风格：concise, detailed, balanced
    emoji_usage: bool = False  # 是否使用emoji
    thinking_depth: str = "medium"  # 思考深度：shallow, medium, deep


class UserProfile(BaseModel):
    """增强的用户画像"""
    # 基本信息
    user_id: str = "default"
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    # 沟通偏好
    communication_style: str = "balanced"  # concise, detailed, balanced
    preferred_language: str = "zh-CN"      # zh-CN, en-US, etc.
    response_length_preference: str = "medium"  # short, medium, long

    # 领域熟练度 {领域: 熟练度(1-4)}
    expertise: Dict[str, int] = Field(default_factory=dict)

    # 偏好设置
    preferences: Dict[str, Any] = Field(default_factory=dict)

    # 已知约束（用户明确表示的限制）
    constraints: List[str] = Field(default_factory=list)

    # 兴趣标签
    interests: List[str] = Field(default_factory=list)

    # 使用统计
    usage_stats: Dict[str, Any] = Field(default_factory=dict)

    def get_expertise_level(self, domain: str) -> int:
        """获取某领域的熟练度"""
        return self.expertise.get(domain, 1)

    def set_expertise_level(self, domain: str, level: int):
        """设置某领域的熟练度"""
        if 1 <= level <= 4:
            self.expertise[domain] = level
            self.updated_at = datetime.now()

    def add_preference(self, key: str, value: Any):
        """添加偏好"""
        self.preferences[key] = value
        self.updated_at = datetime.now()

    def add_constraint(self, constraint: str):
        """添加约束"""
        if constraint not in self.constraints:
            self.constraints.append(constraint)
            self.updated_at = datetime.now()

    def remove_constraint(self, constraint: str):
        """移除约束"""
        if constraint in self.constraints:
            self.constraints.remove(constraint)
            self.updated_at = datetime.now()

    def add_interest(self, interest: str):
        """添加兴趣"""
        if interest not in self.interests:
            self.interests.append(interest)
            self.updated_at = datetime.now()

    def record_usage(self, metric: str, value: int = 1):
        """记录使用统计"""
        if metric not in self.usage_stats:
            self.usage_stats[metric] = 0
        self.usage_stats[metric] += value
        self.updated_at = datetime.now()

    def to_summary(self) -> str:
        """生成用户画像摘要"""
        parts = []

        if self.communication_style:
            parts.append(f"沟通风格: {self.communication_style}")

        if self.expertise:
            top_domains = sorted(
                self.expertise.items(),
                key=lambda x: x[1],
                reverse=True
            )[:3]
            domains_str = ", ".join(f"{d}({v})" for d, v in top_domains)
            parts.append(f"擅长领域: {domains_str}")

        if self.constraints:
            parts.append(f"约束: {', '.join(self.constraints[:3])}")

        if self.interests:
            parts.append(f"兴趣: {', '.join(self.interests[:5])}")

        return " | ".join(parts)


class PersonaConfig(BaseModel):
    """人格配置"""
    id: str
    name: str
    description: str = ""
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    # 风格设置
    style: PersonaStyle = Field(default_factory=PersonaStyle)

    # 用户画像（人格专属）
    user_profile: Optional[UserProfile] = None

    # 激活触发词（用于自然语言切换）
    trigger_keywords: List[str] = Field(default_factory=list)

    # 人格专属的系统提示（可选）
    system_prompt: str = ""

    # 是否启用
    enabled: bool = True

    # 使用统计
    usage_count: int = 0
    last_used: Optional[datetime] = None

    def get_or_create_user_profile(self) -> UserProfile:
        """获取或创建用户画像"""
        if self.user_profile is None:
            self.user_profile = UserProfile(user_id=f"persona_{self.id}")
        return self.user_profile


class PersonaSoul(BaseModel):
    """人格专属的元记忆"""
    persona_id: str
    updated_at: datetime = Field(default_factory=datetime.now)

    # 身份信息
    identity: List[Dict[str, Any]] = Field(default_factory=list)

    # 习惯偏好
    habits: List[Dict[str, Any]] = Field(default_factory=list)

    # 能力特征
    abilities: List[Dict[str, Any]] = Field(default_factory=list)

    # 待确认的记忆
    pending: List[Dict[str, Any]] = Field(default_factory=list)


class SharedMemory(BaseModel):
    """共享记忆 - 所有人格共用"""
    version: str = "1.0"
    updated_at: datetime = Field(default_factory=datetime.now)

    # 共享的身份信息（跨人格通用）
    shared_identity: List[Dict[str, Any]] = Field(default_factory=list)

    # 共享的偏好
    shared_habits: List[Dict[str, Any]] = Field(default_factory=list)

    # 共享的知识
    shared_knowledge: List[Dict[str, Any]] = Field(default_factory=list)

    # 跨人格的重要事件
    cross_persona_events: List[Dict[str, Any]] = Field(default_factory=list)

    def add_shared_identity(self, content: str, confirmed: bool = True):
        """添加共享身份"""
        self.shared_identity.append({
            "id": f"shared_id_{len(self.shared_identity):03d}",
            "content": content,
            "confirmed": confirmed,
            "created_at": datetime.now().isoformat()
        })
        self.updated_at = datetime.now()

    def add_shared_knowledge(self, content: str, source_persona: str = ""):
        """添加共享知识"""
        self.shared_knowledge.append({
            "id": f"shared_kno_{len(self.shared_knowledge):03d}",
            "content": content,
            "source_persona": source_persona,
            "created_at": datetime.now().isoformat()
        })
        self.updated_at = datetime.now()


class PersonaIndex(BaseModel):
    """人格索引"""
    version: str = "1.0"
    updated_at: datetime = Field(default_factory=datetime.now)

    # 所有人格列表
    personas: Dict[str, Dict[str, Any]] = Field(default_factory=dict)

    # 当前激活的人格
    active_persona: Optional[str] = None

    # 会话关闭历史（按关闭时间排序，最新的在前面）
    session_close_history: List[Dict[str, Any]] = Field(default_factory=list)

    # 最后关闭的会话信息（快速访问）
    last_closed_session: Optional[Dict[str, Any]] = None

    def add_persona(self, config: PersonaConfig):
        """添加人格"""
        self.personas[config.id] = {
            "name": config.name,
            "description": config.description,
            "enabled": config.enabled,
            "trigger_keywords": config.trigger_keywords,
            "created_at": config.created_at.isoformat() if config.created_at else None
        }
        self.updated_at = datetime.now()

    def remove_persona(self, persona_id: str):
        """移除人格"""
        if persona_id in self.personas:
            del self.personas[persona_id]
            if self.active_persona == persona_id:
                self.active_persona = None
        self.updated_at = datetime.now()

    def set_active(self, persona_id: Optional[str]):
        """设置激活人格"""
        if persona_id is None or persona_id in self.personas:
            self.active_persona = persona_id
            self.updated_at = datetime.now()
            return True
        return False

    def list_personas(self) -> List[Dict[str, Any]]:
        """列出所有人格"""
        result = []
        for pid, info in self.personas.items():
            result.append({
                "id": pid,
                "name": info.get("name", pid),
                "description": info.get("description", ""),
                "is_active": pid == self.active_persona,
                "trigger_keywords": info.get("trigger_keywords", [])
            })
        return result

    def find_by_keyword(self, keyword: str) -> Optional[str]:
        """通过关键词查找人格"""
        keyword_lower = keyword.lower()
        for pid, info in self.personas.items():
            # 检查名称
            if keyword_lower in info.get("name", "").lower():
                return pid
            # 检查触发词
            for trigger in info.get("trigger_keywords", []):
                if keyword_lower in trigger.lower() or trigger.lower() in keyword_lower:
                    return pid
        return None

    def record_session_close(
        self,
        session_id: str,
        active_persona: Optional[str],
        persona_name: str = ""
    ):
        """
        记录会话关闭

        Args:
            session_id: 会话ID
            active_persona: 关闭时的人格ID
            persona_name: 人格名称
        """
        record = {
            "session_id": session_id,
            "closed_at": datetime.now().isoformat(),
            "active_persona": active_persona,
            "persona_name": persona_name
        }

        # 更新最后关闭的会话
        self.last_closed_session = record

        # 添加到历史记录（保持最近20条）
        self.session_close_history.insert(0, record)
        if len(self.session_close_history) > 20:
            self.session_close_history = self.session_close_history[:20]

        self.updated_at = datetime.now()

    def get_last_closed_persona(self) -> Optional[Dict[str, Any]]:
        """
        获取最后关闭会话的人格信息

        Returns:
            包含 persona_id 和 persona_name 的字典，如果没有则返回 None
        """
        if self.last_closed_session:
            return {
                "persona_id": self.last_closed_session.get("active_persona"),
                "persona_name": self.last_closed_session.get("persona_name", ""),
                "session_id": self.last_closed_session.get("session_id", ""),
                "closed_at": self.last_closed_session.get("closed_at", "")
            }
        return None

    def get_persona_to_restore(self) -> Optional[str]:
        """
        获取启动时应该恢复的人格ID

        Returns:
            人格ID，如果没有则返回 None（使用默认状态）
        """
        last = self.get_last_closed_persona()
        if last and last.get("persona_id"):
            # 验证人格仍然存在
            persona_id = last["persona_id"]
            if persona_id in self.personas:
                return persona_id
        return None


class SessionState(BaseModel):
    """会话状态"""
    session_id: str
    started_at: datetime = Field(default_factory=datetime.now)

    # 当前激活的人格（None表示默认状态）
    active_persona: Optional[str] = None

    # 是否已加载记忆
    memory_loaded: bool = False

    # 对话历史
    conversations: List[Dict[str, Any]] = Field(default_factory=list)

    # 本次会话切换人格的历史
    persona_switches: List[Dict[str, Any]] = Field(default_factory=list)

    def switch_persona(self, new_persona: Optional[str], reason: str = ""):
        """切换人格"""
        switch_record = {
            "from": self.active_persona,
            "to": new_persona,
            "reason": reason,
            "timestamp": datetime.now().isoformat()
        }
        self.persona_switches.append(switch_record)
        self.active_persona = new_persona
        self.memory_loaded = False  # 需要重新加载记忆


class SessionCloseRecord(BaseModel):
    """会话关闭记录"""
    session_id: str
    closed_at: datetime = Field(default_factory=datetime.now)
    active_persona: Optional[str] = None  # 关闭时使用的人格
    persona_name: str = ""  # 人格名称（便于显示）

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "closed_at": self.closed_at.isoformat(),
            "active_persona": self.active_persona,
            "persona_name": self.persona_name
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionCloseRecord":
        return cls(
            session_id=data.get("session_id", ""),
            closed_at=datetime.fromisoformat(data["closed_at"]) if data.get("closed_at") else datetime.now(),
            active_persona=data.get("active_persona"),
            persona_name=data.get("persona_name", "")
        )
