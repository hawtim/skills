#!/usr/bin/env python3
"""Daily STAR 50 breadth / human-extremes monitor."""
from __future__ import annotations
import argparse, json, math, statistics, subprocess, sys, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]; TZ=ZoneInfo("Asia/Shanghai")
PLATE="SH.000688"; PLATE_SCRIPT=Path("/Users/icemelon/.agents/skills/futuapi/scripts/quote/get_plate_stock.py")
KLINE_SCRIPT=Path("/Users/icemelon/.agents/skills/futuapi/scripts/quote/get_kline.py")
URL="https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,300,qfq"; WINDOWS=(5,10,20,50,200); BOUNDS={20:(15,85),50:(25,80),200:(15,85)}

def fetch(url):
    q=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 star50-monitor"})
    with urllib.request.urlopen(q,timeout=20) as r:return r.read().decode("utf-8","replace")
def ticker(code):
    a,b=code.split(".",1);return a.lower()+b
def series(code):
    p=json.loads(fetch(URL.format(code=code))); rows=p.get("data",{}).get(code,{}).get("qfqday") or []
    clean=[]
    for row in rows:
        try:
            d,c=date.fromisoformat(row[0]),float(row[2])
            if math.isfinite(c):clean.append((d,c))
        except (IndexError,ValueError,TypeError):pass
    now=datetime.now(TZ)
    if clean and clean[-1][0]==now.date() and (now.hour,now.minute)<(15,10):clean.pop()
    if len(clean)<20:raise RuntimeError(f"历史仅{len(clean)}日")
    return {"dates":[x[0] for x in clean],"closes":[x[1] for x in clean]}
def mean(x,n):return statistics.fmean(x[-n:]) if len(x)>=n else None
def breadth(rows,prices,n,asof=None):
    good=[]
    for r in rows:
        s=prices.get(r["code"])
        if not s:continue
        end=len(s["dates"]) if asof is None else next((i for i,d in enumerate(s["dates"]) if d>asof),len(s["dates"]))
        x=s["closes"][:end]
        if mean(x,n) is not None:good.append(x)
    return {"value":100*sum(x[-1]>mean(x,n) for x in good)/len(good) if good else None,"above":sum(x[-1]>mean(x,n) for x in good),"count":len(good),"coverage":100*len(good)/len(rows) if rows else 0}
def index_series():
    r=subprocess.run([sys.executable,str(KLINE_SCRIPT),"SH.000688","--ktype","1d","--start","2025-01-01","--end","2026-12-31","--num","300","--json"],text=True,capture_output=True,timeout=45)
    for line in reversed(r.stdout.splitlines()):
        try:
            rows=json.loads(line).get("data") or []
            clean=[(date.fromisoformat(str(x["time"])[:10]),float(x["close"])) for x in rows]
            now=datetime.now(TZ)
            if clean and clean[-1][0]==now.date() and (now.hour,now.minute)<(15,10):clean.pop()
            if len(clean)>=200:return {"dates":[x[0] for x in clean],"closes":[x[1] for x in clean]}
        except (json.JSONDecodeError,KeyError,TypeError,ValueError):pass
    raise RuntimeError("科创50指数日线不可用")
def stock_series(ticker_code, futu_code):
    try:return series(ticker_code)
    except RuntimeError:
        r=subprocess.run([sys.executable,str(KLINE_SCRIPT),futu_code,"--ktype","1d","--start","2025-01-01","--end","2026-12-31","--num","300","--json"],text=True,capture_output=True,timeout=45)
        for line in reversed(r.stdout.splitlines()):
            try:
                rows=json.loads(line).get("data") or []
                clean=[(date.fromisoformat(str(x["time"])[:10]),float(x["close"])) for x in rows]
                now=datetime.now(TZ)
                if clean and clean[-1][0]==now.date() and (now.hour,now.minute)<(15,10):clean.pop()
                if len(clean)>=20:return {"dates":[x[0] for x in clean],"closes":[x[1] for x in clean]}
            except (json.JSONDecodeError,KeyError,TypeError,ValueError):pass
        raise RuntimeError("腾讯/富途日线不可用")
def gauge(v,l,h):
    if v is None:return "UNAVAILABLE"
    s=["─"]*25;s[round(l*.24)]="┊";s[round(h*.24)]="┊";s[round(v*.24)]="●";return "".join(s)
