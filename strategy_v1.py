"""
ICT/SMC V2.0 交易策略 (多时间框架版)

改进点:
1. FVG过滤 - 只保留近期有效FVG
2. 趋势确认增强 - 检查更高时间框架
3. 信号质量提高 - 多个条件确认
4. 止损止盈设置优化
"""

import pandas as pd
import numpy as np
from datetime import datetime, time
from typing import Dict, List, Optional, Tuple
from config import Config
from logger import logger


class ICTSMCV2Strategy:
    """ICT/SMC V2.0 交易策略"""
    
    def __init__(self):
        self.active_trade = None
        self.last_signal_time = None
        self.last_fvg_time = None
        
        self.TRAIL_LEVELS = {
            1.5: {'action': 'partial', 'trail_stop': 0.5},
            2.0: {'action': 'trail', 'trail_stop': 1.0},
            3.0: {'action': 'trail', 'trail_stop': 2.0},
            4.0: {'action': 'close', 'trail_stop': 3.0}
        }
    
    def is_trading_session(self, dt) -> Optional[str]:
        """检查是否在交易时段 (CST = UTC-6)"""
        hour = dt.hour
        if hour >= 7 and hour < 20:
            return 'extended'
        return None
    
    def get_trend(self, data: pd.DataFrame) -> str:
        """判断趋势 - 简化版"""
        if len(data) < 5:
            return 'unknown'
        
        highs = data['high'].values
        lows = data['low'].values
        
        recent_high = highs[-1]
        recent_low = lows[-1]
        prev_high = highs[-2]
        prev_low = lows[-2]
        
        if recent_high > prev_high and recent_low > prev_low:
            return 'bullish'
        elif recent_high < prev_high and recent_low < prev_low:
            return 'bearish'
        else:
            return 'ranging'
    
    def detect_fvg(self, data: pd.DataFrame, lookback: int = 10) -> List[Dict]:
        """检测FVG - 只返回近期有效的"""
        fvgs = []
        if len(data) < 3:
            return fvgs
        
        sensitivity = Config.FVG_SENSITIVITY
        
        for i in range(max(2, len(data) - lookback), len(data)):
            prev = data.iloc[i-2]
            middle = data.iloc[i-1]
            curr = data.iloc[i]
            
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
                        'gap': gap,
                        'index': i,
                        'time': data.index[i]
                    })
            
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
                        'gap': gap,
                        'index': i,
                        'time': data.index[i]
                    })
        
        return fvgs
    
    def get_liquidity(self, data: pd.DataFrame) -> Tuple[float, float]:
        """获取流动性水平"""
        recent_highs = data['high'].tail(20).nlargest(3)
        recent_lows = data['low'].tail(20).nsmallest(3)
        return float(recent_highs.max()), float(recent_lows.min())
    
    def analyze_mtf_alignment(self, data: Dict[str, pd.DataFrame]) -> Dict:
        """多时间框架对齐分析"""
        result = {
            'trend_4hr': 'unknown',
            'trend_1hr': 'unknown',
            'trend_15min': 'unknown',
            'fvg_bullish': False,
            'fvg_bearish': False,
            'liquidity_high': 0,
            'liquidity_low': 0,
            'alignment_score': 0,
            'direction': None
        }
        
        if not data or not data.get('15min') or data['15min'].empty:
            return result
        
        df_15min = data['15min']
        df_1hr = data.get('1hr', pd.DataFrame())
        df_4hr = data.get('4hr', pd.DataFrame())
        
        result['trend_4hr'] = self.get_trend(df_4hr) if len(df_4hr) >= 5 else 'unknown'
        result['trend_1hr'] = self.get_trend(df_1hr) if len(df_1hr) >= 5 else 'unknown'
        result['trend_15min'] = self.get_trend(df_15min)
        
        high_liq, low_liq = self.get_liquidity(df_15min)
        result['liquidity_high'] = high_liq
        result['liquidity_low'] = low_liq
        
        fvgs = self.detect_fvg(df_15min)
        for fvg in fvgs:
            if fvg['type'] == 'bullish':
                result['fvg_bullish'] = True
            elif fvg['type'] == 'bearish':
                result['fvg_bearish'] = True
        
        score = 0
        direction = None
        
        if result['trend_4hr'] == 'bullish':
            score += 2
        elif result['trend_4hr'] == 'bearish':
            score -= 2
        
        if result['trend_1hr'] == 'bullish':
            score += 2
        elif result['trend_1hr'] == 'bearish':
            score -= 2
        elif result['trend_1hr'] == 'ranging':
            score += 1
        
        if result['trend_15min'] == 'bullish' and result['fvg_bullish']:
            score += 3
            direction = 'BUY'
        elif result['trend_15min'] == 'bearish' and result['fvg_bearish']:
            score -= 3
            direction = 'SELL'
        
        result['alignment_score'] = score
        result['direction'] = direction
        
        return result
    
    def generate_signal(self, data: Dict[str, pd.DataFrame], current_price: float,
                        current_time: datetime = None) -> Optional[Dict]:
        """生成交易信号"""
        if self.active_trade:
            return None
        
        if current_time and self.last_signal_time:
            if (current_time - self.last_signal_time).total_seconds() < 300:
                return None
        
        if not data or not data.get('15min') or data['15min'].empty:
            return None
        
        df_15min = data['15min']
        if len(df_15min) < 20:
            return None
        
        mtf = self.analyze_mtf_alignment(data)
        direction = mtf['direction']
        
        if not direction:
            return None
        
        confidence = 0.5
        
        if mtf['alignment_score'] >= 5:
            confidence = 0.85
        elif mtf['alignment_score'] >= 3:
            confidence = 0.7
        
        if mtf['trend_4hr'] == direction.lower():
            confidence += 0.1
        
        fvgs = self.detect_fvg(df_15min)
        for fvg in fvgs[-3:]:
            if direction == 'BUY' and fvg['type'] == 'bullish':
                if fvg['low'] <= current_price <= fvg['high'] + 10:
                    confidence += 0.15
                    break
            elif direction == 'SELL' and fvg['type'] == 'bearish':
                if fvg['high'] >= current_price >= fvg['low'] - 10:
                    confidence += 0.15
                    break
        
        high_liq = mtf['liquidity_high']
        low_liq = mtf['liquidity_low']
        
        if direction == 'BUY':
            if high_liq <= current_price:
                return None
            risk_distance = current_price - low_liq + 5
            stop_loss = low_liq - 5
        else:
            if low_liq >= current_price:
                return None
            risk_distance = high_liq + 5 - current_price
            stop_loss = high_liq + 5
        
        if risk_distance <= 0 or risk_distance > 100:
            return None
        
        self.last_signal_time = current_time
        
        return {
            'action': direction,
            'entry_price': current_price,
            'stop_loss': stop_loss,
            'risk_distance': risk_distance,
            'take_profit': current_price + risk_distance * 4 if direction == 'BUY' else current_price - risk_distance * 4,
            'confidence': min(confidence, 1.0),
            'trend_4hr': mtf['trend_4hr'],
            'trend_1hr': mtf['trend_1hr'],
            'trend_15min': mtf['trend_15min'],
            'alignment_score': mtf['alignment_score']
        }
    
    def update_trade(self, current_price: float, current_time) -> Dict:
        """更新交易状态"""
        if not self.active_trade:
            return {'action': 'hold'}
        
        t = self.active_trade
        entry = t['entry_price']
        risk = t['risk_distance']
        
        if t['action'] == 'BUY':
            unrealized_rr = (current_price - entry) / risk
        else:
            unrealized_rr = (entry - current_price) / risk
        
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
            return {'status': 'active', 'trade': self.active_trade}
        return {'status': 'idle'}
    
    def reset(self):
        """重置策略状态"""
        self.active_trade = None
        self.last_signal_time = None


