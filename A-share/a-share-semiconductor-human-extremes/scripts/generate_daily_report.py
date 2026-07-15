#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Daily A-share semiconductor breadth / sentiment monitor."""
from __future__ import annotations

import argparse, json, math, statistics, subprocess, sys, threading, time, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
TZ = ZoneInfo("Asia/Shanghai")
PLATE = "SH.LIST0002"  # Futu A-share industry classification: 半导体
FUTU_PLATE_SCRIPT = Path("/Users/icemelon/.agents/skills/futuapi/scripts/quote/get_plate_stock.py")
FUTU_KLINE_SCRIPT = Path("/Users/icemelon/.agents/skills/futuapi/scripts/quote/get_kline.py")
TENCENT = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,300,qfq"
ETF = {"半导体ETF": "sh512480", "芯片ETF": "sz159995", "设备材料ETF": "sz159516", "设备ETF": "sh561980"}
BREADTH_WINDOWS = (5, 10, 20, 50, 200)
HUMAN_EXTREME_LINES = {20: (15, 85), 50: (25, 80), 200: (15, 85)}
MONTH_SESSIONS = 22
FUTU_MIN_INTERVAL, _futu_last_request, _futu_lock = 0.62, 0.0, threading.Lock()
TENCENT_FAILURE_LIMIT, _tencent_failures, _tencent_lock = 8, 0, threading.Lock()

class HistoryInsufficient(RuntimeError): pass
class SourceUnavailable(RuntimeError): pass

def fetch_text(url: str) -> str:
    global _tencent_failures
    with _tencent_lock:
        if _tencent_failures >= TENCENT_FAILURE_LIMIT:
            raise SourceUnavailable("腾讯日线源健康保护已触发")
    error = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 A-share-semiconductor-monitor"})
            with urllib.request.urlopen(req, timeout=20) as r: return r.read().decode("utf-8", "replace")
        except Exception as exc:
            error = exc
            with _tencent_lock:
                _tencent_failures += 1
            if attempt < 2: time.sleep(1.0 + attempt * 2.0)
    raise error

def last_json(text: str) -> dict:
    for line in reversed(text.splitlines()):
        try:
            value = json.loads(line)
            if isinstance(value, dict): return value
        except json.JSONDecodeError: pass
    raise RuntimeError("source returned no JSON")

def universe() -> list[dict]:
    result = subprocess.run([sys.executable, str(FUTU_PLATE_SCRIPT), PLATE, "--limit", "1000", "--json"], text=True, capture_output=True, timeout=45)
    if result.returncode: raise RuntimeError((result.stderr or result.stdout)[-500:])
    rows = last_json(result.stdout).get("data", [])
    if len(rows) < 50: raise RuntimeError(f"unexpected semiconductor universe size: {len(rows)}")
    return rows

def tencent_code(code: str) -> str:
    market, raw = code.split(".", 1)
    return market.lower() + raw

def futu_code(ticker: str) -> str:
    return ticker[:2].upper() + "." + ticker[2:]

def series(code: str, include_intraday: bool = False) -> dict:
    try: payload = json.loads(fetch_text(TENCENT.format(code=code)))
    except Exception as exc: raise SourceUnavailable(f"腾讯日线请求失败（{type(exc).__name__}）") from exc
    node = payload.get("data", {}).get(code, {})
    rows = node.get("qfqday") or node.get("day") or []
    clean = []
    for row in rows:
        try:
            day, close, vol = date.fromisoformat(row[0]), float(row[2]), float(row[5])
            if math.isfinite(close): clean.append((day, close, vol))
        except (IndexError, ValueError, TypeError): pass
    if not clean: raise SourceUnavailable("腾讯无可用前复权日线")
    # The regular daily monitor excludes a partial session.  Intraday mode
    # deliberately retains it as a marked real-time breadth snapshot.
    now = datetime.now(TZ)
    if not include_intraday and clean and clean[-1][0] == now.date() and (now.hour, now.minute) < (15, 10): clean.pop()
    # A stock can participate in the 20-day breadth as soon as it has 20
    # completed closes; 50/200-day participation is determined separately in
    # breadth().  Newly listed shares with fewer than 20 closes are excluded.
    if len(clean) < 20: raise HistoryInsufficient(f"上市历史仅 {len(clean)} 个交易日，不足 20 日")
    return {"dates": [x[0] for x in clean], "closes": [x[1] for x in clean], "volumes": [x[2] for x in clean]}

