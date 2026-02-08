# CLAWA IBKR MNQ 量化交易系统

基于 **ICT (Inner Circle Trader)** 和 **SMC (Smart Money Concepts)** 策略的自动化交易系统，专门针对 **MNQ (Micro E-mini Nasdaq-100 Futures)** 合约。

## 🎯 核心策略

### ICT 策略要素
- **市场结构转变** (Market Structure Shifts)
- **流动性抓取** (Liquidity Grabbing)  
- **订单块识别** (Order Blocks)
- **公平价值缺口** (Fair Value Gaps - FVG)
- **时间与价格平衡** (Time and Price Equilibrium)

### SMC 策略要素
- **供需区域** (Supply & Demand Zones)
- **失衡区域** (Imbalance Areas)
- **机构算法行为** (Institutional Algorithm Behavior)
- **流动性池分析** (Liquidity Pools)

## 📊 交易逻辑

### 入场条件
1. **市场结构确认**: 识别 BOS (Break of Structure) 或 CHoCH (Change of Character)
2. **流动性验证**: 确认关键流动性水平
3. **订单块确认**: 识别有效的订单块区域
4. **FVG 验证**: 确认公平价值缺口存在
5. **时间窗口**: 符合 ICT 时间框架（伦敦开盘、纽约开盘等）

### 出场条件
- **止盈**: 基于流动性目标或风险回报比 (1:2, 1:3)
- **止损**: 基于订单块边界或市场结构破坏
- **时间止损**: 超过持仓时间限制

### 风险管理
- **单笔风险**: ≤ 1% 账户净值
- **最大持仓**: 1-2 手 MNQ (根据账户大小调整)
- **日最大亏损**: ≤ 3% 账户净值

## ⚙️ 技术架构

```
数据层 → 策略引擎 → 执行层 → 监控层
```

### 数据层
- **实时行情**: IBKR API 获取 MNQ 实时数据
- **历史数据**: IBKR 历史数据用于回测和验证
- **多时间框架**: 15分钟、1小时、4小时、日线

### 策略引擎
- **ICT/SMC 信号生成**: 基于价格行为识别交易信号
- **过滤器**: 多重确认机制减少假信号
- **动态参数**: 根据市场波动性调整参数

### 执行层
- **IBKR API 集成**: 自动下单、修改、取消订单
- **订单类型**: 限价单为主，市价单为辅
- **错误处理**: 网络中断、API 限制等异常处理

### 监控层
- **实时监控**: 交易状态、账户状态监控
- **日志记录**: 详细交易日志和决策过程
- **告警系统**: 异常情况通知

## 🐳 Docker 部署

### 环境要求
- **Docker**: 20.10+
- **IB Gateway/TWS**: 已安装并启用 API
- **Python**: 3.8+ (容器内)

### 快速启动
```bash
# 1. 克隆项目
git clone <repo-url>
cd clawa_ibkr_mnq

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env 文件

# 3. 构建并运行
docker build -t clawa-ibkr-mnq .
docker run --env-file .env --network host -d --name clawa-ibkr-mnq clawa-ibkr-mnq
```

## 🔧 配置说明

### 环境变量 (.env)
```env
# IBKR 配置
IBKR_HOST=host.docker.internal
IBKR_PORT=7497
IBKR_CLIENT_ID=999

# 交易配置
SYMBOL=MNQ
EXCHANGE=CME
CURRENCY=USD

# 风险管理
RISK_PERCENTAGE=1.0
MAX_POSITION_SIZE=2
DAILY_LOSS_LIMIT=3.0

# 日志级别
LOG_LEVEL=INFO
```

### 策略参数
- **时间框架**: 可配置多个时间框架组合
- **FVG 敏感度**: 控制 FVG 识别的严格程度  
- **流动性阈值**: 定义关键流动性水平
- **订单块有效期**: 订单块的有效时间窗口

## 📈 回测与优化

### 回测功能
- **历史数据回测**: 使用 IBKR 历史数据
- **参数优化**: 自动寻找最优参数组合
- **绩效指标**: 胜率、盈亏比、最大回撤等

### 实盘模拟
- **Paper Trading**: 支持 IBKR 模拟账户测试
- **小仓位实盘**: 最小合约测试策略有效性

## ⚠️ 风险提示

- **期货交易高风险**: MNQ 是杠杆产品，可能导致重大损失
- **策略局限性**: ICT/SMC 策略在某些市场环境下可能失效
- **技术风险**: 网络延迟、API 限制等技术问题
- **建议**: 先用模拟账户充分测试，再考虑实盘

## 📚 学习资源

- **ICT 教程**: [Inner Circle Trader YouTube](https://www.youtube.com/c/InnerCircleTrader)
- **SMC 概念**: [Smart Money Concepts 详解](https://www.forex.academy/smart-money-concepts/)
- **MNQ 合约规格**: CME 官方文档
- **IBKR API 文档**: Interactive Brokers 开发者文档

## 📝 开发路线图

### Phase 1: 基础框架
- [x] 项目结构搭建
- [ ] IBKR API 连接
- [ ] 基础数据获取

### Phase 2: 策略实现  
- [ ] ICT 信号识别
- [ ] SMC 逻辑实现
- [ ] 风险管理模块

### Phase 3: 执行与监控
- [ ] 自动交易执行
- [ ] 实时监控系统
- [ ] 日志和告警

### Phase 4: 优化与部署
- [ ] 回测系统
- [ ] 参数优化
- [ ] Docker 部署优化

---

**免责声明**: 本系统仅供学习和研究使用，不构成投资建议。期货交易存在高风险，可能导致本金全部损失。