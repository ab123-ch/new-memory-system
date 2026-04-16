"""Token 统计收集器 - 跟踪 API 使用情况"""
from datetime import datetime, date
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from pathlib import Path
import json
import asyncio
from collections import defaultdict


@dataclass
class UsageStats:
    """使用统计"""
    date: str  # YYYY-MM-DD
    provider: str
    model: str

    # Token 统计
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    # 调用统计
    api_calls: int = 0
    errors: int = 0

    # 功能统计
    summarization_calls: int = 0
    extraction_calls: int = 0
    embedding_calls: int = 0

    # 成本估算（美元）
    estimated_cost: float = 0.0

    updated_at: datetime = field(default_factory=datetime.now)


class TokenStats:
    """
    Token 统计收集器

    功能：
    1. 记录每次 API 调用的 token 使用
    2. 按日期、模型统计
    3. 估算成本
    4. 持久化存储
    """

    # 各模型的定价（美元 / 1K tokens）
    # 数据可能过时，请参考官方最新价格
    PRICING = {
        # 智谱
        "glm-4-flash": {"input": 0.0001, "output": 0.0001},
        "glm-4": {"input": 0.014, "output": 0.014},
        "glm-4-plus": {"input": 0.05, "output": 0.05},
        "embedding-3": {"input": 0.0005, "output": 0},

        # OpenAI
        "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
        "gpt-4": {"input": 0.03, "output": 0.06},
        "gpt-4-turbo": {"input": 0.01, "output": 0.03},
        "text-embedding-3-small": {"input": 0.00002, "output": 0},
        "text-embedding-3-large": {"input": 0.00013, "output": 0},

        # 默认
        "default": {"input": 0.001, "output": 0.002}
    }

    def __init__(self, storage_path: str = "./data/stats"):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)

        self._stats: Dict[str, UsageStats] = {}
        self._lock = asyncio.Lock()

    def _get_stats_key(self, date_str: str, provider: str, model: str) -> str:
        """生成统计键"""
        return f"{date_str}_{provider}_{model}"

    def _get_today_stats(self, provider: str, model: str) -> UsageStats:
        """获取今日统计"""
        today = str(date.today())
        key = self._get_stats_key(today, provider, model)

        if key not in self._stats:
            # 尝试从文件加载
            stats = self._load_stats(today, provider, model)
            if stats:
                self._stats[key] = stats
            else:
                self._stats[key] = UsageStats(
                    date=today,
                    provider=provider,
                    model=model
                )

        return self._stats[key]

    def record_usage(
        self,
        provider: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        call_type: str = "chat"  # chat, summarization, extraction, embedding
    ) -> Dict[str, Any]:
        """
        记录使用情况

        Args:
            provider: 提供者
            model: 模型名称
            prompt_tokens: 输入 tokens
            completion_tokens: 输出 tokens
            call_type: 调用类型

        Returns:
            记录结果
        """
        stats = self._get_today_stats(provider, model)

        stats.prompt_tokens += prompt_tokens
        stats.completion_tokens += completion_tokens
        stats.total_tokens += prompt_tokens + completion_tokens
        stats.api_calls += 1

        # 更新功能统计
        if call_type == "summarization":
            stats.summarization_calls += 1
        elif call_type == "extraction":
            stats.extraction_calls += 1
        elif call_type == "embedding":
            stats.embedding_calls += 1

        # 计算成本
        pricing = self.PRICING.get(model, self.PRICING["default"])
        cost = (
            prompt_tokens * pricing["input"] / 1000 +
            completion_tokens * pricing["output"] / 1000
        )
        stats.estimated_cost += cost

        stats.updated_at = datetime.now()

        return {
            "provider": provider,
            "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "estimated_cost": cost
        }

    def record_error(self, provider: str, model: str):
        """记录错误"""
        stats = self._get_today_stats(provider, model)
        stats.errors += 1
        stats.updated_at = datetime.now()

    def get_daily_summary(self, date_str: Optional[str] = None) -> Dict[str, Any]:
        """
        获取每日统计摘要

        Args:
            date_str: 日期字符串，默认今天

        Returns:
            统计摘要
        """
        if date_str is None:
            date_str = str(date.today())

        # 汇总当天所有模型
        total_prompt = 0
        total_completion = 0
        total_tokens = 0
        total_calls = 0
        total_errors = 0
        total_cost = 0.0

        by_model: Dict[str, Dict[str, Any]] = {}

        for key, stats in self._stats.items():
            if stats.date == date_str:
                total_prompt += stats.prompt_tokens
                total_completion += stats.completion_tokens
                total_tokens += stats.total_tokens
                total_calls += stats.api_calls
                total_errors += stats.errors
                total_cost += stats.estimated_cost

                model_key = f"{stats.provider}/{stats.model}"
                by_model[model_key] = {
                    "prompt_tokens": stats.prompt_tokens,
                    "completion_tokens": stats.completion_tokens,
                    "total_tokens": stats.total_tokens,
                    "api_calls": stats.api_calls,
                    "errors": stats.errors,
                    "estimated_cost": stats.estimated_cost
                }

        return {
            "date": date_str,
            "total_prompt_tokens": total_prompt,
            "total_completion_tokens": total_completion,
            "total_tokens": total_tokens,
            "total_api_calls": total_calls,
            "total_errors": total_errors,
            "total_estimated_cost": round(total_cost, 4),
            "by_model": by_model
        }

    def get_weekly_summary(self) -> Dict[str, Any]:
        """获取本周统计摘要"""
        from datetime import timedelta

        today = date.today()
        week_start = today - timedelta(days=today.weekday())

        daily_summaries = []
        for i in range(7):
            day = week_start + timedelta(days=i)
            daily_summaries.append(self.get_daily_summary(str(day)))

        # 汇总
        total_tokens = sum(s["total_tokens"] for s in daily_summaries)
        total_calls = sum(s["total_api_calls"] for s in daily_summaries)
        total_cost = sum(s["total_estimated_cost"] for s in daily_summaries)

        return {
            "week_start": str(week_start),
            "week_end": str(week_start + timedelta(days=6)),
            "total_tokens": total_tokens,
            "total_api_calls": total_calls,
            "total_estimated_cost": round(total_cost, 4),
            "daily": daily_summaries
        }

    async def save(self):
        """保存统计到文件"""
        async with self._lock:
            for stats in self._stats.values():
                self._save_stats(stats)

    def _save_stats(self, stats: UsageStats):
        """保存单个统计"""
        file_path = self.storage_path / f"{stats.date}.json"

        # 加载现有数据
        data = {}
        if file_path.exists():
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                pass

        # 更新数据
        key = f"{stats.provider}_{stats.model}"
        data[key] = {
            "date": stats.date,
            "provider": stats.provider,
            "model": stats.model,
            "prompt_tokens": stats.prompt_tokens,
            "completion_tokens": stats.completion_tokens,
            "total_tokens": stats.total_tokens,
            "api_calls": stats.api_calls,
            "errors": stats.errors,
            "summarization_calls": stats.summarization_calls,
            "extraction_calls": stats.extraction_calls,
            "embedding_calls": stats.embedding_calls,
            "estimated_cost": stats.estimated_cost,
            "updated_at": stats.updated_at.isoformat()
        }

        # 保存
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _load_stats(self, date_str: str, provider: str, model: str) -> Optional[UsageStats]:
        """从文件加载统计"""
        file_path = self.storage_path / f"{date_str}.json"

        if not file_path.exists():
            return None

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            key = f"{provider}_{model}"
            if key in data:
                item = data[key]
                return UsageStats(
                    date=item["date"],
                    provider=item["provider"],
                    model=item["model"],
                    prompt_tokens=item.get("prompt_tokens", 0),
                    completion_tokens=item.get("completion_tokens", 0),
                    total_tokens=item.get("total_tokens", 0),
                    api_calls=item.get("api_calls", 0),
                    errors=item.get("errors", 0),
                    summarization_calls=item.get("summarization_calls", 0),
                    extraction_calls=item.get("extraction_calls", 0),
                    embedding_calls=item.get("embedding_calls", 0),
                    estimated_cost=item.get("estimated_cost", 0.0),
                    updated_at=datetime.fromisoformat(item["updated_at"])
                )
        except Exception:
            pass

        return None

    def format_report(self, summary: Dict[str, Any]) -> str:
        """格式化报告"""
        lines = [
            f"📊 API 使用统计 - {summary.get('date', summary.get('week_start', ''))}",
            "",
            f"  总调用次数: {summary.get('total_api_calls', 0)}",
            f"  总 Tokens: {summary.get('total_tokens', 0):,}",
            f"  预估成本: ${summary.get('total_estimated_cost', 0):.4f}",
        ]

        if "by_model" in summary:
            lines.append("")
            lines.append("  按模型:")
            for model, data in summary["by_model"].items():
                lines.append(f"    {model}: {data['total_tokens']:,} tokens, ${data['estimated_cost']:.4f}")

        return "\n".join(lines)
