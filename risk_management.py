"""
风险管理模块

实现基于账户净值的风险管理逻辑。
"""

from typing import Dict, Optional
from config import Config
from logger import logger

class RiskManager:
    """风险管理器"""
    
    def __init__(self):
        self.account_equity = 0.0
        self.daily_loss = 0.0
        self.position_size = 0
        self.max_position_size = Config.MAX_POSITION_SIZE
        
    def update_account_info(self, equity: float, daily_pnl: float):
        """
        更新账户信息
        
        Args:
            equity (float): 账户净值
            daily_pnl (float): 当日盈亏
        """
        self.account_equity = equity
        self.daily_loss = abs(daily_pnl) if daily_pnl < 0 else 0
        
    def calculate_position_size(self, entry_price: float, stop_loss: float) -> int:
        """
        计算持仓手数
        
        Args:
            entry_price (float): 入场价格
            stop_loss (float): 止损价格
            
        Returns:
            int: 建议持仓手数
        """
        if self.account_equity <= 0:
            logger.warning("Account equity is zero or negative")
            return 0
            
        # 计算单笔风险金额
        risk_amount = self.account_equity * (Config.RISK_PERCENTAGE / 100)
        
        # 计算每手风险
        risk_per_contract = abs(entry_price - stop_loss) * 2  # MNQ 合约乘数为 2
        
        if risk_per_contract <= 0:
            logger.warning("Risk per contract is zero or negative")
            return 0
            
        # 计算建议手数
        suggested_size = int(risk_amount / risk_per_contract)
        
        # 应用最大持仓限制
        final_size = min(suggested_size, self.max_position_size)
        
        logger.info(f"Position size calculation - Account Equity: ${self.account_equity:.2f}, "
                   f"Risk Amount: ${risk_amount:.2f}, Risk Per Contract: ${risk_per_contract:.2f}, "
                   f"Suggested Size: {suggested_size}, Final Size: {final_size}")
        
        return max(final_size, 0)
    
    def should_trade(self) -> bool:
        """
        判断是否应该进行交易
        
        Returns:
            bool: True 表示可以交易，False 表示暂停交易
        """
        # 检查日亏损限制
        if self.daily_loss >= (self.account_equity * (Config.DAILY_LOSS_LIMIT / 100)):
            logger.warning(f"Daily loss limit reached: ${self.daily_loss:.2f} / "
                          f"${self.account_equity * (Config.DAILY_LOSS_LIMIT / 100):.2f}")
            return False
            
        # 检查账户净值是否足够
        if self.account_equity < 1000:  # 最小账户要求
            logger.warning("Account equity too low for trading")
            return False
            
        return True
    
    def validate_order(self, position_size: int, current_position: int) -> bool:
        """
        验证订单是否符合风险管理规则
        
        Args:
            position_size (int): 拟下单手数
            current_position (int): 当前持仓手数
            
        Returns:
            bool: True 表示订单有效
        """
        total_position = abs(current_position) + position_size
        
        if total_position > self.max_position_size:
            logger.warning(f"Order would exceed max position size: {total_position} > {self.max_position_size}")
            return False
            
        return True

# 使用示例：
# risk_manager = RiskManager()
# risk_manager.update_account_info(10000, -200)
# position_size = risk_manager.calculate_position_size(15000, 14980)
# can_trade = risk_manager.should_trade()