#!/usr/bin/env python3
"""
A 股量化选股引擎 - 主入口
整合数据获取、因子计算、风控过滤、综合评分
"""

import argparse
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data_fetcher import DataFetcher
from factor_calculator import FactorCalculator


class ScreenerEngine:
    """选股引擎"""

    DEFAULT_RISK = {
        "min_amount": 2000_0000,    # 最低成交额 2000 万
        "min_mv": 30_0000_0000,     # 最低市值 30 亿
        "max_pe": 300,              # PE 上限
        "min_pe": -1000,            # PE 下限（允许亏损股）
    }

    def __init__(self, cache_dir=None):
        self.fetcher = DataFetcher(cache_dir=cache_dir)
        self.calc = FactorCalculator()

    def run(self, top_n=20, exclude_st=True, exclude_kcb=True,
            exclude_bse=True, risk=None, weights=None, output_json=False):
        risk = {**self.DEFAULT_RISK, **(risk or {})}

        print("[1/5] 获取全市场行情数据...")
        stocks = self.fetcher.fetch_all_stocks()
        print(f"  获取到 {len(stocks)} 只股票")

        print("[2/5] 基础过滤...")
        stocks = self.fetcher.filter_basic(stocks, exclude_st, exclude_kcb, exclude_bse)
        print(f"  基础过滤后: {len(stocks)} 只")

        stocks = self.fetcher.calc_amplitude(stocks)
        filtered = []
        skip_reasons = {"amount": 0, "mv": 0, "pe": 0}
        for s in stocks:
            if s.get("amount", 0) < risk["min_amount"]:
                skip_reasons["amount"] += 1
                continue
            if s.get("total_mv", 0) < risk["min_mv"]:
                skip_reasons["mv"] += 1
                continue
            pe = s.get("pe_ratio", 0)
            if pe == 0:
                skip_reasons["pe"] += 1
                continue
            if pe > risk["max_pe"] or pe < risk["min_pe"]:
                skip_reasons["pe"] += 1
                continue
            filtered.append(s)
        print(f"  风控过滤后: {len(filtered)} 只 "
              f"(成交额不足:{skip_reasons['amount']}, "
              f"市值不足:{skip_reasons['mv']}, "
              f"PE异常:{skip_reasons['pe']})")

        if not filtered:
            print("没有符合条件的股票")
            return []

        print("[3/5] 计算因子与综合评分...")
        factors = self.calc.compute_all_factors(filtered)
        scores = self.calc.compute_composite_score(factors, weights)

        for i, s in enumerate(filtered):
            s["score"] = round(scores[i], 4)
            for fname, fvals in factors.items():
                s[f"factor_{fname}"] = round(fvals[i], 4)

        print("[4/5] 排序输出...")
        filtered.sort(key=lambda x: x["score"], reverse=True)
        result = filtered[:top_n]

        print("[5/5] 完成!\n")
        if output_json:
            output = []
            for s in result:
                output.append({
                    "code": s["code"], "name": s["name"],
                    "score": s["score"], "price": s["price"],
                    "change_pct": s["change_pct"],
                    "pe_ratio": s["pe_ratio"], "pb_ratio": s["pb_ratio"],
                    "total_mv": s["total_mv"],
                    "turnover_rate": s["turnover_rate"],
                    "change_60d": s["change_60d"],
                    "factors": {k.replace("factor_", ""): v
                                for k, v in s.items() if k.startswith("factor_")},
                })
            print(json.dumps(output, ensure_ascii=False, indent=2))
        else:
            print(f"{'排名':>4s} {'代码':>8s} {'名称':>8s} {'评分':>8s} "
                  f"{'价格':>8s} {'涨跌幅':>8s} {'PE':>8s} {'PB':>7s} "
                  f"{'换手率':>7s} {'市值(亿)':>8s}")
            print("-" * 95)
            for i, s in enumerate(result):
                mv_yi = s.get("total_mv", 0) / 1e8
                print(f"{i+1:>4d} {s['code']:>8s} {s['name']:>8s} "
                      f"{s['score']:>8.4f} {s['price']:>8.2f} "
                      f"{s['change_pct']:>7.2f}% {s['pe_ratio']:>8.1f} "
                      f"{s['pb_ratio']:>7.2f} {s['turnover_rate']:>6.2f}% "
                      f"{mv_yi:>8.1f}")

        return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="A 股量化选股引擎")
    parser.add_argument("--top", type=int, default=20, help="输出前 N 只")
    parser.add_argument("--no-st", action="store_true", default=True)
    parser.add_argument("--no-kcb", action="store_true", default=True)
    parser.add_argument("--no-bse", action="store_true", default=True)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--cache-dir", type=str, default=None)
    parser.add_argument("--min-amount", type=float, default=2000_0000)
    parser.add_argument("--min-mv", type=float, default=30_0000_0000)
    args = parser.parse_args()

    engine = ScreenerEngine(cache_dir=args.cache_dir)
    risk = dict(ScreenerEngine.DEFAULT_RISK)
    risk["min_amount"] = args.min_amount
    risk["min_mv"] = args.min_mv
    engine.run(top_n=args.top, output_json=args.json, risk=risk)
