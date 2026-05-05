"""
yfinance 배치 다운로드 + 품질 필터
"""
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import yfinance as yf

from config import MIN_PRICE, MIN_VOLUME, VOLUME_PERIOD


def fetch_batch(
    tickers: list[str], period: str = "1y", chunk_size: int = 100
) -> dict[str, pd.DataFrame]:
    """
    tickers 를 chunk_size 단위로 나눠 yfinance 배치 다운로드.
    반환: {ticker: OHLCV DataFrame}
    """
    all_data: dict[str, pd.DataFrame] = {}
    total = (len(tickers) + chunk_size - 1) // chunk_size

    for i in range(0, len(tickers), chunk_size):
        chunk = tickers[i : i + chunk_size]
        chunk_no = i // chunk_size + 1
        print(f"  [{chunk_no}/{total}] {len(chunk)}개 다운로드 중...")

        try:
            raw = yf.download(
                " ".join(chunk),
                period=period,
                auto_adjust=True,
                progress=False,
                threads=True,
            )
            if raw.empty:
                continue

            _extract_from_raw(raw, chunk, all_data)

        except Exception as e:
            print(f"    오류: {e}")

        time.sleep(0.5)

    return all_data


def _extract_from_raw(
    raw: pd.DataFrame, chunk: list[str], out: dict[str, pd.DataFrame]
) -> None:
    """MultiIndex / 단일 DataFrame 모두 처리"""
    if not isinstance(raw.columns, pd.MultiIndex):
        # 단일 종목
        if len(chunk) == 1 and len(raw) >= 60 and "Close" in raw.columns:
            out[chunk[0]] = raw.dropna(how="all")
        return

    # MultiIndex: (필드, 티커) 또는 (티커, 필드) 두 가지 경우 처리
    for ticker in chunk:
        df = None
        for level in (1, 0):
            try:
                candidate = raw.xs(ticker, axis=1, level=level)
                if isinstance(candidate, pd.DataFrame) and "Close" in candidate.columns:
                    df = candidate
                    break
            except KeyError:
                continue

        if df is not None:
            df = df.dropna(how="all")
            if len(df) >= 60:
                out[ticker] = df


def apply_quality_filter(
    data: dict[str, pd.DataFrame]
) -> dict[str, pd.DataFrame]:
    """
    주가 > $5, 20일 평균 거래량 > 50만 주 필터
    """
    qualified: dict[str, pd.DataFrame] = {}
    for ticker, df in data.items():
        try:
            last_close = float(df["Close"].iloc[-1])
            avg_vol = float(df["Volume"].tail(VOLUME_PERIOD).mean())
            if last_close >= MIN_PRICE and avg_vol >= MIN_VOLUME:
                qualified[ticker] = df
        except Exception:
            pass
    return qualified


def fetch_fundamentals(tickers: list[str], max_workers: int = 4) -> dict[str, dict]:
    """PER(trailingPE), PBR(priceToBook) 병렬 조회."""
    def _one(t: str) -> tuple[str, dict]:
        for attempt in range(3):
            try:
                ticker = yf.Ticker(t)
                info = ticker.info or {}
                per  = info.get("trailingPE")
                pbr  = info.get("priceToBook")

                # PER fallback: trailingEps + currentPrice
                if not (per and float(per) > 0):
                    eps   = info.get("trailingEps")
                    price = info.get("currentPrice") or info.get("regularMarketPrice")
                    if eps and price and float(eps) > 0 and float(price) > 0:
                        per = round(float(price) / float(eps), 1)

                # PBR fallback: try fast_info
                if not (pbr and float(pbr) > 0):
                    try:
                        fi = ticker.fast_info
                        pbr = getattr(fi, "price_to_book", None)
                    except Exception:
                        pass

                per_ok = per and float(per) > 0
                pbr_ok = pbr and float(pbr) > 0
                if not per_ok and not pbr_ok and attempt < 2:
                    time.sleep(2 ** attempt + 1)
                    continue

                return t, {
                    "per": round(float(per), 1) if per_ok else None,
                    "pbr": round(float(pbr), 2) if pbr_ok else None,
                }
            except Exception:
                if attempt < 2:
                    time.sleep(2 ** attempt + 1)
        return t, {"per": None, "pbr": None}

    results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(_one, t): t for t in tickers}
        for fut in as_completed(futs):
            t, data = fut.result()
            results[t] = data
    return results
