# A 股量化选股系统

基于多因子模型与量化信号的智能选股引擎，参考顶级量化机构（Citadel、AQR、Two Sigma）的选股方法论，针对 A 股市场特性进行系统化实现。

## 项目结构

```
a-stock-screener/
├── SKILL.md                    # Skill 定义文件
├── README.md                   # 项目说明
├── TODO.md                     # 开发待办清单
├── scripts/
│   ├── screener_engine.py      # 选股引擎核心
│   ├── factor_calculator.py    # 因子计算模块
│   ├── data_fetcher.py         # 数据获取模块
│   ├── signal_generator.py     # 信号生成模块
│   └── risk_filter.py          # 风控过滤器
├── references/
│   ├── factors-guide.md        # 因子定义与经济学逻辑
│   └── market-rules.md         # A 股交易规则与约束
├── assets/
│   └── screening-checklist.md  # 选股二次验证清单
└── state/
    └── .gitkeep                # 运行状态目录
```

## 核心能力

- **多因子选股**：Value / Momentum / Quality / Low-Vol / Carry / Size 六大因子
- **信号生成**：IC/ICIR 分析、分层回测、衰减分析
- **风控过滤**：流动性/波动率/ST/退市风险多维度过滤
- **仓位建议**：波动率目标、Kelly 公式、风险平价

## 技术栈

- Python 3.8+
- 数据源：东方财富免费 API（无需 API Key）
- 零外部依赖（纯标准库实现）

## 快速开始

```bash
# 基础选股扫描
python scripts/screener_engine.py --top 20 --no-st --json

# 因子分析模式
python scripts/screener_engine.py --mode factor --factor momentum --top 30
```

## License

MIT
