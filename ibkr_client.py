"""
IBKR API 客户端模块

处理 IBKR API 连接、数据获取和订单执行。
"""

from ib_insync import IB, Future, MarketOrder, LimitOrder
from typing import Optional, List, Dict, Any
import asyncio
from config import Config
from logger import logger

class IBKRClient:
    """IBKR API 客户端"""
    
    def __init__(self):
        self.ib = None
        self.connected = False
        
    async def connect(self) -> bool:
        """
        连接到 IBKR API
        
        Returns:
            bool: 连接是否成功
        """
        try:
            self.ib = IB()
            
            # 异步连接
            await self.ib.connectAsync(
                host=Config.IBKR_HOST,
                port=Config.IBKR_PORT, 
                clientId=Config.IBKR_CLIENT_ID,
                timeout=10
            )
            
            self.connected = True
            logger.info(f"Connected to IBKR at {Config.IBKR_HOST}:{Config.IBKR_PORT}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to IBKR: {e}")
            self.connected = False
            return False
    
    def create_mnq_contract(self) -> Future:
        """
        创建 MNQ 期货合约
        
        Returns:
            Future: MNQ 期货合约对象
        """
        contract = Future(
            symbol=Config.SYMBOL,
            lastTradeDateOrContractMonth=Config.CONTRACT_MONTH,
            exchange=Config.EXCHANGE,
            currency=Config.CURRENCY
        )
        return contract
    
    async def get_historical_data(self, duration: str = '1 D', bar_size: str = '15 mins') -> List[Dict[str, Any]]:
        """
        获取历史数据
        
        Args:
            duration (str): 数据时长，如 '1 D', '1 W', '1 M'
            bar_size (str): K线周期，如 '15 mins', '1 hour', '4 hours'
            
        Returns:
            List[Dict]: 历史K线数据
        """
        if not self.connected:
            logger.error("Not connected to IBKR")
            return []
            
        try:
            contract = self.create_mnq_contract()
            bars = await self.ib.reqHistoricalDataAsync(
                contract,
                endDateTime='',
                durationStr=duration,
                barSizeSetting=bar_size,
                whatToShow='TRADES',
                useRTH=True,
                formatDate=1
            )
            
            # 转换为字典列表
            data = []
            for bar in bars:
                data.append({
                    'date': bar.date,
                    'open': bar.open,
                    'high': bar.high,
                    'low': bar.low,
                    'close': bar.close,
                    'volume': bar.volume
                })
                
            logger.info(f"Retrieved {len(data)} bars of historical data")
            return data
            
        except Exception as e:
            logger.error(f"Failed to get historical data: {e}")
            return []
    
    async def get_realtime_data(self) -> Optional[Dict[str, Any]]:
        """
        获取实时行情数据
        
        Returns:
            Dict or None: 实时行情数据
        """
        if not self.connected:
            logger.error("Not connected to IBKR")
            return None
            
        try:
            contract = self.create_mnq_contract()
            ticker = self.ib.reqMktData(contract)
            
            # 等待数据更新
            await asyncio.sleep(1)
            
            if ticker.last:
                data = {
                    'symbol': Config.SYMBOL,
                    'last': ticker.last,
                    'bid': ticker.bid,
                    'ask': ticker.ask,
                    'volume': ticker.volume,
                    'timestamp': ticker.time
                }
                return data
            else:
                logger.warning("No realtime data available")
                return None
                
        except Exception as e:
            logger.error(f"Failed to get realtime data: {e}")
            return None
    
    async def place_market_order(self, action: str, quantity: int) -> Optional[str]:
        """
        下市价单
        
        Args:
            action (str): 'BUY' 或 'SELL'
            quantity (int): 数量
            
        Returns:
            str or None: 订单ID
        """
        if not self.connected:
            logger.error("Not connected to IBKR")
            return None
            
        try:
            contract = self.create_mnq_contract()
            order = MarketOrder(action, quantity)
            trade = self.ib.placeOrder(contract, order)
            
            # 等待订单确认
            for _ in range(50):
                if trade.orderStatus.status in ['Submitted', 'Filled']:
                    logger.info(f"Market order placed - Action: {action}, Quantity: {quantity}, Status: {trade.orderStatus.status}")
                    return str(trade.order.orderId)
                await asyncio.sleep(0.1)
                
            logger.warning("Market order placement timeout")
            return str(trade.order.orderId)
            
        except Exception as e:
            logger.error(f"Failed to place market order: {e}")
            return None
    
    async def place_limit_order(self, action: str, quantity: int, price: float) -> Optional[str]:
        """
        下限价单
        
        Args:
            action (str): 'BUY' 或 'SELL'
            quantity (int): 数量
            price (float): 价格
            
        Returns:
            str or None: 订单ID
        """
        if not self.connected:
            logger.error("Not connected to IBKR")
            return None
            
        try:
            contract = self.create_mnq_contract()
            order = LimitOrder(action, quantity, price)
            trade = self.ib.placeOrder(contract, order)
            
            logger.info(f"Limit order placed - Action: {action}, Quantity: {quantity}, Price: {price}")
            return str(trade.order.orderId)
            
        except Exception as e:
            logger.error(f"Failed to place limit order: {e}")
            return None
    
    async def disconnect(self):
        """断开 IBKR 连接"""
        if self.ib and self.connected:
            self.ib.disconnect()
            self.connected = False
            logger.info("Disconnected from IBKR")