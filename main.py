"""
主程序入口

协调 IBKR 数据获取、ICT/SMC 策略分析和自动交易执行。
"""

import asyncio
import signal
import sys
import pandas as pd
from typing import Optional
from ibkr_client import IBKRClient
from ict_smc_strategy import ICTSMCStrategy
from risk_management import RiskManager
from config import Config
from logger import logger

class CLAWAIBKRMNQ:
    """CLAWA IBKR MNQ 量化交易系统主类"""
    
    def __init__(self):
        self.ibkr_client = IBKRClient()
        self.strategy = ICTSMCStrategy()
        self.risk_manager = RiskManager()
        self.running = False
        self.current_position = 0
        
    async def initialize(self) -> bool:
        """
        初始化系统
        
        Returns:
            bool: 初始化是否成功
        """
        logger.info("Initializing CLAWA IBKR MNQ trading system...")
        
        # 连接 IBKR
        if not await self.ibkr_client.connect():
            logger.error("Failed to connect to IBKR")
            return False
            
        # 获取初始账户信息
        await self.update_account_info()
        
        # 验证交易权限
        if not self.risk_manager.should_trade():
            logger.warning("Risk management rules prevent trading")
            return False
            
        logger.info("System initialized successfully!")
        return True
    
    async def update_account_info(self):
        """更新账户信息"""
        try:
            # 获取账户净值（简化版本，实际需要从 IBKR 获取）
            account_summary = self.ibkr_client.ib.accountSummary()
            # 这里需要实现具体的账户信息获取逻辑
            equity = 10000.0  # 临时值，实际应从 IBKR 获取
            daily_pnl = 0.0   # 临时值
            
            self.risk_manager.update_account_info(equity, daily_pnl)
            logger.info(f"Account info updated - Equity: ${equity:.2f}")
            
        except Exception as e:
            logger.error(f"Failed to update account info: {e}")
    
    async def get_market_data(self) -> Optional[pd.DataFrame]:
        """
        获取市场数据
        
        Returns:
            pd.DataFrame or None: OHLCV 数据
        """
        try:
            # 获取多时间框架数据
            historical_data = await self.ibkr_client.get_historical_data(
                duration='5 D', 
                bar_size='15 mins'
            )
            
            if not historical_data:
                logger.warning("No historical data retrieved")
                return None
                
            # 转换为 DataFrame
            df = pd.DataFrame(historical_data)
            df.set_index('date', inplace=True)
            
            logger.info(f"Retrieved {len(df)} bars of market data")
            return df
            
        except Exception as e:
            logger.error(f"Failed to get market data: {e}")
            return None
    
    async def analyze_and_trade(self):
        """分析市场并执行交易"""
        try:
            # 获取市场数据
            market_data = await self.get_market_data()
            if market_data is None:
                return
                
            # 获取实时价格
            realtime_data = await self.ibkr_client.get_realtime_data()
            if realtime_data is None:
                return
                
            current_price = realtime_data['last']
            
            # 生成交易信号
            signal = self.strategy.generate_trading_signal(market_data, current_price)
            if signal is None:
                logger.debug("No trading signal generated")
                return
                
            # 风险管理检查
            if not self.risk_manager.should_trade():
                logger.warning("Risk management prevents trading")
                return
                
            # 计算持仓手数
            position_size = self.risk_manager.calculate_position_size(
                signal['entry_price'], 
                signal['stop_loss']
            )
            
            if position_size <= 0:
                logger.warning("Position size is zero or negative")
                return
                
            # 验证订单
            if not self.risk_manager.validate_order(position_size, self.current_position):
                logger.warning("Order validation failed")
                return
                
            # 执行交易
            action = signal['action']
            logger.info(f"Executing {action} order - Size: {position_size}, Price: {current_price}")
            
            # 下单（这里使用市价单，实际可以考虑限价单）
            order_id = await self.ibkr_client.place_market_order(action, position_size)
            if order_id:
                logger.info(f"Order executed successfully - Order ID: {order_id}")
                # 更新当前持仓
                if action == 'BUY':
                    self.current_position += position_size
                else:
                    self.current_position -= position_size
            else:
                logger.error("Order execution failed")
                
        except Exception as e:
            logger.error(f"Error in analyze_and_trade: {e}")
    
    async def start_trading_loop(self):
        """启动交易循环"""
        self.running = True
        logger.info("Starting trading loop...")
        
        while self.running:
            try:
                await self.analyze_and_trade()
                # 等待下一次分析（可以根据需要调整间隔）
                await asyncio.sleep(60)  # 每分钟检查一次
                
            except KeyboardInterrupt:
                logger.info("Received shutdown signal...")
                break
            except Exception as e:
                logger.error(f"Error in trading loop: {e}")
                # 继续运行，不要中断整个系统
                
        await self.stop()
    
    async def stop(self):
        """停止交易系统"""
        if not self.running:
            return
            
        logger.info("Stopping CLAWA IBKR MNQ trading system...")
        self.running = False
        
        # 关闭连接
        await self.ibkr_client.disconnect()
        
        logger.info("Trading system stopped.")

def signal_handler(signum, frame):
    """信号处理器"""
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")

if __name__ == "__main__":
    # 设置信号处理器
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # 启动交易系统
    trading_system = CLAWAIBKRMNQ()
    
    try:
        # 初始化
        if asyncio.run(trading_system.initialize()):
            # 开始交易循环
            asyncio.run(trading_system.start_trading_loop())
        else:
            logger.error("Failed to initialize trading system")
            sys.exit(1)
            
    except KeyboardInterrupt:
        logger.info("Application interrupted by user")
    except Exception as e:
        logger.error(f"Application error: {e}")
        sys.exit(1)