def futu_series(code: str, include_intraday: bool = False) -> dict:
    # OpenD permits 60 historical-K requests per 30 seconds.  Space starts at
    # 0.62s (under 49/30s) so this source can safely carry the whole plate if
    # Tencent's public endpoint is behind its WAF.
    global _futu_last_request
    with _futu_lock:
        wait = FUTU_MIN_INTERVAL - (time.monotonic() - _futu_last_request)
        if wait > 0: time.sleep(wait)
        _futu_last_request = time.monotonic()
    result = subprocess.run([sys.executable, str(FUTU_KLINE_SCRIPT), code, "--ktype", "1d", "--start", "2025-01-01", "--end", "2026-12-31", "--num", "300", "--json"], text=True, capture_output=True, timeout=45)
    payload = last_json(result.stdout)
    rows = payload.get("data") or []
    if not rows: raise SourceUnavailable(f"富途日线不可用：{payload.get('error', '无数据')}")
    clean = []
    for row in rows:
        try: clean.append((date.fromisoformat(str(row["time"])[:10]), float(row["close"]), float(row.get("volume", 0))))
        except (KeyError, ValueError, TypeError): pass
    now = datetime.now(TZ)
    if not include_intraday and clean and clean[-1][0] == now.date() and (now.hour, now.minute) < (15, 10): clean.pop()
    if len(clean) < 20: raise HistoryInsufficient(f"富途历史仅 {len(clean)} 个交易日，不足 20 日")
    return {"dates": [x[0] for x in clean], "closes": [x[1] for x in clean], "volumes": [x[2] for x in clean], "source": "Futu fallback"}

def stock_series(tencent_ticker: str, futu_code: str, tencent_enabled: bool = True, include_intraday: bool = False) -> dict:
    primary = None
    if tencent_enabled:
        try: return series(tencent_ticker, include_intraday)
        except HistoryInsufficient: raise
        except SourceUnavailable as exc: primary = exc
    if futu_code.startswith("SH.920"):
        raise SourceUnavailable("北交所 920 代码未获腾讯/富途日线覆盖") from primary
    try:
        return futu_series(futu_code, include_intraday)
    except HistoryInsufficient:
        raise
    except SourceUnavailable as fallback:
        if primary is None: raise
        raise SourceUnavailable(f"腾讯不可用；{fallback}") from primary

def ma(x, n): return statistics.fmean(x[-n:]) if len(x) >= n else None
def ret(x, n): return (x[-1] / x[-n-1] - 1) * 100 if len(x) > n and x[-n-1] else None
def gauge(v, low, high, slots=24):
    if v is None: return "UNAVAILABLE"
    s = ["─"] * (slots + 1); s[round(low / 100 * slots)] = "┊"; s[round(high / 100 * slots)] = "┊"; s[round(v / 100 * slots)] = "●"
    return "".join(s)
def fmt(v, suffix=""): return "UNAVAILABLE" if v is None else f"{v:.2f}{suffix}"

def breadth(rows: list[dict], prices: dict[str, dict], days: int, asof: date | None = None) -> dict:
    valid = []
    for item in rows:
        source = prices.get(item["code"])
        if not source: continue
        end = len(source["dates"]) if asof is None else next((i for i, day in enumerate(source["dates"]) if day > asof), len(source["dates"]))
        closes = source["closes"][:end]
        if ma(closes, days) is not None: valid.append(closes)
    above = sum(s[-1] > ma(s, days) for s in valid)
    return {"value": 100 * above / len(valid) if valid else None, "above": above, "count": len(valid), "coverage": 100 * len(valid) / len(rows)}

def etf_metric(s: dict) -> dict:
    closes, volumes = s["closes"], s["volumes"]
    high = max(closes[-252:]); baseline = statistics.fmean(volumes[-21:-1]) if len(volumes) >= 21 else None
    return {"close": closes[-1], "date": str(s["dates"][-1]), "ma5": ma(closes, 5), "ma200": ma(closes, 200), "ret20": ret(closes, 20), "drawdown": 100 * (closes[-1] / high - 1), "relvol": volumes[-1] / baseline if baseline else None}

