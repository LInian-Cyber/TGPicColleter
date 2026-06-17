"""
日志系统模块
提供统一的日志记录功能，将下载过程详细记录到文件
"""

import logging
from pathlib import Path
from datetime import datetime
from PySide6.QtCore import QStandardPaths


class DownloadLogger:
    """下载日志管理器"""
    
    def __init__(self):
        self.log_dir = Path(
            QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation)
        ) / "TGCommentCollector" / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # 创建日志文件名（按日期）
        log_file = self.log_dir / f"download_{datetime.now().strftime('%Y%m%d')}.log"
        
        # 配置日志器
        self.logger = logging.getLogger("TGPicCollector")
        self.logger.setLevel(logging.DEBUG)
        
        # 避免重复添加处理器
        if not self.logger.handlers:
            # 文件处理器
            file_handler = logging.FileHandler(log_file, encoding="utf-8")
            file_handler.setLevel(logging.DEBUG)
            file_formatter = logging.Formatter(
                "%(asctime)s [%(levelname)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            )
            file_handler.setFormatter(file_formatter)
            self.logger.addHandler(file_handler)
            
            # 控制台处理器（可选）
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            console_formatter = logging.Formatter("[%(levelname)s] %(message)s")
            console_handler.setFormatter(console_formatter)
            self.logger.addHandler(console_handler)
    
    def info(self, message: str):
        """记录信息"""
        self.logger.info(message)
    
    def debug(self, message: str):
        """记录调试信息"""
        self.logger.debug(message)
    
    def warning(self, message: str):
        """记录警告"""
        self.logger.warning(message)
    
    def error(self, message: str):
        """记录错误"""
        self.logger.error(message)
    
    def task_started(self, channel: str, tag: str):
        """记录任务开始"""
        self.info(f"===== 任务开始 =====")
        self.info(f"频道: {channel}")
        self.info(f"标签: {tag or '全部'}")
    
    def task_completed(self, posts: int, downloaded: int, skipped: int, cancelled: bool = False):
        """记录任务结束"""
        result = "任务已取消" if cancelled else "任务完成"
        self.info(f"{result} - 匹配帖子: {posts}, 下载: {downloaded}, 跳过: {skipped}")
        self.info(f"===== 任务结束 =====\n")
    
    def post_scanning(
        self,
        post_id: int,
        has_replies: bool,
        scan_links: bool = False,
        scan_replies: bool = False,
    ):
        """记录帖子扫描"""
        link_state = "开启" if scan_links else "关闭"
        if not scan_replies:
            reply_state = "未启用"
        else:
            reply_state = "可扫描" if has_replies else "无评论"
        self.debug(
            f"扫描帖子 #{post_id} (正文链接追踪: {link_state}, 评论区扫描: {reply_state})"
        )
    
    def file_downloaded(self, post_id: int, filename: str):
        """记录文件下载"""
        self.info(f"已下载 - 帖子 #{post_id}: {filename}")
    
    def file_skipped(self, post_id: int, filename: str, reason: str = "已存在"):
        """记录文件跳过"""
        self.debug(f"已跳过 - 帖子 #{post_id}: {filename} ({reason})")
    
    def get_log_path(self) -> Path:
        """获取当前日志文件路径"""
        return self.log_dir / f"download_{datetime.now().strftime('%Y%m%d')}.log"


# 全局日志实例
_logger_instance = None


def get_logger() -> DownloadLogger:
    """获取全局日志实例"""
    global _logger_instance
    if _logger_instance is None:
        _logger_instance = DownloadLogger()
    return _logger_instance
