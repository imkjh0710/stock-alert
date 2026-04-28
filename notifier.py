"""
텔레그램 메시지 빌드 및 전송
TOP 10: 풀 디테일 (장단타 점수 + 예상 범위)
TOP 11~: 압축 한 줄 형식
"""
import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()

_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN")
_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
_MAX_LEN = 4096

_DISCLAIMER = (
    "\n⚠️ 위 예상 범위는 변동성(ATR)과 매물대 기반 기술적 분석 결과일 뿐, "
    "실제 주가 움직임을 보장하지 않습니다. "
    "펀더멘털, 매크로 환경, 종목별 이슈를 종합 검토하세요."
)


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
    if score >= 8:  return "🟢🟢"
    if score >= 4:  return "🟢"
    if score >= -3: return "⚪"
    if score >= -7: return "🔴"
    return "🔴🔴"


def _p(v) -> str:
    """가격 포맷: None이면 '—', 소수점 2자리"""
    if v is None: return "—"
    return f"${v:,.2f}"


def _row_full(rank: int, r: dict) -> str:
    """TOP 10용 풀 디테일 행 (5줄 이내)"""
    chg     = r["change_pct"]
    chg_str = f"+{chg:.1f}%" if chg >= 0 else f"{chg:.1f}%"
    icon    = _grade_icon(r["score"])
    ls      = r.get("long_score",  0)
    ss      = r.get("short_score", 0)
    rec     = r.get("recommendation", "")
    pred    = r.get("prediction") or {}
    c       = r.get("close")
    h252    = r.get("high_252")
    l252    = r.get("low_252")

    badges = []
    if h252 and c and c >= h252 * 0.999: badges.append("📈52주高")
    if l252 and c and c <= l252 * 1.001: badges.append("📉52주低")
    badge_str = ("  " + "  ".join(badges)) if badges else ""

    lines = [
        f"{rank}. {icon} <b>{r['ticker']}</b>  {r['score']:+.0f}  "
        f"${c:.2f} ({chg_str}){badge_str}\n",
        f"   장타 {ls:+.0f} / 단타 {ss:+.0f} → {rec}\n",
    ]

    lo68 = pred.get("short_lo_68")
    hi68 = pred.get("short_hi_68")
    if lo68 is not None and hi68 is not None:
        lines.append(f"   ▸ 단기 (1주): ${lo68:.2f} ~ ${hi68:.2f} (68%)\n")

    res = pred.get("short_resistance")
    sup = pred.get("short_support")
    if res is not None and sup is not None:
        lines.append(f"   ▸ 단기 저항 ${res:.2f} / 지지 ${sup:.2f}\n")

    up   = pred.get("mid_upside")
    down = pred.get("mid_downside")
    rr   = pred.get("rr")
    if up is not None and down is not None:
        rr_str = f" (R/R {rr}:1)" if rr else ""
        lines.append(f"   ▸ 중기: 상승 ${up:.2f} / 하락 ${down:.2f}{rr_str}\n")

    return "".join(lines)


def _row_compact(rank: int, r: dict) -> str:
    """TOP 11~ 압축 한 줄 행"""
    chg     = r["change_pct"]
    chg_str = f"+{chg:.1f}%" if chg >= 0 else f"{chg:.1f}%"
    icon    = _grade_icon(r["score"])
    ls      = r.get("long_score",  0)
    ss      = r.get("short_score", 0)
    rec     = r.get("recommendation", "")
    pred    = r.get("prediction") or {}
    lo68    = pred.get("short_lo_68")
    hi68    = pred.get("short_hi_68")
    week    = (f"${lo68:.0f}~${hi68:.0f}" if lo68 is not None and hi68 is not None else "—")

    # 추천 텍스트에서 이모지 제거하고 핵심만
    rec_short = rec.split(" ", 1)[-1] if rec else "—"

    return (
        f"{rank}. {icon} <b>{r['ticker']}</b>  {r['score']:+.0f}  "
        f"${r['close']:.2f} ({chg_str}) / "
        f"장타{ls:+.0f} 단타{ss:+.0f} / "
        f"1주 {week} / {rec_short}\n"
    )


def _split_send(text: str) -> list[str]:
    """4096자 한도에 맞게 줄 단위로 분할"""
    chunks, buf = [], ""
    for line in text.splitlines(keepends=True):
        if len(buf) + len(line) > _MAX_LEN:
            chunks.append(buf)
            buf = ""
        buf += line
    if buf:
        chunks.append(buf)
    return chunks


def _section(title: str, rows: list[dict], limit: int, full_n: int = 10) -> str:
    if not rows:
        return f"\n{title}\n  (해당 종목 없음)\n"
    text = f"\n{title}\n"
    for i, r in enumerate(rows[:limit], 1):
        text += _row_full(i, r) if i <= full_n else _row_compact(i, r)
    return text


def build_messages(
    date_str:     str,
    total:        int,
    sp500_results: list[dict],
    outer_results: list[dict],
    etf_results:   list[dict] = None,
) -> list[str]:
    etf_results = etf_results or []
    all_results = sp500_results + outer_results + etf_results

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
        + _DISCLAIMER
    )

    return _split_send(header + body)