def prior(today: date):
    path = ROOT / "data/history.jsonl"
    if not path.exists(): return None, False
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    rows = [x for x in rows if x.get("report_date") != str(today)][-5:]
    values = [x.get("breadth", {}).get("20", {}).get("value") for x in rows]
    values = [x for x in values if x is not None]
    return (values[-1] if values else None), any(x <= 15 for x in values)

def recent_widths(rows: list[dict], prices: dict[str, dict], core: dict) -> list[dict]:
    """Backfill one month of completed sessions from the current universe."""
    result = []
    for observed in core["dates"][-MONTH_SESSIONS:]:
        result.append({"observation_date": str(observed), "breadth": {str(n): breadth(rows, prices, n, observed) for n in BREADTH_WINDOWS}})
    return result

def classify(b, core, before, had_washout):
    b20 = b[20]["value"]; stress = core["drawdown"] <= -15 or core["close"] < core["ma200"]
    washout = b20 is not None and b20 <= 15
    repaired = core["close"] >= core["ma5"]
    rebound = before is not None and b20 >= before + 5
    if (washout or had_washout) and repaired and rebound: return "A股半导体短线底部（确认改善）", washout, repaired, rebound
    if stress and washout: return "A股半导体短线洗出（底部候选）", washout, repaired, rebound
    if b20 is not None and b20 >= 85 and core["drawdown"] >= -3 and core["ret20"] >= 15: return "A股半导体顶部人性极端（警戒）", washout, repaired, rebound
    return "A股半导体未进入人性极端", washout, repaired, rebound

