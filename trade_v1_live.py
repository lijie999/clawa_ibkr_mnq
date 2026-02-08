#!/usr/bin/env python3
"""
CLAWA IBKR MNQ V1.0 实盘交易系统

连接 IBKR Gateway 获取实时数据运行
如果连接失败，提示用户检查 Gateway 客户端
"""

import nest_asyncio
nest_asyncio.apply()

import signal
import asyncio
from datetime import datetime
import pandas as pd
from config import Config
from logger import logger
from strategy_v1 import ICTSMCV1Strategy, RiskManagerV1
from ib_insync import IB, Future


class LiveTradingV1:
    """IBKR 实盘交易"""
    
    def __init__(self, initial_capital=100000):
        self.capital = initial_capital
        self.strategy = ICTSMCV1Strategy()
        self.risk = RiskManagerV1()
        self.running = False
        self.ib = None
        self.contract = None
        self.orders = []
        self.trade_history = []
        self.daily_pnl = 0.0
    
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
            logger.error("3. 是否启用了 API 连接 (勾选 'Enable ActiveX and Socket Clients')")
            logger.error("4. 防火墙是否允许连接")
            logger.error("")
            logger.error("如何启用 IBKR API:")
            logger.error("- 打开 IBKR Gateway 或 TWS")
            logger.error("- 进入 'Configuration' -> 'API' -> 'Settings'")
            logger.error("- 勾选 'Enable ActiveX and Socket Clients'")
            logger.error("- 确保端口设置为: 7497 (模拟) 或 4002 (实盘)")
            logger.error("=" * 60)
            logger.error("")
            return False
    
    def disconnect_ibkr(self):
        """断开 IBKR 连接"""
        if self.ib and self.ib.isConnected():
            self.ib.disconnect()
            logger.info("已断开 IBKR Gateway 连接")
    
    def get_market_data(self) -> pd.DataFrame:
        """获取实时市场数据"""
        if not self.ib or not self.ib.isConnected():
            return None
        
        try:
            bars = self.ib.reqHistoricalData(
                self.contract,
                endDateTime='',
                durationStr='1 D',
                barSizeSetting='15 mins',
                whatToShow='TRADES',
                useRTH=True,
                formatDate=1
            )
            
            if not bars:
                return None
            
            df = pd.DataFrame([{
                'date': bar.date,
                'open': bar.open,
                'high': bar.high,
                'low': bar.low,
                'close': bar.close,
                'volume': bar.volume
            } for bar in bars])
            
            df['date'] = pd.to_datetime(df['date'], utc=True)
            df.set_index('date', inplace=True)
            return df
            
        except Exception as e:
            logger.error(f"获取市场数据失败: {e}")
            return None
    
    async def run(self):
        """主循环"""
        # 连接 IBKR
        if not self.connect_ibkr():
            return False
        
        self.running = True
        
        logger.info("")
        logger.info("=" * 60)
        logger.info("🚀 V1.0 实盘交易系统启动")
        logger.info("=" * 60)
        logger.info(f"初始资金: ${self.capital:,.2f}")
        logger.info(f"交易合约: {Config.SYMBOL} ({Config.EXCHANGE})")
        logger.info(f"交易时段: 07:00-20:00 CST")
        logger.info(f"策略: ICT/SMC 移动止损 V1.0")
        logger.info("=" * 60)
        
        last_date = None
        
        while self.running:
            try:
                now = datetime.now()
                today = now.date()
                
                # 检查是否新的一天
                if last_date != today:
                    last_date = today
                    self.daily_pnl = 0.0
                    logger.info(f"\n📅 {now.strftime('%Y-%m-%d')} - 新交易日开始")
                
                session = self.strategy.is_trading_session(now)
                
                if not session:
                    if now.minute % 30 == 0:
                        logger.debug(f"当前 {now.strftime('%H:%M')} 不在交易时段 (7:00-20:00 CST)")
                    await asyncio.sleep(60)
                    continue
                
                # 获取市场数据
                df = self.get_market_data()
                
                if df is None or df.empty or len(df) < 20:
                    await asyncio.sleep(30)
                    continue
                
                current_price = float(df['close'].iloc[-1])
                
                # 检查风险管理
                if not self.risk.should_trade(self.capital, self.daily_pnl):
                    logger.warning("风险管理阻止交易")
                    await asyncio.sleep(60)
                    continue
                
                # 策略逻辑
                status = self.strategy.get_status()
                
                if status['status'] == 'idle':
                    signal = self.strategy.generate_signal(df, current_price)
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
                            logger.info("=" * 60)
                            
                            # 发送订单
                            order_id = self.ib.placeOrder(
                                self.contract,
                                self.ib.marketOrder(signal['action'], size)
                            )
                            logger.info(f"   订单ID: {order_id}")
                
                elif status['status'] == 'active':
                    result = self.strategy.update_trade(current_price, now)
                    
                    if result['action'] == 'partial_close':
                        logger.info("")
                        logger.info("-" * 60)
                        logger.info(f"✂️ 半仓平仓 @ ${result['price']:.2f}")
                        logger.info(f"   盈利: ${result['pnl']:.2f} | RR: {result['rr']:.1f}R")
                        logger.info(f"   新止损: ${result['new_stop_loss']:.2f}")
                        logger.info("-" * 60)
                        
                        # 发送半仓平仓订单
                        close_size = self.strategy.active_trade.get('partial_size', 0)
                        if close_size > 0:
                            action = 'SELL' if self.strategy.active_trade['action'] == 'BUY' else 'BUY'
                            self.ib.placeOrder(
                                self.contract,
                                self.ib.marketOrder(action, close_size)
                            )
                        
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
                        
                        # 发送平仓订单
                        remaining_size = self.strategy.active_trade.get('size', 0)
                        if remaining_size > 0:
                            action = 'SELL' if self.strategy.active_trade['action'] == 'BUY' else 'BUY'
                            self.ib.placeOrder(
                                self.contract,
                                self.ib.marketOrder(action, remaining_size)
                            )
                        
                        self.daily_pnl += result['pnl']
                        self.capital += result['pnl']
                        
                        self.trade_history.append({
                            'entry_price': status['trade']['entry_price'],
                            'exit_price': current_price,
                            'pnl': result['pnl'],
                            'rr': result.get('rr', 0),
                            'time': now
                        })
                
                await asyncio.sleep(60)
                
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
