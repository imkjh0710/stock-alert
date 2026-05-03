"""
배당 분석 모듈
settings.json 의 div_years / div_min_yield / div_max_payout / div_min_consec 반영.

yf.download(actions=True) 배치는 yfinance 1.3.0에서 Dividends 컬럼 누락 버그 있음.
→ yf.Ticker(t).dividends 개별 병렬 조회 방식 사용.
"""
import json
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf


# ── 설정 로드 ─────────────────────────────────────────────────────────────
_DIV_DEFAULTS = {
    "div_years":              5,   # 배당성장률 계산 기간 (년)
    "div_min_dgr":            0,   # 최소 배당성장률 (%)
    "div_min_yield":          1,   # 최소 배당률 (%)
    "div_max_payout":        85,   # 최대 배당성향 (%)
    "div_min_consec":         3,   # 최소 연속 배당 증가 연수
    "div_min_price_growth": -50,   # 최소 주가성장률 (%, -50 = 사실상 미적용)
}

def _load_div_settings() -> dict:
    path = Path(__file__).parent / "settings.json"
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                merged = {**_DIV_DEFAULTS, **json.load(f)}
                return {k: merged[k] for k in _DIV_DEFAULTS}
        except Exception:
            pass
    return _DIV_DEFAULTS.copy()


# ── 배당 히스토리 개별 병렬 조회 ────────────────────────────────────────
def _get_one(ticker: str) -> tuple[str, dict | None]:
    """단일 종목의 배당 + 종가 히스토리 조회"""
    try:
        t    = yf.Ticker(ticker)
        divs = t.dividends
        if divs is None or len(divs) < 4:
            return ticker, None

        tz = divs.index.tz
        cutoff3y = (
            pd.Timestamp.now(tz=tz) if tz else pd.Timestamp.now()
        ) - pd.DateOffset(years=3)
        if len(divs[divs.index >= cutoff3y]) < 2:
            return ticker, None

        hist = t.history(period="11y")
        if hist.empty or "Close" not in hist.columns:
            return ticker, None

        return ticker, {
            "dividends": divs[divs > 0],
            "close":     hist["Close"].dropna(),
        }
    except Exception:
        return ticker, None


def fetch_dividend_history(
    tickers: list[str], max_workers: int = 8
) -> dict[str, dict]:
    results: dict[str, dict] = {}
    total = len(tickers)
    done  = 0

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(_get_one, t): t for t in tickers}
        for fut in as_completed(futs):
            ticker, data = fut.result()
            done += 1
            if data:
                results[ticker] = data
            if done % 300 == 0:
                print(f"    진행 {done}/{total}개 (배당주 {len(results)}개 발견)")

    return results


# ── 메트릭 계산 ──────────────────────────────────────────────────────────
def _annual_divs(div_series: pd.Series) -> pd.Series:
    return div_series.groupby(div_series.index.year).sum()


def calc_dgr(annual: pd.Series, years: int) -> tuple[float | None, bool]:
    """DGR CAGR 계산. (dgr%, is_estimated)"""
    if len(annual) < 2:
        return None, False

    now = datetime.now()
    end_year = (now.year - 1) if now.month < 10 else now.year

    avail = sorted(annual.index)
    end_cands = [y for y in avail if y <= end_year]
    if not end_cands:
        return None, False
    end_year = end_cands[-1]

    target_start = end_year - years
    is_estimated = False

    if target_start in annual.index:
        start_year = target_start
    else:
        start_cands = [y for y in avail if y < end_year]
        if not start_cands:
            return None, False
        start_year   = start_cands[0]
        is_estimated = True

    actual_years = end_year - start_year
    if actual_years <= 0:
        return None, False

    sv, ev = float(annual[start_year]), float(annual[end_year])
    if sv <= 0 or ev <= 0:
        return None, False

    dgr = ((ev / sv) ** (1 / actual_years) - 1) * 100
    return round(dgr, 1), is_estimated


def calc_consecutive_growth(annual: pd.Series) -> int:
    now   = datetime.now()
    years = sorted(annual.index)
    if years and years[-1] == now.year and now.month < 10:
        years = years[:-1]
    if len(years) < 2:
        return 0

    count = 0
    for i in range(len(years) - 1, 0, -1):
        curr = float(annual[years[i]])
        prev = float(annual[years[i - 1]])
        if prev > 0 and curr >= prev * 1.001:
            count += 1
        else:
            break
    return count


def had_div_cut(annual: pd.Series, lookback: int = 5) -> bool:
    now    = datetime.now()
    recent = annual[annual.index >= now.year - lookback]
    yrs    = sorted(recent.index)
    for i in range(1, len(yrs)):
        prev = float(recent[yrs[i - 1]])
        curr = float(recent[yrs[i]])
        if prev > 0 and curr < prev * 0.95:
            return True
    return False


