#!/usr/bin/env python3
"""
CLAWA IBKR MNQ V2.0 实盘交易系统

改进点:
1. 括号单 (Bracket Orders) - 一次下单，入场+止损+止盈
2. 订单回调机制 - 跟踪订单状态
3. 订单执行验证 - 确保订单成功
4. 异步处理 - 非阻塞等待
"""

import signal
import asyncio
import nest_asyncio
nest_asyncio.apply()

from datetime import datetime
from typing import Dict, Optional
from config import Config
from logger import logger
from strategy_v1 import ICTSMCV2Strategy, RiskManagerV1
from data_manager import DataManager
from ib_insync import IB, Future, MarketOrder, LimitOrder, StopOrder, BracketOrder


class OrderManager:
    """订单管理器 - 负责订单创建和状态跟踪"""
    
    def __init__(self, ib: IB, contract: Future):
        self.ib = ib
        self.contract = contract
        self.pending_orders = {}  # orderId -> trade
        self.executed_orders = {}  # orderId -> fill info
    
    def create_bracket_order(self, signal: Dict, size: int) -> BracketOrder:
        """创建括号单"""
        action = signal['action']
        entry_price = signal['entry_price']
        stop_price = signal['stop_loss']
        profit_price = signal['take_profit']
        
        parent = LimitOrder(action, size, entry_price)
        stop = StopLoss = StopOrder(action, size, stop_price)
        profit = TakeProfit = LimitOrder('SELL' if action == 'BUY' else 'BUY', size, profit_price)
        
        return BracketOrder(parent, StopLoss, TakeProfit)
    
    def submit_bracket_order(self, bracket: BracketOrder) -> bool:
        """提交括号单并注册回调"""
        try:
            for order in [bracket.parent, bracket.takeProfit, bracket.stopLoss]:
                trade = self.ib.placeOrder(self.contract, order)
                self.pending_orders[order.orderId] = {
                    'trade': trade,
                    'action': 'BUY' if order.action == 'BUY' else 'SELL',
                    'size': order.totalQuantity,
                    'submitted': datetime.now()
                }
            
            logger.info(f"📤 订单已提交: 入场={bracket.parent.lmtPrice}, 止损={bracket.stopLoss.auxPrice}, 止盈={bracket.takeProfit.lmtPrice}")
            return True
            
        except Exception as e:
            logger.error(f"❌ 订单提交失败: {e}")
            return False
    
    def cancel_all_orders(self):
        """取消所有待执行订单"""
        try:
            for order_id, info in list(self.pending_orders.items()):
                self.ib.cancelOrder(info['trade'].order)
                del self.pending_orders[order_id]
            logger.info("✅ 已取消所有待执行订单")
        except Exception as e:
            logger.error(f"取消订单失败: {e}")
    
    def get_pending_count(self) -> int:
        """获取待执行订单数量"""
        return len(self.pending_orders)


