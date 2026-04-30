"""
배당 분석 모듈
10년치 배당 히스토리 기반 메트릭 계산 및 점수화

yf.download(actions=True) 배치는 yfinance 1.3.0에서 Dividends 컬럼 누락 버그 있음.
→ yf.Ticker(t).dividends 개별 병렬 조회 방식 사용.
"""
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import yfinance as yf


# ── 배당 히스토리 개별 병렬 조회 ────────────────────────────────────────
def _get_one(ticker: str) -> tuple[str, dict | None]:
    """단일 종목의 배당 + 종가 히스토리 조회"""
    try:
        t    = yf.Ticker(ticker)
        divs = t.dividends          # 전체 배당 히스토리 Series
        if divs is None or len(divs) < 4:
            return ticker, None

        # 최근 3년 내 배당이 없으면 비활성으로 간주
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
    """
    개별 yf.Ticker() 병렬 조회로 배당 히스토리 수집.
    반환: {ticker: {'dividends': Series, 'close': Series}}
    """
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
    """
    DGR CAGR 계산.
    Returns (dgr%, is_estimated) — is_estimated=True 면 기간 부족으로 대체
    """
    if len(annual) < 2:
        return None, False

    now = datetime.now()
    # 현재 연도가 미완성(10월 이전)이면 전년도 기준
    end_year = (now.year - 1) if now.month < 10 else now.year

    avail = sorted(annual.index)
    # end_year 이하 중 가장 최근
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
        start_year  = start_cands[0]
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
    """연속 배당 증가 연수 (현재 연도 미완성 시 제외)"""
    now = datetime.now()
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
    """최근 lookback 년 내 배당 컷(5% 이상 감소) 여부"""
    now = datetime.now()
    recent = annual[annual.index >= now.year - lookback]
    yrs = sorted(recent.index)
    for i in range(1, len(yrs)):
        prev = float(recent[yrs[i - 1]])
        curr = float(recent[yrs[i]])
        if prev > 0 and curr < prev * 0.95:
            return True
    return False


def ttm_div(div_series: pd.Series) -> float:
    """최근 12개월 배당 합계"""
    try:
        tz = div_series.index.tz
        cutoff = (
            pd.Timestamp.now(tz=tz) if tz else pd.Timestamp.now()
        ) - pd.DateOffset(years=1)
        return float(div_series[div_series.index >= cutoff].sum())
    except Exception:
        return float(div_series.tail(4).sum())


# ── Payout ratio 병렬 조회 ───────────────────────────────────────────────
def _fetch_one_info(ticker: str) -> tuple[str, dict]:
    try:
        info = yf.Ticker(ticker).info
        return ticker, {
            "payoutRatio":             info.get("payoutRatio"),
            "fiveYearAvgDividendYield": info.get("fiveYearAvgDividendYield"),
        }
    except Exception:
        return ticker, {}


def fetch_payout_info(tickers: list[str], max_workers: int = 4) -> dict[str, dict]:
    """payout ratio / 5Y avg yield 병렬 조회"""
    results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(_fetch_one_info, t): t for t in tickers}
        done = 0
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
    score  = 0.0
    dgr10  = metrics.get("dgr10")
    dgr5   = metrics.get("dgr5")
    consec = metrics.get("consecutive_growth", 0)
    cut    = metrics.get("had_cut", False)
    yld    = metrics.get("yield_ttm") or 0
    payout = metrics.get("payout_ratio")       # 0~1 범위
    avg5   = metrics.get("five_yr_avg_yield") or 0

    # ── 1. DGR 10Y ──────────────────────────────────────────────────────
    if dgr10 is not None:
        if   dgr10 >= 20: score += 8
        elif dgr10 >= 15: score += 6
        elif dgr10 >= 10: score += 5
        elif dgr10 >=  5: score += 3
        elif dgr10 >=  0: score += 1
        else:             score -= 6

    # ── 2. 성장 가속화 (5Y DGR vs 10Y DGR) ───────────────────────────
    if dgr5 is not None and dgr10 is not None:
        diff = dgr5 - dgr10
        if   diff >=  5: score += 3
        elif diff >=  2: score += 1
        elif diff <= -5: score -= 3
        elif diff <= -2: score -= 1

    # ── 3. 연속 증가 / 배당 컷 ──────────────────────────────────────
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
    if avg5 > 0 and yld > avg5:  score += 1   # 현재가 저평가 (yield 높음)

    # ── 5. 지속가능성 (payout 과다) ──────────────────────────────────
    if payout is not None:
        if   payout > 1.0: score -= 5
        elif payout > 0.9: score -= 3

    if   score >= 15: grade = "🌟 최우수"
    elif score >= 10: grade = "🟢🟢 우수"
    elif score >=  5: grade = "🟢 양호"
    elif score >=  0: grade = "⚪ 보통"
    else:             grade = "🔴 주의"

    return round(score, 1), grade


# ── 전체 분석 파이프라인 ────────────────────────────────────────────────
def analyze_dividends(all_tickers: list[str]) -> list[dict]:
    """
    배당 지급 종목 필터링 → 메트릭 계산 → 점수화.
    반환: 점수 내림차순 리스트
    """
    print(f"▶ 배당 히스토리 다운로드 ({len(all_tickers)}개 종목)...")
    hist = fetch_dividend_history(all_tickers)
    print(f"  배당 지급 종목: {len(hist)}개\n")

    print("▶ Payout ratio 조회 중...")
    info_map = fetch_payout_info(list(hist.keys()), max_workers=4)
    print(f"  완료: {len(info_map)}개\n")

    print("▶ 배당 메트릭 계산 중...")
    results: list[dict] = []

    for ticker, data in hist.items():
        try:
            divs   = data["dividends"]
            close  = data["close"]
            info   = info_map.get(ticker, {})
            annual = _annual_divs(divs)

            dgr10, est10 = calc_dgr(annual, 10)
            dgr5,  est5  = calc_dgr(annual,  5)
            consec        = calc_consecutive_growth(annual)
            cut           = had_div_cut(annual)
            ttm           = ttm_div(divs)
            curr_price    = float(close.iloc[-1]) if len(close) > 0 else None
            yld_ttm       = (ttm / curr_price * 100) if (curr_price and curr_price > 0) else 0.0

            payout = info.get("payoutRatio")
            avg5   = info.get("fiveYearAvgDividendYield") or 0

            metrics = {
                "dgr10":              dgr10,
                "dgr10_estimated":    est10,
                "dgr5":               dgr5,
                "dgr5_estimated":     est5,
                "consecutive_growth": consec,
                "had_cut":            cut,
                "yield_ttm":          round(yld_ttm, 2),
                "payout_ratio":       payout,
                "five_yr_avg_yield":  avg5,
                "ttm_div":            round(ttm, 4),
                "current_price":      round(curr_price, 2) if curr_price else None,
            }

            score, grade = score_dividend(metrics)
            results.append({"ticker": ticker, "score": score, "grade": grade, **metrics})
        except Exception:
            pass

    print(f"  완료: {len(results)}개 분석됨\n")
    return sorted(results, key=lambda x: x["score"], reverse=True)
