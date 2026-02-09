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
        
        # 数据存储
        self.df_1min: pd.DataFrame = pd.DataFrame()
        self.df_5min: pd.DataFrame = pd.DataFrame()
        self.df_15min: pd.DataFrame = pd.DataFrame()
        self.df_1hr: pd.DataFrame = pd.DataFrame()
        self.df_4hr: pd.DataFrame = pd.DataFrame()
        
        # K线周期配置
        self.timeframes = {
            '1min': {'data': None, 'bars': 2880},      # 2天
            '5min': {'data': None, 'bars': 576},       # 2天
            '15min': {'data': None, 'bars': 192},     # 2天
            '1hr': {'data': None, 'bars': 48},         # 2天
            '4hr': {'data': None, 'bars': 12},         # 2天
        }
        
        # 历史文件
        self.historical_file = 'mnq_1min_20260209_010602.csv'
        self.live_file = 'mnq_1min_live.csv'
    
    def initialize(self, ib, contract):
        """初始化数据管理器"""
        self.ib = ib
        self.contract = contract
        
        # 加载历史数据
        self._load_historical_data()
        
        # 同步最新数据
        self._sync_latest_data()
        
        # 聚合所有时间框架
        self._aggregate_all_timeframes()
        
        logger.info(f"✅ DataManager初始化完成")
        logger.info(f"   1min: {len(self.df_1min)} 根")
        logger.info(f"   5min: {len(self.df_5min)} 根")
        logger.info(f"   15min: {len(self.df_15min)} 根")
        logger.info(f"   1hr: {len(self.df_1hr)} 根")
        logger.info(f"   4hr: {len(self.df_4hr)} 根")
    
    def _load_historical_data(self):
        """加载历史1分钟数据"""
        import os
        
        # 首先尝试加载历史文件
        if os.path.exists(self.historical_file):
            df = pd.read_csv(self.historical_file, parse_dates=['date'])
            df.set_index('date', inplace=True)
            df = df.tz_localize(None)
            self.df_1min = df
            logger.info(f"✅ 加载历史数据: {len(df)} 根1分钟K线")
        
        # 加载实时数据（如果有）
        if os.path.exists(self.live_file):
            df_live = pd.read_csv(self.live_file, parse_dates=['date'])
            df_live.set_index('date', inplace=True)
            df_live = df_live.tz_localize(None)
            
            if not self.df_1min.empty:
                # 合并并去重，实时数据优先
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
            # 获取最近2天的1分钟数据
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
            
            # 转换数据
            df_new = pd.DataFrame([{
                'date': bar.date,
                'open': bar.open,
                'high': bar.high,
                'low': bar.low,
                'close': bar.close,
                'volume': bar.volume
            } for bar in bars])
            
            df_new['date'] = pd.to_datetime(df_new['date'], utc=True)
            df_new.set_index('date', inplace=True)
            df_new = df_new.tz_localize(None)
            
            # 去重并合并
            if not self.df_1min.empty:
                combined = pd.concat([self.df_1min, df_new])
                combined = combined[~combined.index.duplicated(keep='last')]
                combined = combined.sort_index()
            else:
                combined = df_new
            
            # 只保留最近2880根（2天）
            self.df_1min = combined.tail(2880)
            
            # 保存到实时文件
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
        
        # 更新引用
        self.timeframes['1min']['data'] = self.df_1min
        self.timeframes['5min']['data'] = self.df_5min
        self.timeframes['15min']['data'] = self.df_15min
        self.timeframes['1hr']['data'] = self.df_1hr
        self.timeframes['4hr']['data'] = self.df_4hr
    
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
            # 获取最新1根1分钟K线
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
            
            # 转换
            new_bar = pd.DataFrame([{
                'date': bars[-1].date,
                'open': bars[-1].open,
                'high': bars[-1].high,
                'low': bars[-1].low,
                'close': bars[-1].close,
                'volume': bars[-1].volume
            }])
            
            new_bar['date'] = pd.to_datetime(new_bar['date'], utc=True)
            new_bar.set_index('date', inplace=True)
            new_bar = new_bar.tz_localize(None)
            
            # 检查是否是新K线
            if not self.df_1min.empty:
                last_time = self.df_1min.index[-1]
                new_time = new_bar.index[0]
                
                if new_time <= last_time:
                    # K线未更新，跳过
                    return False
            
            # 追加新K线
            self.df_1min = pd.concat([self.df_1min, new_bar])
            
            # 去重（防止重复）
            self.df_1min = self.df_1min[~self.df_1min.index.duplicated(keep='last')]
            
            # 只保留最近2880根
            self.df_1min = self.df_1min.tail(2880)
            
            # 保存
            self._save_live_data()
            
            # 重新聚合
            self._aggregate_all_timeframes()
            
            logger.debug(f"📊 新K线: {new_bar.index[0]} | O:{new_bar.iloc[0]['open']} H:{new_bar.iloc[0]['high']} L:{new_bar.iloc[0]['low']} C:{new_bar.iloc[0]['close']}")
            
            return True
            
        except Exception as e:
            logger.error(f"更新数据失败: {e}")
            return False
    
    def get_data(self, timeframe: str = '15min') -> pd.DataFrame:
        """获取指定时间框架数据"""
        return self.timeframes.get(timeframe, {}).get('data', pd.DataFrame())
    
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
