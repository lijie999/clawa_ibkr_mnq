"""
主程序入口 - 多时间框架版本

协调 IBKR 数据获取、多时间框架 ICT/SMC 策略分析和自动交易执行。
"""

import asyncio
import signal
import sys
import pandas as pd
from typing import Optional, Dict
from ibkr_client import IBKRClient
from multi_timeframe_strategy import MultiTimeframeStrategy
from risk_management import RiskManager
from config import Config
from logger import logger

class CLAWAMultiTimeframe:
    """CLAWA 多时间框架量化交易系统主类"""
    
    def __init__(self):
        self.ibkr_client = IBKRClient()
        self.strategy = MultiTimeframeStrategy()
        self.risk_manager = RiskManager()
        self.running = False
        self.current_position = 0
        
    async def initialize(self) -> bool:
        """
        初始化系统
        
        Returns:
            bool: 初始化是否成功
        """
        logger.info("Initializing CLAWA Multi-Timeframe trading system...")
        
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
            
        logger.info("Multi-timeframe system initialized successfully!")
        return True
    
    async def update_account_info(self):
        """更新账户信息"""
        try:
            # 获取账户净值（简化版本，实际需要从 IBKR 获取）
            account_summary = self.ibkr_client.ib.accountSummary()
            # 这里需要实现具体的账户信息获取逻辑
            equity = 100000.0  # 临时值，实际应从 IBKR 获取
            daily_pnl = 0.0   # 临时值
            
            self.risk_manager.update_account_info(equity, daily_pnl)
            logger.info(f"Account info updated - Equity: ${equity:.2f}")
            
        except Exception as e:
            logger.error(f"Failed to update account info: {e}")
    
    async def get_multi_timeframe_data(self) -> Optional[Dict[str, pd.DataFrame]]:
        """
        获取多时间框架数据
        
        Returns:
            Dict or None: 包含各时间框架数据的字典
        """
        try:
            data_dict = {}
            
            # 获取日线数据
            daily_data = await self.ibkr_client.get_historical_data(
                duration='30 D', 
                bar_size='1 day'
            )
            if daily_data:
                df = pd.DataFrame(daily_data)
                df.set_index('date', inplace=True)
                data_dict['daily'] = df
                
            # 获取1小时数据
            hourly_data = await self.ibkr_client.get_historical_data(
                duration='5 D', 
                bar_size='1 hour'
            )
            if hourly_data:
                df = pd.DataFrame(hourly_data)
                df.set_index('date', inplace=True)
                data_dict['hourly'] = df
                
            # 获取5分钟数据
            five_min_data = await self.ibkr_client.get_historical_data(
                duration='1 D', 
                bar_size='5 mins'
            )
            if five_min_data:
                df = pd.DataFrame(five_min_data)
                df.set_index('date', inplace=True)
                data_dict['five_min'] = df
                
            # 获取1分钟数据
            one_min_data = await self.ibkr_client.get_historical_data(
                duration='4 H', 
                bar_size='1 min'
            )
            if one_min_data:
                df = pd.DataFrame(one_min_data)
                df.set_index('date', inplace=True)
                data_dict['one_min'] = df
                
            if len(data_dict) == 4:
                logger.info("Retrieved multi-timeframe data successfully")
                return data_dict
            else:
                logger.warning(f"Incomplete multi-timeframe data: {len(data_dict)}/4 timeframes")
                return None
                
        except Exception as e:
            logger.error(f"Failed to get multi-timeframe data: {e}")
            return None
    
    async def analyze_and_trade(self):
        """分析市场并执行交易"""
        try:
            # 获取多时间框架数据
            data_dict = await self.get_multi_timeframe_data()
            if data_dict is None:
                return
                
            # 获取实时价格
            realtime_data = await self.ibkr_client.get_realtime_data()
            if realtime_data is None:
                return
                
            current_price = realtime_data['last']
            
            # 生成多时间框架交易信号
            analysis_result = self.strategy.analyze_multi_timeframe(data_dict)
            signal = analysis_result.get('combined', {}).get('trade_signal')
            
            if signal is None:
                logger.debug("No multi-timeframe trading signal generated")
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
            logger.info(f"Signal confidence: {signal['confidence']:.2f}, Reason: {signal['reason']}")
            
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
        logger.info("Starting multi-timeframe trading loop...")
        
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
            
        logger.info("Stopping CLAWA Multi-Timeframe trading system...")
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
    trading_system = CLAWAMultiTimeframe()
    
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