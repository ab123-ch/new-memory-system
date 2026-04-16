"""
文件锁机制 - 解决并发写入冲突

提供跨进程的文件锁，确保同一时间只有一个进程可以写入记忆文件。

使用方式：
1. 上下文管理器：with FileLock(path): ...
2. 手动控制：lock = FileLock(path); lock.acquire(); lock.release()

实现原理：
- Unix: fcntl.flock (BSD 风格的文件锁)
- Windows: msvcrt.locking 或 portalocker
- 降级: 如果无法获取锁，使用时间戳 + 重试机制
"""

import os
import time
import logging
import platform
from pathlib import Path
from typing import Optional
from contextlib import contextmanager
from datetime import datetime

logger = logging.getLogger(__name__)


class FileLockError(Exception):
    """文件锁错误"""
    pass


class FileLockTimeout(FileLockError):
    """获取锁超时"""
    pass


class FileLock:
    """
    跨进程文件锁

    使用方法：
        with FileLock("/path/to/file.yaml", timeout=10):
            # 读写文件
            pass
    """

    def __init__(
        self,
        file_path: str,
        timeout: float = 30.0,
        retry_interval: float = 0.1,
        lock_suffix: str = ".lock"
    ):
        """
        初始化文件锁

        Args:
            file_path: 要锁定的文件路径
            timeout: 获取锁的超时时间（秒）
            retry_interval: 重试间隔（秒）
            lock_suffix: 锁文件后缀
        """
        self.file_path = Path(file_path)
        self.timeout = timeout
        self.retry_interval = retry_interval

        # 锁文件路径
        self.lock_file = self.file_path.with_suffix(
            self.file_path.suffix + lock_suffix
        )

        self._lock_fd: Optional[int] = None
        self._is_windows = platform.system() == "Windows"

    def acquire(self, blocking: bool = True) -> bool:
        """
        获取锁

        Args:
            blocking: 是否阻塞等待

        Returns:
            是否成功获取锁

        Raises:
            FileLockTimeout: 超时未能获取锁
        """
        start_time = time.time()

        while True:
            try:
                # 创建/打开锁文件
                self._lock_fd = os.open(
                    str(self.lock_file),
                    os.O_CREAT | os.O_RDWR,
                    0o644
                )

                # 尝试获取锁
                if self._is_windows:
                    return self._acquire_windows(blocking)
                else:
                    return self._acquire_unix(blocking)

            except (IOError, OSError) as e:
                if self._lock_fd is not None:
                    try:
                        os.close(self._lock_fd)
                    except:
                        pass
                    self._lock_fd = None

                if not blocking:
                    return False

                # 检查超时
                elapsed = time.time() - start_time
                if elapsed >= self.timeout:
                    raise FileLockTimeout(
                        f"获取文件锁超时: {self.file_path} (等待 {elapsed:.1f}s)"
                    )

                # 等待后重试
                time.sleep(self.retry_interval)

    def _acquire_unix(self, blocking: bool) -> bool:
        """Unix 系统获取锁"""
        import fcntl

        try:
            if blocking:
                fcntl.flock(self._lock_fd, fcntl.LOCK_EX)
            else:
                fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except (IOError, OSError) as e:
            if not blocking and e.errno in (11, 35):  # EAGAIN or EWOULDBLOCK
                return False
            raise

    def _acquire_windows(self, blocking: bool) -> bool:
        """Windows 系统获取锁"""
        try:
            import msvcrt
            if blocking:
                msvcrt.locking(self._lock_fd, msvcrt.LK_LOCK, 1)
            else:
                msvcrt.locking(self._lock_fd, msvcrt.LK_NBLCK, 1)
            return True
        except (IOError, OSError):
            if not blocking:
                return False
            raise
        except ImportError:
            # 没有 msvcrt，使用 portalocker 或降级方案
            return self._acquire_fallback(blocking)

    def _acquire_fallback(self, blocking: bool) -> bool:
        """降级方案：使用文件存在检查"""
        if self.lock_file.exists():
            # 检查锁是否过期（超过 60 秒认为是死锁）
            try:
                mtime = self.lock_file.stat().st_mtime
                if time.time() - mtime > 60:
                    logger.warning(f"检测到过期锁，强制清除: {self.lock_file}")
                    self.lock_file.unlink()
                else:
                    return False
            except:
                pass

        # 创建锁文件
        try:
            with open(self.lock_file, 'w') as f:
                f.write(f"{os.getpid()}\n{datetime.now().isoformat()}\n")
            return True
        except:
            return False

    def release(self):
        """释放锁"""
        if self._lock_fd is None:
            return

        try:
            if self._is_windows:
                try:
                    import msvcrt
                    msvcrt.locking(self._lock_fd, msvcrt.LK_UNLCK, 1)
                except:
                    pass
            else:
                import fcntl
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)

            os.close(self._lock_fd)
            self._lock_fd = None

            # 删除锁文件
            try:
                self.lock_file.unlink()
            except:
                pass

        except Exception as e:
            logger.warning(f"释放锁时出错: {e}")

    def __enter__(self):
        self.acquire(blocking=True)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
        return False

    def __del__(self):
        if self._lock_fd is not None:
            self.release()


