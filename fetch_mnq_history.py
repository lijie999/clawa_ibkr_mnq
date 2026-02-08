"""
获取 MNQ 历史数据测试
先测试小数据量，确认连接正常后再请求大数据
"""

import asyncio
import sys
import time

if sys.version_info >= (3, 14):
    asyncio.set_event_loop(asyncio.new_event_loop())

from ib_insync import IB, Future
import pandas as pd
from datetime import datetime, timedelta
import os

IBKR_HOST = '127.0.0.1'
IBKR_PORT = 4002
CLIENT_ID = 999

OUTPUT_DIR = '/Users/lijiaolong/docker/clawa_ibkr_mnq'

def main():
    print(f"🔌 连接到 IBKR Gateway {IBKR_HOST}:{IBKR_PORT}...")
    ib = IB()
    ib.connect(IBKR_HOST, IBKR_PORT, clientId=CLIENT_ID, timeout=30)
    print("✅ 连接成功!\n")
    
    try:
        contract = Future()
        contract.symbol = 'MNQ'
        contract.exchange = 'CME'
        contract.currency = 'USD'
        
        details = ib.reqContractDetails(contract)
        if not details:
            print("❌ 未找到合约")
            return
        
        selected = details[0].contract
        print(f"🎯 合约: {selected.localSymbol} (ID: {selected.conId})\n")
        
        # 测试1: 1天分钟数据
        print("📊 测试 1天 分钟数据...")
        bars = ib.reqHistoricalData(
            selected, endDateTime='', durationStr='1 D',
            barSizeSetting='1 min', whatToShow='TRADES',
            useRTH=True, formatDate=1, timeout=60
        )
        if bars:
            print(f"   ✅ 1天: {len(bars)} 根\n")
        else:
            print("   ❌ 1天无数据\n")
        
        # 测试2: 5天分钟数据
        print("📊 测试 5天 分钟数据...")
        bars = ib.reqHistoricalData(
            selected, endDateTime='', durationStr='5 D',
            barSizeSetting='1 min', whatToShow='TRADES',
            useRTH=True, formatDate=1, timeout=120
        )
        if bars:
            print(f"   ✅ 5天: {len(bars)} 根\n")
        else:
            print("   ❌ 5天无数据\n")
        
        # 测试3: 1小时数据 (用于对比数据量)
        print("📊 测试 5天 1小时数据...")
        bars_hourly = ib.reqHistoricalData(
            selected, endDateTime='', durationStr='5 D',
            barSizeSetting='1 hour', whatToShow='TRADES',
            useRTH=True, formatDate=1, timeout=60
        )
        if bars_hourly:
            print(f"   ✅ 5天1小时: {len(bars_hourly)} 根\n")
        else:
            print("   ❌ 5天1小时无数据\n")
        
        if not bars:
            print("❌ 分钟数据不可用，可能是:")
            print("   - IBKR账户没有历史数据订阅")
            print("   - 合约已过期或未上市")
            print("   - 需要更高的API权限")
            return
        
        # 尝试获取更多数据
        all_bars = list(bars)
        
        print(f"📊 继续获取更多分钟数据 (每次60天)...")
        
        for i in range(1, 6):
            target_date = datetime.now() - timedelta(days=i*60)
            print(f"   块 {i+1}: 结束于 {target_date.strftime('%Y-%m-%d')}...")
            
            bars = ib.reqHistoricalData(
                selected,
                endDateTime=target_date.strftime('%Y%m%d %H:%M:%S'),
                durationStr='60 D',
                barSizeSetting='1 min',
                whatToShow='TRADES',
                useRTH=True,
                formatDate=1,
                timeout=180
            )
            
            if bars:
                print(f"      ✅ {len(bars)} 根")
                all_bars.extend(bars)
            else:
                print(f"      ❌ 无数据")
            
            time.sleep(3)
        
        # 去重
        seen = set()
        unique = []
        for bar in all_bars:
            if bar.date not in seen:
                seen.add(bar.date)
                unique.append(bar)
        
        unique.sort(key=lambda x: x.date)
        print(f"\n✅ 总计 {len(unique):,} 根K线\n")
        
        df = pd.DataFrame([{
            'date': b.date, 'open': b.open, 'high': b.high,
            'low': b.low, 'close': b.close, 'volume': b.volume
        } for b in unique])
        
        df['date'] = pd.to_datetime(df['date'])
        df.set_index('date', inplace=True)
        
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        out_file = os.path.join(OUTPUT_DIR, f'mnq_1min_{ts}.csv')
        df.to_csv(out_file)
        
        print(f"📁 已保存: {out_file}")
        print(f"\n📊 摘要:")
        print(f"   合约: {selected.localSymbol}")
        print(f"   范围: {df.index[0]} 至 {df.index[-1]}")
        print(f"   行数: {len(df):,}")
        print(f"   价格: {df['low'].min():.2f} - {df['high'].max():.2f}")
        print(f"   成交: {df['volume'].sum():,.0f}")
        
    except Exception as e:
        print(f"❌ 错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if ib.isConnected():
            ib.disconnect()
            print("\n🔌 已断开连接")

if __name__ == "__main__":
    main()
