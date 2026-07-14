#!/usr/bin/env python3
"""Fetch optional U.S. semiconductor-option sentiment through local Futu OpenD.

This is intentionally optional: callers must not turn a local permission or
OpenD outage into a fabricated sentiment signal.
"""

from __future__ import annotations

import json
import math
from datetime import datetime


UNDERLYINGS = ("US.SOXX", "US.SMH", "US.SOXL", "US.SOXS")


def clean(value):
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return None
    return float(value) if isinstance(value, (int, float)) else value


def closest_expiry(expiries):
    candidates = [row for _, row in expiries.iterrows() if 21 <= int(row["option_expiry_date_distance"]) <= 60]
    if not candidates:
        return None
    return min(candidates, key=lambda row: abs(int(row["option_expiry_date_distance"]) - 30))


def skew(ctx, code: str):
    """Return 25-delta put IV minus 25-delta call IV, when quotes are usable."""
    ret, expiries = ctx.get_option_expiration_date(code)
    if ret != 0 or expiries is None or expiries.empty:
        return {"skew_25d": None, "skew_expiry": None, "skew_asof": None}
    expiry = closest_expiry(expiries)
    if expiry is None:
        return {"skew_25d": None, "skew_expiry": None, "skew_asof": None}
    expiry_date = str(expiry["strike_time"])
    ret, chain = ctx.get_option_chain(code, start=expiry_date, end=expiry_date)
    if ret != 0 or chain is None or chain.empty:
        return {"skew_25d": None, "skew_expiry": expiry_date, "skew_asof": None}
    ret, quotes = ctx.get_market_snapshot(chain["code"].tolist())
    if ret != 0 or quotes is None or quotes.empty:
        return {"skew_25d": None, "skew_expiry": expiry_date, "skew_asof": None}
    calls, puts = [], []
    for _, row in quotes.iterrows():
        delta, iv = clean(row.get("option_delta")), clean(row.get("option_implied_volatility"))
        if delta is None or iv is None or iv <= 0:
            continue
        if row.get("option_type") == "CALL" and delta > 0:
            calls.append((abs(delta - .25), iv, row.get("update_time")))
        elif row.get("option_type") == "PUT" and delta < 0:
            puts.append((abs(abs(delta) - .25), iv, row.get("update_time")))
    if not calls or not puts:
        return {"skew_25d": None, "skew_expiry": expiry_date, "skew_asof": None}
    call, put = min(calls), min(puts)
    return {"skew_25d": round(put[1] - call[1], 3), "skew_expiry": expiry_date, "skew_asof": max(str(call[2]), str(put[2]))}


def capital_flow(ctx, code: str):
    """Return final-session intraday net-flow proxy only after the close."""
    ret, data = ctx.get_capital_flow(code)
    if ret != 0 or data is None or data.empty:
        return {"net_flow": None, "asof": None, "is_final": False}
    row = data.iloc[-1]
    point = str(row.get("capital_flow_item_time", ""))
    try:
        observed = datetime.strptime(point, "%Y-%m-%d %H:%M:%S").time()
        is_final = (observed.hour, observed.minute) >= (15, 55)
    except ValueError:
        is_final = False
    return {"net_flow": clean(row.get("in_flow")) if is_final else None, "asof": point or None, "is_final": is_final}


def main():
    from futu import OpenQuoteContext

    ctx = OpenQuoteContext(host="127.0.0.1", port=11111)
    try:
        ret, overview = ctx.get_option_underlying_overview(list(UNDERLYINGS))
        if ret != 0:
            raise RuntimeError(str(overview))
        records = {}
        for _, row in overview.iterrows():
            code = str(row["code"])
            records[code.removeprefix("US.")] = {
                "call_volume": clean(row.get("call_volume")),
                "put_volume": clean(row.get("put_volume")),
                "call_open_interest": clean(row.get("call_open_interest")),
                "put_open_interest": clean(row.get("put_open_interest")),
                "iv": clean(row.get("iv")),
                "iv_rank": clean(row.get("iv_rank")),
                "iv_percentile": clean(row.get("iv_percentile")),
            }
        for code in ("SOXX", "SMH"):
            records.setdefault(code, {}).update(skew(ctx, f"US.{code}"))
        print(json.dumps({"underlyings": records, "soxx_capital_flow": capital_flow(ctx, "US.SOXX")}, ensure_ascii=False))
    finally:
        ctx.close()


if __name__ == "__main__":
    main()
