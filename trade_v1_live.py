#!/usr/bin/env python3
"""
CLAWA IBKR MNQ V1.0 实盘交易系统 (多时间框架版)

数据流:
IBKR Gateway → 1分钟K线 → 本地存储 → 多时间框架聚合 → 策略分析

时间框架:
- 1min: 数据存储 (2天)
- 5min: 精确入场 (2天)
- 15min: 入场信号 (2天)
- 1hr: 趋势确认 (2天)
- 4hr: 主要趋势 (2天)
"""

import signal
import asyncio
import nest_asyncio
nest_asyncio.apply()

from datetime import datetime
import pandas as pd
from config import Config
from logger import logger
from strategy_v1 import ICTSMCV1Strategy, RiskManagerV1
from data_manager import DataManager
from ib_insync import IB, Future


class LiveTradingV1:
    """IBKR 实盘交易 V1.0"""
    
    def __init__(self, initial_capital=100000):
        self.capital = initial_capital
        self.strategy = ICTSMCV1Strategy()
        self.risk = RiskManagerV1()
        self.data_manager = DataManager()
        self.running = False
        self.ib = None
        self.contract = None
        self.orders = []
        self.trade_history = []
        self.daily_pnl = 0.0
        self.last_update = None
    
    def connect_ibkr(self) -> bool:
        """连接 IBKR Gateway"""
        logger.info(f"正在连接 IBKR Gateway: {Config.IBKR_HOST}:{Config.IBKR_PORT}...")
        
        try:
            self.ib = IB()
            self.ib.connect(
                host=Config.IBKR_HOST,
                port=Config.IBKR_PORT,
                clientId=Config.IBKR_CLIENT_ID,
                timeout=30
            )
            
            self.contract = Future(
                symbol=Config.SYMBOL,
                exchange=Config.EXCHANGE,
                currency=Config.CURRENCY,
                lastTradeDateOrContractMonth=Config.CONTRACT_MONTH
            )
            
            logger.info("✅ IBKR Gateway 连接成功!")
            return True
            
        except Exception as e:
            logger.error("")
            logger.error("=" * 60)
            logger.error("❌ IBKR Gateway 连接失败!")
            logger.error("=" * 60)
            logger.error(f"错误信息: {e}")
            logger.error("")
            logger.error("请检查以下项目:")
            logger.error("1. IBKR Gateway/TWS 是否正在运行")
            logger.error(f"2. API 端口是否正确配置为: {Config.IBKR_PORT}")
            logger.error("3. 是否启用了 API 连接")
            logger.error("4. 防火墙是否允许连接")
            logger.error("=" * 60)
            return False
    
    def disconnect_ibkr(self):
        """断开 IBKR 连接"""
        if self.ib and self.ib.isConnected():
            self.ib.disconnect()
            logger.info("已断开 IBKR Gateway 连接")
    
    def initialize_data(self):
        """初始化数据管理器"""
        self.data_manager.initialize(self.ib, self.contract)
    
    def get_multi_timeframe_data(self) -> dict:
        """获取多时间框架数据"""
        return {
            '4hr': self.data_manager.get_data('4hr'),
            '1hr': self.data_manager.get_data('1hr'),
            '15min': self.data_manager.get_data('15min'),
            '5min': self.data_manager.get_data('5min'),
            '1min': self.data_manager.get_data('1min'),
        }
    
    async def run(self):
        """主循环"""
        if not self.connect_ibkr():
            return False
        
        self.initialize_data()
        
        self.running = True
        
        logger.info("")
        logger.info("=" * 60)
        logger.info("🚀 V1.0 实盘交易系统启动 (多时间框架)")
        logger.info("=" * 60)
        logger.info(f"初始资金: ${self.capital:,.2f}")
        logger.info(f"交易合约: {Config.SYMBOL} ({Config.EXCHANGE})")
        logger.info(f"交易时段: 07:00-20:00 CST")
        logger.info(f"策略: ICT/SMC 移动止损 V1.0 (MTF)")
        logger.info("=" * 60)
        
        # 显示数据状态
        bar_counts = self.data_manager.get_bar_count()
        logger.info("📊 数据状态:")
        for tf, count in bar_counts.items():
            logger.info(f"   {tf}: {count} 根K线")
        
        last_date = None
        last_minute = None
        
        while self.running:
            try:
                now = datetime.now()
                today = now.date()
                current_minute = now.minute
                
                if last_date != today:
                    last_date = today
                    self.daily_pnl = 0.0
                    logger.info(f"\n📅 {now.strftime('%Y-%m-%d')} - 新交易日开始")
                
                session = self.strategy.is_trading_session(now)
                
                if not session:
                    if now.minute % 30 == 0:
                        logger.debug(f"当前 {now.strftime('%H:%M')} 不在交易时段")
                    await asyncio.sleep(30)
                    continue
                
                # 每1分钟更新数据
                if current_minute != last_minute:
                    updated = self.data_manager.update()
                    if updated:
                        bar_counts = self.data_manager.get_bar_count()
                        logger.debug(f"📊 更新: {bar_counts}")
                    last_minute = current_minute
                
                # 获取多时间框架数据
                mtf_data = self.get_multi_timeframe_data()
                
                if mtf_data['15min'].empty or len(mtf_data['15min']) < 20:
                    await asyncio.sleep(30)
                    continue
                
                current_price = self.data_manager.get_current_price()
                
                if current_price <= 0:
                    await asyncio.sleep(30)
                    continue
                
                # 检查风险管理
                if not self.risk.should_trade(self.capital, self.daily_pnl):
                    if now.minute % 10 == 0:
                        logger.warning("风险管理阻止交易")
                    await asyncio.sleep(30)
                    continue
                
                # 策略逻辑
                status = self.strategy.get_status()
                
                if status['status'] == 'idle':
                    signal = self.strategy.generate_signal(mtf_data, current_price, now)
                    if signal:
                        size = self.risk.calculate_position_size(
                            self.capital,
                            signal['entry_price'],
                            signal['stop_loss']
                        )
                        
                        if size > 0:
                            self.strategy.open_position(signal, size)
                            
                            self.orders.append({
                                'action': signal['action'],
                                'size': size,
                                'entry_price': signal['entry_price'],
                                'time': now,
                                'status': 'open'
                            })
                            
                            logger.info("")
                            logger.info("=" * 60)
                            logger.info(f"📢 开仓信号: {signal['action']}")
                            logger.info(f"   合约: {Config.SYMBOL}")
                            logger.info(f"   手数: {size} 手")
                            logger.info(f"   入场价: ${current_price:.2f}")
                            logger.info(f"   止损价: ${signal['stop_loss']:.2f}")
                            logger.info(f"   置信度: {signal['confidence']:.0%}")
                            logger.info(f"   趋势: 4hr={signal.get('trend_4hr', '?')} | 1hr={signal.get('trend_1hr', '?')} | 15min={signal.get('trend_15min', '?')}")
                            logger.info("=" * 60)
                            
                            # 发送订单
                            order = self.ib.marketOrder(signal['action'], size)
                            trade = self.ib.placeOrder(self.contract, order)
                            logger.info(f"   订单ID: {trade.order.orderId}")
                
                elif status['status'] == 'active':
                    result = self.strategy.update_trade(current_price, now)
                    
                    if result['action'] == 'partial_close':
                        logger.info("")
                        logger.info("-" * 60)
                        logger.info(f"✂️ 半仓平仓 @ ${result['price']:.2f}")
                        logger.info(f"   盈利: ${result['pnl']:.2f} | RR: {result['rr']:.1f}R")
                        logger.info(f"   新止损: ${result['new_stop_loss']:.2f}")
                        logger.info("-" * 60)
                        
                        close_size = self.strategy.active_trade.get('partial_size', 0)
                        if close_size > 0:
                            action = 'SELL' if self.strategy.active_trade['action'] == 'BUY' else 'BUY'
                            order = self.ib.marketOrder(action, close_size)
                            self.ib.placeOrder(self.contract, order)
                        
                        self.daily_pnl += result['pnl']
                        self.capital += result['pnl']
                    
                    elif result['action'] == 'trail_stop':
                        if result['rr'] >= 2:
                            logger.info("")
                            logger.info("-" * 60)
                            logger.info(f"📍 移动止损 @ ${result['new_stop_loss']:.2f}")
                            logger.info(f"   当前盈利: {result['rr']:.1f}R")
                            logger.info("-" * 60)
                    
                    elif result['action'] == 'close':
                        logger.info("")
                        logger.info("=" * 60)
                        logger.info(f"✅ 平仓: {result['reason']}")
                        logger.info(f"   盈亏: ${result['pnl']:.2f} | RR: {result.get('rr', 0):.1f}R")
                        logger.info("=" * 60)
                        
                        remaining_size = self.strategy.active_trade.get('size', 0)
                        if remaining_size > 0:
                            action = 'SELL' if self.strategy.active_trade['action'] == 'BUY' else 'BUY'
                            order = self.ib.marketOrder(action, remaining_size)
                            self.ib.placeOrder(self.contract, order)
                        
                        self.daily_pnl += result['pnl']
                        self.capital += result['pnl']
                        
                        self.trade_history.append({
                            'entry_price': status['trade']['entry_price'],
                            'exit_price': current_price,
                            'pnl': result['pnl'],
                            'rr': result.get('rr', 0),
                            'time': now
                        })
                
                await asyncio.sleep(30)
                
            except Exception as e:
                logger.error(f"交易错误: {e}")
                await asyncio.sleep(30)
        
        self.disconnect_ibkr()
        return True
    
    def get_status(self) -> dict:
        return {
            'capital': self.capital,
            'daily_pnl': self.daily_pnl,
            'active_positions': len([o for o in self.orders if o['status'] == 'open']),
            'total_trades': len(self.trade_history)
        }


def signal_handler(signum, frame):
    logger.info("收到停止信号")


async def main():
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    trading = LiveTradingV1(initial_capital=100000)
    
    try:
        success = await trading.run()
        if not success:
            logger.info("\n❌ 请启动 IBKR Gateway 后重试")
            exit(1)
    except KeyboardInterrupt:
        logger.info("\n用户中断交易")
    finally:
        if trading.running:
            trading.disconnect_ibkr()
            
            status = trading.get_status()
            logger.info("")
            logger.info("=" * 60)
            logger.info("📊 交易摘要")
            logger.info("=" * 60)
            logger.info(f"💰 最终资金: ${status['capital']:,.2f}")
            logger.info(f"📈 日盈亏: ${status['daily_pnl']:,.2f}")
            logger.info(f"🎯 总交易: {status['total_trades']} 笔")
            logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
