"""
ICT/SMC 策略引擎模块

实现 Inner Circle Trader (ICT) 和 Smart Money Concepts (SMC) 的核心交易逻辑。
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from config import Config
from logger import logger

class ICTSMCStrategy:
    """ICT/SMC 策略引擎"""
    
    def __init__(self):
        self.order_blocks = []  # 订单块列表
        self.fvgs = []          # 公平价值缺口列表
        self.liquidity_levels = []  # 流动性水平列表
        self.market_structure = None  # 市场结构状态
        
    def analyze_market_structure(self, data: pd.DataFrame) -> Dict[str, any]:
        """
        分析市场结构
        
        Args:
            data (pd.DataFrame): OHLCV 数据
            
        Returns:
            Dict: 市场结构分析结果
        """
        if len(data) < 3:
            return {'trend': 'unknown', 'structure': 'insufficient_data'}
            
        # 识别高点和低点
        highs = data['high'].values
        lows = data['low'].values
        
        # 检测市场结构转变 (BOS/CHoCH)
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
            
        # 检测 Break of Structure (BOS)
        bos_detected = False
        if trend == 'bullish' and recent_high > max(highs[-5:-1]):
            bos_detected = True
        elif trend == 'bearish' and recent_low < min(lows[-5:-1]):
            bos_detected = True
            
        # 检测 Change of Character (CHoCH)
        choch_detected = False
        if trend == 'bullish' and recent_low < prev_low:
            choch_detected = True
        elif trend == 'bearish' and recent_high > prev_high:
            choch_detected = True
            
        return {
            'trend': trend,
            'bos_detected': bos_detected,
            'choch_detected': choch_detected,
            'recent_high': recent_high,
            'recent_low': recent_low
        }
    
    def detect_fvg(self, data: pd.DataFrame) -> List[Dict[str, any]]:
        """
        检测公平价值缺口 (Fair Value Gap)
        
        Args:
            data (pd.DataFrame): OHLCV 数据
            
        Returns:
            List[Dict]: FVG 列表
        """
        fvgs = []
        sensitivity = Config.FVG_SENSITIVITY
        
        for i in range(2, len(data)):
            # 三根K线模式检测FVG
            prev_candle = data.iloc[i-2]
            middle_candle = data.iloc[i-1]
            current_candle = data.iloc[i]
            
            # Bullish FVG: 当前K线低点 > 前一根K线高点
            if current_candle['low'] > prev_candle['high']:
                gap_size = current_candle['low'] - prev_candle['high']
                avg_range = (prev_candle['high'] - prev_candle['low'] + 
                           middle_candle['high'] - middle_candle['low'] + 
                           current_candle['high'] - current_candle['low']) / 3
                
                # 根据敏感度过滤
                if gap_size > avg_range * sensitivity:
                    fvgs.append({
                        'type': 'bullish',
                        'start_price': prev_candle['high'],
                        'end_price': current_candle['low'],
                        'gap_size': gap_size,
                        'timestamp': current_candle.name,
                        'valid_until': None  # 需要后续逻辑确定有效期
                    })
            
            # Bearish FVG: 当前K线高点 < 前一根K线低点  
            elif current_candle['high'] < prev_candle['low']:
                gap_size = prev_candle['low'] - current_candle['high']
                avg_range = (prev_candle['high'] - prev_candle['low'] + 
                           middle_candle['high'] - middle_candle['low'] + 
                           current_candle['high'] - current_candle['low']) / 3
                
                if gap_size > avg_range * sensitivity:
                    fvgs.append({
                        'type': 'bearish',
                        'start_price': current_candle['high'],
                        'end_price': prev_candle['low'],
                        'gap_size': gap_size,
                        'timestamp': current_candle.name,
                        'valid_until': None
                    })
                    
        return fvgs
    
    def identify_order_blocks(self, data: pd.DataFrame) -> List[Dict[str, any]]:
        """
        识别订单块 (Order Blocks)
        
        Args:
            data (pd.DataFrame): OHLCV 数据
            
        Returns:
            List[Dict]: 订单块列表
        """
        order_blocks = []
        
        # 简化的订单块识别：寻找强突破后的回撤区域
        for i in range(5, len(data)):
            # 检测强阳线（涨幅大，成交量高）
            candle = data.iloc[i]
            prev_candle = data.iloc[i-1]
            
            price_change = (candle['close'] - prev_candle['close']) / prev_candle['close']
            volume_ratio = candle['volume'] / data['volume'].iloc[i-10:i].mean()
            
            # 强势突破条件
            if (abs(price_change) > 0.01 and volume_ratio > 1.5):
                # 订单块区域：突破K线的实体范围
                block_start = min(candle['open'], candle['close'])
                block_end = max(candle['open'], candle['close'])
                
                order_blocks.append({
                    'type': 'bullish' if price_change > 0 else 'bearish',
                    'start_price': block_start,
                    'end_price': block_end,
                    'timestamp': candle.name,
                    'strength': abs(price_change) * volume_ratio,
                    'tested': False  # 是否已被价格测试
                })
                
        return order_blocks
    
    def identify_liquidity_levels(self, data: pd.DataFrame) -> List[Dict[str, any]]:
        """
        识别流动性水平
        
        Args:
            data (pd.DataFrame): OHLCV 数据
            
        Returns:
            List[Dict]: 流动性水平列表
        """
        liquidity_levels = []
        threshold = Config.LIQUIDITY_THRESHOLD
        
        # 识别近期高点和低点作为流动性池
        recent_highs = data['high'].tail(20).nlargest(3)
        recent_lows = data['low'].tail(20).nsmallest(3)
        
        # 高点流动性（止损猎杀区域）
        for high in recent_highs:
            liquidity_levels.append({
                'type': 'sell_side',
                'price': high,
                'strength': threshold
            })
            
        # 低点流动性（止损猎杀区域）
        for low in recent_lows:
            liquidity_levels.append({
                'type': 'buy_side', 
                'price': low,
                'strength': threshold
            })
            
        return liquidity_levels
    
    def generate_trading_signal(self, data: pd.DataFrame, current_price: float) -> Optional[Dict[str, any]]:
        """
        生成交易信号
        
        Args:
            data (pd.DataFrame): OHLCV 数据
            current_price (float): 当前价格
            
        Returns:
            Dict or None: 交易信号
        """
        try:
            # 1. 分析市场结构
            market_analysis = self.analyze_market_structure(data)
            if market_analysis['trend'] == 'unknown':
                return None
                
            # 2. 检测 FVG
            fvgs = self.detect_fvg(data)
            
            # 3. 识别订单块
            order_blocks = self.identify_order_blocks(data)
            
            # 4. 识别流动性水平
            liquidity_levels = self.identify_liquidity_levels(data)
            
            # 5. 综合信号生成
            signal = self._synthesize_signal(
                market_analysis, fvgs, order_blocks, 
                liquidity_levels, current_price
            )
            
            if signal:
                logger.info(f"Generated trading signal: {signal}")
                
            return signal
            
        except Exception as e:
            logger.error(f"Error generating trading signal: {e}")
            return None
    
    def _synthesize_signal(self, market_analysis: Dict, fvgs: List[Dict], 
                          order_blocks: List[Dict], liquidity_levels: List[Dict],
                          current_price: float) -> Optional[Dict[str, any]]:
        """
        综合多个因素生成最终交易信号
        """
        # 简化的信号逻辑：需要多个条件同时满足
        
        # 条件1: 市场结构支持
        if market_analysis['trend'] not in ['bullish', 'bearish']:
            return None
            
        # 条件2: 存在有效的FVG
        valid_fvgs = [fvg for fvg in fvgs if self._is_fvg_valid(fvg, current_price)]
        if not valid_fvgs:
            return None
            
        # 条件3: 接近订单块区域
        near_order_block = self._is_near_order_block(order_blocks, current_price)
        if not near_order_block:
            return None
            
        # 条件4: 流动性确认
        liquidity_confirmed = self._check_liquidity_confirmation(
            liquidity_levels, current_price, market_analysis['trend']
        )
        if not liquidity_confirmed:
            return None
            
        # 生成信号
        trend = market_analysis['trend']
        action = 'BUY' if trend == 'bullish' else 'SELL'
        
        # 设置止损和止盈
        stop_loss = self._calculate_stop_loss(
            order_blocks, liquidity_levels, current_price, action
        )
        take_profit = self._calculate_take_profit(
            liquidity_levels, current_price, action
        )
        
        return {
            'action': action,
            'entry_price': current_price,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'risk_reward_ratio': (take_profit - current_price) / (current_price - stop_loss) if action == 'BUY' 
                              else (current_price - take_profit) / (stop_loss - current_price),
            'confidence': self._calculate_confidence(
                market_analysis, valid_fvgs, near_order_block
            ),
            'reason': f"ICT/SMC signal: {trend} trend with FVG and order block confirmation"
        }
    
    def _is_fvg_valid(self, fvg: Dict, current_price: float) -> bool:
        """检查FVG是否有效"""
        # 简单逻辑：当前价格在FVG范围内或刚突破
        if fvg['type'] == 'bullish':
            return current_price >= fvg['start_price'] and current_price <= fvg['end_price'] + 10
        else:
            return current_price <= fvg['end_price'] and current_price >= fvg['start_price'] - 10
    
    def _is_near_order_block(self, order_blocks: List[Dict], current_price: float) -> bool:
        """检查是否接近订单块"""
        for block in order_blocks:
            if block['start_price'] <= current_price <= block['end_price']:
                return True
            # 或者在订单块附近（5点范围内）
            if abs(current_price - block['start_price']) < 5 or abs(current_price - block['end_price']) < 5:
                return True
        return False
    
    def _check_liquidity_confirmation(self, liquidity_levels: List[Dict], 
                                    current_price: float, trend: str) -> bool:
        """检查流动性确认"""
        # 简化逻辑：存在相关的流动性水平
        if trend == 'bullish':
            # 寻找上方的卖方流动性
            for level in liquidity_levels:
                if level['type'] == 'sell_side' and level['price'] > current_price:
                    return True
        else:
            # 寻找下方的买方流动性  
            for level in liquidity_levels:
                if level['type'] == 'buy_side' and level['price'] < current_price:
                    return True
        return False
    
    def _calculate_stop_loss(self, order_blocks: List[Dict], liquidity_levels: List[Dict],
                           current_price: float, action: str) -> float:
        """计算止损位"""
        if action == 'BUY':
            # 买入止损：订单块下方或最近支撑
            support_levels = [block['start_price'] for block in order_blocks if block['type'] == 'bullish']
            if support_levels:
                return min(support_levels) - 2
            else:
                return current_price - 20  # 默认止损
        else:
            # 卖出止损：订单块上方或最近阻力
            resistance_levels = [block['end_price'] for block in order_blocks if block['type'] == 'bearish']
            if resistance_levels:
                return max(resistance_levels) + 2
            else:
                return current_price + 20  # 默认止损
    
    def _calculate_take_profit(self, liquidity_levels: List[Dict], 
                             current_price: float, action: str) -> float:
        """计算止盈位"""
        if action == 'BUY':
            # 买入止盈：上方流动性水平
            sell_liquidity = [level['price'] for level in liquidity_levels if level['type'] == 'sell_side']
            if sell_liquidity:
                return min([p for p in sell_liquidity if p > current_price] or [current_price + 40])
            else:
                return current_price + 40
        else:
            # 卖出止盈：下方流动性水平
            buy_liquidity = [level['price'] for level in liquidity_levels if level['type'] == 'buy_side']
            if buy_liquidity:
                return max([p for p in buy_liquidity if p < current_price] or [current_price - 40])
            else:
                return current_price - 40
    
    def _calculate_confidence(self, market_analysis: Dict, fvgs: List[Dict], 
                            near_order_block: bool) -> float:
        """计算信号置信度"""
        confidence = 0.5  # 基础置信度
        
        # 市场结构强度
        if market_analysis.get('bos_detected'):
            confidence += 0.2
        if market_analysis.get('choch_detected'):
            confidence += 0.1
            
        # FVG 数量和质量
        confidence += min(len(fvgs) * 0.1, 0.2)
        
        # 订单块确认
        if near_order_block:
            confidence += 0.1
            
        return min(confidence, 1.0)

# 使用示例：
# strategy = ICTSMCStrategy()
# signal = strategy.generate_trading_signal(historical_data, current_price)