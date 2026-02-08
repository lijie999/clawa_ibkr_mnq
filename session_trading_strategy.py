"""
会话交易策略

专注于三个特定交易时段：
1. 亚盘 9-11 点 (亚洲时间)
2. 伦敦盘银弹时间 1 (通常 14:00-16:00 GMT)  
3. 伦敦盘银弹时间 2 (通常 16:00-18:00 GMT)

在这些时段内必须开单并完成 2R 或 50 点盈利目标。
"""

import pandas as pd
import numpy as np
from datetime import datetime, time, timezone
import pytz
from typing import Dict, Optional, Tuple
from config import Config
from logger import logger

class SessionTradingStrategy:
    """会话交易策略引擎"""
    
    def __init__(self):
        # 定义交易时段（使用 UTC 时间）
        self.trading_sessions = {
            'asia': {
                'name': '亚盘',
                'start_time': time(1, 0),   # UTC 1:00 = 北京时间 9:00
                'end_time': time(3, 0),     # UTC 3:00 = 北京时间 11:00
                'timezone': 'Asia/Shanghai'
            },
            'london_silver_1': {
                'name': '伦敦银弹1',
                'start_time': time(14, 0),  # UTC 14:00
                'end_time': time(16, 0),    # UTC 16:00  
                'timezone': 'Europe/London'
            },
            'london_silver_2': {
                'name': '伦敦银弹2',
                'start_time': time(16, 0),  # UTC 16:00
                'end_time': time(18, 0),    # UTC 18:00
                'timezone': 'Europe/London'
            }
        }
        
        # 盈利目标设置
        self.profit_targets = {
            'min_points': 50,      # 最小50点盈利
            'risk_reward_ratio': 2.0  # 2R 风险回报比
        }
        
    def is_trading_session(self, current_time: datetime) -> Optional[str]:
        """
        检查当前时间是否在交易时段内
        
        Args:
            current_time (datetime): 当前时间（带时区信息）
            
        Returns:
            str or None: 交易时段名称，如果不在交易时段返回 None
        """
        # 转换为 UTC 时间进行比较
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=timezone.utc)
        utc_time = current_time.astimezone(timezone.utc)
        current_utc_time = utc_time.time()
        
        for session_name, session_info in self.trading_sessions.items():
            start_time = session_info['start_time']
            end_time = session_info['end_time']
            
            if start_time <= current_utc_time <= end_time:
                return session_name
                
        return None
    
    def should_enter_trade(self, current_time: datetime, market_data: pd.DataFrame) -> Dict[str, any]:
        """
        判断是否应该在当前交易时段开单
        
        Args:
            current_time (datetime): 当前时间
            market_data (pd.DataFrame): 市场数据
            
        Returns:
            Dict: 交易信号和入场信息
        """
        session_name = self.is_trading_session(current_time)
        if not session_name:
            return {'should_trade': False, 'reason': 'Not in trading session'}
            
        # 检查是否已经在这个时段开过单
        if self._has_traded_in_session(session_name, current_time):
            return {'should_trade': False, 'reason': f'Already traded in {session_name}'}
            
        # 分析市场条件
        signal = self._analyze_market_conditions(market_data, session_name)
        if not signal['valid']:
            return {'should_trade': False, 'reason': 'No valid signal'}
            
        # 计算止损和止盈
        entry_price = signal['entry_price']
        stop_loss = signal['stop_loss']
        take_profit = self._calculate_take_profit(entry_price, stop_loss, session_name)
        
        # 验证盈利目标
        profit_points = abs(take_profit - entry_price)
        risk_points = abs(entry_price - stop_loss)
        risk_reward = profit_points / risk_points if risk_points > 0 else 0
        
        # 必须满足 2R 或 50点盈利
        if profit_points < self.profit_targets['min_points'] and risk_reward < self.profit_targets['risk_reward_ratio']:
            return {'should_trade': False, 'reason': 'Profit target not met (need 2R or 50 points)'}
            
        return {
            'should_trade': True,
            'session': session_name,
            'action': signal['action'],
            'entry_price': entry_price,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'profit_points': profit_points,
            'risk_reward': risk_reward,
            'confidence': signal['confidence']
        }
    
    def _has_traded_in_session(self, session_name: str, current_time: datetime) -> bool:
        """
        检查是否已经在当前时段交易过
        
        Args:
            session_name (str): 时段名称
            current_time (datetime): 当前时间
            
        Returns:
            bool: 是否已交易
        """
        # 简化实现：检查今天是否已经在这个时段交易过
        # 实际应用中需要持久化存储交易记录
        today = current_time.date()
        session_key = f"{today}_{session_name}"
        
        # 这里应该查询数据库或文件记录
        # 为了简化，我们假设每次运行都是新的
        return False
    
    def _analyze_market_conditions(self, data: pd.DataFrame, session_name: str) -> Dict[str, any]:
        """
        分析市场条件生成交易信号
        
        Args:
            data (pd.DataFrame): 市场数据
            session_name (str): 交易时段名称
            
        Returns:
            Dict: 信号分析结果
        """
        if len(data) < 10:
            return {'valid': False, 'reason': 'Insufficient data'}
            
        # 获取最新价格
        current_price = data['close'].iloc[-1]
        high = data['high'].iloc[-1]
        low = data['low'].iloc[-1]
        volume = data['volume'].iloc[-1]
        
        # 简化的 ICT/SMC 信号检测
        signal = self._detect_ict_smc_signal(data, session_name)
        if not signal['valid']:
            return signal
            
        # 根据交易时段调整信号
        adjusted_signal = self._adjust_signal_for_session(signal, session_name, current_price)
        return adjusted_signal
    
    def _detect_ict_smc_signal(self, data: pd.DataFrame, session_name: str) -> Dict[str, any]:
        """
        检测 ICT/SMC 信号
        
        Args:
            data (pd.DataFrame): 市场数据
            session_name (str): 交易时段名称
            
        Returns:
            Dict: 信号结果
        """
        # 简化实现：基于价格行为的基本信号
        recent_highs = data['high'].tail(20).nlargest(3)
        recent_lows = data['low'].tail(20).nsmallest(3)
        
        current_price = data['close'].iloc[-1]
        prev_close = data['close'].iloc[-2]
        
        # 检测突破信号
        if current_price > recent_highs.iloc[0] and current_price > prev_close:
            # 突破阻力，看涨信号
            stop_loss = recent_lows.iloc[0]  # 最近支撑位作为止损
            entry_price = current_price
            confidence = 0.7
            
            return {
                'valid': True,
                'action': 'BUY',
                'entry_price': entry_price,
                'stop_loss': stop_loss,
                'confidence': confidence
            }
        elif current_price < recent_lows.iloc[0] and current_price < prev_close:
            # 突破支撑，看跌信号
            stop_loss = recent_highs.iloc[0]  # 最近阻力位作为止损
            entry_price = current_price
            confidence = 0.7
            
            return {
                'valid': True,
                'action': 'SELL',
                'entry_price': entry_price,
                'stop_loss': stop_loss,
                'confidence': confidence
            }
            
        return {'valid': False, 'reason': 'No breakout signal'}
    
    def _adjust_signal_for_session(self, signal: Dict, session_name: str, current_price: float) -> Dict[str, any]:
        """
        根据交易时段调整信号
        
        Args:
            signal (Dict): 原始信号
            session_name (str): 交易时段名称
            current_price (float): 当前价格
            
        Returns:
            Dict: 调整后的信号
        """
        # 亚盘时段：更保守的止损
        if session_name == 'asia':
            if signal['action'] == 'BUY':
                signal['stop_loss'] = min(signal['stop_loss'], current_price - 30)
            else:
                signal['stop_loss'] = max(signal['stop_loss'], current_price + 30)
                
        # 伦敦银弹时段：更激进的目标
        elif session_name.startswith('london'):
            # 伦敦时段波动性更大，可以设置更大的目标
            pass
            
        return signal
    
    def _calculate_take_profit(self, entry_price: float, stop_loss: float, session_name: str) -> float:
        """
        计算止盈目标
        
        Args:
            entry_price (float): 入场价格
            stop_loss (float): 止损价格
            session_name (str): 交易时段名称
            
        Returns:
            float: 止盈价格
        """
        risk_points = abs(entry_price - stop_loss)
        
        # 2R 目标
        rr_target = entry_price + (entry_price - stop_loss) * self.profit_targets['risk_reward_ratio']
        
        # 50点目标
        points_target = entry_price + 50 if entry_price > stop_loss else entry_price - 50
        
        # 选择更激进的目标（更大的盈利）
        if entry_price > stop_loss:  # 多头
            take_profit = max(rr_target, points_target)
        else:  # 空头
            take_profit = min(rr_target, points_target)
            
        return take_profit
    
    def manage_active_trade(self, trade_info: Dict, current_price: float, current_time: datetime) -> Dict[str, any]:
        """
        管理活跃交易
        
        Args:
            trade_info (Dict): 交易信息
            current_price (float): 当前价格
            current_time (datetime): 当前时间
            
        Returns:
            Dict: 交易管理决策
        """
        session_name = trade_info['session']
        entry_price = trade_info['entry_price']
        take_profit = trade_info['take_profit']
        stop_loss = trade_info['stop_loss']
        action = trade_info['action']
        
        # 检查是否达到止盈
        if action == 'BUY' and current_price >= take_profit:
            return {'action': 'CLOSE', 'reason': 'Take profit reached', 'pnl_points': current_price - entry_price}
        elif action == 'SELL' and current_price <= take_profit:
            return {'action': 'CLOSE', 'reason': 'Take profit reached', 'pnl_points': entry_price - current_price}
            
        # 检查是否达到止损
        if action == 'BUY' and current_price <= stop_loss:
            return {'action': 'CLOSE', 'reason': 'Stop loss hit', 'pnl_points': current_price - entry_price}
        elif action == 'SELL' and current_price >= stop_loss:
            return {'action': 'CLOSE', 'reason': 'Stop loss hit', 'pnl_points': entry_price - current_price}
            
        # 检查是否超出交易时段
        if not self.is_trading_session(current_time):
            # 时段结束，平仓
            pnl_points = current_price - entry_price if action == 'BUY' else entry_price - current_price
            return {'action': 'CLOSE', 'reason': 'Session ended', 'pnl_points': pnl_points}
            
        # 继续持仓
        return {'action': 'HOLD', 'reason': 'Trade still active'}

# 使用示例
if __name__ == "__main__":
    strategy = SessionTradingStrategy()
    
    # 测试时间
    test_time = datetime(2026, 2, 8, 2, 30, tzinfo=timezone.utc)  # UTC 2:30 = 北京时间 10:30 (亚盘时段)
    
    # 模拟市场数据
    market_data = pd.DataFrame({
        'open': [25000, 25050, 25100],
        'high': [25080, 25120, 25150], 
        'low': [24980, 25030, 25080],
        'close': [25050, 25100, 25120],
        'volume': [1000, 1200, 1100]
    })
    
    # 检查是否应该交易
    trade_decision = strategy.should_enter_trade(test_time, market_data)
    print(f"Trade decision: {trade_decision}")
    
    # 如果有活跃交易，管理它
    if trade_decision.get('should_trade'):
        active_trade = {
            'session': trade_decision['session'],
            'action': trade_decision['action'],
            'entry_price': trade_decision['entry_price'],
            'take_profit': trade_decision['take_profit'],
            'stop_loss': trade_decision['stop_loss']
        }
        
        current_price = 25150
        management_decision = strategy.manage_active_trade(active_trade, current_price, test_time)
        print(f"Management decision: {management_decision}")