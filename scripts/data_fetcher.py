#!/usr/bin/env python3
"""
数据获取模块 - 从新浪财经/东方财富获取 A 股行情与基本面数据
新浪财经为主要数据源（稳定），东方财富为备用
使用 curl 作为传输层，纯标准库实现，无需安装第三方依赖
"""

import json
import subprocess
import os
import time
from datetime import datetime
from typing import List, Dict, Optional
from urllib.parse import urlencode


class DataFetcher:
    """A 股数据获取器"""

    # 新浪财经 API（主要数据源）
    SINA_URL = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
    # 东方财富 API（备用）
    EM_URL = "https://push2.eastmoney.com/api/qt/clist/get"
    EM_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"

    UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

    def __init__(self, cache_dir: Optional[str] = None, cache_ttl: int = 3600):
        self.cache_dir = cache_dir
        self.cache_ttl = cache_ttl
        if cache_dir and not os.path.exists(cache_dir):
            os.makedirs(cache_dir)

    def _curl_get(self, url: str, referer: str = "", timeout: int = 15,
                  retries: int = 2) -> str:
        """通过 curl.exe 发起 GET 请求，返回响应文本"""
        cmd = ["curl.exe", "-s", "--max-time", str(timeout),
               "-H", f"User-Agent: {self.UA}"]
        if referer:
            cmd += ["-H", f"Referer: {referer}"]
        cmd.append(url)

        last_err = None
        for attempt in range(retries + 1):
            try:
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=timeout + 5
                )
                if result.returncode == 0 and result.stdout:
                    return result.stdout
                last_err = f"rc={result.returncode}"
            except subprocess.TimeoutExpired:
                last_err = "timeout"
            except Exception as e:
                last_err = str(e)
            if attempt < retries:
                time.sleep(0.5 * (attempt + 1))

        print(f"[WARN] curl 请求失败 ({retries + 1} 次): {last_err}")
        return ""

    def _request_json(self, url: str, params: dict, referer: str = "") -> dict:
        """构建 URL + 参数，发起请求并返回 JSON"""
        query = urlencode(params)
        full_url = f"{url}?{query}"
        raw = self._curl_get(full_url, referer=referer)
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            print(f"[WARN] JSON 解析失败, raw[:80]={raw[:80]}")
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
        """获取全市场 A 股实时行情（新浪财经）"""
        cached = self._read_cache("all_stocks_realtime")
        if cached:
            print(f"  [缓存] 使用缓存数据 ({cached.get('timestamp', '?')})")
            return cached.get("data", [])

        all_data = []
        page = 1
        page_size = 80

        while True:
            params = {
                "page": page, "num": page_size, "sort": "changepercent",
                "asc": 0, "node": "hs_a", "symbol": "", "_s_r_a": "init",
            }
            data = self._request_json(
                self.SINA_URL, params,
                referer="https://finance.sina.com.cn/"
            )
            if not data or not isinstance(data, list):
                break
            for item in data:
                all_data.append(self._parse_sina_item(item))
            if len(data) < page_size:
                break
            page += 1
            if page % 10 == 0:
                time.sleep(0.3)

        result = {"data": all_data, "timestamp": datetime.now().isoformat()}
        self._write_cache("all_stocks_realtime", result)
        return all_data

    @staticmethod
    def _parse_sina_item(item: dict) -> Dict:
        """解析新浪财经数据项为统一格式"""
        def safe_float(val, default=0.0):
            try:
                v = float(val)
                return v
            except (ValueError, TypeError):
                return default

        code = str(item.get("code", ""))
        name = str(item.get("name", ""))

        return {
            "code": code, "name": name,
            "price": safe_float(item.get("trade")),
            "change_pct": safe_float(item.get("changepercent")),
            "volume": safe_float(item.get("volume")),
            "amount": safe_float(item.get("amount")),
            "amplitude": 0.0,
            "turnover_rate": safe_float(item.get("turnoverratio")),
            "pe_ratio": safe_float(item.get("per")),
            "volume_ratio": 0.0,
            "pb_ratio": safe_float(item.get("pb")),
            "high": safe_float(item.get("high")),
            "low": safe_float(item.get("low")),
            "open": safe_float(item.get("open")),
            "prev_close": safe_float(item.get("settlement")),
            "total_mv": safe_float(item.get("mktcap")) * 10000,
            "circ_mv": safe_float(item.get("nmc")) * 10000,
            "change_60d": 0.0,
            "change_ytd": 0.0,
        }

    def fetch_kline(self, code: str, market: str = "auto",
                    period: str = "daily", count: int = 250) -> List[Dict]:
        """获取个股 K 线数据（东方财富）"""
        if market == "auto":
            market = "1" if code.startswith("6") else "0"
        period_map = {"daily": "101", "weekly": "102", "monthly": "103"}
        klt = period_map.get(period, "101")

        cache_key = f"kline_{code}_{period}_{count}"
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
        data = self._request_json(
            self.EM_KLINE_URL, params,
            referer="https://quote.eastmoney.com/"
        )
        if not data or "data" not in data or data["data"] is None:
            return []

        result_data = []
        for line in data["data"].get("klines", []):
            parts = line.split(",")
            if len(parts) >= 7:
                result_data.append({
                    "date": parts[0],
                    "open": float(parts[1]), "close": float(parts[2]),
                    "high": float(parts[3]), "low": float(parts[4]),
                    "volume": float(parts[5]), "amount": float(parts[6]),
                })

        result = {"data": result_data, "timestamp": datetime.now().isoformat()}
        self._write_cache(cache_key, result)
        return result_data

    @staticmethod
    def calc_amplitude(stocks: List[Dict]) -> List[Dict]:
        """计算振幅 = (high - low) / prev_close * 100"""
        for s in stocks:
            high = s.get("high", 0)
            low = s.get("low", 0)
            prev_close = s.get("prev_close", 0)
            if prev_close > 0 and high > 0 and low > 0:
                s["amplitude"] = round((high - low) / prev_close * 100, 2)
        return stocks

    @staticmethod
    def is_st(name: str) -> bool:
        return "ST" in name.upper()

    @staticmethod
    def is_kcb(code: str) -> bool:
        return code.startswith("688")

    @staticmethod
    def is_bse(code: str) -> bool:
        return code.startswith("8") or code.startswith("4")

    def filter_basic(self, stocks: List[Dict],
                     exclude_st: bool = True,
                     exclude_kcb: bool = True,
                     exclude_bse: bool = True) -> List[Dict]:
        """基础过滤：排除 ST、科创板、北交所、无效数据"""
        filtered = []
        for s in stocks:
            name = s.get("name", "")
            code = s.get("code", "")
            if exclude_st and self.is_st(name):
                continue
            if exclude_kcb and self.is_kcb(code):
                continue
            if exclude_bse and self.is_bse(code):
                continue
            price = s.get("price", 0)
            mv = s.get("total_mv", 0)
            if not isinstance(price, (int, float)) or price <= 0:
                continue
            if not isinstance(mv, (int, float)) or mv <= 0:
                continue
            filtered.append(s)
        return filtered

    @staticmethod
    def data_quality_report(stocks: List[Dict]) -> Dict:
        """生成数据质量报告"""
        if not stocks:
            return {"total": 0, "fields": {}}
        n = len(stocks)
        fields = ["price", "pe_ratio", "pb_ratio", "turnover_rate",
                  "amount", "total_mv", "amplitude"]
        report = {"total": n, "fields": {}}
        for field in fields:
            missing = sum(1 for s in stocks
                         if not s.get(field) or s.get(field) == 0
                         or s.get(field) == "-")
            report["fields"][field] = {
                "missing": missing,
                "missing_pct": round(missing / n * 100, 1),
            }
        return report


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="A 股数据获取工具")
    parser.add_argument("--mode", choices=["realtime", "kline"], default="realtime")
    parser.add_argument("--code", type=str, help="股票代码（kline 模式）")
    parser.add_argument("--count", type=int, default=250)
    parser.add_argument("--no-st", action="store_true", default=True)
    parser.add_argument("--no-kcb", action="store_true", default=True)
    parser.add_argument("--no-bse", action="store_true", default=True)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--cache-dir", type=str, default=None)
    parser.add_argument("--quality", action="store_true", help="数据质量报告")
    args = parser.parse_args()

    fetcher = DataFetcher(cache_dir=args.cache_dir)

    if args.mode == "realtime":
        print("正在获取全市场 A 股实时行情（新浪财经）...")
        stocks = fetcher.fetch_all_stocks()
        print(f"获取到 {len(stocks)} 只股票")
        stocks = fetcher.calc_amplitude(stocks)
        stocks = fetcher.filter_basic(
            stocks, exclude_st=args.no_st,
            exclude_kcb=args.no_kcb, exclude_bse=args.no_bse
        )
        print(f"基础过滤后: {len(stocks)} 只")
        if args.quality:
            report = fetcher.data_quality_report(stocks)
            print(f"\n数据质量报告 (共 {report['total']} 只):")
            for field, info in report["fields"].items():
                print(f"  {field:>15s}: 缺失 {info['missing']:>5d} ({info['missing_pct']:>5.1f}%)")
        if args.json:
            print(json.dumps(stocks[:5], ensure_ascii=False, indent=2))
        else:
            print(f"\n{'代码':>8s} {'名称':>8s} {'价格':>8s} {'涨跌幅':>8s} "
                  f"{'换手率':>7s} {'PE':>8s} {'PB':>7s} {'成交额(亿)':>10s}")
            print("-" * 80)
            for s in stocks[:15]:
                amt = s.get("amount", 0)
                amt_yi = amt / 1e8 if isinstance(amt, (int, float)) else 0
                print(f"{s['code']:>8s} {s['name']:>8s} {s['price']:>8.2f} "
                      f"{s['change_pct']:>7.2f}% {s['turnover_rate']:>6.2f}% "
                      f"{s['pe_ratio']:>8.1f} {s['pb_ratio']:>7.2f} "
                      f"{amt_yi:>10.2f}")
    elif args.mode == "kline":
        if not args.code:
            print("请指定 --code")
        else:
            klines = fetcher.fetch_kline(args.code, count=args.count)
            print(f"获取到 {len(klines)} 条 K 线数据")
            if klines:
                print(f"  最新: {klines[-1]['date']} 收盘:{klines[-1]['close']}")
                print(f"  最早: {klines[0]['date']} 收盘:{klines[0]['close']}")
