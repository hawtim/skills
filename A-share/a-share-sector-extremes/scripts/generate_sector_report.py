#!/usr/bin/env python3
"""Configurable A-share sector breadth / human-extremes scanner."""
from __future__ import annotations

import argparse
import json
import math
import statistics
import subprocess
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
TZ = ZoneInfo("Asia/Shanghai")
PLATE_SCRIPT = Path("/Users/icemelon/.agents/skills/futuapi/scripts/quote/get_plate_stock.py")
SNAPSHOT_SCRIPT = Path("/Users/icemelon/.agents/skills/futuapi/scripts/quote/get_snapshot.py")
KLINE_SCRIPT = Path("/Users/icemelon/.agents/skills/futuapi/scripts/quote/get_kline.py")
TENCENT = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,300,qfq"
WINDOWS = (5, 10, 20, 50, 200)
EXTREME = {20: (15, 85), 50: (25, 80), 200: (15, 85)}
PLATE_MIN_INTERVAL = 3.15
_plate_lock, _plate_last = threading.Lock(), 0.0
PRICE_MIN_INTERVAL = 0.18
_price_lock, _price_last = threading.Lock(), 0.0
FUTU_KLINE_MIN_INTERVAL = 0.62
_futu_lock, _futu_last = threading.Lock(), 0.0


class DataUnavailable(RuntimeError):
    pass


def load_boards() -> list[dict]:
    return json.loads((ROOT / "references/board-definitions.json").read_text(encoding="utf-8"))["boards"]


def last_json(text: str) -> dict:
    for line in reversed(text.splitlines()):
        try:
            value = json.loads(line)
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            pass
    raise DataUnavailable("数据源未返回 JSON")


def plate_members(code: str) -> list[dict]:
    global _plate_last
    with _plate_lock:
        wait = PLATE_MIN_INTERVAL - (time.monotonic() - _plate_last)
        if wait > 0:
            time.sleep(wait)
        _plate_last = time.monotonic()
    result = None
    for attempt in range(4):
        result = subprocess.run([sys.executable, str(PLATE_SCRIPT), code, "--limit", "1000", "--json"], text=True, capture_output=True, timeout=50)
        if not result.returncode:
            break
        message = (result.stderr or result.stdout)[-500:]
        if "频率太高" not in message or attempt == 3:
            raise DataUnavailable(message)
        time.sleep(10 * (attempt + 1))
    rows = last_json(result.stdout).get("data") or []
    if not rows:
        raise DataUnavailable(f"{code} 无成分股")
    return rows


def turnover_sample(rows: list[dict], limit: int) -> list[dict]:
    if len(rows) <= limit:
        return rows
    result = subprocess.run([sys.executable, str(SNAPSHOT_SCRIPT), *[x["code"] for x in rows], "--json"], text=True, capture_output=True, timeout=90)
    if result.returncode:
        raise DataUnavailable("流动性样本快照不可用：" + (result.stderr or result.stdout)[-240:])
    turnover = {x.get("code"): float(x.get("turnover") or 0) for x in last_json(result.stdout).get("data", [])}
    return sorted(rows, key=lambda x: (turnover.get(x["code"], 0), x["code"]), reverse=True)[:limit]


def members(board: dict) -> tuple[list[dict], list[dict]]:
    merged: dict[str, dict] = {}
    for plate in board["plates"]:
        for row in plate_members(plate):
            if row.get("code"):
                merged[row["code"]] = {"code": row["code"], "name": row.get("name", "")}
    if len(merged) < 10:
        raise DataUnavailable(f"{board['name']} 动态股票池仅 {len(merged)} 只")
    full = sorted(merged.values(), key=lambda x: x["code"])
    return full, turnover_sample(full, board.get("max_members", len(full)))


