"""
미국 장 오픈(+30분) / 마감 자동 알람
- open  : 10:00 AM ET (장 오픈 30분 후)
- close : 4:00 PM ET  (장 마감)
- auto  : 현재 ET 시간을 보고 open/close 자동 판단 (기본값)

실행 방법:
    venv/Scripts/python market_alert.py [open|close|auto]
"""
import json
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

from notifier import send_message

# ── 타임존 ────────────────────────────────────────────────────────────────
ET  = ZoneInfo("America/New_York")
KST = ZoneInfo("Asia/Seoul")

# ── 고정 티커 리스트 ──────────────────────────────────────────────────────
_INDICES = ["SPY", "QQQ", "DIA", "IWM"]
_SECTORS = ["XLK", "XLF", "XLE", "XLV", "XLI", "XLP", "XLY", "XLU", "XLB", "XLRE", "XLC"]

_MAX_LEN = 4096


# ── 유틸 ─────────────────────────────────────────────────────────────────
def _load_holdings() -> list[str]:
    env = os.getenv("MY_HOLDINGS")
    if env:
        try:
            return [h["ticker"] for h in json.loads(env)]
        except Exception:
            pass
    if os.path.exists("holdings.json"):
        with open("holdings.json", encoding="utf-8") as f:
            return [h["ticker"] for h in json.load(f)]
    return []


def _detect_alert_type() -> str | None:
    """현재 ET 시간 기반으로 open/close 자동 판단"""
    now_et = datetime.now(ET)
    # 평일만
    if now_et.weekday() >= 5:
        return None
    total_min = now_et.hour * 60 + now_et.minute
    # 09:45 ~ 10:30 → open
    if 9 * 60 + 45 <= total_min <= 10 * 60 + 30:
        return "open"
    # 15:45 ~ 16:30 → close
    if 15 * 60 + 45 <= total_min <= 16 * 60 + 30:
        return "close"
    return None


# ── 시세 다운로드 ─────────────────────────────────────────────────────────
def _extract_df(raw: pd.DataFrame, ticker: str, tickers: list) -> pd.DataFrame | None:
    """MultiIndex / 단일 DataFrame 공통 추출"""
    if isinstance(raw.columns, pd.MultiIndex):
        for level in (1, 0):
            try:
                sub = raw.xs(ticker, axis=1, level=level)
                if "Close" in sub.columns:
                    return sub
            except KeyError:
                continue
        return None
    else:
        if len(tickers) == 1:
            return raw
        return None


