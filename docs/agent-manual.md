# A 股量化模拟交易系统 - Agent 执行手册

> 项目地址: `D:\gjb\project\aiskill\a-stock-screener`
> GitHub: `guo-nan-1314/a-stock-screener`
> 数据库: SQLite (`scripts/quant_trading.db`) + MySQL MCP 同步

---

## 一、系统概述

本金 **10 万元**，基于六大因子（价值/动量/质量/低波/规模/换手率）选股，市值中性化处理，自动模拟买卖。目标月收益 10%。

### 核心文件

| 文件 | 用途 |
|:---|:---|
| `scripts/trading_engine.py` | 交易引擎主程序（信号生成+买卖执行+定时调度） |
| `scripts/data_fetcher.py` | 数据获取（新浪财经 API + curl 传输层） |
| `scripts/factor_calculator.py` | 因子计算 + 市值中性化 |
| `scripts/screener_engine.py` | 独立选股筛选器 |
| `scripts/quant_trading.db` | SQLite 本地数据库（自动创建） |

---

## 二、启动自动调度

### 2.1 启动命令

```bash
cd D:\gjb\project\aiskill\a-stock-screener
python scripts/trading_engine.py --schedule --time "15:05"
```

- `--schedule`: 启动自动定时调度器
- `--time "15:05"`: 每个交易日 15:05 自动触发（收盘后 5 分钟，确保数据更新）
- 调度器会持续运行，每 5 秒检查时间，到达设定时间自动执行
- 仅周一至周五运行（法定节假日暂不处理）
- 按 `Ctrl+C` 停止

### 2.2 每日自动执行流程

到达触发时间后，系统自动执行以下 7 步：

```
[1/7] 获取全市场行情        → 新浪财经 API，约 5500 只 A 股
[2/7] 基础过滤              → 排除 ST/科创板/北交所/成交额<2000万/市值<30亿/PE异常
[3/7] 更新持仓价格          → 用最新价格更新持仓市值和盈亏
[4/7] 计算因子与评分        → 六大因子 + 市值中性化 + 综合评分
[5/7] 检查卖出信号          → 止损(-5%)/止盈(+15%)/评分衰减(<0.3)
[6/7] 检查买入信号          → 评分>1.0 的候选股，等权买入
[7/7] 记录每日快照          → 总资产/日收益/累计收益 写入数据库
```

### 2.3 后台运行（可选）

如需关闭终端后继续运行：

```powershell
Start-Process python -ArgumentList "scripts/trading_engine.py","--schedule","--time","15:05" -WindowStyle Hidden -WorkingDirectory "D:\gjb\project\aiskill\a-stock-screener"
```

或使用 Windows 任务计划程序（开机自启）：

```powershell
schtasks /create /tn "QuantTrading" /tr "python D:\gjb\project\aiskill\a-stock-screener\scripts\trading_engine.py --schedule --time 15:05" /sc onlogon
```

---

## 三、查看状态与报告

### 3.1 查看当前账户

```bash
python scripts/trading_engine.py --report
```

输出示例：
```
  账户状态:
  初始本金:     100,000.00 元
  总资产:        99,975.00 元
  可用资金:      18,170.00 元
  持仓市值:      81,805.00 元
  总盈亏:           -25.00 元
  总收益率:       -0.0250%

  持仓 (5/5):
  600694 大商股份 1100股 成本14.26 现价14.26 盈亏0.00%
  ...
```

### 3.2 查看历史收益曲线

```bash
python scripts/trading_engine.py --history
```

### 3.3 查看交易记录

```bash
python scripts/trading_engine.py --trades
```

### 3.4 查看信号记录

```bash
python scripts/trading_engine.py --signals
```

### 3.5 手动触发一次（不等调度）

```bash
python scripts/trading_engine.py --run
```

---

## 四、策略参数调整

所有参数在 `scripts/trading_engine.py` 的 `TradingEngine` 类顶部定义：

