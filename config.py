"""
配置管理模块

负责加载和管理 CLAWA IBKR MNQ 量化交易系统的配置参数。
"""

import os
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()

class Config:
    """应用程序配置类"""
    
    # IBKR 配置
    IBKR_HOST = os.getenv('IBKR_HOST', 'host.docker.internal')
    IBKR_PORT = int(os.getenv('IBKR_PORT', '7497'))
    IBKR_CLIENT_ID = int(os.getenv('IBKR_CLIENT_ID', '999'))
    
    # 交易配置
    SYMBOL = os.getenv('SYMBOL', 'MNQ')
    EXCHANGE = os.getenv('EXCHANGE', 'CME')
    CURRENCY = os.getenv('CURRENCY', 'USD')
    CONTRACT_MONTH = os.getenv('CONTRACT_MONTH', '')  # 空字符串表示当前活跃合约
    
    # 风险管理
    RISK_PERCENTAGE = float(os.getenv('RISK_PERCENTAGE', '1.0'))
    MAX_POSITION_SIZE = int(os.getenv('MAX_POSITION_SIZE', '10'))
    DAILY_LOSS_LIMIT = float(os.getenv('DAILY_LOSS_LIMIT', '3.0'))
    
    # 策略参数
    TIMEFRAME_15M = int(os.getenv('TIMEFRAME_15M', '900'))
    TIMEFRAME_1H = int(os.getenv('TIMEFRAME_1H', '3600'))
    TIMEFRAME_4H = int(os.getenv('TIMEFRAME_4H', '14400'))
    FVG_SENSITIVITY = float(os.getenv('FVG_SENSITIVITY', '0.8'))
    LIQUIDITY_THRESHOLD = float(os.getenv('LIQUIDITY_THRESHOLD', '2.0'))
    
    # 日志配置
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    
    # 回测配置
    BACKTEST_START_DATE = os.getenv('BACKTEST_START_DATE', '2025-01-01')
    BACKTEST_END_DATE = os.getenv('BACKTEST_END_DATE', '2026-01-01')
    
    @classmethod
    def validate(cls):
        """验证必需的配置是否存在"""
        required_fields = ['IBKR_HOST', 'IBKR_PORT', 'SYMBOL']
        missing = []
        for field in required_fields:
            if not getattr(cls, field):
                missing.append(field)
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

# 验证配置
Config.validate()