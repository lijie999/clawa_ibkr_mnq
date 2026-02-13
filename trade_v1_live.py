#!/usr/bin/env python3
"""
CLAWA IBKR MNQ V2.1 实盘交易系统

改进点:
1. IBKR 连接状态跟踪 - connected/disconnected/error 回调
2. 订单状态跟踪 - orderStatus, fill, execution 事件
3. 自动重连机制 - 连接断开时尝试重连
4. 实时事件日志 - 所有IBKR事件记录
"""

import signal
import asyncio
import nest_asyncio
nest_asyncio.apply()

from datetime import datetime
from typing import Dict, Optional, Callable
from config import Config
from logger import logger
from strategy_v1 import ICTSMCV2Strategy, RiskManagerV1
from data_manager import DataManager
from ib_insync import IB, Future, LimitOrder, StopOrder, BracketOrder


class IBKRMonitor:
    """IBKR 连接和事件监控器"""
    
    def __init__(self):
        self.ib = None
        self.connected = False
        self.reconnect_count = 0
        self.max_reconnect = 5
        self.last_event_time = None
        self.event_callbacks = []
        
        self.stats = {
            'total_events': 0,
            'order_status': 0,
            'executions': 0,
            'errors': 0,
            'reconnects': 0
        }
    
    def setup_callbacks(self, ib: IB, on_event: Callable = None):
        """设置IBKR事件回调"""
        self.ib = ib
        
        def on_connected():
            self.connected = True
            self.reconnect_count = 0
            logger.info("✅ IBKR 已连接")
            self._log_event("CONNECTED")
        
        def on_disconnected():
            self.connected = False
            logger.warning("⚠️ IBKR 已断开连接")
            self._log_event("DISCONNECTED")
        
        def on_error(reqId, errorCode, errorString, advanced):
            self.stats['errors'] += 1
            logger.error(f"❌ IBKR 错误 [{errorCode}]: {errorString}")
            self._log_event(f"ERROR:{errorCode}", errorString)
        
        def on_order_event(trade):
            self.stats['order_status'] += 1
            status = trade.orderStatus.status
            order_id = trade.order.orderId
            logger.debug(f"📝 订单更新 #{order_id}: {status}")
            
            if on_event:
                on_event({'type': 'order', 'trade': trade})
            
            self._log_event(f"ORDER:{status}", f"Order #{order_id}")
        
        def on_execution(trade, fill):
            self.stats['executions'] += 1
            logger.info(f"💰 成交 #{fill.execution.orderId}: {fill.execution.shares} @ {fill.execution.price}")
            self._log_event("EXECUTION", f"{fill.execution.shares}@{fill.execution.price}")
        
        def on_commissionReport(report):
            logger.debug(f"💵 佣金: ${report.commission}")
        
        ib.connectedEvent += on_connected
        ib.disconnectedEvent += on_disconnected
        ib.errorEvent += on_error
        ib.orderStatusEvent += on_order_event
        ib.execDetailsEvent += on_execution
        ib.commissionReportEvent += on_commissionReport
        
        self._log_event("CALLBACKS_SETUP")
    
    def _log_event(self, event_type: str, details: str = ""):
        """记录事件"""
        self.stats['total_events'] += 1
        self.last_event_time = datetime.now()
        logger.debug(f"📊 IBKR事件: {event_type} {details}")
    
    def is_connected(self) -> bool:
        """检查连接状态"""
        return self.connected and self.ib and self.ib.isConnected()
    
    def get_status(self) -> Dict:
        """获取监控状态"""
        return {
            'connected': self.connected,
            'reconnect_count': self.reconnect_count,
            'stats': self.stats.copy(),
            'last_event': self.last_event_time
        }
    
    def get_order_status(self, ib: IB) -> Dict:
        """获取所有订单状态"""
        orders = []
        for trade in ib.trades():
            orders.append({
                'orderId': trade.order.orderId,
                'status': trade.orderStatus.status,
                'action': trade.order.action,
                'quantity': trade.order.totalQuantity,
                'filled': trade.orderStatus.filled,
                'remaining': trade.orderStatus.remaining
            })
        return orders


