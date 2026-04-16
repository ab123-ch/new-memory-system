"""LLM 客户端接口 - 支持多种大模型"""
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
import asyncio
import os
import json
from pathlib import Path
import yaml


def _load_model_config() -> Dict[str, Any]:
    """从 model_config.yaml 读取模型配置"""
    config = {}
    possible_paths = [
        Path.cwd() / "model_config.yaml",
        Path(__file__).parent.parent.parent / "model_config.yaml",
        Path.home() / ".claude" / "mcp" / "memory" / "model_config.yaml",
        Path.home() / "model_config.yaml",
    ]
    for p in possible_paths:
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    config = yaml.safe_load(f) or {}
                break
            except (yaml.YAMLError, IOError):
                pass
    return config


_MODEL_CONFIG = _load_model_config()


def _get_api_key_from_settings(key_name: str) -> Optional[str]:
    """从 Claude settings.json 读取 API Key"""
    settings_path = Path.home() / ".claude" / "settings.json"
    if settings_path.exists():
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("env", {}).get(key_name)
        except (json.JSONDecodeError, IOError):
            pass
    return None


def _resolve_api_key(key_name: str, explicit_key: Optional[str] = None) -> Optional[str]:
    """
    获取 API Key，优先级: 显式传入 > model_config.yaml > Claude settings > 环境变量
    """
    if explicit_key:
        return explicit_key

    # 从 model_config.yaml 读取
    llm_config = _MODEL_CONFIG.get("llm", {})
    api_key = llm_config.get("api_key")
    if api_key:
        return api_key

    # 从 Claude settings 读取
    key = _get_api_key_from_settings(key_name)
    if key:
        return key

    return os.environ.get(key_name)


@dataclass
class LLMResponse:
    """LLM 响应"""
    content: str
    model: str
    usage: Dict[str, int]  # {prompt_tokens, completion_tokens, total_tokens}
    finish_reason: str = "stop"


class LLMClient(ABC):
    """LLM 客户端基类"""

    @abstractmethod
    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 500
    ) -> LLMResponse:
        """发送聊天请求"""
        pass

    @abstractmethod
    async def complete(
        self,
        prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 500
    ) -> LLMResponse:
        """发送补全请求"""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """检查服务是否可用"""
        pass


class ZhipuClient(LLMClient):
    """
    智谱 GLM 客户端

    支持模型: glm-4, glm-4-flash, glm-4-plus, glm-5
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "glm-4-flash",
        base_url: Optional[str] = None
    ):
        self.api_key = _resolve_api_key("ZHIPU_API_KEY", api_key)
        self.model = model
        self.base_url = base_url or "https://open.bigmodel.cn/api/paas/v4/"
        self._client = None
        self._available = None

    def _get_client(self):
        """懒加载客户端"""
        if self._client is None:
            try:
                from zhipuai import ZhipuAI
                if not self.api_key:
                    raise ValueError("ZHIPU_API_KEY not set")
                self._client = ZhipuAI(api_key=self.api_key)
            except ImportError:
                raise ImportError(
                    "zhipuai not installed. Run: pip install zhipuai"
                )
        return self._client

    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 500
    ) -> LLMResponse:
        """发送聊天请求"""
        client = self._get_client()

        def _call():
            response = client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )
            return response

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, _call)

        return LLMResponse(
            content=response.choices[0].message.content,
            model=response.model,
            usage={
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens
            },
            finish_reason=response.choices[0].finish_reason
        )

    async def complete(
        self,
        prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 500
    ) -> LLMResponse:
        """发送补全请求（转换为聊天格式）"""
        messages = [{"role": "user", "content": prompt}]
        return await self.chat(messages, temperature, max_tokens)

    def is_available(self) -> bool:
        if self._available is not None:
            return self._available

        if not self.api_key:
            self._available = False
            return False

        try:
            import zhipuai  # noqa: F401
            self._available = True
        except ImportError:
            self._available = False

        return self._available


class OpenAIClient(LLMClient):
    """
    OpenAI 客户端

    支持模型: gpt-4, gpt-4-turbo, gpt-3.5-turbo
    也支持兼容 OpenAI API 的服务
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gpt-3.5-turbo",
        base_url: Optional[str] = None
    ):
        self.api_key = _resolve_api_key("OPENAI_API_KEY", api_key)
        self.model = model
        self.base_url = base_url
        self._client = None
        self._available = None

    def _get_client(self):
        """懒加载客户端"""
        if self._client is None:
            try:
                from openai import OpenAI
                if not self.api_key:
                    raise ValueError("OPENAI_API_KEY not set")
                kwargs = {"api_key": self.api_key}
                if self.base_url:
                    kwargs["base_url"] = self.base_url
                self._client = OpenAI(**kwargs)
            except ImportError:
                raise ImportError(
                    "openai not installed. Run: pip install openai"
                )
        return self._client

    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 500
    ) -> LLMResponse:
        """发送聊天请求"""
        client = self._get_client()

        def _call():
            response = client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )
            return response

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, _call)

        return LLMResponse(
            content=response.choices[0].message.content,
            model=response.model,
            usage={
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens
            },
            finish_reason=response.choices[0].finish_reason
        )

    async def complete(
        self,
        prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 500
    ) -> LLMResponse:
        """发送补全请求"""
        messages = [{"role": "user", "content": prompt}]
        return await self.chat(messages, temperature, max_tokens)

    def is_available(self) -> bool:
        if self._available is not None:
            return self._available

        if not self.api_key:
            self._available = False
            return False

        try:
            import openai  # noqa: F401
            self._available = True
        except ImportError:
            self._available = False

        return self._available


