"""
数据管理器

职责:
1. 从IBKR获取实时1分钟K线数据
2. 追加存储到本地CSV文件
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
    """实时数据管理器"""
    
    def __init__(self):
        self.ib = None
        self.contract = None
        self.data_dirty = False
        
        self.df_1min = pd.DataFrame()
        self.df_5min = pd.DataFrame()
        self.df_15min = pd.DataFrame()
        self.df_1hr = pd.DataFrame()
        self.df_4hr = pd.DataFrame()
        
        self.timeframes = {
            '1min': None,
            '5min': None,
            '15min': None,
            '1hr': None,
            '4hr': None,
        }
        
        self.historical_file = 'mnq_1min_20260209_010602.csv'
        self.live_file = 'mnq_1min_live.csv'
    
    def initialize(self, ib, contract):
        """初始化数据管理器"""
        self.ib = ib
        self.contract = contract
        
        self._load_historical_data()
        self._sync_latest_data()
        self._aggregate_all_timeframes()
        
        logger.info(f"✅ DataManager初始化完成")
        logger.info(f"   1min: {len(self.df_1min)} 根")
        logger.info(f"   5min: {len(self.df_5min)} 根")
        logger.info(f"   15min: {len(self.df_15min)} 根")
        logger.info(f"   1hr: {len(self.df_1hr)} 根")
        logger.info(f"   4hr: {len(self.df_4hr)} 根")
    
    def _ensure_datetimeindex(self, df):
        """确保DataFrame有DatetimeIndex且无时区"""
        if df.empty:
            return df
        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index, utc=True)
        # 移除时区信息，统一使用无时区
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        return df
    
    def _convert_ibkr_bar(self, bar):
        """转换IBKR K线数据"""
        dt = pd.to_datetime(bar.date, utc=True)
        dt = dt.tz_localize(None)
        return {
            'date': dt,
            'open': bar.open,
            'high': bar.high,
            'low': bar.low,
            'close': bar.close,
            'volume': bar.volume
        }
    
    def _load_historical_data(self):
        """加载历史1分钟数据"""
        import os
        
        if os.path.exists(self.historical_file):
            df = pd.read_csv(self.historical_file, parse_dates=['date'])
            df.set_index('date', inplace=True)
            df = self._ensure_datetimeindex(df)
            self.df_1min = df
            logger.info(f"✅ 加载历史数据: {len(df)} 根1分钟K线")
        
        if os.path.exists(self.live_file):
            df_live = pd.read_csv(self.live_file, parse_dates=['date'])
            df_live.set_index('date', inplace=True)
            df_live = self._ensure_datetimeindex(df_live)
            
            if not self.df_1min.empty:
                combined = pd.concat([self.df_1min, df_live])
                combined = combined[~combined.index.duplicated(keep='last')]
                combined = combined.sort_index()
                self.df_1min = combined.tail(2880)
            else:
                self.df_1min = df_live.tail(2880)
            
            logger.info(f"✅ 合并实时数据: {len(df_live)} 根")
    
    def _sync_latest_data(self):
        """同步IBKR最新数据"""
        if not self.ib or not self.ib.isConnected():
            logger.warning("IBKR未连接，跳过同步")
            return
        
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
                logger.warning("未获取到K线数据")
                return
            
            df_new = pd.DataFrame([self._convert_ibkr_bar(bar) for bar in bars])
            df_new.set_index('date', inplace=True)
            
            if not self.df_1min.empty:
                combined = pd.concat([self.df_1min, df_new])
                combined = combined[~combined.index.duplicated(keep='last')]
                combined = combined.sort_index()
            else:
                combined = df_new
            
            self.df_1min = combined.tail(2880)
            self._save_live_data()
            
            logger.info(f"✅ 同步完成: {len(df_new)} 根新数据")
            
        except Exception as e:
            logger.error(f"同步数据失败: {e}")
    
    def _save_live_data(self):
        """保存实时数据到CSV"""
        try:
            self.df_1min.to_csv(self.live_file)
            logger.debug(f"💾 保存实时数据: {len(self.df_1min)} 根")
        except Exception as e:
            logger.error(f"保存数据失败: {e}")
    
    def _aggregate_all_timeframes(self):
        """聚合所有时间框架"""
        if self.df_1min.empty:
            return
        
        self.df_5min = self._resample_dataframe(self.df_1min, '5min')
        self.df_15min = self._resample_dataframe(self.df_1min, '15min')
        self.df_1hr = self._resample_dataframe(self.df_1min, '60min')
        self.df_4hr = self._resample_dataframe(self.df_1min, '240min')
        
        self.timeframes['1min'] = self.df_1min
        self.timeframes['5min'] = self.df_5min
        self.timeframes['15min'] = self.df_15min
        self.timeframes['1hr'] = self.df_1hr
        self.timeframes['4hr'] = self.df_4hr
    
    def _resample_dataframe(self, df: pd.DataFrame, freq: str) -> pd.DataFrame:
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
    
    def update(self):
        """更新数据（每1分钟调用）"""
        if not self.ib or not self.ib.isConnected():
            return False
        
        try:
            bars = self.ib.reqHistoricalData(
                self.contract,
                endDateTime='',
                durationStr='1 D',
                barSizeSetting='1 min',
                whatToShow='TRADES',
                useRTH=True,
                formatDate=1
            )
            
            if not bars:
                return False
            
            new_bar = pd.DataFrame([self._convert_ibkr_bar(bars[-1])])
            new_bar.set_index('date', inplace=True)
            
            if not self.df_1min.empty:
                last_time = self.df_1min.index[-1]
                new_time = new_bar.index[0]
                
                if new_time <= last_time:
                    return False
            
            self.df_1min = pd.concat([self.df_1min, new_bar])
            self.df_1min = self.df_1min[~self.df_1min.index.duplicated(keep='last')]
            self.df_1min = self.df_1min.tail(2880)
            
            self._save_live_data()
            self._aggregate_all_timeframes()
            
            logger.debug(f"📊 新K线: {new_bar.index[0]} | O:{new_bar.iloc[0]['open']} H:{new_bar.iloc[0]['high']} L:{new_bar.iloc[0]['low']} C:{new_bar.iloc[0]['close']}")
            
            return True
            
        except Exception as e:
            logger.error(f"更新数据失败: {e}")
            return False
    
    def get_data(self, timeframe: str = '15min') -> pd.DataFrame:
        """获取指定时间框架数据"""
        return self.timeframes.get(timeframe, pd.DataFrame())
    
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