def ttm_div(div_series: pd.Series) -> float:
    try:
        tz     = div_series.index.tz
        cutoff = (
            pd.Timestamp.now(tz=tz) if tz else pd.Timestamp.now()
        ) - pd.DateOffset(years=1)
        return float(div_series[div_series.index >= cutoff].sum())
    except Exception:
        return float(div_series.tail(4).sum())


# ── Payout / FCF 병렬 조회 ───────────────────────────────────────────────
def _fetch_one_info(ticker: str) -> tuple[str, dict]:
    try:
        info = yf.Ticker(ticker).info
        per  = info.get("trailingPE")
        pbr  = info.get("priceToBook")
        return ticker, {
            "payoutRatio":              info.get("payoutRatio"),
            "fiveYearAvgDividendYield": info.get("fiveYearAvgDividendYield"),
            "freeCashflow":             info.get("freeCashflow"),
            "sharesOutstanding":        info.get("sharesOutstanding"),
            "trailingPE":               per,
            "priceToBook":              pbr,
        }
    except Exception:
        return ticker, {}


def fetch_payout_info(tickers: list[str], max_workers: int = 4) -> dict[str, dict]:
    results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(_fetch_one_info, t): t for t in tickers}
        done  = 0
        total = len(tickers)
        for fut in as_completed(futs):
            t, info = fut.result()
            results[t] = info
            done += 1
            if done % 50 == 0:
                print(f"    payout info {done}/{total}...")
    return results


# ── 점수 계산 ──────────────────────────────────────────────────────────
def score_dividend(metrics: dict) -> tuple[float, str]:
    score     = 0.0
    dgr_long  = metrics.get("dgr_long")
    dgr_short = metrics.get("dgr_short")
    consec    = metrics.get("consecutive_growth", 0)
    cut       = metrics.get("had_cut", False)
    yld       = metrics.get("yield_ttm") or 0
    payout    = metrics.get("payout_ratio")     # 0~1 범위
    avg5      = metrics.get("five_yr_avg_yield") or 0
    fcf_pay   = metrics.get("fcf_payout")       # 0~∞ (1.0 = FCF 100% 소진)

    # ── 1. DGR 장기 ────────────────────────────────────────────────────
    if dgr_long is not None:
        if   dgr_long >= 20: score += 8
        elif dgr_long >= 15: score += 6
        elif dgr_long >= 10: score += 5
        elif dgr_long >=  5: score += 3
        elif dgr_long >=  0: score += 1
        else:                score -= 6

    # ── 2. 성장 가속화 (단기 DGR vs 장기 DGR) ─────────────────────────
    if dgr_short is not None and dgr_long is not None:
        diff = dgr_short - dgr_long
        if   diff >=  5: score += 3
        elif diff >=  2: score += 1
        elif diff <= -5: score -= 3
        elif diff <= -2: score -= 1

    # ── 3. 연속 증가 / 배당 컷 ────────────────────────────────────────
    if cut:
        score -= 5
    elif consec >= 50: score += 8
    elif consec >= 25: score += 5
    elif consec >= 10: score += 3
    elif consec >=  5: score += 1

    # ── 4. 현재 배당률 ────────────────────────────────────────────────
    payout_ok = payout is None or payout < 0.70
    if   yld > 5 and payout_ok:  score += 2
    elif yld >= 3 and payout_ok: score += 1
    if avg5 > 0 and yld > avg5:  score += 1  # 현재 저평가 (yield 높음)

    # ── 5. FCF 배당성향 기반 지속가능성 ──────────────────────────────
    if fcf_pay is not None:
        if   fcf_pay < 0.30: score += 2   # FCF 30% 이하 → 매우 안전
        elif fcf_pay < 0.50: score += 1   # FCF 50% 이하 → 안전
        elif fcf_pay > 2.00: score -= 5   # FCF 2배 초과 → 매우 위험
        elif fcf_pay > 1.50: score -= 3   # FCF 1.5배 초과 → 위험
        elif fcf_pay > 1.00: score -= 1   # FCF 초과 → 주의

    if   score >= 15: grade = "🌟 최우수"
    elif score >= 10: grade = "🟢🟢 우수"
    elif score >=  5: grade = "🟢 양호"
    elif score >=  0: grade = "⚪ 보통"
    else:             grade = "🔴 주의"

    return round(score, 1), grade


