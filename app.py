"""
주식 시그널 분석 Streamlit 앱
실행: streamlit run app.py
"""
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd
import streamlit as st
import yfinance as yf

# ── 경로 설정 ─────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

SETTINGS_FILE   = BASE_DIR / "settings.json"
HOLDINGS_FILE   = BASE_DIR / "holdings.json"
LOGS_DIR        = BASE_DIR / "logs"
LAST_RESULTS    = BASE_DIR / "cache" / "last_results.json"
LAST_DIVIDEND   = BASE_DIR / "cache" / "last_dividend.json"

# ── 기본 설정값 ───────────────────────────────────────────────────────
DEFAULT_SETTINGS = {
    "rsi_overbought":        70,
    "rsi_overbought_strong": 75,
    "rsi_oversold":          30,
    "rsi_oversold_strong":   25,
    "macd_fast":             12,
    "macd_slow":             26,
    "macd_signal":            9,
    "ma_short":              20,
    "ma_mid":                60,
    "ma_long":              200,
    "volume_t1":              2,
    "volume_t2":              3,
    "volume_t3":              5,
    "vp_window":             90,
    # ── 배당 분석 설정 ─────────────────────────────────────────
    "div_years":              5,   # 배당성장률 계산 기간 (년)
    "div_min_dgr":            0,   # 최소 배당성장률 (%)
    "div_min_yield":          1,   # 최소 배당률 (%)
    "div_max_payout":        85,   # 최대 Payout 비율 (%)
    "div_min_consec":         3,   # 최소 연속 배당 증가 연수
    "div_min_price_growth": -50,   # 최소 주가성장률 (%, -50 = 사실상 미적용)
}

# ── 유틸 함수 ─────────────────────────────────────────────────────────
def load_settings() -> dict:
    if SETTINGS_FILE.exists():
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            return {**DEFAULT_SETTINGS, **json.load(f)}
    return DEFAULT_SETTINGS.copy()

def save_settings(s: dict):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=2, ensure_ascii=False)

