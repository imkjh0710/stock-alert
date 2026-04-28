"""
종목 유니버스 관리 — S&P 500 + Russell 3000, 주 1회 캐싱
"""
import json
import os
import time
from datetime import datetime, timedelta
from io import StringIO

import pandas as pd
import requests

from config import (
    CACHE_DIR, UNIVERSE_CACHE, UNIVERSE_REFRESH_DAYS,
    SP500_URL, SP400_URL, SP600_URL, IWV_URL, ETF_TICKERS,
)


_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def _wiki_tickers(url: str) -> list[str]:
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=30)
        resp.raise_for_status()
        tables = pd.read_html(StringIO(resp.text), flavor="lxml")
        df = tables[0]
        # Wikipedia 표마다 컬럼명이 조금씩 다름
        col = next(
            (c for c in df.columns if "symbol" in str(c).lower() or "ticker" in str(c).lower()),
            None,
        )
        if col is None:
            return []
        return (
            df[col]
            .astype(str)
            .str.replace(".", "-", regex=False)
            .str.strip()
            .tolist()
        )
    except Exception as e:
        print(f"    Wikipedia 스크래핑 실패: {e}")
        return []


def _iwv_tickers() -> list[str]:
    """iShares IWV ETF 보유 종목 (Russell 3000 기준)"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Referer": "https://www.ishares.com/us/products/239714/",
        }
        resp = requests.get(IWV_URL, headers=headers, timeout=30)
        resp.raise_for_status()
        lines = resp.text.splitlines()
        # CSV 헤더 행 찾기
        start = next(
            (i for i, l in enumerate(lines) if "Ticker" in l or "ticker" in l), None
        )
        if start is None:
            return []
        df = pd.read_csv(StringIO("\n".join(lines[start:])))
        col = next((c for c in df.columns if "ticker" in c.lower()), None)
        if col is None:
            return []
        tickers = df[col].dropna().astype(str)
        return tickers[tickers.str.match(r"^[A-Z]{1,5}$")].tolist()
    except Exception as e:
        print(f"    IWV 다운로드 실패: {e}")
        return []


def get_etf_tickers() -> list[str]:
    """고정 ETF 리스트 반환"""
    return list(ETF_TICKERS)


def get_universe(force_refresh: bool = False) -> tuple[list[str], list[str]]:
    """
    (전체 종목 리스트, S&P 500 종목 리스트) 반환.
    캐시가 7일 이내면 캐시 사용.
    """
    os.makedirs(CACHE_DIR, exist_ok=True)

    if not force_refresh and os.path.exists(UNIVERSE_CACHE):
        with open(UNIVERSE_CACHE, encoding="utf-8") as f:
            cached = json.load(f)
        age = datetime.now() - datetime.fromisoformat(cached["timestamp"])
        if age < timedelta(days=UNIVERSE_REFRESH_DAYS):
            print(f"  캐시 사용 중 (마지막 갱신: {cached['timestamp'][:10]})")
            return cached["tickers"], cached["sp500"]

    print("  유니버스 갱신 시작...")

    sp500 = _wiki_tickers(SP500_URL)
    print(f"    S&P 500: {len(sp500)}개")
    time.sleep(1)

    # Russell 3000: iShares IWV 시도 → 실패 시 S&P 400+600 대체
    russell = _iwv_tickers()
    if len(russell) < 500:
        print("    IWV 불충분 → S&P 400/600 대체 사용")
        russell = _wiki_tickers(SP400_URL)
        time.sleep(1)
        russell += _wiki_tickers(SP600_URL)
    print(f"    Russell/Extended: {len(russell)}개")

    all_tickers = sorted(set(sp500 + russell))
    print(f"    합산 유니버스: {len(all_tickers)}개")

    with open(UNIVERSE_CACHE, "w", encoding="utf-8") as f:
        json.dump(
            {"timestamp": datetime.now().isoformat(), "tickers": all_tickers, "sp500": sp500},
            f,
        )

    return all_tickers, sp500