```python
class TradingEngine:
    INITIAL_CAPITAL = 100_000.0    # 初始本金
    MAX_POSITIONS = 5              # 最大持仓数（可调 3~8）
    LOT_SIZE = 100                 # A 股最小交易单位

    BUY_THRESHOLD = 1.0            # 买入阈值（调高=更严格，调低=更宽松）
    SELL_THRESHOLD = 0.3           # 卖出阈值（调高=更早卖出弱势股）
    TOP_CANDIDATES = 30            # 候选池大小

    STOP_LOSS_PCT = -5.0           # 止损线（调大如-3%=更保守）
    TAKE_PROFIT_PCT = 15.0         # 止盈线（调小如10%=更快落袋）

    COMMISSION_RATE = 0.00025      # 佣金万2.5
    MIN_COMMISSION = 5.0           # 最低佣金5元
    STAMP_TAX_RATE = 0.0005        # 印花税万5（卖出）

    USE_NEUTRALIZE = True          # 是否启用市值中性化
```

### 调参建议

| 场景 | 调整方向 |
|:---|:---|
| 交易太少，想更激进 | `BUY_THRESHOLD` 降到 0.8，`STOP_LOSS_PCT` 降到 -8% |
| 交易太频繁，想更保守 | `BUY_THRESHOLD` 升到 1.3，`STOP_LOSS_PCT` 升到 -3% |
| 亏损频繁 | `STOP_LOSS_PCT` 调到 -3%，`TAKE_PROFIT_PCT` 调到 8% |
| 想更集中持仓 | `MAX_POSITIONS` 调到 3 |
| 想更分散持仓 | `MAX_POSITIONS` 调到 8 |
| 想关闭中性化 | `USE_NEUTRALIZE = False` |

---

## 五、MySQL 数据同步

系统使用 SQLite 本地存储，可通过 MySQL MCP 工具同步数据以便远程查看。

### 5.1 同步账户数据

通过 MySQL MCP 执行：

```sql
USE quant_trading;
SELECT * FROM account;
SELECT * FROM positions WHERE shares > 0;
SELECT * FROM daily_snapshots ORDER BY trade_date DESC LIMIT 10;
SELECT * FROM trades ORDER BY trade_time DESC LIMIT 20;
```

### 5.2 同步时机

建议每次 `--run` 执行后，手动通过 MySQL MCP 同步一次关键数据。

---

## 六、定期复盘流程

建议每周执行一次复盘：

### 6.1 查看本周收益

```bash
python scripts/trading_engine.py --history
```

### 6.2 分析交易质量

```bash
python scripts/trading_engine.py --trades
```

关注：
- 胜率（盈利交易数 / 总交易数）
- 平均盈利 vs 平均亏损
- 最大单笔亏损

### 6.3 调参决策

根据复盘结果，参考第四节的调参建议，修改策略参数。

---

## 七、常见问题

### Q: 调度器没有触发？
- 检查是否为工作日（周一至周五）
- 检查终端是否还在运行
- 手动执行 `--run` 验证功能正常

### Q: 获取数据失败？
- 检查网络连接
- 新浪财经 API 偶尔不稳定，等待几分钟后重试
- 确认 curl.exe 在系统 PATH 中

### Q: 如何重置账户？

```bash
del scripts\quant_trading.db
python scripts/trading_engine.py --run
```

### Q: 如何查看某天的详细因子评分？

```bash
python scripts/screener_engine.py --top 20 --neutralize-mc
```

---

## 八、快速参考卡片

```
┌─────────────────────────────────────────────────────┐
│  启动调度:  python trading_engine.py --schedule      │
│  手动运行:  python trading_engine.py --run           │
│  查看账户:  python trading_engine.py --report        │
│  收益曲线:  python trading_engine.py --history       │
│  交易记录:  python trading_engine.py --trades        │
│  信号记录:  python trading_engine.py --signals       │
│  重置账户:  del quant_trading.db + 重新运行          │
├─────────────────────────────────────────────────────┤
│  工作目录:  D:\gjb\project\aiskill\a-stock-screener │
│  数据库:    scripts\quant_trading.db                │
│  触发时间:  默认 15:05（收盘后5分钟）                │
│  运行频率:  每个交易日一次（周一至周五）              │
│  最大持仓:  5 只，等权分配                           │
│  止损/止盈: -5% / +15%                             │
└─────────────────────────────────────────────────────┘
```
