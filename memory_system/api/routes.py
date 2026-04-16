"""API接口 - 提供HTTP访问"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import asdict

from ..session import MemorySystem, MemorySession
from ..models import SoulMemory, DailyMemory, GlobalIndex


class MemoryAPI:
    """记忆系统API"""

    def __init__(self, storage_path: str = "./data/memory"):
        self.system = MemorySystem(storage_path)
        self._current_sessions: Dict[str, MemorySession] = {}

    async def initialize_session(
        self,
        user_id: str = "default_user"
    ) -> Dict[str, Any]:
        """初始化会话"""
        session = self.system.start_session(user_id)
        context = await session.initialize()
        self._current_sessions[user_id] = session

        return {
            "success": True,
            "session_id": session._session.session_id if session._session else None,
            "context": context
        }

    async def chat(
        self,
        user_id: str,
        message: str
    ) -> Dict[str, Any]:
        """处理对话"""
        if user_id not in self._current_sessions:
            await self.initialize_session(user_id)

        session = self._current_sessions[user_id]
        result = await session.chat(message)

        return {
            "success": True,
            "session_id": result.session_id,
            "recalled": result.recalled,
            "recall_prompt": result.recall_prompt,
            "recalled_memories": result.recalled_memories
        }

    async def save_response(
        self,
        user_id: str,
        content: str
    ) -> Dict[str, Any]:
        """保存AI响应"""
        if user_id not in self._current_sessions:
            return {"success": False, "error": "No active session"}

        session = self._current_sessions[user_id]
        await session.save_assistant_response(content)

        return {"success": True}

    async def recall(
        self,
        user_id: str,
        topic: str
    ) -> Dict[str, Any]:
        """主动召回记忆"""
        if user_id not in self._current_sessions:
            await self.initialize_session(user_id)

        session = self._current_sessions[user_id]
        result = await session.recall(topic)

        return {
            "success": True,
            "recalled": result.need_recall,
            "recall_prompt": result.recall_prompt,
            "memories": result.memories
        }

    async def set_soul_memory(
        self,
        user_id: str,
        memory_type: str,
        content: str,
        confirmed: bool = True
    ) -> Dict[str, Any]:
        """设置本元记忆"""
        if user_id not in self._current_sessions:
            await self.initialize_session(user_id)

        session = self._current_sessions[user_id]
        await session.set_soul_memory(memory_type, content, confirmed)

        return {"success": True}

    async def get_soul(self, user_id: str = "default_user") -> Dict[str, Any]:
        """获取本元记忆"""
        soul = self.system.get_soul(user_id)
        return {
            "success": True,
            "soul": {
                "identity": [i.model_dump() for i in soul.identity],
                "habits": [h.model_dump() for h in soul.habits],
                "abilities": [a.model_dump() for a in soul.abilities],
                "pending": [p.model_dump() for p in soul.pending]
            }
        }

    async def get_recent_memories(
        self,
        days: int = 3
    ) -> Dict[str, Any]:
        """获取最近记忆"""
        memories = self.system.get_recent_memories(days)

        return {
            "success": True,
            "memories": [
                {
                    "date": str(m.date),
                    "sessions": len(m.sessions),
                    "events": len(m.events),
                    "summary": m.sessions[-1].summary if m.sessions else ""
                }
                for m in memories
            ]
        }

    async def search(
        self,
        query: str,
        days: int = 7
    ) -> Dict[str, Any]:
        """搜索记忆"""
        results = await self.system.search(query, days)

        return {
            "success": True,
            "query": query,
            "results": results
        }

    async def end_session(
        self,
        user_id: str = "default_user"
    ) -> Dict[str, Any]:
        """结束会话"""
        if user_id in self._current_sessions:
            await self._current_sessions[user_id].end()
            del self._current_sessions[user_id]

        return {"success": True}

    async def get_context(
        self,
        user_id: str = "default_user"
    ) -> Dict[str, Any]:
        """获取当前上下文"""
        if user_id not in self._current_sessions:
            return {"success": False, "error": "No active session"}

        session = self._current_sessions[user_id]
        context = session.get_context()

        return {
            "success": True,
            "context": context
        }


def create_app(storage_path: str = "./data/memory"):
    """创建FastAPI应用"""
    try:
        from fastapi import FastAPI, HTTPException
        from fastapi.middleware.cors import CORSMiddleware
        from pydantic import BaseModel
    except ImportError:
        raise ImportError("FastAPI is required. Install with: pip install fastapi")

    app = FastAPI(
        title="AI Memory System",
        description="基于'夺舍'架构的AI对话记忆系统",
        version="1.0.0"
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    api = MemoryAPI(storage_path)

    # 请求模型
    class ChatRequest(BaseModel):
        user_id: str = "default_user"
        message: str

    class RecallRequest(BaseModel):
        user_id: str = "default_user"
        topic: str

    class SoulMemoryRequest(BaseModel):
        user_id: str = "default_user"
        type: str
        content: str
        confirmed: bool = True

    class SearchRequest(BaseModel):
        query: str
        days: int = 7

    # 路由
    @app.post("/session/init")
    async def init_session(user_id: str = "default_user"):
        return await api.initialize_session(user_id)

    @app.post("/chat")
    async def chat(request: ChatRequest):
        return await api.chat(request.user_id, request.message)

    @app.post("/response")
    async def save_response(user_id: str, content: str):
        return await api.save_response(user_id, content)

    @app.post("/recall")
    async def recall(request: RecallRequest):
        return await api.recall(request.user_id, request.topic)

    @app.post("/soul")
    async def set_soul(request: SoulMemoryRequest):
        return await api.set_soul_memory(
            request.user_id,
            request.type,
            request.content,
            request.confirmed
        )

    @app.get("/soul")
    async def get_soul(user_id: str = "default_user"):
        return await api.get_soul(user_id)

    @app.get("/recent")
    async def get_recent(days: int = 3):
        return await api.get_recent_memories(days)

    @app.post("/search")
    async def search(request: SearchRequest):
        return await api.search(request.query, request.days)

    @app.post("/session/end")
    async def end_session(user_id: str = "default_user"):
        return await api.end_session(user_id)

    @app.get("/context")
    async def get_context(user_id: str = "default_user"):
        return await api.get_context(user_id)

    return app