def load_holdings() -> list:
    if HOLDINGS_FILE.exists():
        with open(HOLDINGS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return []

def save_holdings(h: list):
    with open(HOLDINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(h, f, indent=2, ensure_ascii=False)


# ── 캐시 함수 (메모리 최적화) ─────────────────────────────────────────
@st.cache_data(ttl=300)
def _load_json(path_str: str, mtime: float) -> dict:
    """파일 수정 시각이 바뀔 때만 실제로 재로드 (mtime이 캐시 키)."""
    with open(path_str, encoding="utf-8") as f:
        return json.load(f)

def _read_cache(path: Path) -> dict | None:
    if not path.exists():
        return None
    return _load_json(str(path), path.stat().st_mtime)

@st.cache_data(ttl=3600)
def _fetch_holding_scores(tickers: tuple) -> dict:
    """보유 종목 점수 — 동일 티커 목록이면 1시간 동안 재다운로드 안 함."""
    try:
        from fetcher import fetch_batch, apply_quality_filter
        from scorer import score_all
        raw      = fetch_batch(list(tickers), period="6mo", chunk_size=max(len(tickers), 1))
        filtered = apply_quality_filter(raw)
        return {r["ticker"]: r for r in score_all(filtered)}
    except Exception:
        return {}


# ══════════════════════════════════════════════════════════════════════
# 앱 전역 설정
# ══════════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="📊 주식 시그널 분석",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


with st.sidebar:
    st.markdown("## 📊 주식 시그널 분석")
    st.markdown("---")
    page = st.radio(
        "페이지",
        ["⚙️ 지표 설정", "📋 보유 종목", "🚀 분석 실행", "💰 배당 분석", "📁 리포트 기록"],
        label_visibility="collapsed",
    )
    st.markdown("---")
    st.caption("Russell 3000 + S&P 500 기반\n매일 오전 6:30 자동 실행")


# ══════════════════════════════════════════════════════════════════════
# 1. 지표 설정
# ══════════════════════════════════════════════════════════════════════
if page == "⚙️ 지표 설정":
    st.title("⚙️ 지표 설정")
    st.caption("변경 후 저장하면 다음 분석 실행부터 반영됩니다.")

    settings = load_settings()
    new: dict = {}

    h1, h2, h3 = st.columns([5, 2, 4])
    h1.markdown("**지표명**")
    h2.markdown("**현재 값**")
    h3.markdown("**변경 입력**")
    st.markdown('<hr style="margin:6px 0 10px">', unsafe_allow_html=True)

    def row(label: str, key: str, lo: int, hi: int, step: int = 1):
        c1, c2, c3 = st.columns([5, 2, 4])
        c1.write(label)
        c2.markdown(f"`{settings[key]}`")
        new[key] = int(c3.number_input(
            label, value=int(settings[key]),
            min_value=lo, max_value=hi, step=step,
            key=f"s_{key}", label_visibility="collapsed",
        ))

    st.markdown("#### RSI 임계값")
    row("과매수 기준  →  매도 -2점",       "rsi_overbought",        60, 99)
    row("과매수 강한 기준  →  매도 -4점",  "rsi_overbought_strong", 60, 99)
    row("과매도 기준  →  매수 +2점",       "rsi_oversold",           1, 40)
    row("과매도 강한 기준  →  매수 +4점",  "rsi_oversold_strong",    1, 40)

    st.markdown("#### MACD")
    row("Fast EMA 기간",  "macd_fast",    2,  50)
    row("Slow EMA 기간",  "macd_slow",    5, 100)
    row("Signal 기간",    "macd_signal",  2,  30)

    st.markdown("#### 이동평균선")
    row("단기 MA",  "ma_short",   5,  50)
    row("중기 MA",  "ma_mid",    20, 120)
    row("장기 MA",  "ma_long",   50, 500)

    st.markdown("#### 거래량 임계 배수  (가격 ±2% 조건 함께 충족 시)")
    row("1단계 배수  →  ±2점",  "volume_t1",  1, 10)
    row("2단계 배수  →  ±3점",  "volume_t2",  2, 20)
    row("3단계 배수  →  ±4점",  "volume_t3",  3, 30)

    st.markdown("#### 매물대 (Volume Profile)")
    row("분석 윈도우 (영업일)",  "vp_window",  20, 252)

    st.markdown("#### 배당 분석")
    row("배당성장률 계산 기간 (년)  →  장기/단기 CAGR 기준",        "div_years",            1,   20)
    row("최소 배당성장률 (%)  →  미만 종목 제외",                    "div_min_dgr",        -50,   50)
    row("최소 배당률 (%)  →  미만 종목 제외",                        "div_min_yield",         0,   10)
    row("최대 FCF 배당성향 (%)  →  초과 종목 제외 (잉여현금 대비 배당)", "div_max_payout",     50,  200)
    row("최소 연속 배당 증가 (년)  →  미만 종목 제외",               "div_min_consec",        0,   50)
    row("최소 주가성장률 (%)  →  미만 종목 제외 (-50 = 사실상 미적용)", "div_min_price_growth", -50, 50)

    st.markdown("---")
    c_save, c_reset, _ = st.columns([2, 2, 6])

    if c_save.button("💾 저장", type="primary", use_container_width=True):
        save_settings(new)
        st.success("✅ 저장 완료. 다음 분석부터 반영됩니다.")

    if c_reset.button("🔄 기본값 초기화", use_container_width=True):
        save_settings(DEFAULT_SETTINGS)
        for k in DEFAULT_SETTINGS:
            st.session_state.pop(f"s_{k}", None)
        st.success("✅ 기본값으로 초기화했습니다.")
        st.rerun()


# ══════════════════════════════════════════════════════════════════════
# 2. 보유 종목
# ══════════════════════════════════════════════════════════════════════
elif page == "📋 보유 종목":
    st.title("📋 보유 종목 관리")
    holdings = load_holdings()

    # 현재 점수 조회 (1시간 캐시)
    scores: dict = {}
    if holdings:
        with st.spinner("보유 종목 최신 점수 조회 중..."):
            scores = _fetch_holding_scores(tuple(h["ticker"] for h in holdings))

    # 배당 캐시 로드 (파일 변경 시에만 재로드)
    div_map: dict = {}
    _dc = _read_cache(LAST_DIVIDEND)
    if _dc:
        for _r in _dc.get("holdings_data", []):
            div_map[_r["ticker"]] = _r
        for _cat in ("growth_top", "royalty", "high_yield", "risk"):
            for _r in _dc.get(_cat, []):
                if _r["ticker"] not in div_map:
                    div_map[_r["ticker"]] = _r

    # 종목 목록
    if not holdings:
        st.info("등록된 보유 종목이 없습니다. 아래에서 추가해주세요.")
    else:
        st.markdown(f"**총 {len(holdings)}개 종목**")
        for col, label in zip(
            st.columns([2, 5, 4, 3, 2]),
            ["**티커**", "**종목명**", "**등급**", "**점수**", ""],
        ):
            col.markdown(label)
        st.divider()

        delete_idx = None
        for i, h in enumerate(holdings):
            sc = scores.get(h["ticker"])
            c1, c2, c3, c4, c5 = st.columns([2, 5, 4, 3, 2])
            c1.write(h["ticker"])
            c2.write(h.get("name", "—"))
            c3.write(sc["grade"] if sc else "—")
            c4.write(f"{sc['score']:+.1f}" if sc else "—")
            if c5.button("🗑️", key=f"del_{i}", help="삭제"):
                delete_idx = i

        if delete_idx is not None:
            holdings.pop(delete_idx)
            save_holdings(holdings)
            st.rerun()

        # 배당 현황 테이블
        st.markdown("---")
        st.markdown("#### 💰 보유 종목 배당 현황")
        if not div_map:
            st.caption("배당 데이터 없음 — 매일 22:00 KST 자동 업데이트됩니다.")
        else:
            div_records = []
            for h in holdings:
                t  = h["ticker"]
                dr = div_map.get(t)
                if dr is None:
                    div_records.append({
                        "티커": t, "배당등급": "—", "배당점수": "—",
                        "배당률(TTM)": "—", "10Y DGR": "—", "5Y DGR": "—",
                        "연속증가": "—", "Payout": "—", "배당컷": "—",
                    })
                    continue
                consec = dr.get("consecutive_growth", 0)
                if   consec >= 50: king = "👑킹"
                elif consec >= 25: king = "🏆귀족"
                elif consec >= 10: king = "⭐챔피언"
                else:              king = ""
                dgr_l   = dr.get("dgr_long")
                dgr_s   = dr.get("dgr_short")
                ly      = dr.get("dgr_long_years",  5)
                sy      = dr.get("dgr_short_years", 2)
                payout  = dr.get("payout_ratio")
                fcf_pay = dr.get("fcf_payout")
                pg      = dr.get("price_growth_cagr")
                div_records.append({
                    "티커":                           t,
                    "배당등급":                       dr.get("grade", "—"),
                    "배당점수":                       f"{dr['score']:+.0f}",
                    "배당률(최근1년)":                f"{dr.get('yield_ttm', 0):.1f}%",
                    f"배당성장률({ly}년·연평균)":     f"{dgr_l:.0f}%" if dgr_l is not None else "N/A",
                    f"배당성장률({sy}년·연평균)":     f"{dgr_s:.0f}%" if dgr_s is not None else "N/A",
                    "연속 배당 증가":                  f"{consec}년 {king}".strip(),
                    "FCF 배당성향":                   f"{fcf_pay*100:.0f}%" if fcf_pay is not None else "N/A",
                    f"주가성장률({ly}년·연평균)":      f"{pg:+.1f}%" if pg is not None else "N/A",
                    "배당컷":                          "✂컷" if dr.get("had_cut") else "—",
                })
            if div_records:
                st.dataframe(
                    pd.DataFrame(div_records),
                    use_container_width=True, hide_index=True,
                )
            else:
                st.caption("보유 종목이 배당 데이터에 없습니다.")

    # 종목 추가
    st.markdown("---")
    st.markdown("#### ➕ 종목 추가")
    c1, c2 = st.columns([4, 1])
    ticker_in = c1.text_input("티커 입력 (예: AAPL, NVDA)", key="add_ticker").strip().upper()

    if c2.button("추가", type="primary", use_container_width=True):
        if not ticker_in:
            st.warning("티커를 입력해주세요.")
        elif any(h["ticker"] == ticker_in for h in holdings):
            st.warning(f"**{ticker_in}** 은(는) 이미 등록되어 있습니다.")
        else:
            with st.spinner(f"{ticker_in} 정보 조회 중..."):
                try:
                    ticker_obj = yf.Ticker(ticker_in)
                    # fast_info 로 가격 확인 (가벼운 API — rate limit 회피)
                    price = None
                    try:
                        fi    = ticker_obj.fast_info
                        price = getattr(fi, "last_price", None) or getattr(fi, "previous_close", None)
                    except Exception:
                        pass
                    # fast_info 실패 시 history 로 폴백
                    if not price:
                        _h = ticker_obj.history(period="5d")
                        if not _h.empty:
                            price = float(_h["Close"].iloc[-1])
                    # 종목명은 별도 조회 (실패해도 티커로 대체)
                    name = ticker_in
                    try:
                        info = ticker_obj.info
                        name = info.get("longName") or info.get("shortName") or ticker_in
                    except Exception:
                        pass

                    if price:
                        holdings.append({"ticker": ticker_in, "name": name})
                        save_holdings(holdings)
                        st.success(f"✅ **{ticker_in}** ({name}) 추가됨")
                        st.rerun()
                    else:
                        st.error(f"❌ **{ticker_in}**: 유효하지 않은 티커입니다.")
                except Exception as e:
                    st.error(f"❌ 조회 실패: {e}")


# ══════════════════════════════════════════════════════════════════════
# 3. 분석 실행
# ══════════════════════════════════════════════════════════════════════
elif page == "🚀 분석 실행":
    st.title("🚀 분석 실행")

    daily_tab, weekly_tab = st.tabs(["📅 데일리", "📆 위클리"])

    # ── 데일리 ────────────────────────────────────────────────────────
    with daily_tab:
        st.caption("Russell 3000 전체 종목을 분석합니다.")
        c1, c2 = st.columns([2, 8])
        run_btn = c1.button("▶ 지금 분석 돌리기", type="primary", use_container_width=True)
        c2.info("⏱ 첫 실행 ~20분  /  캐시 있을 때 ~2분  /  실행 중 페이지 이동 시 중단됩니다.")

        if run_btn:
            import io, contextlib, importlib
            buf = io.StringIO()
            t0  = time.time()
            with st.spinner("분석 중... (약 20분 소요, 완료 시 결과가 표시됩니다)"):
                try:
                    import main as _main_mod
                    importlib.reload(_main_mod)
                    with contextlib.redirect_stdout(buf):
                        _main_mod.main()
                    elapsed = int(time.time() - t0)
                    st.success(f"✅ 분석 완료! (소요 {elapsed // 60}분 {elapsed % 60}초)")
                    st.code(buf.getvalue(), language="")
                    _load_json.clear()
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ 오류 발생: {e}")
                    st.code(buf.getvalue(), language="")

        last = _read_cache(LAST_RESULTS)
        if last:
            st.markdown("---")
            st.caption(
                f"분석일: **{last.get('date', '—')}**  |  "
                f"분석 종목: **{last.get('total', 0):,}개**"
            )
            d1, d2, d3, d4, d5, d6 = st.tabs(
                ["🏆 S&P 500 매수 TOP 25", "🔻 S&P 500 매도 TOP 25",
                 "📊 ETF 매수 TOP 10",     "🔻 ETF 매도 TOP 10",
                 "💎 외곽 매수 TOP 15",    "🔻 외곽 매도 TOP 15"]
            )
            for tab, key in zip(
                [d1, d2, d3, d4, d5, d6],
                ["sp500_buy", "sp500_sell", "etf_buy", "etf_sell", "outer_buy", "outer_sell"],
            ):
                with tab:
                    rows = last.get(key, [])
                    if rows:
                        records = []
                        for r in rows:
                            pred = r.get("prediction") or {}
                            lo   = pred.get("short_lo_68")
                            hi   = pred.get("short_hi_68")
                            week = f"${lo:.0f}~${hi:.0f}" if lo is not None and hi is not None else "—"
                            records.append({
                                "티커":    r["ticker"],
                                "합산":    f"{r['score']:+.1f}",
                                "장타":    f"{r.get('long_score',  0):+.0f}",
                                "단타":    f"{r.get('short_score', 0):+.0f}",
                                "추천":    r.get("recommendation", "—"),
                                "등급":    r["grade"],
                                "종가($)": r["close"],
                                "등락(%)": f"{r['change_pct']:+.1f}%",
                                "1주범위": week,
                            })
                        st.dataframe(
                            pd.DataFrame(records),
                            use_container_width=True, hide_index=True,
                        )
                    else:
                        st.info("해당 항목 없음 (관망 구간에 속하는 종목만 있거나 데이터 없음)")
        else:
            st.info("아직 분석 기록이 없습니다. 위 버튼을 눌러 첫 분석을 실행해보세요.")

    # ── 위클리 ────────────────────────────────────────────────────────
    with weekly_tab:
        from datetime import date as _date, timedelta as _td

        DAILY_DIR = BASE_DIR / "cache" / "daily"

        def _build_weekly(category: str) -> list[dict]:
            if not DAILY_DIR.exists():
                return []
            cutoff = _date.today() - _td(days=7)
            ticker_data: dict[str, dict] = {}
            for fp in sorted(DAILY_DIR.glob("*.json")):
                try:
                    file_date = _date.fromisoformat(fp.stem)
                except ValueError:
                    continue
                if file_date < cutoff:
                    continue
                try:
                    with open(fp, encoding="utf-8") as f:
                        data = json.load(f)
                except Exception:
                    continue
                for r in data.get(category, []):
                    t = r["ticker"]
                    if t not in ticker_data:
                        ticker_data[t] = {
                            "count": 0, "scores": [],
                            "last_date": "", "last_score": 0,
                            "last_grade": "—", "last_rec": "—",
                        }
                    d = ticker_data[t]
                    d["count"] += 1
                    d["scores"].append(r.get("score", 0))
                    if str(file_date) > d["last_date"]:
                        d["last_date"]  = str(file_date)
                        d["last_score"] = r.get("score", 0)
                        d["last_grade"] = r.get("grade", "—")
                        d["last_rec"]   = r.get("recommendation", "—")

            out = []
            for ticker, d in ticker_data.items():
                avg = sum(d["scores"]) / len(d["scores"]) if d["scores"] else 0
                out.append({
                    "티커":   ticker,
                    "출현(회)": d["count"],
                    "평균점수": f"{avg:+.1f}",
                    "최근점수": f"{d['last_score']:+.1f}",
                    "최근등급": d["last_grade"],
                    "최근추천": d["last_rec"],
                    "_avg":   avg,
                })
            return sorted(out, key=lambda x: (-x["출현(회)"], -x["_avg"]))

        def _weekly_df(records: list, tbl_key: str) -> None:
            if not records:
                st.info("위클리 데이터가 없습니다. 데일리 분석이 누적되면 자동으로 표시됩니다.")
                return
            display = [{k: v for k, v in r.items() if k != "_avg"} for r in records]
            st.dataframe(pd.DataFrame(display), use_container_width=True, hide_index=True)

        if not DAILY_DIR.exists() or not any(DAILY_DIR.glob("*.json")):
            st.info("위클리 데이터가 없습니다. 데일리 분석이 누적되면 자동으로 표시됩니다.")
        else:
            file_dates = sorted(
                fp.stem for fp in DAILY_DIR.glob("*.json")
                if fp.stem >= str(_date.today() - _td(days=7))
            )
            st.caption(f"최근 7일 데이터 기준  |  포함 날짜: **{', '.join(file_dates)}**")
            w1, w2, w3, w4, w5, w6 = st.tabs(
                ["🏆 S&P 500 매수", "🔻 S&P 500 매도",
                 "📊 ETF 매수",     "🔻 ETF 매도",
                 "💎 외곽 매수",    "🔻 외곽 매도"]
            )
            for tab, key in zip(
                [w1, w2, w3, w4, w5, w6],
                ["sp500_buy", "sp500_sell", "etf_buy", "etf_sell", "outer_buy", "outer_sell"],
            ):
                with tab:
                    _weekly_df(_build_weekly(key), f"w_tbl_{key}")


# ══════════════════════════════════════════════════════════════════════
# 4. 배당 분석
# ══════════════════════════════════════════════════════════════════════
elif page == "💰 배당 분석":
    st.title("💰 배당주 일일 리포트")

    # ── 수동 실행 버튼 ────────────────────────────────────────────────
    dc1, dc2 = st.columns([2, 8])
    div_run_btn = dc1.button("▶ 배당 분석 실행", type="primary", use_container_width=True)
    dc2.info("⏱ ~30분 소요 (전체 종목 배당 히스토리 다운로드)  /  매일 오전 6:30 KST 자동 실행")

    if div_run_btn:
        import io, contextlib, importlib
        buf = io.StringIO()
        t0  = time.time()
        with st.spinner("배당 분석 중... (약 30분 소요, 완료 시 결과가 표시됩니다)"):
            try:
                import weekly_dividend
                importlib.reload(weekly_dividend)
                with contextlib.redirect_stdout(buf):
                    weekly_dividend.main()
                elapsed = int(time.time() - t0)
                st.success(f"✅ 배당 분석 완료! (소요 {elapsed // 60}분 {elapsed % 60}초)")
                st.code(buf.getvalue(), language="")
                _load_json.clear()
                st.rerun()
            except Exception as e:
                st.error(f"❌ 오류 발생: {e}")
                st.code(buf.getvalue(), language="")

    st.markdown("---")

    div_data = _read_cache(LAST_DIVIDEND)
    if not div_data:
        st.info("아직 배당 분석 기록이 없습니다. 위 버튼을 눌러 첫 분석을 실행해보세요.")
    else:

        st.caption(
            f"분석일: **{div_data.get('date', '—')}**  |  "
            f"배당 지급 종목: **{div_data.get('total', 0):,}개**"
        )

        def _div_table(rows: list, tbl_key: str) -> None:
            if not rows:
                st.info("해당 항목 없음")
                return
            ly = rows[0].get("dgr_long_years",  5) if rows else 5
            sy = rows[0].get("dgr_short_years", 2) if rows else 2
            records = []
            for r in rows:
                consec  = r.get("consecutive_growth", 0)
                if   consec >= 50: king = "👑킹"
                elif consec >= 25: king = "🏆귀족"
                elif consec >= 10: king = "⭐챔피언"
                else:              king = ""
                dgr_l    = r.get("dgr_long")
                dgr_s    = r.get("dgr_short")
                payout   = r.get("payout_ratio")
                fcf_pay  = r.get("fcf_payout")
                pg       = r.get("price_growth_cagr")
                records.append({
                    "티커":                            r["ticker"],
                    "등급":                            r.get("grade", "—"),
                    "점수":                            f"{r['score']:+.0f}",
                    f"배당성장률({ly}년·연평균)":      f"{dgr_l:.0f}%" if dgr_l is not None else "N/A",
                    f"배당성장률({sy}년·연평균)":      f"{dgr_s:.0f}%" if dgr_s is not None else "N/A",
                    "연속 배당 증가":                   f"{consec}년 {king}".strip(),
                    "배당률(최근1년)":                  f"{r.get('yield_ttm', 0):.1f}%",
                    "FCF 배당성향":                    f"{fcf_pay*100:.0f}%" if fcf_pay is not None else "N/A",
                    f"주가성장률({ly}년·연평균)":       f"{pg:+.1f}%" if pg is not None else "N/A",
                    "배당컷":                           "✂컷" if r.get("had_cut") else "—",
                })
            st.dataframe(pd.DataFrame(records), use_container_width=True, hide_index=True)

        tab1, tab2, tab3, tab4, tab5 = st.tabs([
            "🚀 배당 성장 TOP 15",
            "🏆 킹/귀족 TOP 10",
            "💰 고배당 TOP 10",
            "⚠️ 배당 컷 위험",
            "⭐ 내 보유 종목",
        ])
        with tab1:
            _div_table(div_data.get("growth_top", []), "div_growth")
        with tab2:
            _div_table(div_data.get("royalty", []),    "div_royalty")
        with tab3:
            _div_table(div_data.get("high_yield", []), "div_yield")
        with tab4:
            _div_table(div_data.get("risk", []),       "div_risk")
        with tab5:
            held = div_data.get("holdings_data", [])
            if held:
                _div_table(held, "div_held")
            else:
                st.info("보유 종목 배당 데이터가 없습니다. 보유 종목을 등록하거나 배당 분석을 실행해주세요.")


# ══════════════════════════════════════════════════════════════════════
# 5. 리포트 기록
# ══════════════════════════════════════════════════════════════════════
elif page == "📁 리포트 기록":
    st.title("📁 리포트 기록")

    LOGS_DIR.mkdir(exist_ok=True)
    log_files = sorted(LOGS_DIR.glob("*.log"), reverse=True)

    if not log_files:
        st.info("저장된 로그 파일이 없습니다. 분석을 실행하면 logs/ 폴더에 자동 저장됩니다.")
    else:
        c1, c2 = st.columns([1, 3])
        with c1:
            st.markdown(f"**{len(log_files)}개 파일**")
            selected = st.radio(
                "날짜 선택",
                [f.name for f in log_files],
                label_visibility="collapsed",
            )
        with c2:
            content = (LOGS_DIR / selected).read_text(encoding="utf-8", errors="replace")
            st.markdown(f"#### 📄 {selected}")
            st.code(content, language="")
