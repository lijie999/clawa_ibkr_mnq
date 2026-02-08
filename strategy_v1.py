"""
ICT/SMC V1.0 交易策略

移动止损策略:
- 1.5R 半仓平仓，止损移至 +0.5R
- 2R 止损移至 +1R
- 3R 止损移至 +2R
- 4R 止盈离场
"""

import pandas as pd
import numpy as np
from datetime import datetime, time
from typing import Dict, List, Optional, Tuple
from config import Config
from logger import logger

class ICTSMCV1Strategy:
    """ICT/SMC V1.0 交易策略"""
    
    def __init__(self):
        self.order_blocks = []
        self.fvgs = []
        self.liquidity_levels = []
        self.active_trade = None
        
        # 移动止损参数
        self.TRAIL_LEVELS = {
            1.5: {'action': 'partial', 'trail_stop': 0.5},
            2.0: {'action': 'trail', 'trail_stop': 1.0},
            3.0: {'action': 'trail', 'trail_stop': 2.0},
            4.0: {'action': 'close', 'trail_stop': 3.0}
        }
    
    def is_trading_session(self, dt) -> Optional[str]:
        """检查是否在交易时段 (CST = UTC-6)
        
        交易时段: 07:00 - 20:00 CST
        """
        hour = dt.hour
        if hour >= 7 and hour < 20:
            return 'extended'
        return None
    
    def analyze_market_structure(self, data: pd.DataFrame) -> Dict:
        """分析市场结构"""
        if len(data) < 5:
            return {'trend': 'unknown', 'bos': False, 'choch': False}
        
        highs = data['high'].values
        lows = data['low'].values
        closes = data['close'].values
        
        recent_high = highs[-1]
        recent_low = lows[-1]
        prev_high = highs[-2]
        prev_low = lows[-2]
        
        # 判断趋势
        if recent_high > prev_high and recent_low > prev_low:
            trend = 'bullish'
        elif recent_high < prev_high and recent_low < prev_low:
            trend = 'bearish'
        else:
            trend = 'ranging'
        
        # BOS 检测
        bos = False
        if trend == 'bullish' and recent_high > max(highs[-5:-1]):
            bos = True
        elif trend == 'bearish' and recent_low < min(lows[-5:-1]):
            bos = True
        
        # CHoCH 检测
        choch = False
        if trend == 'bullish' and recent_low < prev_low:
            choch = True
        elif trend == 'bearish' and recent_high > prev_high:
            choch = True
        
        return {'trend': trend, 'bos': bos, 'choch': choch}
    
    def detect_fvg(self, data: pd.DataFrame) -> List[Dict]:
        """检测公平价值缺口"""
        fvgs = []
        sensitivity = Config.FVG_SENSITIVITY
        
        for i in range(2, len(data)):
            prev = data.iloc[i-2]
            middle = data.iloc[i-1]
            curr = data.iloc[i]
            
            # Bullish FVG
            if curr['low'] > prev['high']:
                gap = curr['low'] - prev['high']
                avg_range = (prev['high'] - prev['low'] + 
                           middle['high'] - middle['low'] +
                           curr['high'] - curr['low']) / 3
                if gap > avg_range * sensitivity:
                    fvgs.append({
                        'type': 'bullish',
                        'low': prev['high'],
                        'high': curr['low'],
                        'gap': gap
                    })
            
            # Bearish FVG
            elif curr['high'] < prev['low']:
                gap = prev['low'] - curr['high']
                avg_range = (prev['high'] - prev['low'] + 
                           middle['high'] - middle['low'] +
                           curr['high'] - curr['low']) / 3
                if gap > avg_range * sensitivity:
                    fvgs.append({
                        'type': 'bearish',
                        'low': curr['high'],
                        'high': prev['low'],
                        'gap': gap
                    })
        
        return fvgs
    
    def find_liquidity(self, data: pd.DataFrame) -> Tuple[float, float]:
        """寻找流动性水平"""
        recent_highs = data['high'].tail(20).nlargest(3)
        recent_lows = data['low'].tail(20).nsmallest(3)
        return float(recent_highs.max()), float(recent_lows.min())
    
    def generate_signal(self, data: pd.DataFrame, current_price: float) -> Optional[Dict]:
        """生成交易信号"""
        if self.active_trade:
            return None
        
        structure = self.analyze_market_structure(data)
        if structure['trend'] == 'ranging':
            return None
        
        fvgs = self.detect_fvg(data)
        high_liq, low_liq = self.find_liquidity(data)
        
        # 检查 FVG 有效性
        valid_fvg = False
        for fvg in fvgs[-5:]:
            if fvg['type'] == 'bullish' and fvg['low'] <= current_price <= fvg['high'] + 10:
                valid_fvg = True
                break
            elif fvg['type'] == 'bearish' and fvg['high'] >= current_price >= fvg['low'] - 10:
                valid_fvg = True
                break
        
        if not valid_fvg:
            return None
        
        # 流动性确认
        if structure['trend'] == 'bullish' and high_liq > current_price:
            action = 'BUY'
            risk_distance = current_price - low_liq + 5
            stop_loss = low_liq - 5
        elif structure['trend'] == 'bearish' and low_liq < current_price:
            action = 'SELL'
            risk_distance = high_liq + 5 - current_price
            stop_loss = high_liq + 5
        else:
            return None
        
        if risk_distance <= 0:
            return None
        
        # 计算置信度
        confidence = 0.5
        if structure['bos']:
            confidence += 0.2
        if structure['choch']:
            confidence += 0.1
        confidence += min(len(fvgs[-10:]) * 0.05, 0.2)
        
        return {
            'action': action,
            'entry_price': current_price,
            'stop_loss': stop_loss,
            'risk_distance': risk_distance,
            'take_profit': current_price + risk_distance * 4,
            'confidence': min(confidence, 1.0),
            'trend': structure['trend']
        }
    
    def update_trade(self, current_price: float, current_time) -> Dict:
        """更新活跃交易，返回操作指令"""
        if not self.active_trade:
            return {'action': 'hold'}
        
        t = self.active_trade
        entry = t['entry_price']
        risk = t['risk_distance']
        
        if t['action'] == 'BUY':
            unrealized_rr = (current_price - entry) / risk
        else:
            unrealized_rr = (entry - current_price) / risk
        
        # 检查移动止损触发
        for level, config in sorted(self.TRAIL_LEVELS.items()):
            if unrealized_rr >= level and t['trail_level'] < level:
                t['trail_level'] = level
                
                if config['action'] == 'partial' and not t['partial_filled']:
                    t['partial_filled'] = True
                    t['partial_size'] = t['size'] // 2
                    t['size'] = t['size'] - t['partial_size']
                    
                    if t['action'] == 'BUY':
                        t['stop_loss'] = entry + risk * config['trail_stop']
                    else:
                        t['stop_loss'] = entry - risk * config['trail_stop']
                    
                    return {
                        'action': 'partial_close',
                        'size': t['partial_size'],
                        'price': current_price,
                        'rr': unrealized_rr,
                        'new_stop_loss': t['stop_loss']
                    }
                
                elif config['action'] == 'trail':
                    if t['action'] == 'BUY':
                        t['stop_loss'] = entry + risk * config['trail_stop']
                    else:
                        t['stop_loss'] = entry - risk * config['trail_stop']
                    
                    return {
                        'action': 'trail_stop',
                        'new_stop_loss': t['stop_loss'],
                        'rr': unrealized_rr
                    }
                
                elif config['action'] == 'close':
                    t['pnl'] = (t['take_profit'] - entry) * t['size'] * 2
                    if t.get('partial_size', 0) > 0:
                        t['pnl'] += (t['take_profit'] - entry) * t['partial_size'] * 2
                    
                    result = {
                        'action': 'close',
                        'pnl': t['pnl'],
                        'rr': unrealized_rr,
                        'reason': '4R止盈'
                    }
                    self.active_trade = None
                    return result
        
        # 检查止损
        if t['action'] == 'BUY':
            if current_price <= t['stop_loss']:
                t['pnl'] = (t['stop_loss'] - entry) * t['size'] * 2
                if t.get('partial_size', 0) > 0:
                    t['pnl'] += (t['stop_loss'] - entry) * t['partial_size'] * 2
                
                result = {'action': 'close', 'pnl': t['pnl'], 'rr': unrealized_rr, 'reason': '止损'}
                self.active_trade = None
                return result
        
        else:
            if current_price >= t['stop_loss']:
                t['pnl'] = (entry - t['stop_loss']) * t['size'] * 2
                if t.get('partial_size', 0) > 0:
                    t['pnl'] += (entry - t['stop_loss']) * t['partial_size'] * 2
                
                result = {'action': 'close', 'pnl': t['pnl'], 'rr': unrealized_rr, 'reason': '止损'}
                self.active_trade = None
                return result
        
        return {'action': 'hold', 'current_rr': unrealized_rr}
    
    def open_position(self, signal: Dict, position_size: int):
        """开仓"""
        if self.active_trade:
            return None
        
        self.active_trade = {
            'action': signal['action'],
            'entry_price': signal['entry_price'],
            'stop_loss': signal['stop_loss'],
            'take_profit': signal['take_profit'],
            'risk_distance': signal['risk_distance'],
            'size': position_size,
            'trail_level': 0,
            'partial_filled': False,
            'partial_size': 0,
            'open_time': datetime.now()
        }
        
        return self.active_trade
    
    def get_status(self) -> Dict:
        """获取策略状态"""
        if self.active_trade:
            return {
                'status': 'active',
                'trade': self.active_trade
            }
        return {'status': 'idle'}
    
    def reset(self):
        """重置策略状态"""
        self.active_trade = None


