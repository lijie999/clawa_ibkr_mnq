"""
多时间框架 ICT/SMC 策略

遵循 1分钟、5分钟、1小时、日线 的四重时间框架分析。
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from config import Config
from logger import logger

class MultiTimeframeStrategy:
    """多时间框架策略引擎"""
    
    def __init__(self):
        # 时间框架配置（从高到低）
        self.timeframes = {
            'daily': '1 day',
            'hourly': '1 hour', 
            'five_min': '5 mins',
            'one_min': '1 min'
        }
        
        # 权重配置（高时间框架权重更高）
        self.weights = {
            'daily': 0.4,
            'hourly': 0.3,
            'five_min': 0.2,
            'one_min': 0.1
        }
        
    def analyze_multi_timeframe(self, data_dict: Dict[str, pd.DataFrame]) -> Dict[str, any]:
        """
        多时间框架综合分析
        
        Args:
            data_dict (Dict): 包含各时间框架数据的字典
            
        Returns:
            Dict: 综合分析结果
        """
        if not self._validate_data(data_dict):
            return {'error': 'Insufficient data for multi-timeframe analysis'}
            
        # 分析各时间框架
        daily_analysis = self._analyze_timeframe(data_dict['daily'], 'daily')
        hourly_analysis = self._analyze_timeframe(data_dict['hourly'], 'hourly')  
        five_min_analysis = self._analyze_timeframe(data_dict['five_min'], 'five_min')
        one_min_analysis = self._analyze_timeframe(data_dict['one_min'], 'one_min')
        
        # 综合信号
        combined_signal = self._combine_signals(
            daily_analysis, hourly_analysis, 
            five_min_analysis, one_min_analysis
        )
        
        return {
            'daily': daily_analysis,
            'hourly': hourly_analysis,
            'five_min': five_min_analysis,
            'one_min': one_min_analysis,
            'combined': combined_signal
        }
    
    def _validate_data(self, data_dict: Dict[str, pd.DataFrame]) -> bool:
        """验证数据完整性"""
        required_timeframes = ['daily', 'hourly', 'five_min', 'one_min']
        for tf in required_timeframes:
            if tf not in data_dict or len(data_dict[tf]) < 10:
                logger.warning(f"Insufficient data for timeframe: {tf}")
                return False
        return True
    
    def _analyze_timeframe(self, data: pd.DataFrame, timeframe: str) -> Dict[str, any]:
        """
        单时间框架分析
        
        Args:
            data (pd.DataFrame): OHLCV 数据
            timeframe (str): 时间框架标识
            
        Returns:
            Dict: 分析结果
        """
        if len(data) < 3:
            return {'trend': 'unknown', 'signal': None}
            
        # 1. 趋势分析
        trend = self._determine_trend(data)
        
        # 2. 关键水平识别
        support_resistance = self._identify_support_resistance(data)
        
        # 3. ICT/SMC 信号检测
        ict_signals = self._detect_ict_signals(data, timeframe)
        smc_signals = self._detect_smc_signals(data, timeframe)
        
        # 4. 信号强度评估
        signal_strength = self._calculate_signal_strength(
            trend, ict_signals, smc_signals, timeframe
        )
        
        return {
            'trend': trend,
            'support_levels': support_resistance['support'],
            'resistance_levels': support_resistance['resistance'],
            'ict_signals': ict_signals,
            'smc_signals': smc_signals,
            'signal_strength': signal_strength,
            'timeframe_weight': self.weights[timeframe]
        }
    
    def _determine_trend(self, data: pd.DataFrame) -> str:
        """确定趋势方向"""
        # 使用移动平均线判断趋势
        ma_20 = data['close'].rolling(20).mean().iloc[-1]
        ma_50 = data['close'].rolling(50).mean().iloc[-1]
        current_price = data['close'].iloc[-1]
        
        if current_price > ma_20 > ma_50:
            return 'bullish'
        elif current_price < ma_20 < ma_50:
            return 'bearish'
        else:
            return 'ranging'
    
    def _identify_support_resistance(self, data: pd.DataFrame) -> Dict[str, List[float]]:
        """识别支撑阻力位"""
        # 简化的支撑阻力识别
        recent_highs = data['high'].tail(20).nlargest(3).tolist()
        recent_lows = data['low'].tail(20).nsmallest(3).tolist()
        
        return {
            'support': recent_lows,
            'resistance': recent_highs
        }
    
    def _detect_ict_signals(self, data: pd.DataFrame, timeframe: str) -> Dict[str, any]:
        """检测 ICT 信号"""
        signals = {}
        
        # 市场结构转变 (BOS/CHoCH)
        signals['market_structure'] = self._detect_market_structure(data)
        
        # 公平价值缺口 (FVG)
        signals['fvg'] = self._detect_fvg(data, timeframe)
        
        # 订单块 (Order Blocks)
        signals['order_blocks'] = self._detect_order_blocks(data, timeframe)
        
        # 流动性水平
        signals['liquidity'] = self._detect_liquidity(data, timeframe)
        
        return signals
    
    def _detect_smc_signals(self, data: pd.DataFrame, timeframe: str) -> Dict[str, any]:
        """检测 SMC 信号"""
        signals = {}
        
        # 供需区域
        signals['supply_demand'] = self._detect_supply_demand(data, timeframe)
        
        # 失衡区域
        signals['imbalance'] = self._detect_imbalance(data, timeframe)
        
        # 机构行为
        signals['institutional_behavior'] = self._detect_institutional_behavior(data, timeframe)
        
        return signals
    
    def _detect_market_structure(self, data: pd.DataFrame) -> Dict[str, any]:
        """检测市场结构"""
        if len(data) < 3:
            return {'trend': 'unknown', 'bos': False, 'choch': False}
            
        highs = data['high'].values
        lows = data['low'].values
        
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
            
        # 检测 BOS (Break of Structure)
        bos_detected = False
        if trend == 'bullish' and recent_high > max(highs[-5:-1]):
            bos_detected = True
        elif trend == 'bearish' and recent_low < min(lows[-5:-1]):
            bos_detected = True
            
        # 检测 CHoCH (Change of Character)
        choch_detected = False
        if trend == 'bullish' and recent_low < prev_low:
            choch_detected = True
        elif trend == 'bearish' and recent_high > prev_high:
            choch_detected = True
            
        return {
            'trend': trend,
            'bos': bos_detected,
            'choch': choch_detected
        }
    
    def _detect_fvg(self, data: pd.DataFrame, timeframe: str) -> List[Dict]:
        """检测公平价值缺口"""
        fvgs = []
        sensitivity = self._get_fvg_sensitivity(timeframe)
        
        for i in range(2, len(data)):
            prev_candle = data.iloc[i-2]
            middle_candle = data.iloc[i-1]
            current_candle = data.iloc[i]
            
            # Bullish FVG
            if current_candle['low'] > prev_candle['high']:
                gap_size = current_candle['low'] - prev_candle['high']
                avg_range = (prev_candle['high'] - prev_candle['low'] + 
                           middle_candle['high'] - middle_candle['low'] + 
                           current_candle['high'] - current_candle['low']) / 3
                
                if gap_size > avg_range * sensitivity:
                    fvgs.append({
                        'type': 'bullish',
                        'start_price': prev_candle['high'],
                        'end_price': current_candle['low'],
                        'gap_size': gap_size,
                        'timeframe': timeframe
                    })
            
            # Bearish FVG  
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
                        'timeframe': timeframe
                    })
                    
        return fvgs
    
    def _get_fvg_sensitivity(self, timeframe: str) -> float:
        """根据时间框架调整 FVG 敏感度"""
        sensitivity_map = {
            'daily': 0.5,      # 日线更严格
            'hourly': 0.6,
            'five_min': 0.7,
            'one_min': 0.8     # 1分钟更敏感
        }
        return sensitivity_map.get(timeframe, 0.7)
    
    def _detect_order_blocks(self, data: pd.DataFrame, timeframe: str) -> List[Dict]:
        """检测订单块"""
        order_blocks = []
        
        # 在高时间框架上寻找更强的订单块
        lookback_periods = {
            'daily': 50,
            'hourly': 30, 
            'five_min': 20,
            'one_min': 10
        }
        
        lookback = lookback_periods.get(timeframe, 20)
        
        for i in range(5, len(data)):
            candle = data.iloc[i]
            prev_candle = data.iloc[i-1]
            
            price_change = (candle['close'] - prev_candle['close']) / prev_candle['close']
            volume_ratio = candle['volume'] / data['volume'].iloc[i-10:i].mean()
            
            # 强势突破条件
            if abs(price_change) > 0.005 and volume_ratio > 1.5:
                block_start = min(candle['open'], candle['close'])
                block_end = max(candle['open'], candle['close'])
                
                order_blocks.append({
                    'type': 'bullish' if price_change > 0 else 'bearish',
                    'start_price': block_start,
                    'end_price': block_end,
                    'strength': abs(price_change) * volume_ratio,
                    'timeframe': timeframe
                })
                
        return order_blocks
    
    def _detect_liquidity(self, data: pd.DataFrame, timeframe: str) -> Dict[str, List[float]]:
        """检测流动性水平"""
        # 高时间框架的流动性更重要
        recent_highs = data['high'].tail(20).nlargest(3).tolist()
        recent_lows = data['low'].tail(20).nsmallest(3).tolist()
        
        return {
            'sell_side_liquidity': recent_highs,  # 止损猎杀区域（上方）
            'buy_side_liquidity': recent_lows     # 止损猎杀区域（下方）
        }
    
    def _detect_supply_demand(self, data: pd.DataFrame, timeframe: str) -> List[Dict]:
        """检测供需区域"""
        supply_demand_zones = []
        
        # 供需区域通常在强突破后形成
        for i in range(10, len(data)):
            # 检测强阳线后的回调区域（需求区）
            if (data.iloc[i]['close'] > data.iloc[i]['open'] and 
                (data.iloc[i]['close'] - data.iloc[i]['open']) / data.iloc[i]['open'] > 0.01):
                
                # 需求区：强阳线的实体范围
                demand_zone = {
                    'type': 'demand',
                    'price_level': data.iloc[i]['open'],
                    'strength': (data.iloc[i]['close'] - data.iloc[i]['open']) / data.iloc[i]['open'],
                    'timeframe': timeframe
                }
                supply_demand_zones.append(demand_zone)
                
            # 检测强阴线后的反弹区域（供给区）
            elif (data.iloc[i]['close'] < data.iloc[i]['open'] and 
                  (data.iloc[i]['open'] - data.iloc[i]['close']) / data.iloc[i]['open'] > 0.01):
                  
                supply_zone = {
                    'type': 'supply',
                    'price_level': data.iloc[i]['open'],
                    'strength': (data.iloc[i]['open'] - data.iloc[i]['close']) / data.iloc[i]['open'],
                    'timeframe': timeframe
                }
                supply_demand_zones.append(supply_zone)
                
        return supply_demand_zones
    
    def _detect_imbalance(self, data: pd.DataFrame, timeframe: str) -> List[Dict]:
        """检测失衡区域"""
        imbalances = []
        
        for i in range(1, len(data)):
            current = data.iloc[i]
            prev = data.iloc[i-1]
            
            # 检测价格快速移动造成的失衡
            price_move = abs(current['close'] - prev['close']) / prev['close']
            if price_move > 0.008:  # 0.8% 以上的快速移动
                imbalance = {
                    'direction': 'up' if current['close'] > prev['close'] else 'down',
                    'magnitude': price_move,
                    'start_price': prev['close'],
                    'end_price': current['close'],
                    'timeframe': timeframe
                }
                imbalances.append(imbalance)
                
        return imbalances
    
    def _detect_institutional_behavior(self, data: pd.DataFrame, timeframe: str) -> Dict[str, any]:
        """检测机构行为"""
        # 机构行为通常表现为：
        # 1. 大成交量
        # 2. 价格在关键水平反复测试
        # 3. 缓慢的积累/派发过程
        
        avg_volume = data['volume'].mean()
        high_volume_threshold = avg_volume * 2
        
        institutional_activity = {
            'high_volume_bars': len(data[data['volume'] > high_volume_threshold]),
            'key_level_tests': self._count_key_level_tests(data),
            'accumulation_distribution': self._detect_accumulation_distribution(data),
            'timeframe': timeframe
        }
        
        return institutional_activity
    
    def _count_key_level_tests(self, data: pd.DataFrame) -> int:
        """计算关键水平测试次数"""
        # 简化实现：计算价格在近期高低点附近的次数
        recent_high = data['high'].tail(10).max()
        recent_low = data['low'].tail(10).min()
        
        test_count = 0
        for price in data['close'].tail(20):
            if abs(price - recent_high) < (recent_high - recent_low) * 0.02:
                test_count += 1
            elif abs(price - recent_low) < (recent_high - recent_low) * 0.02:
                test_count += 1
                
        return test_count
    
    def _detect_accumulation_distribution(self, data: pd.DataFrame) -> str:
        """检测积累/派发阶段"""
        # 简化实现：基于价格和成交量的关系
        price_change = (data['close'].iloc[-1] - data['close'].iloc[-10]) / data['close'].iloc[-10]
        volume_change = (data['volume'].iloc[-1] - data['volume'].iloc[-10]) / data['volume'].iloc[-10]
        
        if price_change < 0.01 and volume_change > 0.1:
            return 'accumulation'  # 价格上涨缓慢但成交量增加
        elif price_change < -0.01 and volume_change > 0.1:
            return 'distribution'  # 价格下跌但成交量增加
        else:
            return 'neutral'
    
    def _calculate_signal_strength(self, trend: str, ict_signals: Dict, 
                                smc_signals: Dict, timeframe: str) -> float:
        """计算信号强度"""
        strength = 0.0
        
        # 趋势强度
        if trend in ['bullish', 'bearish']:
            strength += 0.3
            
        # ICT 信号强度
        if ict_signals['market_structure']['bos']:
            strength += 0.2
        if ict_signals['market_structure']['choch']:
            strength += 0.15
        if ict_signals['fvg']:
            strength += 0.1 * len(ict_signals['fvg'])
        if ict_signals['order_blocks']:
            strength += 0.1 * len(ict_signals['order_blocks'])
            
        # SMC 信号强度  
        if smc_signals['supply_demand']:
            strength += 0.05 * len(smc_signals['supply_demand'])
        if smc_signals['imbalance']:
            strength += 0.05 * len(smc_signals['imbalance'])
            
        # 时间框架权重调整
        strength *= self.weights[timeframe]
        
        return min(strength, 1.0)
    
    def _combine_signals(self, daily: Dict, hourly: Dict, 
                       five_min: Dict, one_min: Dict) -> Dict[str, any]:
        """综合多时间框架信号"""
        
        # 计算综合趋势
        trend_score = (
            (1 if daily['trend'] == 'bullish' else -1 if daily['trend'] == 'bearish' else 0) * daily['signal_strength'] +
            (1 if hourly['trend'] == 'bullish' else -1 if hourly['trend'] == 'bearish' else 0) * hourly['signal_strength'] +
            (1 if five_min['trend'] == 'bullish' else -1 if five_min['trend'] == 'bearish' else 0) * five_min['signal_strength'] +
            (1 if one_min['trend'] == 'bullish' else -1 if one_min['trend'] == 'bearish' else 0) * one_min['signal_strength']
        )
        
        combined_trend = 'bullish' if trend_score > 0 else 'bearish' if trend_score < 0 else 'ranging'
        
        # 综合信号强度
        total_strength = (
            daily['signal_strength'] + hourly['signal_strength'] + 
            five_min['signal_strength'] + one_min['signal_strength']
        )
        
        # 生成交易信号
        trade_signal = self._generate_trade_signal(
            combined_trend, total_strength, 
            daily, hourly, five_min, one_min
        )
        
        return {
            'trend': combined_trend,
            'strength': total_strength,
            'trade_signal': trade_signal,
            'confidence': min(total_strength, 1.0)
        }
    
    def _generate_trade_signal(self, trend: str, strength: float,
                             daily: Dict, hourly: Dict, 
                             five_min: Dict, one_min: Dict) -> Optional[Dict]:
        """生成交易信号"""
        if strength < 0.3 or trend == 'ranging':
            return None
            
        # 确定入场价格（基于1分钟图）
        current_price = one_min.get('support_levels', [0])[-1] if trend == 'bullish' else one_min.get('resistance_levels', [float('inf')])[0]
        
        # 确定止损（基于订单块或关键水平）
        if trend == 'bullish':
            stop_loss = min([
                daily.get('support_levels', [float('inf')])[0] if daily.get('support_levels') else float('inf'),
                hourly.get('support_levels', [float('inf')])[0] if hourly.get('support_levels') else float('inf'),
                current_price - 50  # 默认止损
            ])
            take_profit = current_price + (current_price - stop_loss) * 2  # 1:2 风险回报比
        else:
            stop_loss = max([
                daily.get('resistance_levels', [0])[0] if daily.get('resistance_levels') else 0,
                hourly.get('resistance_levels', [0])[0] if hourly.get('resistance_levels') else 0,
                current_price + 50  # 默认止损
            ])
            take_profit = current_price - (stop_loss - current_price) * 2  # 1:2 风险回报比
            
        return {
            'action': 'BUY' if trend == 'bullish' else 'SELL',
            'entry_price': current_price,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'risk_reward_ratio': 2.0,
            'confidence': min(strength, 1.0),
            'reason': f"Multi-timeframe confirmation: {trend} trend with strength {strength:.2f}"
        }

# 使用示例
if __name__ == "__main__":
    strategy = MultiTimeframeStrategy()
    
    # 假设有四个时间框架的数据
    # daily_data = get_historical_data('MNQ', '1 day', 30)
    # hourly_data = get_historical_data('MNQ', '1 hour', 100)  
    # five_min_data = get_historical_data('MNQ', '5 mins', 500)
    # one_min_data = get_historical_data('MNQ', '1 min', 1000)
    #
    # data_dict = {
    #     'daily': daily_data,
    #     'hourly': hourly_data,
    #     'five_min': five_min_data,
    #     'one_min': one_min_data
    # }
    #
    # result = strategy.analyze_multi_timeframe(data_dict)
    # print(f"Combined signal: {result['combined']['trade_signal']}")