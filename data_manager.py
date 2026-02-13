"""
数据管理器 V2.0

职责:
1. 从IBKR获取实时1分钟K线数据
2. 增量更新，高效存储
3. 聚合生成多时间框架K线
4. 提供统一的数据访问接口
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, Optional
from config import Config
from logger import logger


class DataManager:
    """实时数据管理器 V2.0 - 增量更新版"""
    
    def __init__(self):
        self.ib = None
        self.contract = None
        
        self.df_1min = pd.DataFrame()
        self.df_5min = pd.DataFrame()
        self.df_15min = pd.DataFrame()
        self.df_1hr = pd.DataFrame()
        self.df_4hr = pd.DataFrame()
        
        self.historical_file = 'mnq_1min_20260209_010602.csv'
        self.live_file = 'mnq_1min_live.csv'
        
        self._last_bar_time = None
    
    def _to_naive_datetime(self, dt):
        """转换到无时区datetime"""
        if isinstance(dt, str):
            dt = pd.to_datetime(dt, utc=True)
        if hasattr(dt, 'tz') and dt.tz is not None:
            dt = dt.tz_localize(None)
        return dt
    
    def _ensure_datetimeindex(self, df):
        """确保DataFrame有DatetimeIndex"""
        if df.empty:
            return df
        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index, utc=True)
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        return df
    
    def _convert_bar(self, bar):
        """转换IBKR K线数据"""
        dt = self._to_naive_datetime(bar.date)
        return {
            'date': dt,
            'open': float(bar.open),
            'high': float(bar.high),
            'low': float(bar.low),
            'close': float(bar.close),
            'volume': int(bar.volume)
        }
    
    def initialize(self, ib, contract):
        """初始化数据管理器"""
        self.ib = ib
        self.contract = contract
        
        self._load_all_data()
        self._aggregate_all_timeframes()
        
        logger.info(f"✅ DataManager初始化完成")
        logger.info(f"   1min: {len(self.df_1min)} 根")
        logger.info(f"   5min: {len(self.df_5min)} 根")
        logger.info(f"   15min: {len(self.df_15min)} 根")
        logger.info(f"   1hr: {len(self.df_1hr)} 根")
        logger.info(f"   4hr: {len(self.df_4hr)} 根")
    
    def _load_all_data(self):
        """加载所有数据"""
        import os
        
        df_merged = pd.DataFrame()
        
        if os.path.exists(self.historical_file):
            df_hist = pd.read_csv(self.historical_file, parse_dates=['date'])
            df_hist.set_index('date', inplace=True)
            df_hist = self._ensure_datetimeindex(df_hist)
            df_merged = df_hist
            logger.info(f"✅ 历史数据: {len(df_hist)} 根")
        
        if os.path.exists(self.live_file):
            df_live = pd.read_csv(self.live_file, parse_dates=['date'])
            df_live.set_index('date', inplace=True)
            df_live = self._ensure_datetimeindex(df_live)
            if not df_merged.empty:
                df_merged = pd.concat([df_merged, df_live])
                df_merged = df_merged[~df_merged.index.duplicated(keep='last')]
                df_merged = df_merged.sort_index()
            else:
                df_merged = df_live
            logger.info(f"✅ 实时数据: {len(df_live)} 根")
        
        if not df_merged.empty:
            self.df_1min = df_merged.tail(2880)
            self._last_bar_time = self.df_1min.index[-1]
            self._save_live_data()
    
    def _save_live_data(self):
        """保存实时数据到CSV"""
        import os
        try:
            self.df_1min.to_csv(self.live_file)
            logger.debug(f"💾 保存: {len(self.df_1min)} 根")
        except Exception as e:
            logger.error(f"保存失败: {e}")
    
    def _aggregate_all_timeframes(self):
        """聚合所有时间框架"""
        if self.df_1min.empty:
            return
        
        self.df_5min = self._resample(self.df_1min, '5min')
        self.df_15min = self._resample(self.df_1min, '15min')
        self.df_1hr = self._resample(self.df_1min, '60min')
        self.df_4hr = self._resample(self.df_1min, '240min')
    
    def _resample(self, df: pd.DataFrame, freq: str) -> pd.DataFrame:
        """聚合K线"""
        if df.empty:
            return pd.DataFrame()
        
        resampled = df.resample(freq).agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        }).dropna()
        
        return resampled
    
    def update(self) -> bool:
        """更新数据 - 增量获取最新K线"""
        if not self.ib or not self.ib.isConnected():
            return False
        
        try:
            bars = self.ib.reqHistoricalData(
                self.contract,
                endDateTime='',
                durationStr='2 D',
                barSizeSetting='1 min',
                whatToShow='TRADES',
                useRTH=True,
                formatDate=1
            )
            
            if not bars:
                return False
            
            df_new = pd.DataFrame([self._convert_bar(bar) for bar in bars])
            df_new.set_index('date', inplace=True)
            df_new = df_new[~df_new.index.duplicated(keep='last')]
            df_new = df_new.sort_index()
            
            if self._last_bar_time is not None:
                df_new = df_new[df_new.index > self._last_bar_time]
            
            if df_new.empty:
                return False
            
            self.df_1min = pd.concat([self.df_1min, df_new])
            self.df_1min = self.df_1min[~self.df_1min.index.duplicated(keep='last')]
            self.df_1min = self.df_1min.tail(2880)
            
            self._last_bar_time = self.df_1min.index[-1]
            self._save_live_data()
            self._aggregate_all_timeframes()
            
            logger.debug(f"📊 新增{len(df_new)}根K线 | 最新: {self._last_bar_time}")
            return True
            
        except Exception as e:
            logger.error(f"数据更新失败: {e}")
            return False
    
    def get_data(self, timeframe: str = '15min') -> pd.DataFrame:
        """获取指定时间框架数据"""
        tf_map = {
            '1min': self.df_1min,
            '5min': self.df_5min,
            '15min': self.df_15min,
            '1hr': self.df_1hr,
            '4hr': self.df_4hr,
        }
        return tf_map.get(timeframe, pd.DataFrame())
    
    def get_current_price(self) -> float:
        """获取当前价格"""
        if self.df_1min.empty:
            return 0.0
        return float(self.df_1min.iloc[-1]['close'])
    
    def get_bar_count(self) -> Dict[str, int]:
        """获取各时间框架的K线数量"""
        return {
            '1min': len(self.df_1min),
            '5min': len(self.df_5min),
            '15min': len(self.df_15min),
            '1hr': len(self.df_1hr),
            '4hr': len(self.df_4hr),
        }
