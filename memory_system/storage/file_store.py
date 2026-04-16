"""YAML文件存储"""
import yaml
from datetime import datetime, date
from pathlib import Path
from typing import Optional, List

from ..models import (
    SoulMemory, DailyMemory, GlobalIndex, DailyIndex,
    Session, Event
)
from .path_manager import PathManager
from .file_lock import file_lock, LockableFileStore

# 统一日志
try:
    from ..logging_config import get_logger
    _logger = get_logger("file_store", "mcp")
except ImportError:
    import logging
    _logger = logging.getLogger(__name__)


class FileStore(LockableFileStore):
    """
    YAML文件存储管理

    继承 LockableFileStore 以支持并发安全。
    所有写入操作都会自动获取文件锁。
    """

    def __init__(self, base_path: str = "./data/memory", lock_timeout: float = 30.0):
        self.path_manager = PathManager(base_path)
        self._lock_timeout = lock_timeout

    def _sanitize_string(self, s: str) -> str:
        """清理字符串中的非法字符（控制字符等）"""
        if not isinstance(s, str):
            return s
        # 移除控制字符（保留换行符、制表符等常用字符）
        import re
        # 移除 null 字节和其他控制字符（除了 \t \n \r）
        return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', s)

    def _sanitize_dict(self, data: dict) -> dict:
        """递归清理字典中所有字符串的非法字符"""
        if not isinstance(data, dict):
            return data
        result = {}
        for k, v in data.items():
            if isinstance(v, str):
                result[k] = self._sanitize_string(v)
            elif isinstance(v, dict):
                result[k] = self._sanitize_dict(v)
            elif isinstance(v, list):
                result[k] = self._sanitize_list(v)
            else:
                result[k] = v
        return result

    def _sanitize_list(self, data: list) -> list:
        """递归清理列表中所有字符串的非法字符"""
        if not isinstance(data, list):
            return data
        result = []
        for item in data:
            if isinstance(item, str):
                result.append(self._sanitize_string(item))
            elif isinstance(item, dict):
                result.append(self._sanitize_dict(item))
            elif isinstance(item, list):
                result.append(self._sanitize_list(item))
            else:
                result.append(item)
        return result

    # ==================== 本元记忆 ====================

    def load_soul(self) -> SoulMemory:
        """加载本元记忆"""
        soul_path = self.path_manager.get_soul_path()

        if self.path_manager.file_exists(soul_path):
            try:
                with open(soul_path, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f) or {}
                return SoulMemory(**data)
            except Exception as e:
                _logger.error(f"加载本元记忆失败: {e}")
                return SoulMemory()

        return SoulMemory()

    def save_soul(self, soul: SoulMemory) -> bool:
        """保存本元记忆（带文件锁）"""
        soul_path = self.path_manager.get_soul_path()

        try:
            soul.updated_at = datetime.now()

            def merge_soul(existing_data: dict) -> dict:
                """合并本元记忆"""
                new_data = soul.model_dump(mode='json')

                if not existing_data:
                    return new_data

                # 合并各个字段
                for field in ['identity', 'habits', 'abilities']:
                    existing_items = existing_data.get(field, [])
                    new_items = new_data.get(field, [])
                    existing_ids = {i.get('id') for i in existing_items}

                    for item in new_items:
                        if item.get('id') not in existing_ids:
                            existing_items.append(item)

                    existing_data[field] = existing_items

                existing_data['updated_at'] = new_data.get('updated_at')
                return existing_data

            return self._modify_with_lock(
                soul_path,
                merge_soul,
                default_factory=lambda: soul.model_dump(mode='json')
            )

        except Exception as e:
            _logger.error(f"保存本元记忆失败: {e}")
            return False

    # ==================== 每日记忆 ====================

    def load_daily_memory(self, date_obj: date) -> DailyMemory:
        """加载指定日期的记忆"""
        file_path = self.path_manager.get_daily_memory_path(date_obj)

        if self.path_manager.file_exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f) or {}

                # 处理日期字段
                if 'date' in data and isinstance(data['date'], str):
                    data['date'] = datetime.strptime(data['date'], "%Y-%m-%d").date()

                return DailyMemory(**data)
            except Exception as e:
                _logger.error(f"加载每日记忆失败 ({date_obj}): {e}")
                return DailyMemory(date=date_obj)

        return DailyMemory(date=date_obj)

    def save_daily_memory(self, memory: DailyMemory) -> bool:
        """
        保存每日记忆（带文件锁，并发安全）

        使用读取-合并-写入模式，避免覆盖其他会话的数据
        """
        file_path = self.path_manager.get_daily_memory_path(memory.date)

        try:
            # 确保目录存在
            file_path.parent.mkdir(parents=True, exist_ok=True)

            def merge_and_save(existing_data: dict) -> dict:
                """合并现有数据和新数据"""
                memory.updated_at = datetime.now()
                new_data = memory.model_dump(mode='json')

                # 如果没有现有数据，直接返回清理后的新数据
                if not existing_data:
                    return self._sanitize_dict(new_data)

                # 合并 sessions
                existing_sessions = existing_data.get('sessions', [])
                new_sessions = new_data.get('sessions', [])

                # 创建 session 索引
                existing_session_ids = {s.get('session_id') for s in existing_sessions}

                # 添加新的 sessions（不覆盖现有的）
                for session in new_sessions:
                    if session.get('session_id') not in existing_session_ids:
                        existing_sessions.append(session)
                    else:
                        # 更新现有 session（合并对话）
                        for es in existing_sessions:
                            if es.get('session_id') == session.get('session_id'):
                                # 合并对话
                                existing_conv_ids = {c.get('id') for c in es.get('conversations', [])}
                                for conv in session.get('conversations', []):
                                    if conv.get('id') not in existing_conv_ids:
                                        es.setdefault('conversations', []).append(conv)
                                # 更新摘要和关键词（如果新的更完整）
                                if session.get('summary') and not es.get('summary'):
                                    es['summary'] = session['summary']
                                if session.get('keywords'):
                                    es.setdefault('keywords', []).extend(
                                        k for k in session['keywords']
                                        if k not in es.get('keywords', [])
                                    )

                # 更新字段
                existing_data['sessions'] = existing_sessions
                existing_data['updated_at'] = new_data.get('updated_at')

                # 清理数据中的非法字符
                return self._sanitize_dict(existing_data)

            # 使用带锁的修改操作
            return self._modify_with_lock(
                file_path,
                merge_and_save,
                default_factory=lambda: self._sanitize_dict(memory.model_dump(mode='json'))
            )

        except Exception as e:
            _logger.error(f"保存每日记忆失败: {e}")
            return False

    def load_today_memory(self) -> DailyMemory:
        """加载今天的记忆"""
        return self.load_daily_memory(date.today())

    def save_today_memory(self, memory: DailyMemory) -> bool:
        """保存今天的记忆"""
        return self.save_daily_memory(memory)

    # ==================== 索引文件 ====================

    def load_global_index(self) -> GlobalIndex:
        """加载全局索引"""
        index_path = self.path_manager.get_global_index_path()

        if self.path_manager.file_exists(index_path):
            try:
                with open(index_path, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f) or {}
                return GlobalIndex(**data)
            except Exception as e:
                _logger.error(f"加载全局索引失败: {e}")
                return GlobalIndex()

        return GlobalIndex()

    def save_global_index(self, index: GlobalIndex) -> bool:
        """保存全局索引（带文件锁）"""
        index_path = self.path_manager.get_global_index_path()

        try:
            index.updated_at = datetime.now()
            return self._write_with_lock(index_path, index.model_dump(mode='json'))
        except Exception as e:
            _logger.error(f"保存全局索引失败: {e}")
            return False

    def load_daily_index(self, date_obj: date) -> DailyIndex:
        """加载每日索引"""
        file_path = self.path_manager.get_daily_index_path(date_obj)

        if self.path_manager.file_exists(file_path):
            try:
                data = self._read_with_lock(file_path)
                if data:
                    return DailyIndex(**data)
            except Exception as e:
                _logger.error(f"加载每日索引失败 ({date_obj}): {e}")

        return DailyIndex(date=date_obj.isoformat())

    def save_daily_index(self, index: DailyIndex) -> bool:
        """保存每日索引（带文件锁）"""
        date_obj = datetime.strptime(index.date, "%Y-%m-%d").date()
        file_path = self.path_manager.get_daily_index_path(date_obj)

        try:
            # 确保目录存在
            file_path.parent.mkdir(parents=True, exist_ok=True)
            return self._write_with_lock(file_path, index.model_dump(mode='json'))
        except Exception as e:
            _logger.error(f"保存每日索引失败: {e}")
            return False

    # ==================== 批量操作 ====================

    def load_recent_memories(self, days: int = 3) -> List[DailyMemory]:
        """加载最近几天的记忆"""
        from datetime import timedelta

        memories = []
        today = date.today()

        for i in range(days):
            target_date = today - timedelta(days=i)
            memory = self.load_daily_memory(target_date)
            if memory.sessions:  # 只返回有内容的
                memories.append(memory)

        return memories

    def search_memories_by_date_range(
        self,
        start_date: date,
        end_date: date
    ) -> List[DailyMemory]:
        """按日期范围搜索记忆"""
        from datetime import timedelta

        memories = []
        current = start_date

        while current <= end_date:
            memory = self.load_daily_memory(current)
            if memory.sessions:
                memories.append(memory)
            current += timedelta(days=1)

        return memories

    def get_file_size(self, path: Path) -> int:
        """获取文件大小"""
        if path.exists():
            return path.stat().st_size
        return 0

    def cleanup_old_files(self, days_to_keep: int = 90) -> int:
        """清理旧文件（返回删除的文件数）"""
        from datetime import timedelta

        deleted = 0
        cutoff_date = date.today() - timedelta(days=days_to_keep)

        for month_dir in self.path_manager.list_month_dirs():
            for file_path in month_dir.glob("*.yaml"):
                file_date = self.path_manager.parse_date_from_filename(file_path.name)
                if file_date and file_date < cutoff_date:
                    try:
                        file_path.unlink()
                        deleted += 1
                    except Exception:
                        pass

        return deleted
