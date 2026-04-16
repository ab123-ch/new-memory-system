"""文件路径管理器"""
from datetime import datetime, date
from pathlib import Path
from typing import Optional


class PathManager:
    """管理记忆文件的路径"""

    def __init__(self, base_path: str = "./data/memory"):
        self.base_path = Path(base_path)
        self._ensure_base_path()

    def _ensure_base_path(self):
        """确保基础路径存在"""
        self.base_path.mkdir(parents=True, exist_ok=True)

    def get_soul_path(self) -> Path:
        """获取本元记忆文件路径"""
        return self.base_path / "soul.yaml"

    def get_global_index_path(self) -> Path:
        """获取全局索引文件路径"""
        return self.base_path / "index.yaml"

    def get_month_dir(self, date_obj: date) -> Path:
        """获取月份目录路径"""
        month_dir = self.base_path / date_obj.strftime("%Y-%m")
        month_dir.mkdir(parents=True, exist_ok=True)
        return month_dir

    def get_daily_memory_path(self, date_obj: date) -> Path:
        """获取每日记忆文件路径"""
        month_dir = self.get_month_dir(date_obj)
        filename = date_obj.strftime("%Y-%m-%d.yaml")
        return month_dir / filename

    def get_daily_index_path(self, date_obj: date) -> Path:
        """获取每日索引文件路径"""
        month_dir = self.get_month_dir(date_obj)
        filename = date_obj.strftime("%Y-%m-%d.index.yaml")
        return month_dir / filename

    def get_today_memory_path(self) -> Path:
        """获取今天的记忆文件路径"""
        return self.get_daily_memory_path(date.today())

    def get_today_index_path(self) -> Path:
        """获取今天的索引文件路径"""
        return self.get_daily_index_path(date.today())

    def list_month_dirs(self) -> list[Path]:
        """列出所有月份目录"""
        dirs = []
        for item in self.base_path.iterdir():
            if item.is_dir() and len(item.name) == 7 and "-" in item.name:
                try:
                    year, month = item.name.split("-")
                    if year.isdigit() and month.isdigit():
                        dirs.append(item)
                except ValueError:
                    continue
        return sorted(dirs)

    def list_daily_files(self, month_dir: Optional[Path] = None) -> list[Path]:
        """列出每日记忆文件"""
        if month_dir:
            dirs = [month_dir]
        else:
            dirs = self.list_month_dirs()

        files = []
        for d in dirs:
            for item in d.iterdir():
                if item.is_file() and item.name.endswith(".yaml") and "index" not in item.name:
                    files.append(item)

        return sorted(files)

    def list_index_files(self, month_dir: Optional[Path] = None) -> list[Path]:
        """列出索引文件"""
        if month_dir:
            dirs = [month_dir]
        else:
            dirs = self.list_month_dirs()

        files = []
        for d in dirs:
            for item in d.iterdir():
                if item.is_file() and item.name.endswith(".index.yaml"):
                    files.append(item)

        return sorted(files)

    def parse_date_from_filename(self, filename: str) -> Optional[date]:
        """从文件名解析日期"""
        try:
            # 格式: YYYY-MM-DD.yaml 或 YYYY-MM-DD.index.yaml
            date_str = filename.replace(".index.yaml", "").replace(".yaml", "")
            return datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return None

    def get_relative_path(self, full_path: Path) -> str:
        """获取相对路径（用于索引）"""
        try:
            return str(full_path.relative_to(self.base_path))
        except ValueError:
            return str(full_path)

    def file_exists(self, path: Path) -> bool:
        """检查文件是否存在"""
        return path.exists() and path.is_file()