def report(today, state, b, etfs, washout, repaired, rebound, history, errors, price_source, intraday=False, as_of=None):
    title = f"# A股半导体{'盘中宽度' if intraday else '人性极端监测'}｜{today}"
    if intraday:
        title += f" {as_of}"
    scope = "盘中价格快照，非收盘结论；收盘后日报会以最终收盘价另行沉淀。" if intraday else "以全行业参与度为主、半导体/芯片/设备材料 ETF 为趋势与拥挤度交叉验证；不是交易指令。"
    lines = [title, "", "## 今日结论", "", f"**{state}{'（盘中，待收盘验证）' if intraday else ''}**", "", scope, "", "## 行业宽度位置", "", "宽度是富途 A 股“半导体”行业板块内，站上对应均线股票的比例。该行业板块比单只 ETF 更适合观察整体参与度；暂不将其伪装为 ETF 官方权重宽度。5/10 日用于观察短线修复速度，不单独作为人性极端信号。", "", "| 周期 | 读数（股票数） | 位置图 | 极端线 |", "|---|---:|---|---|"]
    for n in BREADTH_WINDOWS:
        x = b[n]
        if n in HUMAN_EXTREME_LINES:
            low, high = HUMAN_EXTREME_LINES[n]
            position, extreme = f"`{gauge(x['value'], low, high)}`", f"{low}% / {high}%"
        else:
            position, extreme = "—", "观察值"
        lines.append(f"| {n} 日 | {fmt(x['value'],'%')}（{x['above']}/{x['count']}，覆盖 {x['coverage']:.1f}%） | {position} | {extreme} |")
    history_label = "最近一个月（含当前盘中）" if intraday else "最近一个月已完成交易日"
    history_note = "本表按当前行业股票池以历史收盘价回算，最后一行是当前盘中快照，不写入收盘宽度历史。" if intraday else "逐日宽度会保存到 `data/breadth_history.jsonl`。本表按**当前**行业股票池以历史收盘价回算；随后每日读数将持续累积。"
    lines += ["", f"## 宽度变化趋势（{history_label}）", "", history_note, "", "| 观测交易日 | 5日 | 10日 | 20日 | 日变化 | 50日 | 200日 |", "|---|---:|---:|---:|---:|---:|---:|"]
    previous = None
    for row in history:
        x = row.get("breadth", {})
        current = x.get("20", {}).get("value"); change = None if previous is None or current is None else current - previous
        lines.append(f"| {row.get('observation_date','—')} | {fmt(x.get('5',{}).get('value'),'%')} | {fmt(x.get('10',{}).get('value'),'%')} | {fmt(current,'%')} | {fmt(change,'pct')} | {fmt(x.get('50',{}).get('value'),'%')} | {fmt(x.get('200',{}).get('value'),'%')} |")
        previous = current
    lines += ["", "## 两阶段底部判断", "", f"- 短线洗出：{'已触发' if washout else '未触发'}（20 日宽度 ≤15%）。", f"- 价格修复：{'已触发' if repaired else '未触发'}（半导体 ETF 收回 5 日线）。", f"- 宽度回升：{'已触发' if rebound else '未触发'}（20 日宽度较前日回升至少 5pct）。", "", "## ETF 交叉验证与拥挤代理", "", "| ETF | 收盘 | 20日变化 | 252日回撤 | 相对成交量 | 观测日 |", "|---|---:|---:|---:|---:|---|"]
    for name, x in etfs.items(): lines.append(f"| {name} | {fmt(x['close'])} | {fmt(x['ret20'],'%')} | {fmt(x['drawdown'],'%')} | {fmt(x['relvol'],'x')} | {x['date']} |")
    lines += ["", "## 怎么读", "", "- 全行业宽度与半导体ETF/芯片ETF同步洗出，才是较强的板块级短线恐慌证据。", "- 只有设备材料 ETF 显著弱或强，更多反映设备材料子行业，不直接代表设计、制造、封测全链条。", "- ETF 相对成交量是交易拥挤代理，不等于申赎或北向资金。", "", "## 数据来源与限制", "", "- 行业股票池：富途 OpenD A 股行业板块“半导体”（SH.LIST0002），每日保存快照。", f"- 本轮股票与 ETF 日线、成交量：{price_source}。无可核验的实时 ETF 权重时，仅计算等权行业宽度。", "- A股缺少与美股 AAII/NAAIM 对应的统一公开日频情绪调查；本版不虚构散户或机构情绪指数。"]
    if errors:
        listings = [x for x in errors if "历史仅" in x]
        coverage = [x for x in errors if x not in listings]
        lines += ["", "## 数据覆盖说明", "", "以下标的未计入相应均线宽度；报告在有效覆盖率低于 75% 时会自动停止给出极端判断。"]
        if listings:
            lines += ["", "- 新上市、历史不足 20 个交易日：" + "；".join(listings)]
        if coverage:
            lines += ["", "- 数据源暂未覆盖或临时不可用：" + "；".join(coverage)]
    return "\n".join(lines)+"\n"