@contextmanager
def file_lock(file_path: str, timeout: float = 30.0):
    """
    文件锁上下文管理器

    用法：
        with file_lock("/path/to/file.yaml"):
            # 读写文件
            pass
    """
    lock = FileLock(file_path, timeout=timeout)
    try:
        lock.acquire(blocking=True)
        yield lock
    finally:
        lock.release()


class LockableFileStore:
    """
    带锁的文件存储混入类

    为 FileStore 添加自动锁定功能
    """

    _lock_timeout: float = 30.0

    def _with_lock(self, file_path: Path, operation, *args, **kwargs):
        """
        在锁的保护下执行文件操作

        Args:
            file_path: 文件路径
            operation: 要执行的操作函数
            *args, **kwargs: 操作的参数

        Returns:
            操作的返回值
        """
        with file_lock(str(file_path), timeout=self._lock_timeout):
            return operation(*args, **kwargs)

    def _read_with_lock(self, file_path: Path) -> Optional[dict]:
        """带锁读取 YAML 文件"""
        import yaml

        if not file_path.exists():
            return None

        with file_lock(str(file_path), timeout=self._lock_timeout):
            with open(file_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}

    def _write_with_lock(self, file_path: Path, data: dict) -> bool:
        """带锁写入 YAML 文件"""
        import yaml

        # 确保目录存在
        file_path.parent.mkdir(parents=True, exist_ok=True)

        with file_lock(str(file_path), timeout=self._lock_timeout):
            with open(file_path, 'w', encoding='utf-8') as f:
                yaml.dump(
                    data,
                    f,
                    allow_unicode=True,
                    sort_keys=False,
                    default_flow_style=False
                )
        return True

    def _modify_with_lock(
        self,
        file_path: Path,
        modify_func,
        default_factory=None
    ) -> bool:
        """
        带锁的读取-修改-写入操作

        Args:
            file_path: 文件路径
            modify_func: 修改函数，接收当前数据，返回修改后的数据
            default_factory: 默认值工厂函数

        Returns:
            是否成功
        """
        import yaml

        with file_lock(str(file_path), timeout=self._lock_timeout):
            # 读取
            data = None
            if file_path.exists():
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        data = yaml.safe_load(f)
                except:
                    pass

            if data is None:
                data = default_factory() if default_factory else {}

            # 修改
            modified_data = modify_func(data)
            if modified_data is None:
                # modify_func 返回 None 表示不需要保存
                return True

            # 写入
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, 'w', encoding='utf-8') as f:
                yaml.dump(
                    modified_data,
                    f,
                    allow_unicode=True,
                    sort_keys=False,
                    default_flow_style=False
                )

        return True
