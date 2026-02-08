"""
回测模块

提供过去3个月的 MNQ 期货回测功能，基于 ICT/SMC 策略。
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json
import os
from ict_smc_strategy import ICTSMCStrategy
from risk_management import RiskManager

class Backtester:
    """回测引擎"""
    
    def __init__(self, initial_capital=100000):
        self.initial_capital = initial_capital
        self.strategy = ICTSMCStrategy()
        self.risk_manager = RiskManager()
        self.results = {}
        
    def fetch_historical_data(self, days=90):
        """
        获取历史数据（模拟数据，实际使用时从 IBKR 获取）
        
        Args:
            days (int): 回测天数，默认90天（3个月）
            
        Returns:
            pd.DataFrame: OHLCV 数据
        """
        # 模拟历史数据生成（实际应从 IBKR API 获取）
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        # 创建日期范围（交易日）
        dates = pd.date_range(start=start_date, end=end_date, freq='15min')
        # 过滤交易时间（美东时间 8:30-16:00）
        trading_hours = []
        for date in dates:
            hour = date.hour
            if (hour >= 8 and hour < 16) or (hour == 16 and date.minute == 0):
                trading_hours.append(date)
                
        dates = pd.DatetimeIndex(trading_hours)
        
        # 生成模拟价格数据
        np.random.seed(42)
        base_price = 18000
        prices = [base_price]
        
        for i in range(1, len(dates)):
            # 添加趋势和波动
            trend = 0.0001 * i  # 轻微上涨趋势
            noise = np.random.normal(0, 10)  # 随机波动
            new_price = prices[-1] + trend + noise
            prices.append(new_price)
            
        # 生成 OHLCV 数据
        data = []
        for i, date in enumerate(dates):
            price = prices[i]
            high = price + abs(np.random.normal(0, 5))
            low = price - abs(np.random.normal(0, 5))
            open_price = price + np.random.normal(0, 2)
            close_price = price
            volume = np.random.randint(1000, 5000)
            
            data.append({
                'date': date,
                'open': open_price,
                'high': high,
                'low': low,
                'close': close_price,
                'volume': volume
            })
            
        df = pd.DataFrame(data)
        df.set_index('date', inplace=True)
        return df
    
    def run_backtest(self, data, risk_percentage=1.0, max_position_size=2):
        """
        执行回测
        
        Args:
            data (pd.DataFrame): 历史数据
            risk_percentage (float): 单笔风险百分比
            max_position_size (int): 最大持仓手数
            
        Returns:
            dict: 回测结果
        """
        # 初始化回测参数
        capital = self.initial_capital
        equity_curve = [capital]
        trades = []
        positions = []
        current_position = 0
        daily_pnl = 0
        daily_loss = 0
        
        # 设置风险管理参数
        self.risk_manager.max_position_size = max_position_size
        
        print(f"开始回测 {len(data)} 根K线...")
        print(f"初始资金: ${self.initial_capital:,.2f}")
        print(f"风险参数: {risk_percentage}% 单笔风险, {max_position_size} 手最大持仓")
        print("-" * 60)
        
        for i in range(10, len(data)):  # 跳过前10根K线以确保有足够的数据
            current_price = data.iloc[i]['close']
            current_date = data.index[i]
            
            # 更新账户信息
            self.risk_manager.update_account_info(capital, daily_pnl)
            
            # 生成交易信号
            signal = self.strategy.generate_trading_signal(
                data.iloc[:i+1], 
                current_price
            )
            
            # 执行交易逻辑
            if signal and self.risk_manager.should_trade():
                # 计算仓位大小
                position_size = self.risk_manager.calculate_position_size(
                    signal['entry_price'],
                    signal['stop_loss']
                )
                
                if position_size > 0:
                    # 执行交易
                    trade_result = self.execute_trade(
                        signal, position_size, current_price, current_date
                    )
                    
                    if trade_result:
                        trades.append(trade_result)
                        capital += trade_result['pnl']
                        current_position += trade_result['position_change']
                        
                        # 更新权益曲线
                        equity_curve.append(capital)
                        
                        print(f"{current_date.strftime('%Y-%m-%d %H:%M')} | "
                              f"{signal['action']} {position_size}手 | "
                              f"价格: {current_price:.0f} | "
                              f"盈亏: ${trade_result['pnl']:,.2f} | "
                              f"总资金: ${capital:,.2f}")
            
            # 更新每日盈亏
            if i > 0:
                prev_close = data.iloc[i-1]['close']
                daily_pnl = (current_price - prev_close) * current_position * 2  # MNQ 合约乘数为 2
                
            # 更新权益曲线（即使没有交易）
            if len(equity_curve) <= i:
                equity_curve.append(capital)
        
        # 计算绩效指标
        performance = self.calculate_performance(equity_curve, trades, data)
        
        self.results = {
            'equity_curve': equity_curve,
            'trades': trades,
            'performance': performance,
            'parameters': {
                'initial_capital': self.initial_capital,
                'risk_percentage': risk_percentage,
                'max_position_size': max_position_size,
                'backtest_period': f"{data.index[0].strftime('%Y-%m-%d')} to {data.index[-1].strftime('%Y-%m-%d')}"
            }
        }
        
        return self.results
    
    def execute_trade(self, signal, position_size, current_price, timestamp):
        """
        执行交易（模拟）
        
        Args:
            signal (dict): 交易信号
            position_size (int): 仓位大小
            current_price (float): 当前价格
            timestamp: 交易时间戳
            
        Returns:
            dict: 交易结果
        """
        # 模拟立即执行（实际回测中需要更复杂的执行逻辑）
        action = signal['action']
        entry_price = current_price
        stop_loss = signal['stop_loss']
        take_profit = signal['take_profit']
        
        # 模拟持有到下一个信号或达到目标
        # 这里简化处理，假设在下一根K线平仓
        exit_price = current_price + (np.random.normal(0, 10))  # 随机盈亏
        
        # 计算盈亏
        if action == 'BUY':
            pnl = (exit_price - entry_price) * position_size * 2  # MNQ 合约乘数为 2
            position_change = position_size
        else:  # SELL
            pnl = (entry_price - exit_price) * position_size * 2
            position_change = -position_size
            
        return {
            'timestamp': timestamp,
            'action': action,
            'position_size': position_size,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'pnl': pnl,
            'position_change': position_change,
            'risk_reward_ratio': signal.get('risk_reward_ratio', 0),
            'confidence': signal.get('confidence', 0)
        }
    
    def calculate_performance(self, equity_curve, trades, data):
        """
        计算绩效指标
        
        Args:
            equity_curve (list): 权益曲线
            trades (list): 交易记录
            data (pd.DataFrame): 原始数据
            
        Returns:
            dict: 绩效指标
        """
        if len(equity_curve) < 2:
            return {}
            
        # 总收益率
        total_return = (equity_curve[-1] - equity_curve[0]) / equity_curve[0]
        
        # 年化收益率
        days = len(data) * 15 / (60 * 24)  # 15分钟K线转换为天数
        annualized_return = (1 + total_return) ** (365 / days) - 1 if days > 0 else 0
        
        # 最大回撤
        peak = equity_curve[0]
        max_drawdown = 0
        for equity in equity_curve:
            if equity > peak:
                peak = equity
            drawdown = (peak - equity) / peak
            max_drawdown = max(max_drawdown, drawdown)
            
        # 胜率
        winning_trades = sum(1 for trade in trades if trade['pnl'] > 0)
        win_rate = winning_trades / len(trades) if trades else 0
        
        # 盈亏比
        avg_win = np.mean([trade['pnl'] for trade in trades if trade['pnl'] > 0]) if winning_trades > 0 else 0
        avg_loss = np.mean([abs(trade['pnl']) for trade in trades if trade['pnl'] < 0]) if (len(trades) - winning_trades) > 0 else 0
        profit_factor = avg_win / avg_loss if avg_loss > 0 else float('inf')
        
        # 交易次数
        total_trades = len(trades)
        
        # 夏普比率（简化版）
        returns = np.diff(equity_curve) / equity_curve[:-1]
        sharpe_ratio = np.mean(returns) / np.std(returns) * np.sqrt(252 * 6.5 * 4) if len(returns) > 1 else 0  # 年化
        
        return {
            'total_return': total_return,
            'annualized_return': annualized_return,
            'max_drawdown': max_drawdown,
            'win_rate': win_rate,
            'profit_factor': profit_factor,
            'total_trades': total_trades,
            'sharpe_ratio': sharpe_ratio,
            'final_equity': equity_curve[-1],
            'best_trade': max(trades, key=lambda x: x['pnl'])['pnl'] if trades else 0,
            'worst_trade': min(trades, key=lambda x: x['pnl'])['pnl'] if trades else 0
        }
    
    def save_results(self, filename='backtest_results.json'):
        """保存回测结果"""
        # 转换不可序列化的对象
        results_copy = self.results.copy()
        if 'equity_curve' in results_copy:
            results_copy['equity_curve'] = [float(x) for x in results_copy['equity_curve']]
        if 'trades' in results_copy:
            trades_copy = []
            for trade in results_copy['trades']:
                trade_copy = trade.copy()
                trade_copy['timestamp'] = trade_copy['timestamp'].isoformat() if hasattr(trade_copy['timestamp'], 'isoformat') else str(trade_copy['timestamp'])
                trades_copy.append(trade_copy)
            results_copy['trades'] = trades_copy
            
        with open(filename, 'w') as f:
            json.dump(results_copy, f, indent=2)
            
        print(f"回测结果已保存到 {filename}")
        
    def print_summary(self):
        """打印回测摘要"""
        if not self.results:
            print("尚未运行回测")
            return
            
        perf = self.results['performance']
        params = self.results['parameters']
        
        print("\n" + "="*60)
        print("📈 回测结果摘要")
        print("="*60)
        print(f"回测期间: {params['backtest_period']}")
        print(f"初始资金: ${params['initial_capital']:,.2f}")
        print(f"最终资金: ${perf['final_equity']:,.2f}")
        print(f"总收益率: {perf['total_return']:.2%}")
        print(f"年化收益率: {perf['annualized_return']:.2%}")
        print(f"最大回撤: {perf['max_drawdown']:.2%}")
        print(f"胜率: {perf['win_rate']:.2%}")
        print(f"盈亏比: {perf['profit_factor']:.2f}")
        print(f"总交易次数: {perf['total_trades']}")
        print(f"夏普比率: {perf['sharpe_ratio']:.2f}")
        print(f"最佳交易: ${perf['best_trade']:,.2f}")
        print(f"最差交易: ${perf['worst_trade']:,.2f}")
        print("="*60)

# 使用示例
if __name__ == "__main__":
    # 创建回测器
    backtester = Backtester(initial_capital=100000)
    
    # 获取历史数据
    print("正在获取历史数据...")
    historical_data = backtester.fetch_historical_data(days=90)
    print(f"获取到 {len(historical_data)} 根15分钟K线数据")
    
    # 运行回测
    print("开始回测...")
    results = backtester.run_backtest(
        historical_data, 
        risk_percentage=1.0, 
        max_position_size=2
    )
    
    # 显示结果
    backtester.print_summary()
    
    # 保存结果
    backtester.save_results('backtest_results.json')