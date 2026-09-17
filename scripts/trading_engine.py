#!/usr/bin/env python3
"""
个人量化模拟交易引擎
- SQLite 本地持久化存储
- 信号生成：基于因子评分的买入/卖出信号
- 持仓管理：仓位控制、止损止盈
- 交易执行：模拟成交（含佣金/印花税）
- 每日调度：定时选股 → 信号 → 交易 → 快照
"""

import json
import math
import os
import sys
import sqlite3
from datetime import datetime, date
from typing import List, Dict, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data_fetcher import DataFetcher
from factor_calculator import FactorCalculator

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "quant_trading.db")


class TradingEngine:
    INITIAL_CAPITAL = 100_000.0
    MAX_POSITIONS = 5
    LOT_SIZE = 100
    BUY_THRESHOLD = 1.0
    SELL_THRESHOLD = 0.3
    TOP_CANDIDATES = 30
    STOP_LOSS_PCT = -5.0
    TAKE_PROFIT_PCT = 15.0
    COMMISSION_RATE = 0.00025
    MIN_COMMISSION = 5.0
    STAMP_TAX_RATE = 0.0005
    USE_NEUTRALIZE = True

    def __init__(self, cache_dir=None):
        self.fetcher = DataFetcher(cache_dir=cache_dir)
        self.calc = FactorCalculator()
        self.today = date.today().isoformat()
        self.db = sqlite3.connect(DB_PATH)
        self.db.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self):
        cur = self.db.cursor()
        cur.executescript("""
            CREATE TABLE IF NOT EXISTS account (
                id INTEGER PRIMARY KEY DEFAULT 1,
                initial_capital REAL NOT NULL DEFAULT 100000.00,
                available_cash REAL NOT NULL DEFAULT 100000.00,
                frozen_amount REAL NOT NULL DEFAULT 0.00,
                total_assets REAL NOT NULL DEFAULT 100000.00,
                market_value REAL NOT NULL DEFAULT 0.00,
                total_profit REAL NOT NULL DEFAULT 0.00,
                total_return_pct REAL NOT NULL DEFAULT 0.0000,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL,
                name TEXT NOT NULL,
                shares INTEGER NOT NULL DEFAULT 0,
                avg_cost REAL NOT NULL,
                current_price REAL NOT NULL DEFAULT 0,
                market_value REAL NOT NULL DEFAULT 0,
                profit_loss REAL NOT NULL DEFAULT 0,
                profit_pct REAL NOT NULL DEFAULT 0,
                buy_date TEXT,
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(code)
            );
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL,
                name TEXT NOT NULL,
                direction TEXT NOT NULL,
                price REAL NOT NULL,
                shares INTEGER NOT NULL,
                amount REAL NOT NULL,
                commission REAL NOT NULL DEFAULT 5.00,
                stamp_tax REAL NOT NULL DEFAULT 0,
                total_cost REAL NOT NULL,
                signal_score REAL,
                factor_detail TEXT,
                reason TEXT,
                trade_time TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS daily_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_date TEXT NOT NULL,
                total_assets REAL NOT NULL,
                available_cash REAL NOT NULL,
                market_value REAL NOT NULL,
                position_count INTEGER NOT NULL DEFAULT 0,
                daily_pnl REAL NOT NULL DEFAULT 0,
                daily_return_pct REAL NOT NULL DEFAULT 0,
                cumulative_return_pct REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(trade_date)
            );
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_date TEXT NOT NULL,
                code TEXT NOT NULL,
                name TEXT NOT NULL,
                signal_type TEXT NOT NULL,
                score REAL NOT NULL,
                factor_value REAL,
                factor_momentum REAL,
                factor_quality REAL,
                factor_low_vol REAL,
                factor_size REAL,
                factor_turnover REAL,
                price REAL,
                executed INTEGER NOT NULL DEFAULT 0,
                executed_at TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
        """)
        cur.execute("SELECT COUNT(*) FROM account")
        if cur.fetchone()[0] == 0:
            cur.execute(
                "INSERT INTO account (initial_capital, available_cash, total_assets) VALUES (?, ?, ?)",
                (self.INITIAL_CAPITAL, self.INITIAL_CAPITAL, self.INITIAL_CAPITAL)
            )
        self.db.commit()

    def close(self):
        self.db.close()

    def get_account(self) -> Dict:
        cur = self.db.cursor()
        cur.execute("SELECT * FROM account WHERE id=1")
        row = cur.fetchone()
        return dict(row) if row else {}

    def update_account(self, available_cash, market_value):
        total_assets = available_cash + market_value
        total_profit = total_assets - self.INITIAL_CAPITAL
        total_return = (total_profit / self.INITIAL_CAPITAL) * 100
        self.db.execute(
            "UPDATE account SET available_cash=?, market_value=?, total_assets=?, "
            "total_profit=?, total_return_pct=?, updated_at=datetime('now') WHERE id=1",
            (available_cash, market_value, total_assets, total_profit, total_return)
        )
        self.db.commit()

    def get_positions(self) -> List[Dict]:
        cur = self.db.cursor()
        cur.execute("SELECT * FROM positions WHERE shares > 0")
        return [dict(r) for r in cur.fetchall()]

    def update_position_price(self, code, price):
        cur = self.db.cursor()
        cur.execute("SELECT shares, avg_cost FROM positions WHERE code=?", (code,))
        row = cur.fetchone()
        if not row:
            return
        shares, avg_cost = row[0], row[1]
        mv = shares * price
        pnl = mv - shares * avg_cost
        pct = ((price - avg_cost) / avg_cost) * 100 if avg_cost > 0 else 0
        self.db.execute(
            "UPDATE positions SET current_price=?, market_value=?, profit_loss=?, "
            "profit_pct=?, updated_at=datetime('now') WHERE code=?",
            (price, mv, pnl, pct, code)
        )
        self.db.commit()

    def add_or_update_position(self, code, name, shares, price):
        cur = self.db.cursor()
        cur.execute("SELECT shares, avg_cost FROM positions WHERE code=?", (code,))
        existing = cur.fetchone()
        if existing:
            old_shares, old_cost = existing[0], existing[1]
            new_shares = old_shares + shares
            new_cost = (old_cost * old_shares + price * shares) / new_shares
            mv = new_shares * price
            pnl = mv - new_shares * new_cost
            pct = ((price - new_cost) / new_cost) * 100 if new_cost > 0 else 0
            self.db.execute(
                "UPDATE positions SET shares=?, avg_cost=?, current_price=?, "
                "market_value=?, profit_loss=?, profit_pct=?, updated_at=datetime('now') WHERE code=?",
                (new_shares, new_cost, price, mv, pnl, pct, code)
            )
        else:
            mv = shares * price
            self.db.execute(
                "INSERT INTO positions (code, name, shares, avg_cost, current_price, market_value, buy_date) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (code, name, shares, price, price, mv, self.today)
            )
        self.db.commit()

    def remove_position(self, code, sell_shares):
        cur = self.db.cursor()
        cur.execute("SELECT shares FROM positions WHERE code=?", (code,))
        row = cur.fetchone()
        if not row:
            return 0
        remaining = row[0] - sell_shares
        if remaining <= 0:
            self.db.execute("DELETE FROM positions WHERE code=?", (code,))
        else:
            self.db.execute(
                "UPDATE positions SET shares=?, market_value=?*current_price, updated_at=datetime('now') WHERE code=?",
                (remaining, remaining, code)
            )
        self.db.commit()
        return max(remaining, 0)

    def execute_buy(self, code, name, price, available_cash, score, factors=None, reason=""):
        max_amount = available_cash / max(1, self.MAX_POSITIONS - len(self.get_positions()) + 1)
        max_shares = int(max_amount / price / self.LOT_SIZE) * self.LOT_SIZE
        if max_shares < self.LOT_SIZE:
            print(f"  [\u8df3\u8fc7] {code} {name} \u8d44\u91d1\u4e0d\u8db3")
            return False
        amount = max_shares * price
        commission = max(amount * self.COMMISSION_RATE, self.MIN_COMMISSION)
        total_cost = amount + commission
        if total_cost > available_cash:
            max_shares -= self.LOT_SIZE
            if max_shares < self.LOT_SIZE:
                return False
            amount = max_shares * price
            commission = max(amount * self.COMMISSION_RATE, self.MIN_COMMISSION)
            total_cost = amount + commission
        factor_json = json.dumps(factors, ensure_ascii=False) if factors else "{}"
        self.db.execute(
            "INSERT INTO trades (code, name, direction, price, shares, amount, commission, stamp_tax, total_cost, signal_score, factor_detail, reason) "
            "VALUES (?, ?, 'BUY', ?, ?, ?, ?, 0, ?, ?, ?, ?)",
            (code, name, price, max_shares, amount, commission, total_cost, score, factor_json, reason)
        )
        self.add_or_update_position(code, name, max_shares, price)
        new_cash = available_cash - total_cost
        mv = sum(p["market_value"] for p in self.get_positions())
        self.update_account(new_cash, mv)
        print(f"  [\u4e70\u5165] {code} {name} {max_shares}\u80a1 @ {price:.2f} \u91d1\u989d={amount:.0f} \u4f63\u91d1={commission:.1f} \u8bc4\u5206={score:.2f}")
        return True

    def execute_sell(self, code, name, price, reason=""):
        cur = self.db.cursor()
        cur.execute("SELECT shares, avg_cost FROM positions WHERE code=?", (code,))
        row = cur.fetchone()
        if not row:
            return False
        shares, avg_cost = row[0], row[1]
        amount = shares * price
        commission = max(amount * self.COMMISSION_RATE, self.MIN_COMMISSION)
        stamp_tax = amount * self.STAMP_TAX_RATE
        total_cost = commission + stamp_tax
        net_amount = amount - total_cost
        pnl = net_amount - shares * avg_cost
        self.db.execute(
            "INSERT INTO trades (code, name, direction, price, shares, amount, commission, stamp_tax, total_cost, reason) "
            "VALUES (?, ?, 'SELL', ?, ?, ?, ?, ?, ?, ?)",
            (code, name, price, shares, amount, commission, stamp_tax, total_cost, reason)
        )
        self.remove_position(code, shares)
        account = self.get_account()
        new_cash = account["available_cash"] + net_amount
        mv = sum(p["market_value"] for p in self.get_positions())
        self.update_account(new_cash, mv)
        pnl_sign = f"+{pnl:.0f}" if pnl >= 0 else f"{pnl:.0f}"
        print(f"  [\u5356\u51fa] {code} {name} {shares}\u80a1 @ {price:.2f} \u76c8\u4e8f={pnl_sign}\u5143 \u539f\u56e0={reason}")
        return True

    def generate_sell_signals(self, stocks, scores_map):
        positions = self.get_positions()
        if not positions:
            return []
        stock_map = {s["code"]: s for s in stocks}
        sells = []
        for pos in positions:
            code = pos["code"]
            stock = stock_map.get(code)
            if not stock:
                continue
            price = stock.get("price", 0)
            profit_pct = pos["profit_pct"]
            score = scores_map.get(code, 0)
            if profit_pct <= self.STOP_LOSS_PCT:
                sells.append({"code": code, "name": pos["name"], "price": price,
                              "reason": f"\u6b62\u635f({profit_pct:.1f}%\u2264{self.STOP_LOSS_PCT}%)"})
            elif profit_pct >= self.TAKE_PROFIT_PCT:
                sells.append({"code": code, "name": pos["name"], "price": price,
                              "reason": f"\u6b62\u76c8({profit_pct:.1f}%\u2265{self.TAKE_PROFIT_PCT}%)"})
            elif score < self.SELL_THRESHOLD:
                sells.append({"code": code, "name": pos["name"], "price": price,
                              "reason": f"\u8bc4\u5206\u8870\u51cf({score:.2f}<{self.SELL_THRESHOLD})"})
        return sells

    def generate_buy_signals(self, scored_stocks, held_codes):
        buys = []
        for s in scored_stocks:
            if s["code"] in held_codes:
                continue
            if s.get("score", 0) >= self.BUY_THRESHOLD:
                buys.append({
                    "code": s["code"], "name": s["name"], "price": s["price"],
                    "score": s["score"],
                    "factors": {k: v for k, v in s.items() if k.startswith("factor_")},
                })
        return buys

    def run_daily(self):
        print(f"\n{'='*60}")
        print(f"  \u91cf\u5316\u6a21\u62df\u4ea4\u6613 - \u6bcf\u65e5\u8fd0\u884c  {self.today}")
        print(f"{'='*60}")
        print("\n[1/7] \u83b7\u53d6\u5168\u5e02\u573a\u884c\u60c5...")
        stocks = self.fetcher.fetch_all_stocks()
        print(f"  \u83b7\u53d6\u5230 {len(stocks)} \u53ea\u80a1\u7968")
        print("[2/7] \u57fa\u7840\u8fc7\u6ee4...")
        stocks = self.fetcher.filter_basic(stocks, True, True, True)
        self.fetcher.calc_amplitude(stocks)
        risk = {"min_amount": 2000_0000, "min_mv": 30_0000_0000, "max_pe": 300, "min_pe": -1000}
        filtered = []
        for s in stocks:
            if s.get("amount", 0) < risk["min_amount"]: continue
            if s.get("total_mv", 0) < risk["min_mv"]: continue
            pe = s.get("pe_ratio", 0)
            if pe == 0 or pe > risk["max_pe"] or pe < risk["min_pe"]: continue
            filtered.append(s)
        print(f"  \u8fc7\u6ee4\u540e: {len(filtered)} \u53ea")
        print("[3/7] \u66f4\u65b0\u6301\u4ed3\u4ef7\u683c...")
        positions = self.get_positions()
        stock_map = {s["code"]: s for s in filtered}
        for pos in positions:
            stock = stock_map.get(pos["code"])
            if stock:
                self.update_position_price(pos["code"], stock["price"])
        positions = self.get_positions()
        account = self.get_account()
        print(f"  \u6301\u4ed3 {len(positions)} \u53ea, \u53ef\u7528\u8d44\u91d1 {account['available_cash']:.0f}\u5143")
        print("[4/7] \u8ba1\u7b97\u56e0\u5b50\u4e0e\u8bc4\u5206...")
        factors = self.calc.compute_all_factors(filtered)
        if self.USE_NEUTRALIZE:
            factors = self.calc.neutralize_all(factors, filtered, market_cap=True)
        scores = self.calc.compute_composite_score(factors)
        scored_stocks = []
        scores_map = {}
        for i, s in enumerate(filtered):
            s["score"] = round(scores[i], 4)
            scores_map[s["code"]] = scores[i]
            for fname, fvals in factors.items():
                s[f"factor_{fname}"] = round(fvals[i], 4)
            scored_stocks.append(s)
        scored_stocks.sort(key=lambda x: x["score"], reverse=True)
        print("[5/7] \u68c0\u67e5\u5356\u51fa\u4fe1\u53f7...")
        sell_signals = self.generate_sell_signals(filtered, scores_map)
        if not sell_signals:
            print("  \u65e0\u5356\u51fa\u4fe1\u53f7")
        for sig in sell_signals:
            self.execute_sell(sig["code"], sig["name"], sig["price"], sig["reason"])
        print("[6/7] \u68c0\u67e5\u4e70\u5165\u4fe1\u53f7...")
        account = self.get_account()
        positions = self.get_positions()
        held_codes = {p["code"] for p in positions}
        available_slots = self.MAX_POSITIONS - len(positions)
        if available_slots <= 0:
            print(f"  \u5df2\u6ee1\u4ed3\uff08{len(positions)}/{self.MAX_POSITIONS}\uff09\uff0c\u8df3\u8fc7\u4e70\u5165")
        elif account["available_cash"] < 1000:
            print(f"  \u8d44\u91d1\u4e0d\u8db3\uff0c\u8df3\u8fc7\u4e70\u5165")
        else:
            buy_signals = self.generate_buy_signals(scored_stocks[:self.TOP_CANDIDATES], held_codes)
            for sig in buy_signals[:available_slots]:
                self.db.execute(
                    "INSERT INTO signals (signal_date, code, name, signal_type, score, price, "
                    "factor_value, factor_momentum, factor_quality, factor_low_vol, factor_size, factor_turnover, executed) "
                    "VALUES (?, ?, ?, 'BUY', ?, ?, ?, ?, ?, ?, ?, ?, 0)",
                    (self.today, sig["code"], sig["name"], sig["score"], sig["price"],
                     sig["factors"].get("factor_value"), sig["factors"].get("factor_momentum"),
                     sig["factors"].get("factor_quality"), sig["factors"].get("factor_low_vol"),
                     sig["factors"].get("factor_size"), sig["factors"].get("factor_turnover"))
                )
            self.db.commit()
            if not buy_signals:
                print("  \u65e0\u4e70\u5165\u4fe1\u53f7")
            else:
                print(f"  \u53d1\u73b0 {len(buy_signals)} \u4e2a\u4e70\u5165\u4fe1\u53f7\uff0c\u53ef\u4e70 {available_slots} \u53ea")
                for sig in buy_signals[:available_slots]:
                    account = self.get_account()
                    if self.execute_buy(sig["code"], sig["name"], sig["price"], account["available_cash"], sig["score"], sig.get("factors"), reason=f"\u8bc4\u5206{sig['score']:.2f}>\u9608\u503c{self.BUY_THRESHOLD}"):
                        held_codes.add(sig["code"])
                        self.db.execute("UPDATE signals SET executed=1, executed_at=datetime('now') WHERE signal_date=? AND code=?", (self.today, sig["code"]))
                        self.db.commit()
        print("[7/7] \u8bb0\u5f55\u6bcf\u65e5\u5feb\u7167...")
        account = self.get_account()
        positions = self.get_positions()
        total_assets = account["total_assets"]
        cum_return = ((total_assets - self.INITIAL_CAPITAL) / self.INITIAL_CAPITAL) * 100
        cur = self.db.cursor()
        cur.execute("SELECT total_assets FROM daily_snapshots WHERE trade_date < ? ORDER BY trade_date DESC LIMIT 1", (self.today,))
        row = cur.fetchone()
        prev_assets = row[0] if row else self.INITIAL_CAPITAL
        daily_pnl = total_assets - prev_assets
        daily_return = (daily_pnl / prev_assets) * 100 if prev_assets > 0 else 0
        self.db.execute(
            "INSERT INTO daily_snapshots (trade_date, total_assets, available_cash, market_value, position_count, daily_pnl, daily_return_pct, cumulative_return_pct) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(trade_date) DO UPDATE SET total_assets=?, available_cash=?, market_value=?, position_count=?, daily_pnl=?, daily_return_pct=?, cumulative_return_pct=?",
            (self.today, total_assets, account["available_cash"], account["market_value"], len(positions), daily_pnl, daily_return, cum_return,
             total_assets, account["available_cash"], account["market_value"], len(positions), daily_pnl, daily_return, cum_return)
        )
        self.db.commit()
        self._print_daily_report(account, positions, daily_pnl, daily_return, cum_return)
        return account

    def _print_daily_report(self, account, positions, daily_pnl, daily_return, cum_return):
        print(f"\n{'='*60}")
        print(f"  \u6bcf\u65e5\u4ea4\u6613\u62a5\u544a  {self.today}")
        print(f"{'='*60}")
        print(f"  \u521d\u59cb\u672c\u91d1:   {account['initial_capital']:>12,.2f} \u5143")
        print(f"  \u603b\u8d44\u4ea7:     {account['total_assets']:>12,.2f} \u5143")
        print(f"  \u53ef\u7528\u8d44\u91d1:   {account['available_cash']:>12,.2f} \u5143")
        print(f"  \u6301\u4ed3\u5e02\u503c:   {account['market_value']:>12,.2f} \u5143")
        sign = "+" if account['total_profit'] >= 0 else ""
        print(f"  \u603b\u76c8\u4e8f:     {sign}{account['total_profit']:>11,.2f} \u5143")
        print(f"  \u603b\u6536\u76ca\u7387:   {sign}{account['total_return_pct']:.4f}%")
        print(f"  \u5f53\u65e5\u76c8\u4e8f:   {'+' if daily_pnl >= 0 else ''}{daily_pnl:>11,.2f} \u5143")
        print(f"  \u5f53\u65e5\u6536\u76ca\u7387: {'+' if daily_return >= 0 else ''}{daily_return:.4f}%")
        print(f"  \u7d2f\u8ba1\u6536\u76ca\u7387: {'+' if cum_return >= 0 else ''}{cum_return:.4f}%")
        if positions:
            print(f"\n  \u5f53\u524d\u6301\u4ed3 ({len(positions)}/{self.MAX_POSITIONS}):")
            print(f"  {'\u4ee3\u7801':>8s} {'\u540d\u79f0':>8s} {'\u80a1\u6570':>6s} {'\u6210\u672c':>8s} {'\u73b0\u4ef7':>8s} {'\u76c8\u4e8f%':>8s} {'\u4e70\u5165\u65e5':>12s}")
            print(f"  {'-'*70}")
            for p in positions:
                print(f"  {p['code']:>8s} {p['name']:>8s} {p['shares']:>6d} {p['avg_cost']:>8.2f} {p['current_price']:>8.2f} {'+' if p['profit_pct'] >= 0 else ''}{p['profit_pct']:>7.2f}% {p['buy_date']:>12s}")
        else:
            print(f"\n  \u5f53\u524d\u7a7a\u4ed3")
        cur = self.db.cursor()
        cur.execute("SELECT code, name, direction, price, shares, amount, reason FROM trades WHERE DATE(trade_time)=? ORDER BY trade_time", (self.today,))
        rows = cur.fetchall()
        if rows:
            print(f"\n  \u4eca\u65e5\u4ea4\u6613 ({len(rows)} \u7b14):")
            for r in rows:
                d = "\u4e70\u5165" if r["direction"] == "BUY" else "\u5356\u51fa"
                print(f"  {d} {r['code']} {r['name']} {r['shares']}\u80a1 @ {r['price']:.2f} \u91d1\u989d={r['amount']:.0f} {r['reason'] or ''}")
        print(f"{'='*60}\n")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="\u91cf\u5316\u6a21\u62df\u4ea4\u6613\u5f15\u64ce")
    parser.add_argument("--run", action="store_true", help="\u6267\u884c\u6bcf\u65e5\u9009\u80a1\u4ea4\u6613")
    parser.add_argument("--report", action="store_true", help="\u67e5\u770b\u5f53\u524d\u8d26\u6237\u62a5\u544a")
    parser.add_argument("--history", action="store_true", help="\u67e5\u770b\u5386\u53f2\u6536\u76ca\u66f2\u7ebf")
    parser.add_argument("--trades", action="store_true", help="\u67e5\u770b\u4ea4\u6613\u8bb0\u5f55")
    parser.add_argument("--signals", action="store_true", help="\u67e5\u770b\u4fe1\u53f7\u8bb0\u5f55")
    args = parser.parse_args()
    engine = TradingEngine()
    if args.run:
        engine.run_daily()
    elif args.report:
        account = engine.get_account()
        positions = engine.get_positions()
        print(f"\n  \u8d26\u6237\u72b6\u6001:")
        print(f"  \u521d\u59cb\u672c\u91d1: {account.get('initial_capital', 0):>12,.2f} \u5143")
        print(f"  \u603b\u8d44\u4ea7:   {account.get('total_assets', 0):>12,.2f} \u5143")
        print(f"  \u53ef\u7528\u8d44\u91d1: {account.get('available_cash', 0):>12,.2f} \u5143")
        print(f"  \u6301\u4ed3\u5e02\u503c: {account.get('market_value', 0):>12,.2f} \u5143")
        print(f"  \u603b\u76c8\u4e8f:   {account.get('total_profit', 0):>12,.2f} \u5143")
        print(f"  \u603b\u6536\u76ca\u7387: {account.get('total_return_pct', 0):>11.4f}%")
        if positions:
            print(f"\n  \u6301\u4ed3 ({len(positions)}/{engine.MAX_POSITIONS}):")
            for p in positions:
                print(f"  {p['code']} {p['name']} {p['shares']}\u80a1 \u6210\u672c{p['avg_cost']:.2f} \u73b0\u4ef7{p['current_price']:.2f} \u76c8\u4e8f{p['profit_pct']:.2f}%")
    elif args.history:
        cur = engine.db.cursor()
        cur.execute("SELECT trade_date, total_assets, daily_return_pct, cumulative_return_pct FROM daily_snapshots ORDER BY trade_date")
        rows = cur.fetchall()
        if rows:
            print(f"\n  {'\u65e5\u671f':>12s} {'\u603b\u8d44\u4ea7':>12s} {'\u65e5\u6536\u76ca%':>10s} {'\u7d2f\u8ba1\u6536\u76ca%':>10s}")
            print("  " + "-" * 50)
            for r in rows:
                print(f"  {r[0]:>12s} {r[1]:>12,.2f} {r[2]:>+10.4f} {r[3]:>+10.4f}")
        else:
            print("\u6682\u65e0\u5386\u53f2\u6570\u636e")
    elif args.trades:
        cur = engine.db.cursor()
        cur.execute("SELECT trade_time, code, name, direction, price, shares, amount, reason FROM trades ORDER BY trade_time DESC LIMIT 50")
        rows = cur.fetchall()
        if rows:
            print(f"\n  \u6700\u8fd1\u4ea4\u6613\u8bb0\u5f55:")
            for r in rows:
                d = "\u4e70" if r["direction"] == "BUY" else "\u5356"
                print(f"  {r['trade_time']} {d} {r['code']} {r['name']} {r['shares']}\u80a1 @ {r['price']:.2f} = {r['amount']:.0f}\u5143 {r['reason'] or ''}")
        else:
            print("\u6682\u65e0\u4ea4\u6613\u8bb0\u5f55")
    elif args.signals:
        cur = engine.db.cursor()
        cur.execute("SELECT signal_date, code, name, signal_type, score, price, executed FROM signals ORDER BY created_at DESC LIMIT 30")
        rows = cur.fetchall()
        if rows:
            print(f"\n  \u6700\u8fd1\u4fe1\u53f7:")
            for r in rows:
                ex = "\u5df2\u6267\u884c" if r["executed"] else "\u672a\u6267\u884c"
                print(f"  {r['signal_date']} {r['signal_type']} {r['code']} {r['name']} \u8bc4\u5206={r['score']:.2f} \u4ef7\u683c={r['price']:.2f} [{ex}]")
        else:
            print("\u6682\u65e0\u4fe1\u53f7\u8bb0\u5f55")
    else:
        parser.print_help()
    engine.close()
