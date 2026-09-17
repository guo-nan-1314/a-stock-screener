#!/usr/bin/env python3
"""
数据获取模块 - 从东方财富获取 A 股行情与基本面数据
纯标准库实现，无需安装第三方依赖
"""

import json
import urllib.request
import urllib.parse
import os
import time
from datetime import datetime
from typing import List, Dict, Optional


class DataFetcher:
    """东方财富数据获取器"""

    BASE_URL = "https://push2.eastmoney.com/api/qt/clist/get"
    KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://quote.eastmoney.com/",
    }

    def __init__(self, cache_dir: Optional[str] = None, cache_ttl: int = 3600):
        self.cache_dir = cache_dir
        self.cache_ttl = cache_ttl
        if cache_dir and not os.path.exists(cache_dir):
            os.makedirs(cache_dir)

    def _request(self, url: str, params: dict) -> dict:
        query = urllib.parse.urlencode(params)
        full_url = f"{url}?{query}"
        req = urllib.request.Request(full_url, headers=self.HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            print(f"[ERROR] 请求失败: {e}")
            return {}

    def _read_cache(self, key: str) -> Optional[dict]:
        if not self.cache_dir:
            return None
        path = os.path.join(self.cache_dir, f"{key}.json")
        if not os.path.exists(path):
            return None
        if time.time() - os.path.getmtime(path) > self.cache_ttl:
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def _write_cache(self, key: str, data: dict):
        if not self.cache_dir:
            return
        path = os.path.join(self.cache_dir, f"{key}.json")
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        except Exception:
            pass

    def fetch_all_stocks(self) -> List[Dict]:
        """获取全市场 A 股实时行情数据"""
        cached = self._read_cache("all_stocks_realtime")
        if cached:
            return cached.get("data", [])

        all_data = []
        page = 1
        while True:
            params = {
                "pn": page, "pz": 5000, "po": 1, "np": 1,
                "ut": "bd1d9ddb04089700cf9c27f6f7426281",
                "fltt": 2, "invt": 2, "fid": "f3",
                "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048",
                "fields": "f2,f3,f5,f6,f7,f8,f9,f10,f12,f14,f15,f16,f17,f18,f20,f21,f23,f24,f25",
            }
            data = self._request(self.BASE_URL, params)
            if not data or "data" not in data or data["data"] is None:
                break
            diff = data["data"].get("diff", [])
            if not diff:
                break
            for item in diff:
                all_data.append({
                    "code": str(item.get("f12", "")),
                    "name": str(item.get("f14", "")),
                    "price": item.get("f2", 0),
                    "change_pct": item.get("f3", 0),
                    "volume": item.get("f5", 0),
                    "amount": item.get("f6", 0),
                    "amplitude": item.get("f7", 0),
                    "turnover_rate": item.get("f8", 0),
                    "pe_ratio": item.get("f9", 0),
                    "volume_ratio": item.get("f10", 0),
                    "pb_ratio": item.get("f23", 0),
                    "high": item.get("f15", 0),
                    "low": item.get("f16", 0),
                    "open": item.get("f17", 0),
                    "prev_close": item.get("f18", 0),
                    "total_mv": item.get("f20", 0),
                    "circ_mv": item.get("f21", 0),
                    "change_60d": item.get("f24", 0),
                    "change_ytd": item.get("f25", 0),
                })
            total = data["data"].get("total", 0)
            if page * 5000 >= total:
                break
            page += 1

        result = {"data": all_data, "timestamp": datetime.now().isoformat()}
        self._write_cache("all_stocks_realtime", result)
        return all_data

    def fetch_kline(self, code: str, market: str = "auto",
                    period: str = "daily", count: int = 250) -> List[Dict]:
        """获取个股 K 线数据"""
        if market == "auto":
            market = "1" if code.startswith("6") else "0"
        period_map = {"daily": "101", "weekly": "102", "monthly": "103"}
        klt = period_map.get(period, "101")

        cache_key = f"kline_{code}_{market}_{period}_{count}"
        cached = self._read_cache(cache_key)
        if cached:
            return cached.get("data", [])

        params = {
            "secid": f"{market}.{code}",
            "ut": "fa5fd1943c7b386f172d6893dbfba10b",
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": klt, "fqt": 1, "end": "20500101", "lmt": count,
        }
        data = self._request(self.KLINE_URL, params)
        if not data or "data" not in data or data["data"] is None:
            return []

        result_data = []
        for line in data["data"].get("klines", []):
            parts = line.split(",")
            if len(parts) >= 7:
                result_data.append({
                    "date": parts[0],
                    "open": float(parts[1]),
                    "close": float(parts[2]),
                    "high": float(parts[3]),
                    "low": float(parts[4]),
                    "volume": float(parts[5]),
                    "amount": float(parts[6]),
                })

        result = {"data": result_data, "timestamp": datetime.now().isoformat()}
        self._write_cache(cache_key, result)
        return result_data

    def is_st(self, name: str) -> bool:
        return "ST" in name.upper()

    def is_kcb(self, code: str) -> bool:
        return code.startswith("688")

    def is_bse(self, code: str) -> bool:
        return code.startswith("8") or code.startswith("4")

    def filter_basic(self, stocks: List[Dict],
                     exclude_st: bool = True,
                     exclude_kcb: bool = True,
                     exclude_bse: bool = True) -> List[Dict]:
        """基础过滤：排除 ST、科创板、北交所"""
        filtered = []
        for s in stocks:
            if exclude_st and self.is_st(s.get("name", "")):
                continue
            if exclude_kcb and self.is_kcb(s.get("code", "")):
                continue
            if exclude_bse and self.is_bse(s.get("code", "")):
                continue
            if s.get("price", 0) <= 0 or s.get("total_mv", 0) <= 0:
                continue
            filtered.append(s)
        return filtered


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="A 股数据获取工具")
    parser.add_argument("--mode", choices=["realtime", "kline"], default="realtime")
    parser.add_argument("--code", type=str, help="股票代码（kline 模式）")
    parser.add_argument("--count", type=int, default=250)
    parser.add_argument("--no-st", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--cache-dir", type=str, default=None)
    args = parser.parse_args()

    fetcher = DataFetcher(cache_dir=args.cache_dir)
    if args.mode == "realtime":
        stocks = fetcher.fetch_all_stocks()
        stocks = fetcher.filter_basic(stocks, exclude_st=args.no_st)
        if args.json:
            print(json.dumps(stocks[:5], ensure_ascii=False, indent=2))
        else:
            print(f"获取到 {len(stocks)} 只股票")
            for s in stocks[:10]:
                print(f"  {s['code']} {s['name']:>8s} "
                      f"价格:{s['price']:>8} 涨跌幅:{s['change_pct']:>6}% "
                      f"换手率:{s['turnover_rate']:>6}% PE:{s['pe_ratio']:>8}")
    elif args.mode == "kline":
        if not args.code:
            print("请指定 --code")
        else:
            klines = fetcher.fetch_kline(args.code, count=args.count)
            print(f"获取到 {len(klines)} 条 K 线数据")
            if klines:
                print(f"  最新: {klines[-1]['date']} 收盘:{klines[-1]['close']}")