def fetch_series(code: str) -> dict:
    global _price_last
    with _price_lock:
        wait = PRICE_MIN_INTERVAL - (time.monotonic() - _price_last)
        if wait > 0:
            time.sleep(wait)
        _price_last = time.monotonic()
    ticker = code.replace(".", "").lower()
    request = urllib.request.Request(TENCENT.format(code=ticker), headers={"User-Agent": "Mozilla/5.0 sector-extremes-monitor"})
    error = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8", "replace"))
            break
        except Exception as exc:
            error = exc
            if attempt < 2:
                time.sleep(0.8 * (attempt + 1))
    else:
        if code.startswith("SH.920"):
            raise DataUnavailable(f"腾讯日线请求失败（{type(error).__name__}）；北交所920代码不使用富途备用源") from error
        return futu_series(code, error)
    rows = payload.get("data", {}).get(ticker, {}).get("qfqday") or []
    clean = []
    for row in rows:
        try:
            day, close = date.fromisoformat(row[0]), float(row[2])
            if math.isfinite(close) and close > 0:
                clean.append((day, close))
        except (IndexError, ValueError, TypeError):
            pass
    now = datetime.now(TZ)
    if clean and clean[-1][0] == now.date() and (now.hour, now.minute) < (15, 10):
        clean.pop()
    if len(clean) < 20:
        if code.startswith("SH.920"):
            raise DataUnavailable(f"腾讯完成日线仅 {len(clean)} 天；北交所920代码不使用富途备用源")
        return futu_series(code, DataUnavailable(f"腾讯完成日线仅 {len(clean)} 天"))
    return {"dates": [x[0] for x in clean], "closes": [x[1] for x in clean]}


def futu_series(code: str, primary_error: Exception) -> dict:
    global _futu_last
    with _futu_lock:
        wait = FUTU_KLINE_MIN_INTERVAL - (time.monotonic() - _futu_last)
        if wait > 0:
            time.sleep(wait)
        _futu_last = time.monotonic()
    result = subprocess.run([sys.executable, str(KLINE_SCRIPT), code, "--ktype", "1d", "--start", "2025-01-01", "--end", "2026-12-31", "--num", "300", "--json"], text=True, capture_output=True, timeout=50)
    try:
        rows = last_json(result.stdout).get("data") or []
        clean = [(date.fromisoformat(str(x["time"])[:10]), float(x["close"])) for x in rows]
    except (KeyError, TypeError, ValueError, DataUnavailable) as exc:
        raise DataUnavailable(f"腾讯不可用；富途日线不可用（{type(exc).__name__}）") from primary_error
    now = datetime.now(TZ)
    if clean and clean[-1][0] == now.date() and (now.hour, now.minute) < (15, 10):
        clean.pop()
    if len(clean) < 20:
        raise DataUnavailable(f"腾讯不可用；富途完成日线仅 {len(clean)} 天") from primary_error
    return {"dates": [x[0] for x in clean], "closes": [x[1] for x in clean]}


def mean(values: list[float], days: int) -> float | None:
    return statistics.fmean(values[-days:]) if len(values) >= days else None


def breadth(rows: list[dict], prices: dict[str, dict], days: int) -> dict:
    valid = [prices[row["code"]]["closes"] for row in rows if row["code"] in prices and mean(prices[row["code"]]["closes"], days) is not None]
    above = sum(x[-1] > mean(x, days) for x in valid)
    return {"value": 100 * above / len(valid) if valid else None, "above": above, "count": len(valid), "coverage": 100 * len(valid) / len(rows) if rows else 0}


def synthetic_proxy(rows: list[dict], prices: dict[str, dict]) -> dict | None:
    paths = [prices[row["code"]] for row in rows if row["code"] in prices and len(prices[row["code"]]["closes"]) >= 200]
    if len(paths) < max(10, math.ceil(len(rows) * .5)):
        return None
    values = []
    for offset in range(200):
        normalized = [p["closes"][-200 + offset] / p["closes"][-200] * 100 for p in paths]
        values.append(statistics.fmean(normalized))
    close, high = values[-1], max(values)
    return {"close": close, "ma5": mean(values, 5), "ma50": mean(values, 50), "ma200": mean(values, 200), "drawdown": 100 * (close / high - 1), "date": str(paths[0]["dates"][-1]), "sample": len(paths)}


def prior_snapshots(today: date) -> list[dict]:
    path = ROOT / "data/history.jsonl"
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip() and json.loads(x).get("report_date") != str(today)]


def duration(history: list[dict], board_id: str, direction: str) -> int:
    days = 0
    for snapshot in reversed(history):
        value = snapshot.get("boards", {}).get(board_id, {}).get("breadth", {}).get("20", {}).get("value")
        hit = value is not None and (value <= 15 if direction == "bottom" else value >= 85)
        if not hit:
            break
        days += 1
    return days


