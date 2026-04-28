"""
텔레그램 메시지 빌드 및 전송

메시지 양식 (요청에서 잘렸기 때문에 아래 형식으로 구성):

📊 미국 주식 시그널 리포트
📅 2025-04-26  |  분석 종목: 2,347개

━━━ 🏆 S&P 500 TOP 50 ━━━
1. 🟢🟢  NVDA  +12점  |  $875.40  (+2.3%)  📈52주高
...

━━━ 💎 외곽 TOP 30 ━━━
1. 🟢🟢  SMCI  +13점  |  $980.00  (+5.2%)
...
"""
import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()

_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
_MAX_LEN = 4096


def send_message(text: str, retries: int = 3) -> bool:
    url = f"https://api.telegram.org/bot{_TOKEN}/sendMessage"
    for attempt in range(retries):
        try:
            resp = requests.post(
                url,
                json={"chat_id": _CHAT_ID, "text": text, "parse_mode": "HTML"},
                timeout=30,
            )
            return resp.status_code == 200
        except Exception as e:
            if attempt < retries - 1:
                wait = 5 * (attempt + 1)
                print(f"    전송 실패, {wait}초 후 재시도... ({e})")
                time.sleep(wait)
    return False


def _grade_icon(score: float) -> str:
    if score >= 8:    return "🟢🟢"
    if score >= 4:    return "🟢"
    if score >= -3:   return "⚪"
    if score >= -7:   return "🔴"
    return "🔴🔴"


def _row(rank: int, r: dict) -> str:
    chg = r["change_pct"]
    chg_str = f"+{chg:.1f}%" if chg >= 0 else f"{chg:.1f}%"

    badges = []
    c, h, l = r.get("close"), r.get("high_252"), r.get("low_252")
    if h and c and c >= h * 0.999:
        badges.append("📈52주高")
    if l and c and c <= l * 1.001:
        badges.append("📉52주低")
    badge_str = "  " + "  ".join(badges) if badges else ""

    return (
        f"{rank}. {_grade_icon(r['score'])}  "
        f"<b>{r['ticker']}</b>  "
        f"{r['score']:+.0f}점  |  "
        f"${r['close']:.2f}  ({chg_str})"
        f"{badge_str}\n"
    )


def _split_send(text: str) -> list[str]:
    """4096자 제한에 맞게 자르기"""
    chunks, buf = [], ""
    for line in text.splitlines(keepends=True):
        if len(buf) + len(line) > _MAX_LEN:
            chunks.append(buf)
            buf = ""
        buf += line
    if buf:
        chunks.append(buf)
    return chunks


def _section(title: str, rows: list[dict], limit: int) -> str:
    if not rows:
        return f"\n{title}\n  (해당 종목 없음)\n"
    text = f"\n{title}\n"
    for i, r in enumerate(rows[:limit], 1):
        text += _row(i, r)
    return text


def build_messages(
    date_str: str,
    total: int,
    sp500_results: list[dict],
    outer_results: list[dict],
    etf_results: list[dict] = None,
) -> list[str]:
    etf_results  = etf_results or []
    all_results  = sp500_results + outer_results + etf_results

    # ── 매수/매도 분리 (관망 -3~+3 제외) ──────────────────────────────
    sp_buy   = sorted([r for r in sp500_results if r["score"] >= 4],  key=lambda r: r["score"], reverse=True)
    sp_sell  = sorted([r for r in sp500_results if r["score"] < -3],  key=lambda r: r["score"])
    etf_buy  = sorted([r for r in etf_results   if r["score"] >= 4],  key=lambda r: r["score"], reverse=True)
    etf_sell = sorted([r for r in etf_results   if r["score"] < -3],  key=lambda r: r["score"])
    out_buy  = sorted([r for r in outer_results  if r["score"] >= 4], key=lambda r: r["score"], reverse=True)
    out_sell = sorted([r for r in outer_results  if r["score"] < -3], key=lambda r: r["score"])

    # ── 통계 ──────────────────────────────────────────────────────────
    buy2  = sum(1 for r in all_results if r["score"] >= 8)
    buy1  = sum(1 for r in all_results if 4 <= r["score"] < 8)
    watch = sum(1 for r in all_results if -3 <= r["score"] < 4)
    sell1 = sum(1 for r in all_results if -7 <= r["score"] < -3)
    sell2 = sum(1 for r in all_results if r["score"] < -7)

    header = (
        f"📊 <b>미국 주식 시그널 리포트</b>\n"
        f"📅 {date_str}  |  분석: {total:,}종목\n\n"
        f"📈 🟢🟢 {buy2}개  🟢 {buy1}개"
        f"    📉 🔴 {sell1}개  🔴🔴 {sell2}개"
        f"    ⚪ 관망 {watch}개\n"
    )

    body = (
        _section("━━━ 🏆 <b>S&amp;P 500 매수 TOP 25</b> ━━━", sp_buy,  25)
        + _section("━━━ 🏆 <b>S&amp;P 500 매도 TOP 25</b> ━━━", sp_sell, 25)
        + _section("━━━ 📊 <b>ETF 매수 TOP 10</b> ━━━",          etf_buy,  10)
        + _section("━━━ 📊 <b>ETF 매도 TOP 10</b> ━━━",          etf_sell, 10)
        + _section("━━━ 💎 <b>외곽 매수 TOP 15</b> ━━━",         out_buy,  15)
        + _section("━━━ 💎 <b>외곽 매도 TOP 15</b> ━━━",         out_sell, 15)
    )

    return _split_send(header + body)
