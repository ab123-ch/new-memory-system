"""人格管理器 - 处理人格切换和记忆加载"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pathlib import Path
import os
import yaml
import logging

from .models import (
    PersonaConfig, PersonaSoul, PersonaStyle,
    SharedMemory, PersonaIndex, SessionState, SessionCloseRecord
)
from ..storage import FileStore

# 统一日志
try:
    from ..logging_config import get_logger
    logger = get_logger("persona_manager", "mcp")
except ImportError:
    logger = logging.getLogger(__name__)


class PersonaManager:
    """人格管理器"""

    def __init__(self, storage_path: str = "./data/memory"):
        self.storage_path = Path(storage_path)
        self.personas_path = self.storage_path / "personas"
        self.store = FileStore(storage_path)

        # 确保目录存在
        self.personas_path.mkdir(parents=True, exist_ok=True)

        # 缓存
        self._index_cache: Optional[PersonaIndex] = None
        self._shared_cache: Optional[SharedMemory] = None
        self._persona_configs: Dict[str, PersonaConfig] = {}
        self._current_session: Optional[SessionState] = None

    # ==================== 人格索引管理 ====================

    def load_index(self) -> PersonaIndex:
        """加载人格索引"""
        index_path = self.personas_path / "_index.yaml"

        if index_path.exists():
            try:
                with open(index_path, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f) or {}
                self._index_cache = PersonaIndex(**data)
            except Exception:
                self._index_cache = PersonaIndex()
        else:
            self._index_cache = PersonaIndex()

        return self._index_cache

    def save_index(self, index: PersonaIndex) -> bool:
        """保存人格索引"""
        index_path = self.personas_path / "_index.yaml"

        try:
            index.updated_at = datetime.now()
            with open(index_path, 'w', encoding='utf-8') as f:
                yaml.dump(
                    index.model_dump(mode='json'),
                    f,
                    allow_unicode=True,
                    sort_keys=False
                )
            self._index_cache = index
            return True
        except Exception as e:
            logger.error(f"保存人格索引失败: {e}")
            return False

    # ==================== 会话级人格隔离（PPID） ====================

    def _get_session_key(self) -> str:
        """获取当前进程的会话标识（基于父进程PID）"""
        return str(os.getppid())

    def save_session_persona(self, persona_id: Optional[str]):
        """保存当前会话的人格（per-PPID 文件，供同窗口的 Hook 读取）"""
        session_dir = self.storage_path / "session_personas"
        session_dir.mkdir(parents=True, exist_ok=True)
        session_file = session_dir / f"{self._get_session_key()}.yaml"
        if persona_id:
            with open(session_file, 'w', encoding='utf-8') as f:
                yaml.dump({
                    'persona_id': persona_id,
                    'updated_at': datetime.now().isoformat()
                }, f, allow_unicode=True)
        else:
            if session_file.exists():
                session_file.unlink()

    def load_session_persona(self) -> Optional[str]:
        """加载当前会话的人格（优先 per-session，回退到全局）"""
        session_file = self.storage_path / "session_personas" / f"{self._get_session_key()}.yaml"
        if session_file.exists():
            try:
                with open(session_file, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f)
                pid = data.get('persona_id')
                if pid:
                    return pid
            except Exception:
                pass
        # 回退到全局
        return self.load_index().active_persona

    def cleanup_stale_sessions(self, max_age_hours: int = 24):
        """清理过期的会话人格文件"""
        session_dir = self.storage_path / "session_personas"
        if not session_dir.exists():
            return
        now = datetime.now()
        for f in session_dir.glob("*.yaml"):
            try:
                with open(f, 'r', encoding='utf-8') as fh:
                    data = yaml.safe_load(fh)
                updated = datetime.fromisoformat(data.get('updated_at', ''))
                if (now - updated).total_seconds() > max_age_hours * 3600:
                    f.unlink()
            except Exception:
                pass

    # ==================== 人格配置管理 ====================

    def create_persona(
        self,
        persona_id: str,
        name: str,
        description: str = "",
        trigger_keywords: Optional[List[str]] = None,
        style: Optional[PersonaStyle] = None,
        system_prompt: str = ""
    ) -> PersonaConfig:
        """创建新人格"""
        # 创建人格目录
        persona_dir = self.personas_path / persona_id
        persona_dir.mkdir(parents=True, exist_ok=True)

        # 创建配置
        config = PersonaConfig(
            id=persona_id,
            name=name,
            description=description,
            trigger_keywords=trigger_keywords or [name],
            style=style or PersonaStyle(),
            system_prompt=system_prompt
        )

        # 保存配置
        self.save_persona_config(config)

        # 创建空的元记忆
        soul = PersonaSoul(persona_id=persona_id)
        self.save_persona_soul(soul)

        # 更新索引
        index = self.load_index()
        index.add_persona(config)
        self.save_index(index)

        self._persona_configs[persona_id] = config
        return config

    def load_persona_config(self, persona_id: str) -> Optional[PersonaConfig]:
        """加载人格配置"""
        if persona_id in self._persona_configs:
            return self._persona_configs[persona_id]

        config_path = self.personas_path / persona_id / "persona.yaml"

        if config_path.exists():
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f) or {}
                config = PersonaConfig(**data)
                self._persona_configs[persona_id] = config
                return config
            except Exception:
                return None
        return None

    def save_persona_config(self, config: PersonaConfig) -> bool:
        """保存人格配置"""
        config_path = self.personas_path / config.id / "persona.yaml"

        try:
            config.updated_at = datetime.now()
            with open(config_path, 'w', encoding='utf-8') as f:
                yaml.dump(
                    config.model_dump(mode='json'),
                    f,
                    allow_unicode=True,
                    sort_keys=False
                )
            self._persona_configs[config.id] = config
            return True
        except Exception as e:
            logger.error(f"保存人格配置失败: {e}")
            return False

    def delete_persona(self, persona_id: str) -> bool:
        """删除人格"""
        import shutil

        persona_dir = self.personas_path / persona_id
        if persona_dir.exists():
            try:
                shutil.rmtree(persona_dir)
            except Exception:
                return False

        # 更新索引
        index = self.load_index()
        index.remove_persona(persona_id)
        self.save_index(index)

        if persona_id in self._persona_configs:
            del self._persona_configs[persona_id]

        return True

    def list_personas(self) -> List[Dict[str, Any]]:
        """列出所有人格"""
        index = self.load_index()
        return index.list_personas()

    # ==================== 人格元记忆管理 ====================

    def load_persona_soul(self, persona_id: str) -> PersonaSoul:
        """加载人格元记忆"""
        soul_path = self.personas_path / persona_id / "soul.yaml"

        if soul_path.exists():
            try:
                with open(soul_path, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f) or {}
                return PersonaSoul(**data)
            except Exception:
                pass

        return PersonaSoul(persona_id=persona_id)

    def save_persona_soul(self, soul: PersonaSoul) -> bool:
        """保存人格元记忆"""
        soul_path = self.personas_path / soul.persona_id / "soul.yaml"

        try:
            soul.updated_at = datetime.now()
            with open(soul_path, 'w', encoding='utf-8') as f:
                yaml.dump(
                    soul.model_dump(mode='json'),
                    f,
                    allow_unicode=True,
                    sort_keys=False
                )
            return True
        except Exception as e:
            logger.error(f"保存人格元记忆失败: {e}")
            return False

    def set_persona_memory(
        self,
        persona_id: str,
        memory_type: str,
        content: str,
        confirmed: bool = True
    ) -> bool:
        """
        设置人格元记忆

        Args:
            persona_id: 人格ID
            memory_type: 记忆类型 - "identity", "habit", "ability"
            content: 记忆内容
            confirmed: 是否已确认

        Returns:
            是否保存成功
        """
        # 加载当前 soul
        soul = self.load_persona_soul(persona_id)

        # 创建记忆项
        memory_item = {
            "id": f"{memory_type[:3]}_{len(getattr(soul, memory_type + 's', [])):03d}",
            "content": content,
            "confirmed": confirmed,
            "created_at": datetime.now().isoformat()
        }

        # 添加到对应列表
        if memory_type == "identity":
            soul.identity.append(memory_item)
        elif memory_type == "habit":
            soul.habits.append(memory_item)
        elif memory_type == "ability":
            soul.abilities.append(memory_item)
        else:
            logger.error(f"未知的记忆类型: {memory_type}")
            return False

        # 保存
        return self.save_persona_soul(soul)

    # ==================== 共享记忆管理 ====================

    def load_shared_memory(self) -> SharedMemory:
        """加载共享记忆"""
        if self._shared_cache:
            return self._shared_cache

        shared_path = self.storage_path / "shared.yaml"

        if shared_path.exists():
            try:
                with open(shared_path, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f) or {}
                self._shared_cache = SharedMemory(**data)
            except Exception:
                self._shared_cache = SharedMemory()
        else:
            self._shared_cache = SharedMemory()

        return self._shared_cache

    def save_shared_memory(self, shared: SharedMemory) -> bool:
        """保存共享记忆"""
        shared_path = self.storage_path / "shared.yaml"

        try:
            shared.updated_at = datetime.now()
            with open(shared_path, 'w', encoding='utf-8') as f:
                yaml.dump(
                    shared.model_dump(mode='json'),
                    f,
                    allow_unicode=True,
                    sort_keys=False
                )
            self._shared_cache = shared
            return True
        except Exception as e:
            logger.error(f"保存共享记忆失败: {e}")
            return False

    # ==================== 会话管理 ====================

    def create_session(self, session_id: str) -> SessionState:
        """创建新会话"""
        self._current_session = SessionState(session_id=session_id)
        return self._current_session

    def get_current_session(self) -> Optional[SessionState]:
        """获取当前会话"""
        return self._current_session

    def close_session(self, session_id: Optional[str] = None) -> bool:
        """
        关闭会话并记录状态

        Args:
            session_id: 要关闭的会话ID，默认关闭当前会话

        Returns:
            是否成功记录
        """
        if session_id is None:
            if self._current_session:
                session_id = self._current_session.session_id
            else:
                return False

        # 获取当前激活的人格
        index = self.load_index()
        active_persona = index.active_persona

        # 获取人格名称
        persona_name = ""
        if active_persona:
            config = self.load_persona_config(active_persona)
            if config:
                persona_name = config.name

        # 记录会话关闭
        index.record_session_close(
            session_id=session_id,
            active_persona=active_persona,
            persona_name=persona_name
        )
        self.save_index(index)

        # 清除当前会话
        if self._current_session and self._current_session.session_id == session_id:
            self._current_session = None

        return True

    def get_last_session_persona(self) -> Optional[Dict[str, Any]]:
        """
        获取上一个会话使用的人格

        Returns:
            包含 persona_id, persona_name 等信息的字典
        """
        index = self.load_index()
        return index.get_last_closed_persona()

    def auto_restore_persona(self) -> Dict[str, Any]:
        """
        自动恢复上一个会话的人格

        Returns:
            恢复结果
        """
        index = self.load_index()
        persona_id = index.get_persona_to_restore()

        if persona_id is None:
            return {
                "success": True,
                "restored": False,
                "message": "没有需要恢复的人格，使用默认状态"
            }

        # 执行切换
        result = self.switch_persona(persona_id, reason="auto_restore")

        return {
            "success": result.get("success", False),
            "restored": True,
            "persona_id": persona_id,
            "persona_info": result.get("persona_info", {}),
            "message": f"已自动恢复到上次使用的人格「{result.get('persona_info', {}).get('name', persona_id)}」"
        }

    # ==================== 人格切换 ====================

    def detect_persona_switch(
        self,
        user_message: str
    ) -> Optional[str]:
        """
        检测用户是否要切换人格

        Returns:
            目标人格ID，None表示不切换
        """
        message_lower = user_message.lower()

        # 切换关键词
        switch_patterns = [
            "切换到", "换成", "用", "变成",
            "切换人格", "换人格", "切换模式",
            "switch to", "use", "change to"
        ]

        # 查询人格列表关键词
        list_patterns = [
            "有哪个人格", "有哪些人格", "人格列表",
            "列表人格", "查看人格", "人格选项",
            "list personas", "show personas"
        ]

        # 检查是否要查看人格列表
        for pattern in list_patterns:
            if pattern in message_lower:
                return "__LIST__"

        # 检查是否要切换到默认状态
        default_patterns = [
            "默认", "原始", "重置", "取消人格",
            "default", "reset", "clear"
        ]
        for pattern in default_patterns:
            if pattern in message_lower:
                return "__DEFAULT__"

        # 检查切换意图
        has_switch_intent = False
        for pattern in switch_patterns:
            if pattern in message_lower:
                has_switch_intent = True
                break

        if not has_switch_intent:
            return None

        # 查找目标人格
        index = self.load_index()

        # 尝试通过关键词匹配
        for pid in index.personas:
            config = self.load_persona_config(pid)
            if config:
                for keyword in config.trigger_keywords:
                    if keyword.lower() in message_lower:
                        return pid
                if config.name.lower() in message_lower:
                    return pid

        return None

    def switch_persona(
        self,
        target_persona: Optional[str],
        reason: str = ""
    ) -> Dict[str, Any]:
        """
        切换人格

        Args:
            target_persona: 目标人格ID，None表示切换到默认状态
            reason: 切换原因

        Returns:
            切换结果
        """
        index = self.load_index()

        # 验证目标人格
        if target_persona is not None and target_persona not in index.personas:
            return {
                "success": False,
                "error": f"人格 '{target_persona}' 不存在"
            }

        # 记录切换
        if self._current_session:
            self._current_session.switch_persona(target_persona, reason)

        # 更新索引中的激活状态
        index.set_active(target_persona)
        self.save_index(index)

        # 同步写入 per-session 人格文件（供同窗口的 Hook 读取）
        self.save_session_persona(target_persona)

        # 更新使用统计
        if target_persona:
            config = self.load_persona_config(target_persona)
            if config:
                config.usage_count += 1
                config.last_used = datetime.now()
                self.save_persona_config(config)

        # 构建结果
        result = {
            "success": True,
            "previous_persona": self._current_session.persona_switches[-1].get("from") if self._current_session and self._current_session.persona_switches else None,
            "current_persona": target_persona
        }

        if target_persona:
            config = self.load_persona_config(target_persona)
            if config:
                result["persona_info"] = {
                    "name": config.name,
                    "description": config.description,
                    "style": config.style.model_dump()
                }
        else:
            result["persona_info"] = {
                "name": "默认",
                "description": "无人格状态"
            }

        return result

    # ==================== 记忆加载 ====================

    def get_memory_context(
        self,
        include_shared: bool = True
    ) -> Dict[str, Any]:
        """
        获取当前记忆上下文

        Args:
            include_shared: 是否包含共享记忆

        Returns:
            记忆上下文
        """
        context = {
            "persona": None,
            "soul": None,
            "shared": None,
            "recent_memories": []
        }

        # 获取当前人格
        index = self.load_index()
        active_persona = index.active_persona

        if active_persona:
            config = self.load_persona_config(active_persona)
            soul = self.load_persona_soul(active_persona)

            context["persona"] = {
                "id": active_persona,
                "name": config.name if config else active_persona,
                "description": config.description if config else "",
                "style": config.style.model_dump() if config else {},
                "system_prompt": config.system_prompt if config else ""
            }

            context["soul"] = {
                "identity": [i.get("content") for i in soul.identity if i.get("confirmed", True)],
                "habits": [h.get("content") for h in soul.habits if h.get("confirmed", True)],
                "abilities": [a.get("content") for a in soul.abilities if a.get("confirmed", True)]
            }

            # 加载人格的最近记忆
            context["recent_memories"] = self._load_persona_recent_memories(active_persona)

        # 加载共享记忆
        if include_shared:
            shared = self.load_shared_memory()
            context["shared"] = {
                "identity": [i.get("content") for i in shared.shared_identity],
                "knowledge": [k.get("content") for k in shared.shared_knowledge]
            }

        return context

    def _load_persona_recent_memories(
        self,
        persona_id: str,
        days: int = 3
    ) -> List[Dict[str, Any]]:
        """加载人格的最近记忆"""
        from datetime import date, timedelta

        memories = []
        persona_dir = self.personas_path / persona_id

        today = date.today()
        for i in range(days):
            target_date = today - timedelta(days=i)
            month_dir = persona_dir / target_date.strftime("%Y-%m")
            memory_file = month_dir / target_date.strftime("%Y-%m-%d.yaml")

            if memory_file.exists():
                try:
                    with open(memory_file, 'r', encoding='utf-8') as f:
                        data = yaml.safe_load(f) or {}
                    if data.get("sessions"):
                        memories.append({
                            "date": str(target_date),
                            "sessions": len(data["sessions"]),
                            "summary": data["sessions"][-1].get("summary", "") if data["sessions"] else ""
                        })
                except Exception:
                    continue

        return memories

    def build_system_prompt(self) -> str:
        """构建系统提示"""
        context = self.get_memory_context()

        if not context["persona"]:
            return ""

        parts = []

        # 人格信息
        parts.append(f"你现在是「{context['persona']['name']}」。")
        if context["persona"]["description"]:
            parts.append(context["persona"]["description"])

        # 自定义系统提示
        if context["persona"].get("system_prompt"):
            parts.append(context["persona"]["system_prompt"])

        # 元记忆
        if context["soul"]:
            if context["soul"]["identity"]:
                parts.append("身份: " + ", ".join(context["soul"]["identity"]))
            if context["soul"]["habits"]:
                parts.append("偏好: " + ", ".join(context["soul"]["habits"]))
            if context["soul"]["abilities"]:
                parts.append("能力: " + ", ".join(context["soul"]["abilities"]))

        # 共享记忆
        if context["shared"]:
            if context["shared"]["identity"]:
                parts.append("通用身份: " + ", ".join(context["shared"]["identity"]))

        return "\n\n".join(parts)

    # ==================== 风格记忆管理 ====================

    def load_style_memory(self, persona_id: str) -> "PersonaStyleMemory":
        """
        加载人格风格记忆

        Args:
            persona_id: 人格ID

        Returns:
            PersonaStyleMemory 实例
        """
        from ..style_learning.models import PersonaStyleMemory

        style_path = self.personas_path / persona_id / "style_memory.yaml"

        if style_path.exists():
            try:
                with open(style_path, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f) or {}
                return PersonaStyleMemory(**data)
            except Exception as e:
                logger.warning(f"加载风格记忆失败: {e}")

        return PersonaStyleMemory(persona_id=persona_id)

    def save_style_memory(self, memory: "PersonaStyleMemory") -> bool:
        """
        保存人格风格记忆

        Args:
            memory: PersonaStyleMemory 实例

        Returns:
            是否保存成功
        """
        style_path = self.personas_path / memory.persona_id / "style_memory.yaml"

        try:
            memory.updated_at = datetime.now()
            with open(style_path, 'w', encoding='utf-8') as f:
                yaml.dump(
                    memory.model_dump(mode='json'),
                    f,
                    allow_unicode=True,
                    sort_keys=False
                )
            return True
        except Exception as e:
            logger.error(f"保存风格记忆失败: {e}")
            return False

    def get_style_memory_context(
        self,
        persona_id: str,
        context: Optional[Dict[str, Any]] = None,
        max_techniques: int = 3
    ) -> Dict[str, Any]:
        """
        获取风格记忆上下文（包含智能技巧注入）

        Args:
            persona_id: 人格ID
            context: 创作上下文（stage, keywords, scene等）
            max_techniques: 最大注入技巧数量

        Returns:
            风格记忆上下文
        """
        from ..style_learning import (
            TechniqueRetriever,
            MemoryDecayEngine,
            StyleLearningConfig
        )

        result = {
            "has_style_memory": False,
            "techniques_count": 0,
            "suggestions": [],
            "injection_prompt": ""
        }

        # 加载风格记忆
        memory = self.load_style_memory(persona_id)

        if not memory.techniques:
            return result

        result["has_style_memory"] = True
        result["techniques_count"] = memory.total_techniques

        # 初始化检索器
        config = StyleLearningConfig()
        retriever = TechniqueRetriever(config=config)
        retriever.initialize(memory)

        # 如果有创作上下文，获取相关建议
        if context:
            suggestions = retriever.retrieve_for_context(context, limit=max_techniques)
            result["suggestions"] = suggestions

            # 生成注入提示
            if suggestions:
                result["injection_prompt"] = retriever.generate_context_prompt(
                    context,
                    max_techniques=max_techniques
                )

        return result

    def apply_style_memory_decay(
        self,
        persona_id: str,
        auto_save: bool = True
    ) -> Dict[str, Any]:
        """
        对人格风格记忆应用衰减

        Args:
            persona_id: 人格ID
            auto_save: 是否自动保存

        Returns:
            衰减结果统计
        """
        from ..style_learning import MemoryDecayEngine, StyleLearningConfig

        memory = self.load_style_memory(persona_id)

        if not memory.techniques:
            return {"success": True, "message": "没有技巧需要衰减"}

        # 应用衰减
        config = StyleLearningConfig()
        engine = MemoryDecayEngine(config=config)
        stats = engine.apply_decay(memory)

        # 保存
        if auto_save:
            self.save_style_memory(memory)

        return {
            "success": True,
            "stats": stats
        }

    def build_enhanced_system_prompt(
        self,
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        构建增强的系统提示（包含风格技巧注入）

        Args:
            context: 创作上下文

        Returns:
            增强的系统提示
        """
        # 基础系统提示
        base_prompt = self.build_system_prompt()

        # 获取当前人格
        index = self.load_index()
        active_persona = index.active_persona

        if not active_persona:
            return base_prompt

        # 获取风格记忆上下文
        style_context = self.get_style_memory_context(
            active_persona,
            context=context,
            max_techniques=3
        )

        # 注入风格技巧
        injection_prompt = style_context.get("injection_prompt", "")

        if injection_prompt:
            return f"{base_prompt}\n\n{injection_prompt}"

        return base_prompt

    def get_style_learning_stats(self, persona_id: str) -> Dict[str, Any]:
        """
        获取人格的风格学习统计

        Args:
            persona_id: 人格ID

        Returns:
            统计信息
        """
        from ..style_learning import ArticleLearner

        memory = self.load_style_memory(persona_id)
        learner = ArticleLearner()

        return learner.get_statistics(memory)
