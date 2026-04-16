"""配置管理 - 加载和管理系统配置"""
import os
import json
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
import yaml


def _load_model_config() -> Dict[str, Any]:
    """
    从 model_config.yaml 读取模型配置（包括 API Key）

    Returns:
        Dict: 模型配置字典
    """
    config = {}
    possible_paths = [
        Path.cwd() / "model_config.yaml",
        Path(__file__).parent.parent / "model_config.yaml",
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


def _load_claude_settings_env() -> Dict[str, str]:
    """
    从 Claude Code 的 settings.json 读取环境变量

    Returns:
        Dict[str, str]: 环境变量字典
    """
    env_vars = {}
    settings_path = Path.home() / ".claude" / "settings.json"

    if settings_path.exists():
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                env_vars = data.get("env", {})
        except (json.JSONDecodeError, IOError):
            pass

    return env_vars


# 启动时加载配置
_MODEL_CONFIG = _load_model_config()
_CLAUDE_ENV = _load_claude_settings_env()


def _get_api_key(key_names: List[str], config_section: str = "llm") -> Optional[str]:
    """
    依次从多个来源获取 API Key

    优先级: model_config.yaml > Claude settings > 环境变量

    Args:
        key_names: API Key 的可能名称列表
        config_section: model_config.yaml 中的配置段 (llm/embedding)

    Returns:
        找到的 API Key，或 None
    """
    # 1. 先从 model_config.yaml 找
    section = _MODEL_CONFIG.get(config_section, {})
    api_key = section.get("api_key")
    if api_key:
        return api_key

    # 如果 embedding 没有单独配置 api_key，尝试用 llm 的
    if config_section == "embedding":
        llm_section = _MODEL_CONFIG.get("llm", {})
        api_key = llm_section.get("api_key")
        if api_key:
            return api_key

    # 2. 从 Claude settings 找
    for name in key_names:
        if name in _CLAUDE_ENV and _CLAUDE_ENV[name]:
            return _CLAUDE_ENV[name]

    # 3. 从环境变量找
    for name in key_names:
        value = os.environ.get(name)
        if value:
            return value

    return None


def get_model_config() -> Dict[str, Any]:
    """获取 model_config.yaml 的配置"""
    return _MODEL_CONFIG


def reload_model_config() -> Dict[str, Any]:
    """重新加载 model_config.yaml"""
    global _MODEL_CONFIG
    _MODEL_CONFIG = _load_model_config()
    return _MODEL_CONFIG


@dataclass
class EmbeddingConfig:
    """嵌入模型配置"""
    provider: str = "zhipu"  # zhipu, openai, sentence_transformers, none
    model: str = "embedding-3"
    dimensions: int = 1024
    api_key: Optional[str] = None
    base_url: Optional[str] = None


@dataclass
class VectorConfig:
    """向量存储配置"""
    enabled: bool = True
    provider: str = "chroma"  # chroma, faiss, none
    persist_path: str = "./data/vectors"
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)


@dataclass
class LLMConfig:
    """LLM 配置"""
    provider: str = "zhipu"  # zhipu, openai, anthropic, ollama, none
    model: str = "glm-4-flash"
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    temperature: float = 0.3
    max_tokens: int = 500


@dataclass
class AIConfig:
    """AI 功能配置"""
    enabled: bool = True
    llm: LLMConfig = field(default_factory=LLMConfig)
    summarization_enabled: bool = True
    summarization_max_length: int = 200
    keyword_extraction_enabled: bool = True
    keyword_extraction_max: int = 10


@dataclass
class AutoSaveConfig:
    """自动保存配置"""
    enabled: bool = True
    immediate: bool = True
    index_to_vector: bool = True
    debounce_seconds: float = 2.0


@dataclass
class StorageConfig:
    """存储配置"""
    path: str = "./data/memory"


@dataclass
class MemorySystemConfig:
    """记忆系统完整配置"""
    storage: StorageConfig = field(default_factory=StorageConfig)
    vector: VectorConfig = field(default_factory=VectorConfig)
    ai: AIConfig = field(default_factory=AIConfig)
    auto_save: AutoSaveConfig = field(default_factory=AutoSaveConfig)