def fetch_snapshots(tickers: list[str]) -> dict[str, dict]:
    """
    당일 스냅샷 반환.
    {ticker: {open, high, low, close, prev_close, change_pct, gap_pct}}
    """
    if not tickers:
        return {}
    try:
        raw = yf.download(
            " ".join(tickers),
            period="2d",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
    except Exception as e:
        print(f"  시세 다운로드 오류: {e}")
        return {}

    snapshots: dict[str, dict] = {}
    for ticker in tickers:
        try:
            df = _extract_df(raw, ticker, tickers)
            if df is None or len(df) < 1:
                continue
            df = df.dropna(how="all")
            if len(df) < 1:
                continue

            today     = df.iloc[-1]
            prev_row  = df.iloc[-2] if len(df) >= 2 else today
            prev_close = float(prev_row["Close"])
            curr_close = float(today["Close"])
            gap_pct    = (float(today["Open"]) - prev_close) / prev_close * 100 if prev_close else 0

            snapshots[ticker] = {
                "open":       float(today["Open"]),
                "high":       float(today["High"]),
                "low":        float(today["Low"]),
                "close":      curr_close,
                "prev_close": prev_close,
                "change_pct": (curr_close - prev_close) / prev_close * 100 if prev_close else 0,
                "gap_pct":    gap_pct,
            }
        except Exception:
            pass
    return snapshots


# ── 메시지 포맷 ──────────────────────────────────────────────────────────
def _chg(pct: float) -> str:
    arrow = "▲" if pct >= 0 else "▼"
    return f"{arrow}{abs(pct):.1f}%"


def _split(text: str) -> list[str]:
    chunks, buf = [], ""
    for line in text.splitlines(keepends=True):
        if len(buf) + len(line) > _MAX_LEN:
            chunks.append(buf)
            buf = ""
        buf += line
    if buf:
        chunks.append(buf)
    return chunks


def build_open_alert(
    now_et: datetime,
    snap_idx: dict, snap_sec: dict, snap_hold: dict, holdings: list[str]
) -> list[str]:
    kst_str = datetime.now(KST).strftime("%m/%d %H:%M")
    et_str  = now_et.strftime("%H:%M")

    header = (
        f"📈 <b>미국 장 오픈 +30분 알람</b>\n"
        f"🕙 {et_str} ET  |  🇰🇷 {kst_str} KST\n"
    )

    # ── 주요 지수 ────────────────────────────────────────────────────
    body = "\n📊 <b>지수 현황</b>\n"
    for t in _INDICES:
        if t not in snap_idx:
            continue
        s   = snap_idx[t]
        gap = s["gap_pct"]
        gap_str = f"  갭 {gap:+.1f}%" if abs(gap) >= 0.3 else ""
        body += f"  <b>{t}</b>  ${s['close']:.2f}  ({_chg(s['change_pct'])}){gap_str}\n"

    # ── 섹터 ETF (변동 상위 6개) ─────────────────────────────────────
    if snap_sec:
        top_sec = sorted(snap_sec.items(), key=lambda x: abs(x[1]["change_pct"]), reverse=True)[:6]
        body += "\n🗂 <b>섹터 ETF (변동 큰 순)</b>\n"
        for t, s in top_sec:
            body += f"  <b>{t}</b>  ${s['close']:.2f}  ({_chg(s['change_pct'])})\n"

    # ── 갭 상승/하락 종목 (indices+sectors 제외) ─────────────────────
    all_snap = {**snap_idx, **snap_sec, **snap_hold}
    gap_up   = sorted(
        [(t, s) for t, s in all_snap.items() if s["gap_pct"] >= 2.0],
        key=lambda x: x[1]["gap_pct"], reverse=True,
    )[:5]
    gap_down = sorted(
        [(t, s) for t, s in all_snap.items() if s["gap_pct"] <= -2.0],
        key=lambda x: x[1]["gap_pct"],
    )[:5]

    if gap_up:
        body += "\n💥 <b>갭 상승 2%+</b>\n"
        for t, s in gap_up:
            body += f"  <b>{t}</b>  갭 {s['gap_pct']:+.1f}%  →  현재 {_chg(s['change_pct'])}\n"
    if gap_down:
        body += "\n📉 <b>갭 하락 2%-</b>\n"
        for t, s in gap_down:
            body += f"  <b>{t}</b>  갭 {s['gap_pct']:+.1f}%  →  현재 {_chg(s['change_pct'])}\n"

    # ── 보유 종목 ────────────────────────────────────────────────────
    if holdings and snap_hold:
        body += "\n⭐ <b>내 보유 종목</b>\n"
        for t in holdings:
            if t not in snap_hold:
                continue
            s = snap_hold[t]
            gap_str = f"  (갭 {s['gap_pct']:+.1f}%)" if abs(s["gap_pct"]) >= 0.5 else ""
            body += f"  <b>{t}</b>  ${s['close']:.2f}  ({_chg(s['change_pct'])}){gap_str}\n"

    return _split(header + body)


def build_close_alert(
    now_et: datetime,
    snap_idx: dict, snap_sec: dict, snap_hold: dict, holdings: list[str]
) -> list[str]:
    kst_str = datetime.now(KST).strftime("%m/%d %H:%M")
    et_str  = now_et.strftime("%H:%M")

    header = (
        f"🔔 <b>미국 장 마감 알람</b>\n"
        f"🕓 {et_str} ET  |  🇰🇷 {kst_str} KST\n"
    )

    # ── 지수 마감 (고점/저점 포함) ───────────────────────────────────
    body = "\n📊 <b>지수 마감</b>\n"
    for t in _INDICES:
        if t not in snap_idx:
            continue
        s = snap_idx[t]
        body += (
            f"  <b>{t}</b>  ${s['close']:.2f}  ({_chg(s['change_pct'])})"
            f"  H${s['high']:.2f} / L${s['low']:.2f}\n"
        )

    # ── 섹터 상승/하락 ───────────────────────────────────────────────
    up_sec   = sorted([(t, s) for t, s in snap_sec.items() if s["change_pct"] >= 0],
                      key=lambda x: x[1]["change_pct"], reverse=True)
    down_sec = sorted([(t, s) for t, s in snap_sec.items() if s["change_pct"] < 0],
                      key=lambda x: x[1]["change_pct"])
    if up_sec:
        parts = [f"<b>{t}</b> {_chg(s['change_pct'])}" for t, s in up_sec[:5]]
        body += "\n📈 <b>섹터 상승</b>  " + "  ".join(parts) + "\n"
    if down_sec:
        parts = [f"<b>{t}</b> {_chg(s['change_pct'])}" for t, s in down_sec[:5]]
        body += "📉 <b>섹터 하락</b>  " + "  ".join(parts) + "\n"

    # ── 보유 종목 오늘 성과 (수익률 정렬) ───────────────────────────
    if holdings and snap_hold:
        body += "\n⭐ <b>내 보유 종목 오늘 성과</b>\n"
        ranked = sorted(
            [t for t in holdings if t in snap_hold],
            key=lambda t: snap_hold[t]["change_pct"],
            reverse=True,
        )
        for t in ranked:
            s = snap_hold[t]
            body += (
                f"  <b>{t}</b>  ${s['close']:.2f}  ({_chg(s['change_pct'])})"
                f"  H${s['high']:.2f} / L${s['low']:.2f}\n"
            )

    return _split(header + body)


# ── 메인 ─────────────────────────────────────────────────────────────────
def main():
    alert_type = sys.argv[1] if len(sys.argv) > 1 else "auto"
    now_et     = datetime.now(ET)

    if alert_type == "auto":
        alert_type = _detect_alert_type()
        if alert_type is None:
            print(f"현재 ET {now_et:%H:%M} — 알람 대상 시간 아님. 종료.")
            return

    print(f"[{now_et:%Y-%m-%d %H:%M} ET]  '{alert_type}' 알람 실행")

    holdings    = _load_holdings()
    all_tickers = list(dict.fromkeys(_INDICES + _SECTORS + holdings))  # 순서 유지, 중복 제거

    print(f"  시세 조회 중... ({len(all_tickers)}개)")
    snapshots = fetch_snapshots(all_tickers)

    snap_idx  = {t: s for t, s in snapshots.items() if t in set(_INDICES)}
    snap_sec  = {t: s for t, s in snapshots.items() if t in set(_SECTORS)}
    snap_hold = {t: s for t, s in snapshots.items() if t in set(holdings)}

    if alert_type == "open":
        messages = build_open_alert(now_et, snap_idx, snap_sec, snap_hold, holdings)
    else:
        messages = build_close_alert(now_et, snap_idx, snap_sec, snap_hold, holdings)

    print(f"  텔레그램 전송 중... ({len(messages)}개 메시지)")
    for i, msg in enumerate(messages, 1):
        ok = send_message(msg)
        print(f"  메시지 {i}/{len(messages)}: {'✅ 성공' if ok else '❌ 실패'}")


if __name__ == "__main__":
    main()