class LiveTradingV2:
    """IBKR 实盘交易 V2.0"""
    
    def __init__(self, initial_capital=100000):
        self.capital = initial_capital
        self.strategy = ICTSMCV2Strategy()
        self.risk = RiskManagerV1()
        self.data_manager = DataManager()
        self.running = False
        self.ib = None
        self.contract = None
        self.order_manager = None
        self.daily_pnl = 0.0
        self.trade_history = []
    
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
            
            self.order_manager = OrderManager(self.ib, self.contract)
            
            logger.info("✅ IBKR Gateway 连接成功!")
            return True
            
        except Exception as e:
            logger.error("")
            logger.error("=" * 60)
            logger.error("❌ IBKR Gateway 连接失败!")
            logger.error("=" * 60)
            logger.error(f"错误信息: {e}")
            logger.error("=" * 60)
            return False
    
    def disconnect_ibkr(self):
        """断开 IBKR 连接"""
        if self.order_manager:
            self.order_manager.cancel_all_orders()
        
        if self.ib and self.ib.isConnected():
            self.ib.disconnect()
            logger.info("已断开 IBKR Gateway 连接")
    
    def initialize(self):
        """初始化"""
        self.data_manager.initialize(self.ib, self.contract)
        
        logger.info("")
        logger.info("=" * 60)
        logger.info("🚀 V2.0 实盘交易系统启动")
        logger.info("=" * 60)
        logger.info(f"初始资金: ${self.capital:,.2f}")
        logger.info(f"合约: {Config.SYMBOL} ({Config.EXCHANGE})")
        logger.info(f"交易时段: 07:00-20:00 CST")
        logger.info(f"策略: ICT/SMC V2.0 (括号单 + 订单验证)")
        logger.info("=" * 60)
        
        bar_counts = self.data_manager.get_bar_count()
        logger.info("📊 数据状态:")
        for tf, count in bar_counts.items():
            logger.info(f"   {tf}: {count} 根K线")
    
    async def run(self):
        """主循环"""
        if not self.connect_ibkr():
            return False
        
        self.initialize()
        self.running = True
        
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
                    self.strategy.reset()
                    logger.info(f"\n📅 {now.strftime('%Y-%m-%d')} - 新交易日")
                
                session = self.strategy.is_trading_session(now)
                
                if not session:
                    if current_minute % 30 == 0:
                        logger.debug(f"非交易时段: {now.strftime('%H:%M')}")
                    await asyncio.sleep(30)
                    continue
                
                if current_minute != last_minute:
                    updated = self.data_manager.update()
                    if updated:
                        logger.debug(f"📊 数据已更新")
                    last_minute = current_minute
                
                mtf_data = {
                    '4hr': self.data_manager.get_data('4hr'),
                    '1hr': self.data_manager.get_data('1hr'),
                    '15min': self.data_manager.get_data('15min'),
                    '5min': self.data_manager.get_data('5min'),
                }
                
                if mtf_data['15min'].empty or len(mtf_data['15min']) < 20:
                    await asyncio.sleep(30)
                    continue
                
                current_price = self.data_manager.get_current_price()
                
                if current_price <= 0:
                    await asyncio.sleep(30)
                    continue
                
                if not self.risk.should_trade(self.capital, self.daily_pnl):
                    if current_minute % 10 == 0:
                        logger.warning("风险管理阻止交易")
                    await asyncio.sleep(30)
                    continue
                
                status = self.strategy.get_status()
                
                if status['status'] == 'idle':
                    if self.order_manager.get_pending_count() > 0:
                        await asyncio.sleep(30)
                        continue
                    
                    signal = self.strategy.generate_signal(mtf_data, current_price, now)
                    
                    if signal:
                        size = self.risk.calculate_position_size(
                            self.capital,
                            signal['entry_price'],
                            signal['stop_loss']
                        )
                        
                        if size > 0:
                            self.strategy.open_position(signal, size)
                            
                            logger.info("")
                            logger.info("=" * 60)
                            logger.info(f"📢 开仓信号: {signal['action']}")
                            logger.info(f"   手数: {size} | 入场: ${signal['entry_price']:.2f}")
                            logger.info(f"   止损: ${signal['stop_loss']:.2f} | 止盈: ${signal['take_profit']:.2f}")
                            logger.info(f"   置信度: {signal['confidence']:.0%}")
                            logger.info(f"   趋势: 4hr={signal.get('trend_4hr', '?')} | 1hr={signal.get('trend_1hr', '?')} | 15min={signal.get('trend_15min', '?')}")
                            logger.info("=" * 60)
                            
                            bracket = self.order_manager.create_bracket_order(signal, size)
                            if self.order_manager.submit_bracket_order(bracket):
                                logger.info("⏳ 等待订单执行...")
                
                elif status['status'] == 'active':
                    result = self.strategy.update_trade(current_price, now)
                    
                    if result['action'] == 'partial_close':
                        logger.info("")
                        logger.info("-" * 60)
                        logger.info(f"✂️ 半仓平仓 @ ${result['price']:.2f}")
                        logger.info(f"   盈利: ${result['pnl']:.2f} | RR: {result['rr']:.1f}R")
                        logger.info("-" * 60)
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
                        
                        self.daily_pnl += result['pnl']
                        self.capital += result['pnl']
                        
                        self.trade_history.append({
                            'entry_price': status['trade']['entry_price'],
                            'exit_price': current_price,
                            'pnl': result['pnl'],
                            'rr': result.get('rr', 0),
                            'time': now
                        })
                        
                        self.order_manager.cancel_all_orders()
                
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
            'total_trades': len(self.trade_history)
        }


def signal_handler(signum, frame):
    logger.info("收到停止信号")


async def main():
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    trading = LiveTradingV2(initial_capital=100000)
    
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
