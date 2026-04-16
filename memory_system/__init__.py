"""
AI对话记忆系统 - "夺舍"架构

基于文件的记忆系统，每次会话通过继承之前的记忆保持连贯性。

新功能 (v2.0):
- 向量语义搜索
- AI 驱动的摘要和关键词提取
- 自动对话保存
- Token 统计
"""

from .models import (
    SoulMemory, Identity, Habit, Ability, PendingMemory,
    DailyMemory, Session, Conversation, Event, Knowledge, Emotion,
    GlobalIndex, DailyIndex, RecentMemory, HotKeyword, ActiveEvent, FileInfo
)
from .storage import FileStore, PathManager
from .core import PossessionManager, TriggerDetector, MemoryRecaller, MemoryWriter
from .extraction import KeywordExtractor, Summarizer, NoiseFilter
from .extraction.summary_cache import SummaryCache, ConversationSummaryEntry, get_summary_cache
from .session import MemorySession, MemorySystem

# 新模块
from .config import (
    MemorySystemConfig, load_config, get_config, reload_config,
    VectorConfig, AIConfig, AutoSaveConfig, StorageConfig
)

# 可选导入（依赖可能未安装）
try:
    from .vector import (
        EmbeddingProvider, ZhipuEmbedding, OpenAIEmbedding, MockEmbedding,
        VectorStore, MemoryVector, SearchResult, ChromaVectorStore, NoVectorStore
    )
    _vector_available = True
except ImportError:
    _vector_available = False

try:
    from .auto_save import AutoRecorder, ConversationRecord
    _auto_save_available = True
except ImportError:
    _auto_save_available = False

try:
    from .ai import (
        LLMClient, ZhipuClient, OpenAIClient, MockLLMClient,
        AISummarizer, AIKeywordExtractor
    )
    _ai_available = True
except ImportError:
    _ai_available = False

try:
    from .stats import TokenStats, UsageStats
    _stats_available = True
except ImportError:
    _stats_available = False

# 统一日志配置
try:
    from .logging_config import (
        init_logging, get_logger, get_log_path, cleanup_logs, get_logging_stats
    )
    _logging_available = True
except ImportError:
    _logging_available = False

__version__ = "2.0.0"
__author__ = "AI Memory System"

__all__ = [
    # Models
    "SoulMemory", "Identity", "Habit", "Ability", "PendingMemory",
    "DailyMemory", "Session", "Conversation", "Event", "Knowledge", "Emotion",
    "GlobalIndex", "DailyIndex", "RecentMemory", "HotKeyword", "ActiveEvent", "FileInfo",
    # Storage
    "FileStore", "PathManager",
    # Core
    "PossessionManager", "TriggerDetector", "MemoryRecaller", "MemoryWriter",
    # Extraction
    "KeywordExtractor", "Summarizer", "NoiseFilter",
    "SummaryCache", "ConversationSummaryEntry", "get_summary_cache",
    # Main classes
    "MemorySession", "MemorySystem",
    # Config
    "MemorySystemConfig", "load_config", "get_config", "reload_config",
    "VectorConfig", "AIConfig", "AutoSaveConfig", "StorageConfig",
]

# 条件导出
if _vector_available:
    __all__.extend([
        "EmbeddingProvider", "ZhipuEmbedding", "OpenAIEmbedding", "MockEmbedding",
        "VectorStore", "MemoryVector", "SearchResult", "ChromaVectorStore", "NoVectorStore"
    ])

if _auto_save_available:
    __all__.extend(["AutoRecorder", "ConversationRecord"])

if _ai_available:
    __all__.extend([
        "LLMClient", "ZhipuClient", "OpenAIClient", "MockLLMClient",
        "AISummarizer", "AIKeywordExtractor"
    ])

if _stats_available:
    __all__.extend(["TokenStats", "UsageStats"])

if _logging_available:
    __all__.extend([
        "init_logging", "get_logger", "get_log_path", "cleanup_logs", "get_logging_stats"
    ])
