#!/usr/bin/env python3
"""
因子计算模块 - 六大核心因子的构建与标准化
参考 AQR 因子模型构建师（角色 06）的因子定义
"""

import math
from typing import List, Dict, Optional


class FactorCalculator:
    """多因子计算器"""

    @staticmethod
    def zscore_normalize(values: List[float], winsorize_sigma: float = 3.0) -> List[float]:
        """截面 Z-score 标准化 + Winsorization"""
        n = len(values)
        if n == 0:
            return []
        mean = sum(values) / n
        variance = sum((x - mean) ** 2 for x in values) / max(n - 1, 1)
        std = math.sqrt(variance) if variance > 0 else 1e-8
        z_values = [(x - mean) / std for x in values]
        z_values = [max(-winsorize_sigma, min(winsorize_sigma, z)) for z in z_values]
        return z_values

    def compute_value_factor(self, stocks: List[Dict]) -> List[float]:
        """Value 价值因子：EP + BP 综合"""
        n = len(stocks)
        if n == 0:
            return []
        ep_list, bp_list = [], []
        for s in stocks:
            pe, pb = s.get("pe_ratio", 0), s.get("pb_ratio", 0)
            ep_list.append(1.0 / pe if pe > 0 else 0.0)
            bp_list.append(1.0 / pb if pb > 0 else 0.0)
        ep_z = self.zscore_normalize(ep_list)
        bp_z = self.zscore_normalize(bp_list)
        return [(ep_z[i] + bp_z[i]) / 2.0 for i in range(n)]

    def compute_momentum_factor(self, stocks: List[Dict]) -> List[float]:
        """Momentum 动量因子：60 日涨跌幅代理"""
        return self.zscore_normalize([s.get("change_60d", 0) for s in stocks])

    def compute_quality_factor(self, stocks: List[Dict]) -> List[float]:
        """Quality 质量因子：PE/PB 合理区间综合"""
        n = len(stocks)
        if n == 0:
            return []
        quality_list = []
        for s in stocks:
            pe, pb = s.get("pe_ratio", 0), s.get("pb_ratio", 0)
            q = 0.0
            if 0 < pe < 100:
                q += 1.0 / pe
            if 0 < pb < 20:
                q += 1.0 / pb
            quality_list.append(q)
        return self.zscore_normalize(quality_list)

    def compute_low_vol_factor(self, stocks: List[Dict]) -> List[float]:
        """Low-Vol 低波动因子：振幅反向"""
        return self.zscore_normalize([-s.get("amplitude", 0) for s in stocks])

    def compute_size_factor(self, stocks: List[Dict]) -> List[float]:
        """Size 规模因子：市值反向对数"""
        return self.zscore_normalize(
            [-math.log(s.get("total_mv", 0)) if s.get("total_mv", 0) > 0 else 0.0 for s in stocks]
        )

    def compute_turnover_factor(self, stocks: List[Dict]) -> List[float]:
        """Turnover 换手率因子（A 股特色）"""
        return self.zscore_normalize([-s.get("turnover_rate", 0) for s in stocks])

    def compute_all_factors(self, stocks: List[Dict]) -> Dict[str, List[float]]:
        """计算所有因子"""
        return {
            "value": self.compute_value_factor(stocks),
            "momentum": self.compute_momentum_factor(stocks),
            "quality": self.compute_quality_factor(stocks),
            "low_vol": self.compute_low_vol_factor(stocks),
            "size": self.compute_size_factor(stocks),
            "turnover": self.compute_turnover_factor(stocks),
        }

    def compute_composite_score(self, factors: Dict[str, List[float]],
                                weights: Optional[Dict[str, float]] = None) -> List[float]:
        """综合评分"""
        if weights is None:
            weights = {
                "value": 0.25, "momentum": 0.20, "quality": 0.25,
                "low_vol": 0.15, "size": 0.10, "turnover": 0.05,
            }
        n = len(next(iter(factors.values()))) if factors else 0
        scores = [0.0] * n
        for fname, fvals in factors.items():
            w = weights.get(fname, 0.0)
            for i in range(n):
                scores[i] += w * fvals[i]
        return scores


if __name__ == "__main__":
    calc = FactorCalculator()
    test_stocks = [
        {"code": "000001", "name": "平安银行", "price": 12.5, "pe_ratio": 5.2, "pb_ratio": 0.6,
         "turnover_rate": 0.8, "amplitude": 2.1, "total_mv": 2.4e11, "change_60d": 5.3},
        {"code": "600519", "name": "贵州茅台", "price": 1680, "pe_ratio": 32.0, "pb_ratio": 10.5,
         "turnover_rate": 0.3, "amplitude": 1.5, "total_mv": 2.1e12, "change_60d": -3.2},
        {"code": "000858", "name": "五粮液", "price": 148, "pe_ratio": 22.0, "pb_ratio": 6.8,
         "turnover_rate": 0.5, "amplitude": 1.8, "total_mv": 5.7e11, "change_60d": 2.1},
    ]
    factors = calc.compute_all_factors(test_stocks)
    scores = calc.compute_composite_score(factors)
    print("因子计算测试:")
    for i, s in enumerate(test_stocks):
        print(f"  {s['code']} {s['name']}")
        for fname, fvals in factors.items():
            print(f"    {fname:>10s}: {fvals[i]:>7.4f}")
        print(f"    {'composite':>10s}: {scores[i]:>7.4f}")
