#!/usr/bin/env python3
"""
CLAWA IBKR MNQ V1.0 自动化交易系统

基于 ICT/SMC 移动止损策略的自动化实盘交易
"""

import asyncio
import signal
import sys
from datetime import datetime
from config import Config
from logger import logger
from ibkr_client import IBKRClient
from strategy_v1 import ICTSMCV1Strategy, RiskManagerV1


class TradingV1:
    """V1.0 自动化交易系统"""
    
    def __init__(self):
        self.ibkr = IBKRClient()
        self.strategy = ICTSMCV1Strategy()
        self.risk = RiskManagerV1()
        self.running = False
        self.daily_pnl = 0.0
        
    async def initialize(self) -> bool:
        """初始化"""
        logger.info("=" * 60)
        logger.info("CLAWA IBKR MNQ V1.0 交易系统启动")
        logger.info("=" * 60)
        logger.info(f"策略: ICT/SMC 移动止损策略 V1.0")
        logger.info(f"交易时段: 07:00-20:00 CST")
        logger.info(f"最大持仓: {Config.MAX_POSITION_SIZE} 手")
        logger.info(f"风险比例: {Config.RISK_PERCENTAGE}%")
        
        if not await self.ibkr.connect():
            logger.error("连接 IBKR 失败")
            return False
        
        logger.info("连接 IBKR 成功")
        return True
    
    async def get_market_data(self) -> dict:
        """获取市场数据"""
        data = await self.ibkr.get_historical_data(
            duration='1 D',
            bar_size='15 mins'
        )
        if not data:
            return None
        
        df = pd.DataFrame(data)
        df.set_index('date', inplace=True)
        return df
    
    async def run(self):
        """主循环"""
        self.running = True
        
        while self.running:
            try:
                now = datetime.now()
                session = self.strategy.is_trading_session(now)
                
                if not session:
                    logger.debug(f"当前 {now.strftime('%H:%M')} 不在交易时段")
                    await asyncio.sleep(60)
                    continue
                
                # 获取数据
                df = await self.get_market_data()
                if df is None:
                    await asyncio.sleep(30)
                    continue
                
                current_price = df['close'].iloc[-1]
                
                # 检查风险管理
                if not self.risk.should_trade(self.ibkr.get_account_value(), self.daily_pnl):
                    logger.warning("风险管理阻止交易")
                    await asyncio.sleep(60)
                    continue
                
                # 获取策略状态
                status = self.strategy.get_status()
                
                if status['status'] == 'idle':
                    # 生成信号
                    signal = self.strategy.generate_signal(df, current_price)
                    if signal:
                        # 计算仓位
                        size = self.risk.calculate_position_size(
                            self.ibkr.get_account_value(),
                            signal['entry_price'],
                            signal['stop_loss']
                        )
                        
                        if size > 0:
                            # 开仓
                            trade = self.strategy.open_position(signal, size)
                            logger.info(f"开仓: {signal['action']} {size}手 @ {signal['entry_price']}")
                            
                            # 下单
                            order_id = await self.ibkr.place_market_order(
                                signal['action'], size
                            )
                            
                            if order_id:
                                logger.info(f"订单执行成功: {order_id}")
                            else:
                                logger.error("订单执行失败")
                                self.strategy.reset()
                
                elif status['status'] == 'active':
                    # 更新交易
                    result = self.strategy.update_trade(current_price, now)
                    
                    if result['action'] == 'partial_close':
                        logger.info(f"半仓平仓 @ {result['price']}, RR: {result['rr']:.1f}R")
                        self.daily_pnl += result['pnl']
                        
                    elif result['action'] == 'trail_stop':
                        logger.info(f"移动止损 @ {result['new_stop_loss']}, RR: {result['rr']:.1f}R")
                        
                    elif result['action'] == 'close':
                        logger.info(f"平仓: {result['reason']}, PnL: ${result['pnl']:.2f}")
                        self.daily_pnl += result['pnl']
                        
                        # 关闭订单
                        action = 'SELL' if self.strategy.active_trade['action'] == 'BUY' else 'BUY'
                        size = self.strategy.active_trade['size']
                        await self.ibkr.place_market_order(action, size)
                
                await asyncio.sleep(60)
                
            except Exception as e:
                logger.error(f"交易循环错误: {e}")
                await asyncio.sleep(30)
    
    async def stop(self):
        """停止"""
        self.running = False
        await self.ibkr.disconnect()
        logger.info("V1.0 交易系统已停止")


def signal_handler(signum, frame):
    """信号处理"""
    logger.info(f"收到信号 {signum}")


async def main():
    """主入口"""
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    trading = TradingV1()
    
    try:
        if await trading.initialize():
            await trading.run()
    except KeyboardInterrupt:
        logger.info("用户中断")
    finally:
        await trading.stop()


if __name__ == "__main__":
    import pandas as pd
    asyncio.run(main())