def run(intraday: bool = False):
    now = datetime.now(TZ)
    today, errors = now.date(), []
    try: rows = universe()
    except Exception as e: print(f"universe error: {e}"); return 1
    codes = {x["code"]: tencent_code(x["code"]) for x in rows}
    # Fetch the four ETF anchors first, before the high-cardinality industry
    # fan-out can trigger a public-source rate limit.
    etfs, etf_prices, tencent_enabled = {}, {}, True
    for name,ticker in ETF.items():
        try:
            etf_prices[name] = series(ticker, intraday) if tencent_enabled else futu_series(futu_code(ticker), intraday)
            etfs[name] = etf_metric(etf_prices[name])
        except SourceUnavailable as e:
            # A WAF/HTTP failure is source-wide, so switch the batch once;
            # subsequent equities use the rate-limited OpenD route directly.
            tencent_enabled = False
            try:
                etf_prices[name] = futu_series(futu_code(ticker), intraday)
                etfs[name] = etf_metric(etf_prices[name])
            except (HistoryInsufficient, SourceUnavailable) as fallback:
                errors.append(f"{name}: 腾讯不可用；{fallback}")
        except Exception as e: errors.append(f"{name}: 未预期错误 {type(e).__name__}")
    prices = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs={pool.submit(stock_series, ticker, code, tencent_enabled, intraday): code for code,ticker in codes.items()}
        for job in as_completed(jobs):
            code=jobs[job]
            try: prices[code]=job.result()
            except HistoryInsufficient as e: errors.append(f"{code}: {e}")
            except SourceUnavailable as e: errors.append(f"{code}: {e}")
            except Exception as e: errors.append(f"{code}: 未预期错误 {type(e).__name__}")
    b={n: breadth(rows, prices, n) for n in BREADTH_WINDOWS}
    # Source-wide failures must not overwrite a valid same-day report or
    # contaminate the stored breadth trend with a tiny, biased subset.
    source_outage = any("请求失败" in e or "健康保护" in e for e in errors)
    if source_outage and len(prices) / len(rows) < 0.75:
        print(f"数据源覆盖仅 {len(prices)}/{len(rows)}；保留既有日报与宽度历史，本轮不落盘。")
        return 2
    width_history = recent_widths(rows, prices, etf_prices["半导体ETF"]) if "半导体ETF" in etf_prices else []
    if "半导体ETF" not in etfs or min(x["coverage"] for x in b.values()) < 75: state="数据不足 / 不作极端判断"; washout=repaired=rebound=False
    else:
        before = width_history[-2]["breadth"]["20"]["value"] if len(width_history) > 1 else None
        had = any(row["breadth"]["20"]["value"] is not None and row["breadth"]["20"]["value"] <= 15 for row in width_history[:-1])
        state,washout,repaired,rebound=classify(b,etfs["半导体ETF"],before,had)
    price_source = "腾讯 qfq 日线" if tencent_enabled else "富途 OpenD 日线（腾讯公开接口 WAF 不可用时的限速备用）"
    as_of = now.strftime("%H:%M CST")
    body=report(today,state,b,etfs,washout,repaired,rebound,width_history,errors,price_source,intraday,as_of)
    for folder in (ROOT/"reports",ROOT/"data"): folder.mkdir(exist_ok=True)
    report_name = f"a-share-semiconductor-human-extremes-{today}{'-' + now.strftime('%H%M') if intraday else ''}.md"
    (ROOT/"reports"/report_name).write_text(body,encoding="utf-8")
    (ROOT/"data"/f"universe-{today}.json").write_text(json.dumps(rows,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    snap={"report_date":str(today),"observation_date":etfs.get("半导体ETF",{}).get("date"),"as_of":as_of,"mode":"intraday" if intraday else "daily","state":state,"price_source":price_source,"breadth":b,"recent_width_history":width_history,"etfs":etfs,"errors":errors}
    (ROOT/"data"/("latest_intraday_snapshot.json" if intraday else "latest_snapshot.json")).write_text(json.dumps(snap,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    if intraday:
        print(body); return 0
    ledger = ROOT / "data/breadth_history.jsonl"; existing = {}
    if ledger.exists():
        for line in ledger.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line); existing[row["observation_date"]] = row
            except (json.JSONDecodeError, KeyError): pass
    for point in width_history:
        observed = point["observation_date"]
        # Refresh the one-month window so the ledger gains the new 5/10-day
        # fields as well as the same-universe historical comparison.
        existing[observed] = {"observation_date": observed, "breadth": point["breadth"], "universe_source": "current-universe retrospective backfill" if observed != etfs["半导体ETF"]["date"] else "daily current-universe snapshot"}
    ledger.write_text("".join(json.dumps(existing[key],ensure_ascii=False)+"\n" for key in sorted(existing)),encoding="utf-8")
    hist=ROOT/"data/history.jsonl"; prior_rows=[]
    if hist.exists(): prior_rows=[json.loads(x) for x in hist.read_text(encoding="utf-8").splitlines() if x.strip() and json.loads(x).get("report_date")!=str(today)]
    hist.write_text("".join(json.dumps(x,ensure_ascii=False)+"\n" for x in prior_rows+[snap]),encoding="utf-8")
    print(body); return 0

if __name__ == "__main__":
    p=argparse.ArgumentParser(); p.add_argument("--self-test",action="store_true"); p.add_argument("--intraday",action="store_true",help="include the current partial A-share session without writing close-history"); a=p.parse_args()
    if a.self_test:
        b={20:{"value":10},50:{"value":30},200:{"value":90}}; core={"drawdown":-16,"close":90,"ma5":95,"ma200":100,"ret20":-5}; assert "洗出" in classify(b,core,None,False)[0]; print("self-test: ok")
    else: raise SystemExit(run(a.intraday))