class MockLLMClient(LLMClient):
    """
    模拟 LLM 客户端（用于测试或无 API 时回退）

    不进行实际调用，返回简单规则处理的结果
    支持基本的文章分析功能
    """

    def __init__(self):
        pass

    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 500
    ) -> LLMResponse:
        """模拟聊天响应"""
        # 合并消息
        combined = " ".join(m.get("content", "") for m in messages)

        # 简单的规则处理
        if "经验学习分析" in combined or "提取可学习的经验" in combined or "JSON 格式返回分析结果" in combined:
            content = self._mock_experience_analysis(combined)
        elif "摘要" in combined or "总结" in combined:
            content = self._mock_summarize(combined)
        elif "关键词" in combined or "提取" in combined:
            content = self._mock_extract_keywords(combined)
        elif "写作技巧" in combined or "分析文章" in combined or "技巧" in combined:
            content = self._mock_analyze_article(combined)
        else:
            content = f"[Mock Response] 收到消息: {combined[:100]}..."

        return LLMResponse(
            content=content,
            model="mock",
            usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            finish_reason="stop"
        )

    async def complete(
        self,
        prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 500
    ) -> LLMResponse:
        """模拟补全响应"""
        return await self.chat([{"role": "user", "content": prompt}], temperature, max_tokens)

    def is_available(self) -> bool:
        return True

    def _mock_summarize(self, text: str) -> str:
        """模拟摘要"""
        sentences = text.replace("。", ".").replace("！", "!").replace("？", "?").split(".")
        if sentences:
            return f"讨论了关于: {sentences[0][:50]}..."
        return "进行了一次对话"

    def _mock_extract_keywords(self, text: str) -> str:
        """模拟关键词提取"""
        # 简单提取中英文词汇
        import re
        chinese = re.findall(r'[\u4e00-\u9fff]{2,4}', text)
        english = re.findall(r'[a-zA-Z]{3,}', text)

        keywords = list(set(chinese[:5] + english[:5]))
        return json.dumps(keywords, ensure_ascii=False)

    def _mock_experience_analysis(self, text: str) -> str:
        """模拟经验分析（返回 JSON 格式）"""
        import re

        # 尝试从文本中提取用户消息
        user_msg_match = re.search(r'## 用户消息\s*\n(.*?)(?=\n## |$)', text, re.DOTALL)
        user_msg = user_msg_match.group(1).strip()[:200] if user_msg_match else "用户消息"

        # 根据关键词判断经验类型
        summary = "从对话中提取的经验"
        key_points = ["注意代码质量", "遵循规范"]
        tags = ["经验", "学习"]

        if "代码" in user_msg or "bug" in user_msg.lower():
            summary = "代码相关经验：注意规范和最佳实践"
            key_points = ["遵循编码规范", "注意代码质量", "及时测试验证"]
            tags = ["编程", "代码规范", "最佳实践"]
        elif "建议" in user_msg:
            summary = "优化建议：改进工作流程或方法"
            key_points = ["考虑用户建议", "持续优化改进", "保持开放心态"]
            tags = ["优化", "建议", "改进"]
        elif "错误" in user_msg or "不对" in user_msg:
            summary = "纠错经验：从错误中学习"
            key_points = ["认真对待错误反馈", "及时修正问题", "避免重复犯错"]
            tags = ["纠错", "反馈", "学习"]

        result = {
            "summary": summary,
            "key_points": key_points,
            "tags": tags,
            "importance": 0.75,
            "confidence": 0.8
        }

        return json.dumps(result, ensure_ascii=False, indent=2)

    def _mock_analyze_article(self, text: str) -> str:
        """模拟文章分析（返回基础的写作技巧模板）"""
        # 提取标题
        import re
        title_match = re.search(r'文章标题\s*\n?\s*(.+?)(?:\n|$)', text)
        title = title_match.group(1) if title_match else "未知文章"

        # 返回一个基础的技巧分析模板
        result = {
            "article_info": {
                "genre": "玄幻/仙侠",
                "style_tags": ["极道流", "黑暗风", "加点系统"],
                "quality_score": 0.85
            },
            "techniques": [
                {
                    "category": "narrative",
                    "principle": "开篇使用简洁有力的环境描写（如'冷风如刀，大雪纷飞'），快速建立氛围并切入故事",
                    "examples": ["冷风如刀，大雪纷飞。路胜一睁眼，便看到自己坐在一辆马车上..."],
                    "scenarios": ["穿越开局", "场景转换", "氛围渲染"],
                    "tags": ["开篇", "环境描写", "氛围"]
                },
                {
                    "category": "structure",
                    "principle": "用'睁眼'等简单动作直接切入穿越场景，避免冗长的前世回忆",
                    "examples": ["路胜一睁眼，便看到自己坐在一辆黄灰色的马车上"],
                    "scenarios": ["穿越开局", "场景切入"],
                    "tags": ["穿越", "开篇", "节奏"]
                },
                {
                    "category": "worldbuilding",
                    "principle": "通过县志记录、对话等方式分层揭示世界观，让读者逐步了解世界危险",
                    "examples": ["大宋七十二年，九连城郊出现一人，疯癫中持刀连杀十二人..."],
                    "scenarios": ["世界观铺陈", "危机感营造"],
                    "tags": ["世界观", "铺垫", "记录体"]
                },
                {
                    "category": "character",
                    "principle": "通过行为而非心理描写塑造主角性格：务实、谨慎、低调、果断",
                    "examples": ["路胜走过去，伸手从他身上拔出朴刀。在尸体上擦拭了下刀身。'走吧，送我回去。'"],
                    "scenarios": ["主角塑造", "性格刻画"],
                    "tags": ["人物", "行为描写", "性格"]
                },
                {
                    "category": "pacing",
                    "principle": "战斗描写简洁有力，一击必杀，战后冷静处理（如擦刀就走）",
                    "examples": ["哧！一把朴刀刀尖从他胸口穿出。血缓缓顺着伤口渗出。"],
                    "scenarios": ["战斗场景", "节奏控制"],
                    "tags": ["战斗", "节奏", "简洁"]
                }
            ]
        }

        return json.dumps(result, ensure_ascii=False, indent=2)


def create_llm_client(
    provider: str = "zhipu",
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None
) -> LLMClient:
    """
    创建 LLM 客户端

    Args:
        provider: 提供者类型 (zhipu, openai, mock)
        api_key: API 密钥
        model: 模型名称
        base_url: API 基础 URL

    Returns:
        LLMClient: LLM 客户端实例
    """
    provider = provider.lower()

    if provider == "zhipu":
        return ZhipuClient(
            api_key=api_key,
            model=model or "glm-4-flash",
            base_url=base_url
        )
    elif provider == "openai":
        return OpenAIClient(
            api_key=api_key,
            model=model or "gpt-3.5-turbo",
            base_url=base_url
        )
    elif provider == "mock" or provider == "none":
        return MockLLMClient()
    else:
        raise ValueError(f"Unknown LLM provider: {provider}")
