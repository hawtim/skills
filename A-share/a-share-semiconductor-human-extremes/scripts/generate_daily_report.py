#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Daily A-share semiconductor breadth / sentiment monitor."""
from __future__ import annotations

import argparse, json, math, statistics, subprocess, sys, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
TZ = ZoneInfo("Asia/Shanghai")
PLATE = "SH.LIST0002"  # Futu A-share industry classification: 半导体
FUTU_PLATE_SCRIPT = Path("/Users/icemelon/.agents/skills/futuapi/scripts/quote/get_plate_stock.py")
TENCENT = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,300,qfq"
ETF = {"半导体ETF": "sh512480", "芯片ETF": "sz159995", "设备材料ETF": "sz159516", "设备ETF": "sh561980"}

def fetch_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 A-share-semiconductor-monitor"})
    with urllib.request.urlopen(req, timeout=20) as r: return r.read().decode("utf-8", "replace")

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

def series(code: str) -> dict:
    payload = json.loads(fetch_text(TENCENT.format(code=code)))
    node = payload.get("data", {}).get(code, {})
    rows = node.get("qfqday") or node.get("day") or []
    clean = []
    for row in rows:
        try:
            day, close, vol = date.fromisoformat(row[0]), float(row[2]), float(row[5])
            if math.isfinite(close): clean.append((day, close, vol))
        except (IndexError, ValueError, TypeError): pass
    if len(clean) < 30: raise RuntimeError("insufficient daily history")
    return {"dates": [x[0] for x in clean], "closes": [x[1] for x in clean], "volumes": [x[2] for x in clean]}

def ma(x, n): return statistics.fmean(x[-n:]) if len(x) >= n else None
def ret(x, n): return (x[-1] / x[-n-1] - 1) * 100 if len(x) > n and x[-n-1] else None
def gauge(v, low, high, slots=24):
    if v is None: return "UNAVAILABLE"
    s = ["─"] * (slots + 1); s[round(low / 100 * slots)] = "┊"; s[round(high / 100 * slots)] = "┊"; s[round(v / 100 * slots)] = "●"
    return "".join(s)
def fmt(v, suffix=""): return "UNAVAILABLE" if v is None else f"{v:.2f}{suffix}"

def breadth(rows: list[dict], prices: dict[str, dict], days: int) -> dict:
    valid = [prices[x["code"]] for x in rows if x["code"] in prices and ma(prices[x["code"]]["closes"], days) is not None]
    above = sum(s["closes"][-1] > ma(s["closes"], days) for s in valid)
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

def classify(b, core, before, had_washout):
    b20 = b[20]["value"]; stress = core["drawdown"] <= -15 or core["close"] < core["ma200"]
    washout = b20 is not None and b20 <= 15
    repaired = core["close"] >= core["ma5"]
    rebound = before is not None and b20 >= before + 5
    if (washout or had_washout) and repaired and rebound: return "A股半导体短线底部（确认改善）", washout, repaired, rebound
    if stress and washout: return "A股半导体短线洗出（底部候选）", washout, repaired, rebound
    if b20 is not None and b20 >= 85 and core["drawdown"] >= -3 and core["ret20"] >= 15: return "A股半导体顶部人性极端（警戒）", washout, repaired, rebound
    return "A股半导体未进入人性极端", washout, repaired, rebound