class RiskManagerV1:
    """风险管理器"""
    
    def __init__(self):
        self.max_position = Config.MAX_POSITION_SIZE
        self.risk_pct = Config.RISK_PERCENTAGE
    
    def calculate_position_size(self, capital: float, entry_price: float, 
                             stop_loss: float) -> int:
        if capital <= 0:
            return 0
        
        risk_amount = capital * (self.risk_pct / 100)
        risk_per_contract = abs(entry_price - stop_loss) * 2
        
        if risk_per_contract <= 0:
            return 1
        
        size = int(risk_amount / risk_per_contract)
        return min(size, self.max_position)
    
    def should_trade(self, capital: float, daily_pnl: float) -> bool:
        daily_loss_limit = capital * (Config.DAILY_LOSS_LIMIT / 100)
        if abs(daily_pnl) >= daily_loss_limit:
            return False
        if capital < 1000:
            return False
        return True


STRATEGY_CONFIG = {
    'version': 'V2.0',
    'name': 'ICT/SMC 移动止损策略 V2.0',
    'sessions': {'extended': {'start': 7, 'end': 20, 'tz': 'CST'}},
    'trail_stops': {
        '1.5R': {'action': 'partial', 'trail_stop': 0.5},
        '2R': {'action': 'trail', 'trail_stop': 1.0},
        '3R': {'action': 'trail', 'trail_stop': 2.0},
        '4R': {'action': 'close', 'trail_stop': 3.0}
    },
    'timeframes': {
        '4hr': '主要趋势',
        '1hr': '趋势确认',
        '15min': '入场信号',
        '5min': '精确入场'
    },
    'risk': {
        'max_position': Config.MAX_POSITION_SIZE,
        'risk_per_trade': Config.RISK_PERCENTAGE,
        'daily_loss_limit': Config.DAILY_LOSS_LIMIT
    }
}