class OrderManager:
    """订单管理器 - 负责订单创建和状态跟踪"""
    
    def __init__(self, ib: IB, contract: Future):
        self.ib = ib
        self.contract = contract
        self.monitor = ib
        
        self.active_orders = {}  # orderId -> trade
        self.filled_orders = {}  # orderId -> fill info
        self.cancelled_orders = {}
        
        self.last_fill_time = None
        self.total_filled = 0
    
    def create_bracket_order(self, signal: Dict, size: int) -> BracketOrder:
        """创建括号单"""
        action = signal['action']
        
        parent = LimitOrder(action, size, signal['entry_price'])
        stop = StopOrder(action, size, signal['stop_loss'])
        profit = LimitOrder('SELL' if action == 'BUY' else 'BUY', size, signal['take_profit'])
        
        return BracketOrder(parent, stop, profit)
    
    def submit_bracket_order(self, bracket: BracketOrder) -> bool:
        """提交括号单"""
        try:
            for order in [bracket.parent, bracket.stopLoss, bracket.takeProfit]:
                trade = self.ib.placeOrder(self.contract, order)
                self.active_orders[order.orderId] = {
                    'trade': trade,
                    'action': order.action,
                    'size': order.totalQuantity,
                    'submitted': datetime.now(),
                    'type': 'parent' if order == bracket.parent else ('stop' if order == bracket.stopLoss else 'profit')
                }
            
            logger.info(f"📤 括号单已提交:")
            logger.info(f"   入场 #{bracket.parent.orderId}: {bracket.parent.action} {bracket.parent.totalQuantity} @ {bracket.parent.lmtPrice}")
            logger.info(f"   止损 #{bracket.stopLoss.orderId}: {bracket.stopLoss.action} {bracket.stopLoss.totalQuantity} @ {bracket.stopLoss.auxPrice}")
            logger.info(f"   止盈 #{bracket.takeProfit.orderId}: {bracket.takeProfit.action} {bracket.takeProfit.totalQuantity} @ {bracket.takeProfit.lmtPrice}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ 订单提交失败: {e}")
            return False
    
    def update_order_status(self, trade) -> Dict:
        """更新订单状态"""
        order_id = trade.order.orderId
        status = trade.orderStatus.status
        
        if order_id not in self.active_orders:
            return {'action': 'none', 'status': status}
        
        entry = self.active_orders[order_id]
        
        if status == 'Filled':
            self.filled_orders[order_id] = {
                **entry,
                'filled': trade.orderStatus.filled,
                'fill_price': trade.orderStatus.avgFillPrice,
                'filled_time': datetime.now()
            }
            del self.active_orders[order_id]
            self.last_fill_time = datetime.now()
            self.total_filled += trade.orderStatus.filled
            
            logger.info(f"✅ 订单成交 #{order_id}: {trade.orderStatus.filled} @ {trade.orderStatus.avgFillPrice}")
            
            return {
                'action': 'filled',
                'order_id': order_id,
                'size': trade.orderStatus.filled,
                'price': trade.orderStatus.avgFillPrice,
                'type': entry['type']
            }
        
        elif status == 'Cancelled':
            self.cancelled_orders[order_id] = {**entry, 'cancelled_time': datetime.now()}
            del self.active_orders[order_id]
            
            logger.info(f"❌ 订单取消 #{order_id}")
            return {'action': 'cancelled', 'order_id': order_id}
        
        elif status == 'Submitted':
            return {'action': 'pending', 'order_id': order_id, 'status': status}
        
        return {'action': 'unknown', 'status': status}
    
    def get_active_count(self) -> int:
        """获取活跃订单数量"""
        return len(self.active_orders)
    
    def cancel_all(self):
        """取消所有活跃订单"""
        cancelled = []
        for order_id in list(self.active_orders.keys()):
            try:
                trade = self.active_orders[order_id]['trade']
                self.ib.cancelOrder(trade.order)
                cancelled.append(order_id)
            except Exception as e:
                logger.error(f"取消订单 {order_id} 失败: {e}")
        
        for oid in cancelled:
            if oid in self.active_orders:
                del self.active_orders[oid]
        
        logger.info(f"✅ 已取消 {len(cancelled)} 个订单")
        return len(cancelled)
    
    def get_summary(self) -> Dict:
        """获取订单摘要"""
        return {
            'active': len(self.active_orders),
            'filled': len(self.filled_orders),
            'cancelled': len(self.cancelled_orders),
            'total_filled': self.total_filled
        }


