"""OpenCode 配置模块"""

from typing import Optional

from pydantic import BaseModel, Field


class OpenCodeConfig(BaseModel):
    """
    OpenCode 配置模型

    所有 LLM 调用通过 OpenCode CLI 的配置参数

    Attributes:
        model: 默认使用的模型
        timeout: 执行超时时间（秒）
        max_retries: 最大重试次数
        models: 可用模型列表
        working_dir: 工作目录
        compaction_threshold: 压缩阈值（消息数量）
        warning_tokens: 警告 token 数量
    """

    model: str = Field(default="glm-4.7", description="默认模型")
    timeout: int = Field(default=300, ge=10, le=3600, description="超时时间(秒)")
    max_retries: int = Field(default=3, ge=0, le=10, description="最大重试次数")
    models: list[str] = Field(
        default=["glm-4.5", "glm-4.6", "glm-4.7", "glm-5"],
        description="可用模型列表"
    )
    working_dir: Optional[str] = Field(default=None, description="工作目录")
    compaction_threshold: int = Field(
        default=10,
        ge=5,
        le=50,
        description="压缩阈值（消息数量）"
    )
    warning_tokens: int = Field(
        default=60000,
        ge=10000,
        le=200000,
        description="警告 token 数量"
    )

    model_config = {
        "extra": "forbid",
        "str_strip_whitespace": True,
    }