def report(today, state, b, etfs, washout, repaired, rebound, errors):
    lines = [f"# A股半导体人性极端监测｜{today}", "", "## 今日结论", "", f"**{state}**", "", "以全行业参与度为主、半导体/芯片/设备材料 ETF 为趋势与拥挤度交叉验证；不是交易指令。", "", "## 行业宽度位置", "", "宽度是富途 A 股“半导体”行业板块内，站上对应均线股票的比例。该行业板块比单只 ETF 更适合观察整体参与度；暂不将其伪装为 ETF 官方权重宽度。", "", "| 周期 | 读数（股票数） | 位置图 | 极端线 |", "|---|---:|---|---|"]
    for n, low, high in ((20,15,85),(50,25,80),(200,15,85)):
        x=b[n]; lines.append(f"| {n} 日 | {fmt(x['value'],'%')}（{x['above']}/{x['count']}，覆盖 {x['coverage']:.1f}%） | `{gauge(x['value'],low,high)}` | {low}% / {high}% |")
    lines += ["", "## 两阶段底部判断", "", f"- 短线洗出：{'已触发' if washout else '未触发'}（20 日宽度 ≤15%）。", f"- 价格修复：{'已触发' if repaired else '未触发'}（半导体 ETF 收回 5 日线）。", f"- 宽度回升：{'已触发' if rebound else '未触发'}（20 日宽度较前日回升至少 5pct）。", "", "## ETF 交叉验证与拥挤代理", "", "| ETF | 收盘 | 20日变化 | 252日回撤 | 相对成交量 | 观测日 |", "|---|---:|---:|---:|---:|---|"]
    for name, x in etfs.items(): lines.append(f"| {name} | {fmt(x['close'])} | {fmt(x['ret20'],'%')} | {fmt(x['drawdown'],'%')} | {fmt(x['relvol'],'x')} | {x['date']} |")
    lines += ["", "## 怎么读", "", "- 全行业宽度与半导体ETF/芯片ETF同步洗出，才是较强的板块级短线恐慌证据。", "- 只有设备材料 ETF 显著弱或强，更多反映设备材料子行业，不直接代表设计、制造、封测全链条。", "- ETF 相对成交量是交易拥挤代理，不等于申赎或北向资金。", "", "## 数据来源与限制", "", "- 行业股票池：富途 OpenD A 股行业板块“半导体”（SH.LIST0002），每日保存快照。", "- 股票与 ETF 日线、成交量：腾讯 qfq 日线。无可核验的实时 ETF 权重时，仅计算等权行业宽度。", "- A股缺少与美股 AAII/NAAIM 对应的统一公开日频情绪调查；本版不虚构散户或机构情绪指数。"]
    if errors: lines += ["", "## 数据问题", ""] + [f"- {x}" for x in errors]
    return "\n".join(lines)+"\n"

def run():
    today, errors = datetime.now(TZ).date(), []
    try: rows = universe()
    except Exception as e: print(f"universe error: {e}"); return 1
    codes = {x["code"]: tencent_code(x["code"]) for x in rows}
    prices = {}
    with ThreadPoolExecutor(max_workers=12) as pool:
        jobs={pool.submit(series, ticker): code for code,ticker in codes.items()}
        for job in as_completed(jobs):
            code=jobs[job]
            try: prices[code]=job.result()
            except Exception as e: errors.append(f"{code}: {type(e).__name__}")
    etfs={}
    for name,ticker in ETF.items():
        try: etfs[name]=etf_metric(series(ticker))
        except Exception as e: errors.append(f"{name}: {type(e).__name__}")
    b={n: breadth(rows, prices, n) for n in (20,50,200)}
    if "半导体ETF" not in etfs or min(x["coverage"] for x in b.values()) < 75: state="数据不足 / 不作极端判断"; washout=repaired=rebound=False
    else:
        before, had=prior(today); state,washout,repaired,rebound=classify(b,etfs["半导体ETF"],before,had)
    body=report(today,state,b,etfs,washout,repaired,rebound,errors)
    for folder in (ROOT/"reports",ROOT/"data"): folder.mkdir(exist_ok=True)
    (ROOT/"reports"/f"a-share-semiconductor-human-extremes-{today}.md").write_text(body,encoding="utf-8")
    (ROOT/"data"/f"universe-{today}.json").write_text(json.dumps(rows,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    snap={"report_date":str(today),"state":state,"breadth":b,"etfs":etfs,"errors":errors}
    (ROOT/"data"/"latest_snapshot.json").write_text(json.dumps(snap,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    hist=ROOT/"data/history.jsonl"; prior_rows=[]
    if hist.exists(): prior_rows=[json.loads(x) for x in hist.read_text(encoding="utf-8").splitlines() if x.strip() and json.loads(x).get("report_date")!=str(today)]
    hist.write_text("".join(json.dumps(x,ensure_ascii=False)+"\n" for x in prior_rows+[snap]),encoding="utf-8")
    print(body); return 0

if __name__ == "__main__":
    p=argparse.ArgumentParser(); p.add_argument("--self-test",action="store_true"); a=p.parse_args()
    if a.self_test:
        b={20:{"value":10},50:{"value":30},200:{"value":90}}; core={"drawdown":-16,"close":90,"ma5":95,"ma200":100,"ret20":-5}; assert "洗出" in classify(b,core,None,False)[0]; print("self-test: ok")
    else: raise SystemExit(run())
