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
        ep_list = []
        bp_list = []
        for s in stocks:
            pe = s.get("pe_ratio", 0)
            pb = s.get("pb_ratio", 0)
            ep = 1.0 / pe if pe > 0 else 0.0
            bp = 1.0 / pb if pb > 0 else 0.0
            ep_list.append(ep)
            bp_list.append(bp)
        ep_z = self.zscore_normalize(ep_list)
        bp_z = self.zscore_normalize(bp_list)
        return [(ep_z[i] + bp_z[i]) / 2.0 for i in range(n)]

    def compute_momentum_factor(self, stocks: List[Dict]) -> List[float]:
        """Momentum 动量因子：60 日涨跌幅代理"""
        mom_list = [s.get("change_60d", 0) for s in stocks]
        return self.zscore_normalize(mom_list)

    def compute_quality_factor(self, stocks: List[Dict]) -> List[float]:
        """Quality 质量因子：PE/PB 合理区间综合"""
        n = len(stocks)
        if n == 0:
            return []
        quality_list = []
        for s in stocks:
            pe = s.get("pe_ratio", 0)
            pb = s.get("pb_ratio", 0)
            q = 0.0
            if 0 < pe < 100:
                q += 1.0 / pe
            if 0 < pb < 20:
                q += 1.0 / pb
            quality_list.append(q)
        return self.zscore_normalize(quality_list)

    def compute_low_vol_factor(self, stocks: List[Dict]) -> List[float]:
        """Low-Vol 低波动因子：振幅反向"""
        vol_list = [-s.get("amplitude", 0) for s in stocks]
        return self.zscore_normalize(vol_list)

    def compute_size_factor(self, stocks: List[Dict]) -> List[float]:
        """Size 规模因子：市值反向对数"""
        size_list = []
        for s in stocks:
            mv = s.get("total_mv", 0)
            size_list.append(-math.log(mv) if mv > 0 else 0.0)
        return self.zscore_normalize(size_list)

    def compute_turnover_factor(self, stocks: List[Dict]) -> List[float]:
        """Turnover 换手率因子（A 股特色）"""
        turnover_list = [-s.get("turnover_rate", 0) for s in stocks]
        return self.zscore_normalize(turnover_list)

    # ================================================================
    # 因子中性化
    # ================================================================
    @staticmethod
    def _ols_residual(y: List[float], x: List[float]) -> List[float]:
        """OLS 回归取残差: y = alpha + beta*x + epsilon, return epsilon
        纯 Python 实现，无需 numpy
        """
        n = len(y)
        if n < 3:
            return list(y)
        mean_x = sum(x) / n
        mean_y = sum(y) / n
        cov_xy = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n)) / (n - 1)
        var_x = sum((xi - mean_x) ** 2 for xi in x) / (n - 1)
        if var_x < 1e-12:
            return [yi - mean_y for yi in y]
        beta = cov_xy / var_x
        alpha = mean_y - beta * mean_x
        residual = [y[i] - (alpha + beta * x[i]) for i in range(n)]
        return residual

    def neutralize_market_cap(self, factor_values: List[float],
                               stocks: List[Dict]) -> List[float]:
        """市值中性化：回归掉 log(market_cap) 的影响"""
        log_mv = []
        for s in stocks:
            mv = s.get("total_mv", 0)
            log_mv.append(math.log(mv) if mv > 0 else 0.0)
        return self._ols_residual(factor_values, log_mv)

    def neutralize_industry(self, factor_values: List[float],
                            stocks: List[Dict],
                            industry_key: str = "industry") -> List[float]:
        """行业中性化：组内去均值"""
        n = len(factor_values)
        if n == 0:
            return []
        groups = {}
        for i in range(n):
            ind = stocks[i].get(industry_key, "unknown")
            if ind not in groups:
                groups[ind] = []
            groups[ind].append(i)
        result = [0.0] * n
        for ind, indices in groups.items():
            group_vals = [factor_values[i] for i in indices]
            group_mean = sum(group_vals) / len(group_vals)
            for i in indices:
                result[i] = factor_values[i] - group_mean
        return result

    def neutralize_all(self, factors: Dict[str, List[float]],
                       stocks: List[Dict],
                       market_cap: bool = True,
                       industry: bool = False,
                       industry_key: str = "industry") -> Dict[str, List[float]]:
        """对所有因子执行中性化（Size 因子除外）"""
        neutral_factors = {}
        skip = {"size"}
        for fname, fvals in factors.items():
            if fname in skip:
                neutral_factors[fname] = fvals
                continue
            result = list(fvals)
            if industry:
                result = self.neutralize_industry(result, stocks, industry_key)
            if market_cap:
                result = self.neutralize_market_cap(result, stocks)
            result = self.zscore_normalize(result)
            neutral_factors[fname] = result
        return neutral_factors

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