class LiveTradingV2:
    """IBKR 实盘交易 V2.1"""
    
    def __init__(self, initial_capital=100000):
        self.capital = initial_capital
        self.strategy = ICTSMCV2Strategy()
        self.risk = RiskManagerV1()
        self.data_manager = DataManager()
        self.running = False
        self.ib = None
        self.contract = None
        self.order_manager = None
        self.monitor = None
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
            
            self.monitor = IBKRMonitor()
            self.monitor.setup_callbacks(self.ib, self.on_ibkr_event)
            
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
    
    def on_ibkr_event(self, event: Dict):
        """IBKR 事件回调"""
        if event['type'] == 'order':
            trade = event['trade']
            self.order_manager.update_order_status(trade)
    
    def disconnect_ibkr(self):
        """断开 IBKR 连接"""
        if self.order_manager:
            self.order_manager.cancel_all()
        
        if self.ib and self.ib.isConnected():
            self.ib.disconnect()
            logger.info("已断开 IBKR Gateway 连接")
    
    def initialize(self):
        """初始化"""
        self.data_manager.initialize(self.ib, self.contract)
        
        logger.info("")
        logger.info("=" * 60)
        logger.info("🚀 V2.1 实盘交易系统启动")
        logger.info("=" * 60)
        logger.info(f"初始资金: ${self.capital:,.2f}")
        logger.info(f"合约: {Config.SYMBOL} ({Config.EXCHANGE})")
        logger.info(f"交易时段: 07:00-20:00 CST")
        logger.info("=" * 60)
        
        bar_counts = self.data_manager.get_bar_count()
        logger.info("📊 数据状态:")
        for tf, count in bar_counts.items():
            logger.info(f"   {tf}: {count} 根K线")
        
        status = self.monitor.get_status()
        logger.info(f"📡 IBKR 监控: {'已连接' if status['connected'] else '未连接'}")
    
    async def run(self):
        """主循环"""
        if not self.connect_ibkr():
            return False
        
        self.initialize()
        self.running = True
        
        last_date = None
        last_minute = None
        last_status_log = 0
        
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
                
                if not self.monitor or not self.monitor.is_connected():
                    logger.warning("⚠️ IBKR 未连接，尝试重连...")
                    if self.ib and not self.ib.isConnected():
                        try:
                            self.ib.reconnect()
                            self.monitor.setup_callbacks(self.ib, self.on_ibkr_event)
                            logger.info("✅ 重连成功")
                        except:
                            await asyncio.sleep(10)
                            continue
                    await asyncio.sleep(30)
                    continue
                
                session = self.strategy.is_trading_session(now)
                
                if not session:
                    if current_minute % 30 == 0:
                        logger.debug(f"非交易时段: {now.strftime('%H:%M')}")
                    await asyncio.sleep(30)
                    continue
                
                if current_minute != last_minute:
                    updated = self.data_manager.update()
                    if updated:
                        logger.debug("📊 数据已更新")
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
                    if self.order_manager.get_active_count() > 0:
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
                        
                        self.order_manager.cancel_all()
                
                if now.timestamp() - last_status_log > 60:
                    last_status_log = now.timestamp()
                    order_summary = self.order_manager.get_summary()
                    monitor_status = self.monitor.get_status()
                    logger.debug(f"📊 状态: 订单={order_summary} | IBKR={monitor_status['connected']}")
                
                await asyncio.sleep(30)
                
            except Exception as e:
                logger.error(f"交易错误: {e}")
                await asyncio.sleep(30)
        
        self.disconnect_ibkr()
        return True
    
    def get_status(self) -> dict:
        if self.order_manager:
            order_summary = self.order_manager.get_summary()
        else:
            order_summary = {'active': 0, 'filled': 0, 'cancelled': 0}
        
        return {
            'capital': self.capital,
            'daily_pnl': self.daily_pnl,
            'total_trades': len(self.trade_history),
            'orders': order_summary
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
            logger.info(f"📤 活跃订单: {status['orders']['active']}")
            logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