def fmt(v,s="%"):return "UNAVAILABLE" if v is None else f"{v:.2f}{s}"
def universe():
    r=subprocess.run([sys.executable,str(PLATE_SCRIPT),PLATE,"--limit","100","--json"],text=True,capture_output=True,timeout=45)
    for line in reversed(r.stdout.splitlines()):
        try:
            x=json.loads(line)
            if "data" in x and len(x["data"])>=45:return x["data"]
        except json.JSONDecodeError:pass
    raise RuntimeError("科创50成分股不可用")
def run():
    today=datetime.now(TZ).date(); rows=universe(); prices={}; errors=[]
    with ThreadPoolExecutor(max_workers=6) as pool:
        jobs={pool.submit(stock_series,ticker(r["code"]),r["code"]):r["code"] for r in rows}
        for f in as_completed(jobs):
            try:prices[jobs[f]]=f.result()
            except Exception as e:errors.append(f"{jobs[f]}: {e}")
    index=index_series(); b={n:breadth(rows,prices,n) for n in WINDOWS}; prior=breadth(rows,prices,20,index["dates"][-2])["value"]
    close=index["closes"][-1]; ma5=mean(index["closes"],5); ma200=mean(index["closes"],200); high=max(index["closes"][-252:]); wash=b[20]["value"] is not None and b[20]["value"]<=15; repair=close>=ma5; rebound=prior is not None and b[20]["value"]>=prior+5
    if b[20]["coverage"]<75:state="数据不足 / 不作极端判断"
    elif wash and repair and rebound:state="科创50短线底部（确认改善）"
    elif wash:state="科创50短线洗出（底部候选）"
    elif b[20]["value"]>=85 and close>=ma5 and close/high>=.97:state="科创50顶部人性极端（警戒）"
    else:state="科创50未进入人性极端"
    lines=[f"# 科创50人性极端监测｜{today}","","## 今日结论","",f"**{state}**","","基于当前科创50成分股的等权宽度；不是交易指令。","","## 宽度位置","","| 周期 | 读数（股票数） | 位置图 | 极端线 |","|---|---:|---|---|"]
    for n in WINDOWS:
        x=b[n]
        if n in BOUNDS:l,h=BOUNDS[n];pos=f"`{gauge(x['value'],l,h)}`";line=f"{l}% / {h}%"
        else:pos="—";line="观察值"
        lines.append(f"| {n}日 | {fmt(x['value'])}（{x['above']}/{x['count']}，覆盖{x['coverage']:.1f}%） | {pos} | {line} |")
    lines += ["","## 指数趋势与确认","",f"- 科创50收盘 {close:.2f}（观测日 {index['dates'][-1]}），距252日高点 {100*(close/high-1):.2f}%。",f"- 短线洗出：{'已触发' if wash else '未触发'}（20日≤15%）；价格修复：{'已触发' if repair else '未触发'}；宽度回升：{'已触发' if rebound else '未触发'}。","","## 数据来源与覆盖","",f"- 成分股：富途 SH.000688，共{len(rows)}只；日线：腾讯 qfq 主源、富途备用。", "- 未覆盖："+("；".join(errors) if errors else "无")]
    body="\n".join(lines)+"\n"; (ROOT/"reports").mkdir(exist_ok=True);(ROOT/"data").mkdir(exist_ok=True)
    (ROOT/"reports"/f"star50-human-extremes-{today}.md").write_text(body,encoding="utf-8");(ROOT/"data"/f"universe-{today}.json").write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding="utf-8")
    snapshot={"report_date":str(today),"observation_date":str(index["dates"][-1]),"state":state,"breadth":b,"index":{"close":close,"ma5":ma5,"ma200":ma200,"drawdown_252d_pct":100*(close/high-1)},"errors":errors}
    (ROOT/"data"/"latest_snapshot.json").write_text(json.dumps(snapshot,ensure_ascii=False,indent=2),encoding="utf-8")
    history=ROOT/"data"/"history.jsonl"; existing=[]
    if history.exists():existing=[x for x in history.read_text(encoding="utf-8").splitlines() if x and json.loads(x).get("report_date")!=str(today)]
    history.write_text("\n".join(existing+[json.dumps(snapshot,ensure_ascii=False)])+"\n",encoding="utf-8");print(body)
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--self-test",action="store_true");a=p.parse_args()
    if a.self_test:assert breadth([],{},20)["value"] is None;print("self-test: ok")
    else:run()