# ── 전체 분석 파이프라인 ────────────────────────────────────────────────
def analyze_dividends(all_tickers: list[str], apply_filter: bool = True) -> list[dict]:
    """
    배당 지급 종목 필터링 → 메트릭 계산 → 점수화 → 설정 기반 필터 적용.
    apply_filter=False 이면 필터 없이 배당 지급 종목 전체 반환 (보유 종목용).
    반환: 점수 내림차순 리스트
    """
    cfg              = _load_div_settings()
    div_years        = max(2, int(cfg["div_years"]))
    short_years      = max(1, div_years // 2)
    min_dgr          = float(cfg["div_min_dgr"])
    min_yield        = float(cfg["div_min_yield"])
    max_payout       = float(cfg["div_max_payout"]) / 100.0
    min_consec       = int(cfg["div_min_consec"])
    min_price_growth = float(cfg["div_min_price_growth"])

    print(f"  설정: 배당성장률 {div_years}년/{short_years}년  최소성장률 {min_dgr}%  "
          f"최소배당률 {min_yield}%  최대배당성향 {cfg['div_max_payout']}%  "
          f"최소연속 {min_consec}년  최소주가성장률 {min_price_growth}%")

    print(f"▶ 배당 히스토리 다운로드 ({len(all_tickers)}개 종목)...")
    hist = fetch_dividend_history(all_tickers)
    print(f"  배당 지급 종목: {len(hist)}개\n")

    print("▶ Payout / FCF 정보 조회 중...")
    info_map = fetch_payout_info(list(hist.keys()), max_workers=4)
    print(f"  완료: {len(info_map)}개\n")

    print("▶ 배당 메트릭 계산 중...")
    results: list[dict] = []
    hist_items = list(hist.items())
    del hist

    for ticker, data in hist_items:
        try:
            divs   = data["dividends"]
            close  = data["close"]
            info   = info_map.get(ticker, {})
            annual = _annual_divs(divs)

            dgr_l, est_l = calc_dgr(annual, div_years)
            dgr_s, est_s = calc_dgr(annual, short_years)
            consec        = calc_consecutive_growth(annual)
            cut           = had_div_cut(annual)
            ttm           = ttm_div(divs)
            curr_price    = float(close.iloc[-1]) if len(close) > 0 else None
            yld_ttm       = (ttm / curr_price * 100) if (curr_price and curr_price > 0) else 0.0

            payout = info.get("payoutRatio")
            avg5   = info.get("fiveYearAvgDividendYield") or 0

            # FCF 기반 배당 지속가능성
            fcf_payout = None
            fcf    = info.get("freeCashflow")
            shares = info.get("sharesOutstanding")
            if fcf and fcf > 0 and shares and shares > 0 and ttm > 0:
                total_div  = ttm * shares
                fcf_payout = round(total_div / fcf, 3)

            # 1~5년 전 대비 현재 주가 수익률
            price_growths: dict[int, float | None] = {}
            if curr_price and len(close) > 1:
                now_ts = pd.Timestamp.now(tz=close.index.tz) if close.index.tz else pd.Timestamp.now()
                for yr in range(1, 6):
                    try:
                        past = close[close.index <= now_ts - pd.DateOffset(years=yr)]
                        if len(past) > 0:
                            past_px = float(past.iloc[-1])
                            if past_px > 0:
                                price_growths[yr] = round((curr_price / past_px - 1) * 100, 1)
                    except Exception:
                        pass

            # PER / PBR
            _per = info.get("trailingPE")
            _pbr = info.get("priceToBook")

            metrics = {
                "dgr_long":            dgr_l,
                "dgr_long_estimated":  est_l,
                "dgr_long_years":      div_years,
                "dgr_short":           dgr_s,
                "dgr_short_estimated": est_s,
                "dgr_short_years":     short_years,
                "consecutive_growth":  consec,
                "had_cut":             cut,
                "yield_ttm":           round(yld_ttm, 2),
                "payout_ratio":        payout,
                "fcf_payout":          fcf_payout,
                "price_growth_1y":     price_growths.get(1),
                "price_growth_2y":     price_growths.get(2),
                "price_growth_3y":     price_growths.get(3),
                "price_growth_4y":     price_growths.get(4),
                "price_growth_5y":     price_growths.get(5),
                "five_yr_avg_yield":   avg5,
                "ttm_div":             round(ttm, 4),
                "current_price":       round(curr_price, 2) if curr_price else None,
                "per":                 round(float(_per), 1) if _per and float(_per) > 0 else None,
                "pbr":                 round(float(_pbr), 2) if _pbr and float(_pbr) > 0 else None,
            }

            score, grade = score_dividend(metrics)
            results.append({"ticker": ticker, "score": score, "grade": grade, **metrics})
        except Exception:
            pass

    print(f"  완료: {len(results)}개 분석됨")

    # ── 설정 기반 필터 (apply_filter=True 일 때만 적용) ─────────────────
    if apply_filter:
        before = len(results)
        results = [
            r for r in results
            if (r.get("yield_ttm") or 0) >= min_yield
            and (min_consec == 0 or r.get("consecutive_growth", 0) >= min_consec)
            and (r.get("fcf_payout") is None or r.get("fcf_payout") <= max_payout)
            and (r.get("dgr_long") is None or (r.get("dgr_long") or -999) >= min_dgr)
            and (min_price_growth <= -50
                 or all(r.get(f"price_growth_{y}y") is None for y in range(1, 6))
                 or any((r.get(f"price_growth_{y}y") or -999) >= min_price_growth
                        for y in range(1, 6)))
        ]
        print(f"  필터 후: {len(results)}개 ({before - len(results)}개 제외)\n")

    return sorted(results, key=lambda x: x["score"], reverse=True)
