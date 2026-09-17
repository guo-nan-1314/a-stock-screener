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
        "max_pe": 300,
        "min_pe": 0,
    }

    def __init__(self, cache_dir=None):
        self.fetcher = DataFetcher(cache_dir=cache_dir)
        self.calc = FactorCalculator()

    def run(self, top_n=20, exclude_st=True, exclude_kcb=True,
            exclude_bse=True, risk=None, weights=None, output_json=False):
        risk = risk or self.DEFAULT_RISK

        # Step 1: 获取数据
        print("[1/4] 获取全市场行情数据...")
        stocks = self.fetcher.fetch_all_stocks()
        print(f"  获取到 {len(stocks)} 只股票")

        # Step 2: 基础过滤
        print("[2/4] 基础过滤...")
        stocks = self.fetcher.filter_basic(stocks, exclude_st, exclude_kcb, exclude_bse)
        filtered = []
        for s in stocks:
            if s.get("amount", 0) < risk["min_amount"]:
                continue
            if s.get("total_mv", 0) < risk["min_mv"]:
                continue
            pe = s.get("pe_ratio", 0)
            if pe <= risk["min_pe"] or pe > risk["max_pe"]:
                continue
            filtered.append(s)
        print(f"  过滤后剩余 {len(filtered)} 只股票")

        if not filtered:
            print("没有符合条件的股票")
            return []

        # Step 3: 因子计算 + 综合评分
        print("[3/4] 计算因子与综合评分...")
        factors = self.calc.compute_all_factors(filtered)
        scores = self.calc.compute_composite_score(factors, weights)

        for i, s in enumerate(filtered):
            s["score"] = round(scores[i], 4)
            for fname, fvals in factors.items():
                s[f"factor_{fname}"] = round(fvals[i], 4)

        # Step 4: 排序输出
        print("[4/4] 排序输出...")
        filtered.sort(key=lambda x: x["score"], reverse=True)
        result = filtered[:top_n]

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
            print(f"\n{'排名':>4s} {'代码':>8s} {'名称':>8s} {'评分':>8s} "
                  f"{'价格':>8s} {'涨跌幅':>8s} {'PE':>8s} {'PB':>8s} {'60日涨幅':>8s}")
            print("-" * 80)
            for i, s in enumerate(result):
                print(f"{i+1:>4d} {s['code']:>8s} {s['name']:>8s} "
                      f"{s['score']:>8.4f} {s['price']:>8.2f} "
                      f"{s['change_pct']:>7.2f}% {s['pe_ratio']:>8.1f} "
                      f"{s['pb_ratio']:>8.2f} {s['change_60d']:>7.2f}%")

        return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="A 股量化选股引擎")
    parser.add_argument("--top", type=int, default=20, help="输出前 N 只")
    parser.add_argument("--no-st", action="store_true", default=True, help="排除 ST")
    parser.add_argument("--no-kcb", action="store_true", default=True, help="排除科创板")
    parser.add_argument("--no-bse", action="store_true", default=True, help="排除北交所")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    parser.add_argument("--cache-dir", type=str, default=None, help="缓存目录")
    parser.add_argument("--min-amount", type=float, default=2000_0000, help="最低成交额")
    parser.add_argument("--min-mv", type=float, default=30_0000_0000, help="最低市值")
    args = parser.parse_args()

    engine = ScreenerEngine(cache_dir=args.cache_dir)
    risk = dict(ScreenerEngine.DEFAULT_RISK)
    risk["min_amount"] = args.min_amount
    risk["min_mv"] = args.min_mv
    engine.run(top_n=args.top, output_json=args.json, risk=risk)
