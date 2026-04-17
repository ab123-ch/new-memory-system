"""
通用 LLM 调用工具 - Hook 共享模块

支持所有 OpenAI 兼容 API 的 LLM 提供商，只需配置 base_url + api_key + model 即可切换。
"""

import json
import os
import sys
import urllib.request
import urllib.error
import yaml
from pathlib import Path
from typing import Optional, Dict


# ============== Provider 默认配置 ==============

PROVIDER_DEFAULTS = {
    "zhipu": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "model": "glm-4-flash",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1/chat/completions",
        "model": "gpt-4o-mini",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1/chat/completions",
        "model": "deepseek-chat",
    },
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "model": "qwen-plus",
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1/chat/completions",
        "model": "qwen2.5:7b",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1/chat/completions",
        "model": "deepseek/deepseek-chat",
    },
}


# ============== 配置加载 ==============

_config_cache = None


def load_llm_config() -> Dict:
    """从 model_config.yaml 加载 LLM 配置"""
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    config_paths = [
        Path(__file__).parent.parent / "model_config.yaml",  # MCP 安装目录
        Path.home() / ".claude" / "mcp" / "memory-system" / "model_config.yaml",
    ]

    for config_path in config_paths:
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = yaml.safe_load(f) or {}
                _config_cache = config
                return config
            except Exception:
                pass

    _config_cache = {}
    return _config_cache


def get_llm_settings() -> Dict:
    """
    获取合并后的 LLM 调用参数

    合并逻辑：model_config.yaml 中的显式值 > provider 默认值
    """
    config = load_llm_config()
    llm = config.get("llm", {})
    provider = llm.get("provider", "zhipu").lower()

    # 获取 provider 默认值
    defaults = PROVIDER_DEFAULTS.get(provider, {})

    return {
        "provider": provider,
        "api_key": llm.get("api_key", ""),
        "model": llm.get("model") or defaults.get("model", "glm-4-flash"),
        "base_url": llm.get("base_url") or defaults.get("base_url", ""),
        "temperature": llm.get("temperature", 0.3),
        "max_tokens": llm.get("max_tokens", 2000),
    }


# ============== 通用 LLM 调用 ==============

LLM_TIMEOUT = 30  # 秒


def call_llm(prompt: str, system_prompt: Optional[str] = None) -> Optional[str]:
    """
    调用 LLM，返回模型输出文本

    使用标准 OpenAI 兼容 API 格式，支持所有主流 LLM 提供商。

    Args:
        prompt: 用户提示词
        system_prompt: 可选系统提示词

    Returns:
        模型返回的文本，失败返回 None
    """
    settings = get_llm_settings()
    api_key = settings["api_key"]
    model = settings["model"]
    base_url = settings["base_url"]
    temperature = settings["temperature"]
    max_tokens = settings["max_tokens"]
    provider = settings["provider"]

    if not api_key:
        _log(f"[llm_utils] API Key 未配置 (provider={provider})，请检查 model_config.yaml")
        return None

    if not base_url:
        _log(f"[llm_utils] provider '{provider}' 的 base_url 为空，请检查配置")
        return None

    # 构建消息
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    body = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens
    }).encode("utf-8")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # OpenRouter 需要额外的 header
    if provider == "openrouter":
        headers["HTTP-Referer"] = "https://github.com/memory-system"
        headers["X-Title"] = "Memory System MCP"

    req = urllib.request.Request(base_url, data=body, headers=headers)

    try:
        _log(f"[llm_utils] 调用 {provider}/{model}...")
        with urllib.request.urlopen(req, timeout=LLM_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"]
            _log(f"[llm_utils] API 返回成功，长度: {len(content)}")
            return content
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")[:300]
        _log(f"[llm_utils] HTTP 错误 {e.code}: {err_body}")
        return None
    except Exception as e:
        _log(f"[llm_utils] 调用失败: {e}")
        return None


# ============== 日志 ==============

def _log(msg: str):
    """统一日志输出"""
    print(msg, file=sys.stderr)
