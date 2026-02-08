#!/bin/bash
# CLAWA IBKR MNQ V1.0 交易系统启动器

echo "=========================================="
echo "CLAWA IBKR MNQ V1.0 交易系统"
echo "=========================================="
echo ""
echo "⚠️  注意: 实盘交易将使用真实资金!"
echo ""
echo "请确认 IBKR Gateway 已启动并配置好 API 连接"
echo "- 端口: 4002 (当前配置)"
echo "- 需勾选 'Enable ActiveX and Socket Clients'"
echo ""
echo "请选择:"
echo "1) 启动实盘交易"
echo "2) 验证 IBKR 连接"
echo "3) 查看策略文档"
echo "4) 退出"
echo ""

read -p "请输入选项 (1-4): " option

case $option in
    1)
        echo ""
        echo "正在启动 V1.0 实盘交易系统..."
        echo "=========================================="
        source venv/bin/activate
        python trade_v1_live.py
        ;;
    2)
        echo ""
        echo "测试 IBKR Gateway 连接..."
        source venv/bin/activate
        python -c "
from config import Config
from ib_insync import IB, Future

print(f'尝试连接: {Config.IBKR_HOST}:{Config.IBKR_PORT}...')
try:
    ib = IB()
    ib.connect(host=Config.IBKR_HOST, port=Config.IBKR_PORT, clientId=Config.IBKR_CLIENT_ID, timeout=10)
    print('✅ 连接成功!')
    
    contract = Future(symbol=Config.SYMBOL, exchange=Config.EXCHANGE, currency=Config.CURRENCY)
    bars = ib.reqHistoricalData(contract, durationStr='1 D', barSizeSetting='15 mins', whatToShow='TRADES')
    print(f'✅ 获取到 {len(bars)} 根K线数据')
    ib.disconnect()
    print('✅ 测试完成')
except Exception as e:
    print(f'❌ 连接失败: {e}')
    print('')
    echo '请检查:'
    echo '  1. IBKR Gateway/TWS 是否运行'
    echo '  2. API 端口是否正确'
    echo '  3. 是否启用 API 连接'
"
        ;;
    3)
        echo ""
        cat STRATEGY_V1.md
        ;;
    4)
        echo "退出"
        ;;
    *)
        echo "无效选项"
        ;;
esac
