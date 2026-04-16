"""本元记忆模型 - 永久保存，会话启动时自动加载"""
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class Identity(BaseModel):
    """身份信息"""
    id: str
    content: str
    confirmed: bool = True
    created_at: datetime = Field(default_factory=datetime.now)


class Habit(BaseModel):
    """习惯偏好"""
    id: str
    content: str
    confirmed: bool = True
    created_at: datetime = Field(default_factory=datetime.now)


class Ability(BaseModel):
    """能力特征"""
    id: str
    content: str
    confirmed: bool = True
    created_at: datetime = Field(default_factory=datetime.now)


class PendingMemory(BaseModel):
    """待确认的本元记忆（AI提取，用户未确认）"""
    id: str
    content: str
    source_session: str
    created_at: datetime = Field(default_factory=datetime.now)


class SoulMemory(BaseModel):
    """本元记忆 - 永久保存"""
    version: str = "1.0"
    user_id: str = "default_user"
    updated_at: datetime = Field(default_factory=datetime.now)

    # 身份信息
    identity: List[Identity] = Field(default_factory=list)

    # 习惯偏好
    habits: List[Habit] = Field(default_factory=list)

    # 能力特征
    abilities: List[Ability] = Field(default_factory=list)

    # 待确认的记忆
    pending: List[PendingMemory] = Field(default_factory=list)

    def add_identity(self, content: str, confirmed: bool = False) -> Identity:
        """添加身份信息"""
        identity = Identity(
            id=f"id_{len(self.identity):03d}",
            content=content,
            confirmed=confirmed
        )
        self.identity.append(identity)
        self.updated_at = datetime.now()
        return identity

    def add_habit(self, content: str, confirmed: bool = False) -> Habit:
        """添加习惯偏好"""
        habit = Habit(
            id=f"hab_{len(self.habits):03d}",
            content=content,
            confirmed=confirmed
        )
        self.habits.append(habit)
        self.updated_at = datetime.now()
        return habit

    def add_ability(self, content: str, confirmed: bool = False) -> Ability:
        """添加能力特征"""
        ability = Ability(
            id=f"ab_{len(self.abilities):03d}",
            content=content,
            confirmed=confirmed
        )
        self.abilities.append(ability)
        self.updated_at = datetime.now()
        return ability

    def confirm_pending(self, pending_id: str, memory_type: str = "identity") -> bool:
        """确认待确认的记忆"""
        for i, pending in enumerate(self.pending):
            if pending.id == pending_id:
                content = pending.content
                self.pending.pop(i)

                if memory_type == "identity":
                    self.add_identity(content, confirmed=True)
                elif memory_type == "habit":
                    self.add_habit(content, confirmed=True)
                elif memory_type == "ability":
                    self.add_ability(content, confirmed=True)

                self.updated_at = datetime.now()
                return True
        return False

    def get_confirmed_memories(self) -> dict:
        """获取所有已确认的记忆"""
        return {
            "identity": [i.content for i in self.identity if i.confirmed],
            "habits": [h.content for h in self.habits if h.confirmed],
            "abilities": [a.content for a in self.abilities if a.confirmed]
        }