def classify(b: dict[int, dict], proxy: dict | None, prior: list[dict], board_id: str) -> tuple[str, int]:
    b20 = b[20]["value"]
    if b20 is None or b[20]["coverage"] < 75:
        return "数据不足 / 不作极端判断", 0
    bottom_days, top_days = duration(prior, board_id, "bottom"), duration(prior, board_id, "top")
    if b20 <= 15:
        if proxy and proxy["close"] >= proxy["ma5"] and bottom_days >= 1:
            return "短线底部（确认改善）", bottom_days + 1
        if bottom_days >= 5:
            return "长期弱势 / 极端延续", bottom_days + 1
        return "短线洗出（底部候选）", bottom_days + 1
    if b20 >= 85:
        if proxy and proxy["drawdown"] >= -3 and proxy["close"] >= proxy["ma5"]:
            return "顶部人性极端（警戒）", top_days + 1
        return "宽度拥挤（待价格确认）", top_days + 1
    return "未进入人性极端", 0


def gauge(value: float | None, low: int, high: int, slots: int = 24) -> str:
    if value is None:
        return "UNAVAILABLE"
    cells = ["─"] * (slots + 1)
    cells[round(low / 100 * slots)] = "┊"; cells[round(high / 100 * slots)] = "┊"; cells[round(value / 100 * slots)] = "●"
    return "".join(cells)


def pct(value: float | None) -> str:
    return "UNAVAILABLE" if value is None else f"{value:.1f}%"


def overlaps(results: dict[str, dict]) -> list[dict]:
    rows = []
    values = list(results.values())
    for i, left in enumerate(values):
        a = {x["code"] for x in left["members"]}
        for right in values[i + 1:]:
            b = {x["code"] for x in right["members"]}; inter = a & b
            if inter:
                rows.append({"left": left["name"], "right": right["name"], "count": len(inter), "jaccard": 100 * len(inter) / len(a | b), "smaller": 100 * len(inter) / min(len(a), len(b))})
    return sorted(rows, key=lambda x: (x["jaccard"], x["count"]), reverse=True)


def select_boards(all_boards: list[dict], ids: str | None, plate: str | None, name: str | None) -> list[dict]:
    if plate:
        return [{"id": plate.lower().replace(".", "_"), "name": name or plate, "kind": "用户指定富途板块", "plates": [plate], "max_members": 200}]
    if not ids:
        return all_boards
    wanted = set(ids.split(",")); selected = [b for b in all_boards if b["id"] in wanted]
    missing = wanted - {b["id"] for b in selected}
    if missing:
        raise SystemExit(f"未知板块 ID：{', '.join(sorted(missing))}")
    return selected


def render(today: date, results: dict[str, dict], pairs: list[dict], errors: list[str]) -> str:
    lines = [f"# A股板块人性极端扫描｜{today}", "", "## 极端状态排行榜", "", "以 20 日宽度距 15% / 85% 阈值的最近距离排序。5/10 日用于看修复速度；状态不是交易指令。", "", "| 板块 | 5日 | 10日 | 20日宽度 | 50日 | 200日 | 连续极端 | 状态 |", "|---|---:|---:|---:|---:|---:|---:|---|"]
    ordered = sorted(results.values(), key=lambda x: min(abs((x["breadth"][20]["value"] or 50) - 15), abs((x["breadth"][20]["value"] or 50) - 85)))
    for r in ordered:
        b = r["breadth"]
        lines.append(f"| {r['name']} | {pct(b[5]['value'])} | {pct(b[10]['value'])} | {pct(b[20]['value'])}（{b[20]['above']}/{b[20]['count']}） | {pct(b[50]['value'])} | {pct(b[200]['value'])} | {r['duration']}日 | {r['state']} |")
    lines += ["", "## 宽度位置", ""]
    for r in ordered:
        b, proxy = r["breadth"], r["proxy"]
        population = f"完整池 {r['full_member_count']} 只，按成交额监控前 {len(r['members'])} 只样本" if r['full_member_count'] > len(r['members']) else f"当前 {len(r['members'])} 只动态成分股"
        lines += [f"### {r['name']}", "", f"- 口径：{r['kind']}（{'、'.join(r['plates'])}），{population}；20日覆盖 {b[20]['coverage']:.1f}%。", f"- 20日：`{gauge(b[20]['value'], 15, 85)}` {pct(b[20]['value'])}；50日：`{gauge(b[50]['value'], 25, 80)}` {pct(b[50]['value'])}。"]
        if proxy:
            lines.append(f"- 合成价格代理：样本 {proxy['sample']} 只，观测日 {proxy['date']}，距200日窗口高点 {proxy['drawdown']:.1f}%，{'站上' if proxy['close'] >= proxy['ma5'] else '跌破'}5日均线。")
        else:
            lines.append("- 合成价格代理：UNAVAILABLE（200日历史覆盖不足）。")
        lines.append("")
    lines += ["## 成分重合警示", "", "高重合板块不是独立确认信号；Jaccard=交集/并集，较小集合占比=交集/两者中较小股票池。", "", "| 板块对 | 重合股数 | Jaccard | 较小集合占比 |", "|---|---:|---:|---:|"]
    if pairs:
        for p in pairs[:20]:
            lines.append(f"| {p['left']} × {p['right']} | {p['count']} | {p['jaccard']:.1f}% | {p['smaller']:.1f}% |")
    else:
        lines.append("| — | — | — | — |")
    lines += ["", "## 数据边界", "", "- 成分股每日从富途板块服务重新拉取并归档；概念组合取并集，不等同于官方指数。", "- 日线使用腾讯前复权数据主源、富途日线备用；20日有效覆盖不足75%的板块不做极端判断。", "- 合成价格代理是当前股票池等权重重置序列，用于确认趋势，不替代官方指数或ETF。"]
    if errors:
        lines += ["", "## 未覆盖项", ""] + [f"- {x}" for x in errors[:30]]
    return "\n".join(lines) + "\n"