class RiskManagerV1:
    """V1.0 风险管理器"""
    
    def __init__(self):
        self.max_position = Config.MAX_POSITION_SIZE
        self.risk_pct = Config.RISK_PERCENTAGE
    
    def calculate_position_size(self, capital: float, entry_price: float, 
                             stop_loss: float) -> int:
        """计算仓位大小"""
        if capital <= 0:
            return 0
        
        risk_amount = capital * (self.risk_pct / 100)
        risk_per_contract = abs(entry_price - stop_loss) * 2
        
        if risk_per_contract <= 0:
            return 1
        
        size = int(risk_amount / risk_per_contract)
        return min(size, self.max_position)
    
    def should_trade(self, capital: float, daily_pnl: float) -> bool:
        """检查是否可以交易"""
        daily_loss_limit = capital * (Config.DAILY_LOSS_LIMIT / 100)
        if abs(daily_pnl) >= daily_loss_limit:
            return False
        if capital < 1000:
            return False
        return True


# 策略配置摘要
STRATEGY_CONFIG = {
    'version': 'V1.0',
    'name': 'ICT/SMC 移动止损策略',
    'sessions': {
        'extended': {'start': 7, 'end': 20, 'tz': 'CST'}
    },
    'trail_stops': {
        '1.5R': {'action': 'partial', 'trail_stop': 0.5},
        '2R': {'action': 'trail', 'trail_stop': 1.0},
        '3R': {'action': 'trail', 'trail_stop': 2.0},
        '4R': {'action': 'close', 'trail_stop': 3.0}
    },
    'risk': {
        'max_position': Config.MAX_POSITION_SIZE,
        'risk_per_trade': Config.RISK_PERCENTAGE,
        'daily_loss_limit': Config.DAILY_LOSS_LIMIT
    },
    'backtest_results': {
        'final_capital': 163112.25,
        'return': '63.11%',
        'trades': 400,
        'win_rate': '43.2%'
    }
}
