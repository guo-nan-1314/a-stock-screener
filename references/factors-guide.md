# 因子定义与经济学逻辑

> 参考 quant-research-lab 角色 06（AQR 因子模型构建师）

## 六大核心因子

### 1. Value 价值因子
**经济直觉**：价值因子是对基本面反转风险和困境风险的补偿。
**构建公式**：`Value_Score = mean(z(EP), z(BP))`

### 2. Momentum 动量因子
**经济直觉**：信息扩散延迟和投资者反应不足。
**构建公式**：`Mom = z(change_60d)`

### 3. Quality 质量因子
**经济直觉**：高质量公司被市场系统性低估。
**构建公式**：`Quality = mean(z(EP_quality), z(BP_quality))`

### 4. Low-Vol 低波动因子
**经济直觉**：杠杆约束导致高 Beta 资产被过度追捧。
**构建公式**：`LowVol = -z(amplitude)`

### 5. Size 规模因子
**经济直觉**：小盘股面临更高的流动性风险。
**构建公式**：`Size = -z(log(market_cap))`

### 6. Turnover 换手率因子（A 股特色）
**构建公式**：`Turnover = -z(turnover_rate)`

## 因子标准化
所有因子使用截面 Z-score 标准化 + 3σ Winsorization

## 参考文献
- Fama & French (1992) - 价值因子
- Jegadeesh & Titman (1993) - 动量因子
- Asness et al. (2019) - 质量因子
- Frazzini & Pedersen (2014) - BAB 低波动因子