def run(args: argparse.Namespace) -> None:
    boards = select_boards(load_boards(), args.boards, args.plate, args.name)
    today, prior = datetime.now(TZ).date(), prior_snapshots(datetime.now(TZ).date())
    universes, errors = {}, []
    for board in boards:
        try:
            full, sampled = members(board)
            universes[board["id"]] = {"full": full, "sample": sampled}
        except Exception as exc:
            errors.append(f"{board['name']} 成分股：{exc}")
            universes[board["id"]] = {"full": [], "sample": []}
    unique = {row["code"] for group in universes.values() for row in group["sample"]}
    prices: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=10) as pool:
        jobs = {pool.submit(fetch_series, code): code for code in unique}
        for job in as_completed(jobs):
            code = jobs[job]
            try:
                prices[code] = job.result()
            except Exception as exc:
                errors.append(f"{code}：{exc}")
    results = {}
    for board in boards:
        rows = universes[board["id"]]["sample"]
        b = {n: breadth(rows, prices, n) for n in WINDOWS}
        proxy = synthetic_proxy(rows, prices)
        state, streak = classify(b, proxy, prior, board["id"])
        results[board["id"]] = {**board, "members": rows, "full_member_count": len(universes[board["id"]]["full"]), "breadth": b, "proxy": proxy, "state": state, "duration": streak}
    report = render(today, results, overlaps(results), errors)
    (ROOT / "reports").mkdir(exist_ok=True); (ROOT / "data" / "universes").mkdir(parents=True, exist_ok=True)
    for board_id, result in results.items():
        (ROOT / "data" / "universes" / f"{board_id}-{today}.json").write_text(json.dumps({"full_member_count": result["full_member_count"], "monitored_member_count": len(result["members"]), "members": result["members"]}, ensure_ascii=False, indent=2), encoding="utf-8")
    snapshot = {"report_date": str(today), "boards": {key: {"name": value["name"], "breadth": {str(n): value["breadth"][n] for n in WINDOWS}, "state": value["state"], "duration": value["duration"], "member_count": len(value["members"])} for key, value in results.items()}, "errors": errors}
    is_full = not args.boards and not args.plate
    suffix = "" if is_full else "-" + "-".join(results)
    if is_full:
        history = ROOT / "data" / "history.jsonl"; old = []
        if history.exists(): old = [x for x in history.read_text(encoding="utf-8").splitlines() if x and json.loads(x).get("report_date") != str(today)]
        history.write_text("\n".join(old + [json.dumps(snapshot, ensure_ascii=False)]) + "\n", encoding="utf-8")
        (ROOT / "data" / "latest_snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        (ROOT / "data" / f"latest_snapshot{suffix}.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    (ROOT / "reports" / f"a-share-sector-extremes-{today}{suffix}.md").write_text(report, encoding="utf-8")
    print(report)


def self_test() -> None:
    assert mean([1, 2, 3], 3) == 2
    empty = breadth([], {}, 20)
    assert empty["value"] is None and empty["coverage"] == 0
    assert "UNAVAILABLE" in gauge(None, 15, 85)
    print("self-test: ok")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--boards", help="comma-separated IDs from board-definitions.json")
    parser.add_argument("--plate", help="one user-provided Futu plate/index code")
    parser.add_argument("--name", help="label for --plate")
    parser.add_argument("--self-test", action="store_true")
    parsed = parser.parse_args()
    if parsed.self_test:
        self_test()
    else:
        run(parsed)
