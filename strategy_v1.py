"""
ICT/SMC V1.0 交易策略 (多时间框架版)

移动止损策略:
- 1.5R 半仓平仓，止损移至 +0.5R
- 2R 止损移至 +1R
- 3R 止损移至 +2R
- 4R 止盈离场

多时间框架分析:
- 4hr: 确定主要趋势
- 1hr: 确认趋势方向
- 15min: 寻找入场信号
- 5min: 精确入场时机
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
        self.last_signal_time = None
        
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
        
        if recent_high > prev_high and recent_low > prev_low:
            trend = 'bullish'
        elif recent_high < prev_high and recent_low < prev_low:
            trend = 'bearish'
        else:
            trend = 'ranging'
        
        bos = False
        if trend == 'bullish' and recent_high > max(highs[-5:-1]):
            bos = True
        elif trend == 'bearish' and recent_low < min(lows[-5:-1]):
            bos = True
        
        choch = False
        if trend == 'bullish' and recent_low < prev_low:
            choch = True
        elif trend == 'bearish' and recent_high > prev_high:
            choch = True
        
        return {'trend': trend, 'bos': bos, 'choch': choch}
    
    def detect_fvg(self, data: pd.DataFrame, sensitivity: float = None) -> List[Dict]:
        """检测公平价值缺口"""
        fvgs = []
        if sensitivity is None:
            sensitivity = Config.FVG_SENSITIVITY
        
        for i in range(2, len(data)):
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
                        'index': i
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
                        'index': i
                    })
        
        return fvgs
    
    def find_liquidity(self, data: pd.DataFrame) -> Tuple[float, float]:
        """寻找流动性水平"""
        recent_highs = data['high'].tail(20).nlargest(3)
        recent_lows = data['low'].tail(20).nsmallest(3)
        return float(recent_highs.max()), float(recent_lows.min())
    
    def analyze_multi_timeframe(self, data: Dict[str, pd.DataFrame]) -> Dict:
        """多时间框架分析
        
        Args:
            data: {'4hr': df, '1hr': df, '15min': df, '5min': df}
        
        Returns:
            综合分析结果
        """
        result = {
            'trend_4hr': 'unknown',
            'trend_1hr': 'unknown',
            'trend_15min': 'unknown',
            'fvg_aligned': False,
            'liquidity_bias': None,
            'direction': None,
            'confidence': 0.0
        }
        
        # 1. 4小时图确定主要趋势
        if '4hr' in data and len(data['4hr']) >= 5:
            structure_4hr = self.analyze_market_structure(data['4hr'])
            result['trend_4hr'] = structure_4hr['trend']
        
        # 2. 1小时图确认趋势
        if '1hr' in data and len(data['1hr']) >= 5:
            structure_1hr = self.analyze_market_structure(data['1hr'])
            result['trend_1hr'] = structure_1hr['trend']
        
        # 3. 15分钟图寻找信号
        if '15min' in data and len(data['15min']) >= 10:
            structure_15min = self.analyze_market_structure(data['15min'])
            result['trend_15min'] = structure_15min['trend']
        
        # 4. 检查FVG对齐
        for tf in ['1hr', '15min', '5min']:
            if tf in data:
                fvgs = self.detect_fvg(data[tf])
                if fvgs:
                    result['fvg_aligned'] = True
                    break
        
        # 5. 流动性分析
        if '15min' in data:
            high_liq, low_liq = self.find_liquidity(data['15min'])
            result['liquidity_high'] = high_liq
            result['liquidity_low'] = low_liq
        
        # 6. 确定交易方向（多时间框架对齐）
        trend_4hr = result['trend_4hr']
        trend_1hr = result['trend_1hr']
        trend_15min = result['trend_15min']
        
        # 牛市对齐
        if trend_4hr == 'bullish' and trend_1hr in ['bullish', 'ranging'] and trend_15min == 'bullish':
            result['direction'] = 'BUY'
            result['confidence'] = 0.85
        # 熊市对齐
        elif trend_4hr == 'bearish' and trend_1hr in ['bearish', 'ranging'] and trend_15min == 'bearish':
            result['direction'] = 'SELL'
            result['confidence'] = 0.85
        # 次级确认
        elif trend_15min == 'bullish' and result['fvg_aligned']:
            result['direction'] = 'BUY'
            result['confidence'] = 0.6
        elif trend_15min == 'bearish' and result['fvg_aligned']:
            result['direction'] = 'SELL'
            result['confidence'] = 0.6
        else:
            result['direction'] = None
            result['confidence'] = 0.0
        
        return result
    
    def generate_signal(self, data: Dict[str, pd.DataFrame], current_price: float,
                        current_time: datetime = None) -> Optional[Dict]:
        """生成交易信号（多时间框架版）
        
        Args:
            data: {'4hr': df, '1hr': df, '15min': df, '5min': df}
            current_price: 当前价格
            current_time: 当前时间
        """
        if self.active_trade:
            return None
        
        # 防重复信号（5分钟内不重复）
        if self.last_signal_time and current_time:
            if (current_time - self.last_signal_time).total_seconds() < 300:
                return None
        
        # 多时间框架分析
        mtf_analysis = self.analyze_multi_timeframe(data)
        
        direction = mtf_analysis['direction']
        confidence = mtf_analysis['confidence']
        
        if not direction or confidence < 0.5:
            return None
        
        # 获取15分钟数据做精细分析
        df_15min = data.get('15min', pd.DataFrame())
        if df_15min.empty or len(df_15min) < 20:
            return None
        
        # 检查FVG
        fvgs = self.detect_fvg(df_15min)
        valid_fvg = False
        
        for fvg in fvgs[-5:]:
            if direction == 'BUY' and fvg['type'] == 'bullish':
                if fvg['low'] <= current_price <= fvg['high'] + 10:
                    valid_fvg = True
                    break
            elif direction == 'SELL' and fvg['type'] == 'bearish':
                if fvg['high'] >= current_price >= fvg['low'] - 10:
                    valid_fvg = True
                    break
        
        if not valid_fvg:
            return None
        
        # 流动性确认
        high_liq = mtf_analysis.get('liquidity_high', current_price)
        low_liq = mtf_analysis.get('liquidity_low', current_price)
        
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
        
        if risk_distance <= 0:
            return None
        
        # 增强置信度
        confidence = min(confidence + 0.1 * len(fvgs[-10:]), 0.95)
        
        # 添加BOS加分
        structure = self.analyze_market_structure(df_15min)
        if structure['bos']:
            confidence += 0.1
        if structure['choch']:
            confidence += 0.05
        
        self.last_signal_time = current_time
        
        return {
            'action': direction,
            'entry_price': current_price,
            'stop_loss': stop_loss,
            'risk_distance': risk_distance,
            'take_profit': current_price + risk_distance * 4 if direction == 'BUY' else current_price - risk_distance * 4,
            'confidence': min(confidence, 1.0),
            'trend_4hr': mtf_analysis['trend_4hr'],
            'trend_1hr': mtf_analysis['trend_1hr'],
            'trend_15min': mtf_analysis['trend_15min'],
            'mtf_analysis': mtf_analysis
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
            return {
                'status': 'active',
                'trade': self.active_trade
            }
        return {'status': 'idle'}
    
    def reset(self):
        """重置策略状态"""
        self.active_trade = None
        self.last_signal_time = None


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


STRATEGY_CONFIG = {
    'version': 'V1.0',
    'name': 'ICT/SMC 移动止损策略 (多时间框架)',
    'sessions': {
        'extended': {'start': 7, 'end': 20, 'tz': 'CST'}
    },
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
        '5min': '精确入场',
        '1min': '数据存储'
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
