"""
日志配置模块

设置应用程序的日志格式、级别和输出目标。
"""

import logging
import sys
from config import Config

def setup_logger():
    """设置并返回应用日志记录器"""
    
    # 创建日志记录器
    logger = logging.getLogger('clawa_ibkr_mnq')
    logger.setLevel(getattr(logging, Config.LOG_LEVEL.upper()))
    
    # 避免重复处理器
    if logger.handlers:
        logger.handlers.clear()
    
    # 创建控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, Config.LOG_LEVEL.upper()))
    
    # 创建格式化器
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(formatter)
    
    # 添加处理器到记录器
    logger.addHandler(console_handler)
    
    return logger

# 全局日志记录器实例
logger = setup_logger()