def load_config(config_path: Optional[str] = None) -> MemorySystemConfig:
    """
    加载配置文件

    Args:
        config_path: 配置文件路径，默认为当前目录的 memory_config.yaml

    Returns:
        MemorySystemConfig: 配置对象
    """
    if config_path is None:
        # 查找配置文件
        possible_paths = [
            Path.cwd() / "memory_config.yaml",
            Path(__file__).parent.parent / "memory_config.yaml",
            Path.home() / ".memory_system" / "config.yaml",
        ]
        for p in possible_paths:
            if p.exists():
                config_path = str(p)
                break

    if config_path and Path(config_path).exists():
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return _parse_config(data)

    return MemorySystemConfig()


def _parse_config(data: Dict[str, Any]) -> MemorySystemConfig:
    """解析配置数据"""
    # 存储配置
    storage_data = data.get("storage", {})
    storage = StorageConfig(
        path=storage_data.get("path", "./data/memory")
    )

    # 向量配置
    vector_data = data.get("vector", {})
    embedding_data = vector_data.get("embedding", {})

    # 从 model_config.yaml / Claude settings / 环境变量获取 API Key
    embedding_api_key = embedding_data.get("api_key") or _get_api_key(["ZHIPU_API_KEY", "OPENAI_API_KEY"], "embedding")

    embedding = EmbeddingConfig(
        provider=embedding_data.get("provider", "zhipu"),
        model=embedding_data.get("model", "embedding-3"),
        dimensions=embedding_data.get("dimensions", 1024),
        api_key=embedding_api_key,
        base_url=embedding_data.get("base_url")
    )

    vector = VectorConfig(
        enabled=vector_data.get("enabled", True),
        provider=vector_data.get("provider", "chroma"),
        persist_path=vector_data.get("persist_path", "./data/vectors"),
        embedding=embedding
    )

    # AI 配置
    ai_data = data.get("ai", {})
    llm_data = ai_data.get("llm", {})

    # 从 model_config.yaml / Claude settings / 环境变量获取 LLM API Key
    llm_api_key = llm_data.get("api_key") or _get_api_key(["ZHIPU_API_KEY", "OPENAI_API_KEY"], "llm")

    llm = LLMConfig(
        provider=llm_data.get("provider", "zhipu"),
        model=llm_data.get("model", "glm-4-flash"),
        api_key=llm_api_key,
        base_url=llm_data.get("base_url"),
        temperature=llm_data.get("temperature", 0.3),
        max_tokens=llm_data.get("max_tokens", 500)
    )

    summ_data = ai_data.get("summarization", {})
    kw_data = ai_data.get("keyword_extraction", {})

    ai = AIConfig(
        enabled=ai_data.get("enabled", True),
        llm=llm,
        summarization_enabled=summ_data.get("enabled", True),
        summarization_max_length=summ_data.get("max_length", 200),
        keyword_extraction_enabled=kw_data.get("enabled", True),
        keyword_extraction_max=kw_data.get("max_keywords", 10)
    )

    # 自动保存配置
    auto_save_data = data.get("auto_save", {})
    auto_save = AutoSaveConfig(
        enabled=auto_save_data.get("enabled", True),
        immediate=auto_save_data.get("immediate", True),
        index_to_vector=auto_save_data.get("index_to_vector", True),
        debounce_seconds=auto_save_data.get("debounce_seconds", 2.0)
    )

    return MemorySystemConfig(
        storage=storage,
        vector=vector,
        ai=ai,
        auto_save=auto_save
    )


# 全局配置实例
_config: Optional[MemorySystemConfig] = None


def get_config() -> MemorySystemConfig:
    """获取全局配置实例"""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def reload_config(config_path: Optional[str] = None) -> MemorySystemConfig:
    """重新加载配置"""
    global _config
    _config = load_config(config_path)
    return _config
