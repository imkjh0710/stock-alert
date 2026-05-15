"""
펀더멘털 분석 모듈
ROE / EPS 성장 / 영업이익률 / FCF 마진 기반 점수 (-12 ~ +12)
24시간 캐시: cache/fundamentals_cache.json
"""
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import yfinance as yf

_CACHE_FILE = os.path.join("cache", "fundamentals_cache.json")
_TTL_HOURS  = 24


# ── 캐시 I/O ────────────────────────────────────────────────────────────
def _load_cache() -> dict:
    if not os.path.exists(_CACHE_FILE):
        return {}
    try:
        with open(_CACHE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(cache: dict) -> None:
    os.makedirs(os.path.dirname(_CACHE_FILE), exist_ok=True)
    try:
        with open(_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
    except Exception:
        pass


def _is_fresh(entry: dict) -> bool:
    try:
        updated = datetime.strptime(entry.get("last_updated", ""), "%Y-%m-%d %H:%M")
        return datetime.now() - updated < timedelta(hours=_TTL_HOURS)
    except Exception:
        return False


# ── 개별 점수 함수 ───────────────────────────────────────────────────────
def _roe_score(roe) -> int:
    if roe is None:
        return 0
    p = roe * 100
    if p > 25:  return  3
    if p > 20:  return  2
    if p > 15:  return  1
    if p > 10:  return  0
    if p > 5:   return -1
    return -2


def _eps_score(growth) -> int:
    if growth is None:
        return 0
    p = growth * 100
    if p > 30:   return  3
    if p > 15:   return  2
    if p > 5:    return  1
    if p >= -5:  return  0
    if p >= -15: return -1
    return -3


def _margin_score(margin) -> int:
    if margin is None:
        return 0
    p = margin * 100
    if p > 30:  return  3
    if p > 20:  return  2
    if p > 10:  return  1
    if p > 5:   return  0
    if p >= 0:  return -1
    return -3


def _fcf_score(fcf, revenue) -> int:
    if fcf is None or not revenue or revenue <= 0:
        return 0
    p = fcf / revenue * 100
    if p > 25:  return  3
    if p > 15:  return  2
    if p > 5:   return  1
    if p >= 0:  return  0
    return -3


# ── 핵심 계산 함수 ───────────────────────────────────────────────────────
def calculate_fundamental_score(info: dict) -> dict:
    """
    yfinance ticker.info → 펀더멘털 점수 (-12 ~ +12).
    데이터가 전혀 없으면 fundamental_score=0, grade="데이터 없음".
    """
    roe        = info.get("returnOnEquity")
    eps_growth = info.get("earningsGrowth")
    op_margin  = info.get("operatingMargins")
    fcf        = info.get("freeCashflow")
    revenue    = info.get("totalRevenue")

    has_data = any(v is not None for v in [roe, eps_growth, op_margin, fcf])

    roe_s    = _roe_score(roe)
    eps_s    = _eps_score(eps_growth)
    margin_s = _margin_score(op_margin)
    fcf_s    = _fcf_score(fcf, revenue)
    total    = roe_s + eps_s + margin_s + fcf_s

    if not has_data:
        grade = "데이터 없음"
    elif total >= 9:    grade = "🌟 탁월"
    elif total >= 5:    grade = "🟢 우량"
    elif total >= -4:   grade = "⚪ 평범"
    elif total >= -8:   grade = "🔴 약함"
    else:               grade = "🚨 위험"

    fcf_margin = None
    if fcf is not None and revenue and revenue > 0:
        fcf_margin = round(fcf / revenue * 100, 1)

    try:
        per_raw = info.get("trailingPE")
        per_v   = round(float(per_raw), 1) if per_raw and float(per_raw) > 0 else None
    except Exception:
        per_v = None
    try:
        pbr_raw = info.get("priceToBook")
        pbr_v   = round(float(pbr_raw), 2) if pbr_raw and float(pbr_raw) > 0 else None
    except Exception:
        pbr_v = None

    return {
        "fundamental_score":     total,
        "fundamental_breakdown": {
            "roe_score":    roe_s,
            "eps_score":    eps_s,
            "margin_score": margin_s,
            "fcf_score":    fcf_s,
        },
        "fundamental_grade":    grade,
        "has_fundamental_data": has_data,
        "roe":        round(roe * 100, 1)        if roe        is not None else None,
        "eps_growth": round(eps_growth * 100, 1) if eps_growth is not None else None,
        "op_margin":  round(op_margin * 100, 1)  if op_margin  is not None else None,
        "fcf_margin": fcf_margin,
        # 참고용 (점수에 반영 안 함)
        "per":            per_v,
        "pbr":            pbr_v,
        "debt_to_equity": info.get("debtToEquity"),
    }


def _etf_result() -> dict:
    """ETF는 펀더멘털 점수 0 (해당 없음)."""
    return {
        "fundamental_score":     0,
        "fundamental_breakdown": {"roe_score": 0, "eps_score": 0, "margin_score": 0, "fcf_score": 0},
        "fundamental_grade":     "ETF",
        "has_fundamental_data":  False,
        "roe": None, "eps_growth": None, "op_margin": None, "fcf_margin": None,
        "per": None, "pbr":         None, "debt_to_equity": None,
    }


def _fetch_one(ticker: str) -> tuple[str, dict]:
    """단일 종목 펀더멘털 조회 (3회 재시도)."""
    for attempt in range(3):
        try:
            info = yf.Ticker(ticker).info or {}
            return ticker, calculate_fundamental_score(info)
        except Exception:
            if attempt < 2:
                time.sleep(2 ** attempt + 1)
    return ticker, calculate_fundamental_score({})


def fetch_fundamental_data(
    tickers: list,
    asset_types: dict | None = None,
    max_workers: int = 4,
) -> dict:
    """
    tickers 목록의 펀더멘털 데이터를 가져온다 (24시간 캐시).
    asset_types: {"SPY": "ETF", "AAPL": "STOCK"} — ETF는 즉시 0점 처리.
    반환: {ticker: fundamental_result_dict}
    """
    asset_types = asset_types or {}
    cache       = _load_cache()
    results: dict = {}
    to_fetch: list = []

    for t in tickers:
        if asset_types.get(t) == "ETF":
            results[t] = _etf_result()
            continue
        entry = cache.get(t)
        if entry and _is_fresh(entry):
            results[t] = entry["data"]
        else:
            to_fetch.append(t)

    if to_fetch:
        print(f"  펀더멘털 데이터 조회 ({len(to_fetch)}개, 캐시 미스)...")
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futs = {ex.submit(_fetch_one, t): t for t in to_fetch}
            for fut in as_completed(futs):
                t, data = fut.result()
                results[t]  = data
                cache[t]    = {"data": data, "last_updated": now_str}
        _save_cache(cache)

    return results
