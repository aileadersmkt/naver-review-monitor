"""
네이버 플레이스 리뷰 모니터링 대시보드 (병원용 — 평점 없음, 감성 분석)
실행: streamlit run dashboard.py
"""

import streamlit as st
import sqlite3
import pandas as pd
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

st.set_page_config(page_title="리뷰 모니터 | 8개 병원", page_icon="🏥", layout="wide")

st.markdown("""
<style>
html, body, [class*="css"] { font-family: 'Noto Sans KR', sans-serif; }
#MainMenu, footer, header { visibility: hidden; }
[data-testid="metric-container"] {
    background: #F8F9FA; border: 1px solid #EAECEF;
    border-radius: 12px; padding: 16px 20px;
}
.review-card { background: white; border: 1px solid #EAECEF; border-radius: 12px; padding: 16px; margin-bottom: 10px; }
.review-card.negative { border-left: 4px solid #EF4444; }
.review-card.positive { border-left: 4px solid #10B981; }
.review-card.neutral  { border-left: 4px solid #9CA3AF; }
.badge { font-size: 11px; padding: 2px 8px; border-radius: 20px; font-weight: 500; }
.badge-neg  { background:#FEE2E2; color:#DC2626; }
.badge-pos  { background:#D1FAE5; color:#065F46; }
.badge-neu  { background:#F3F4F6; color:#6B7280; }
.badge-new  { background:#DBEAFE; color:#1D4ED8; }
</style>
""", unsafe_allow_html=True)

BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config" / "hospitals.json"
DB_PATH = BASE_DIR / "data" / "reviews.db"

@st.cache_data(ttl=60)
def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)

CONFIG = load_config()
HOSPITAL_NAMES = [h["name"] for h in CONFIG["hospitals"]]

def get_conn():
    if not DB_PATH.exists():
        return None
    return sqlite3.connect(DB_PATH, check_same_thread=False)

@st.cache_data(ttl=60)
def load_reviews(days: int = 30) -> pd.DataFrame:
    conn = get_conn()
    if not conn:
        return pd.DataFrame()
    since = (datetime.now() - timedelta(days=days)).isoformat()
    df = pd.read_sql_query("""
        SELECT hospital_name, author, content, visit_count,
               sentiment, created_at, crawled_at, is_new
        FROM reviews WHERE crawled_at >= ?
        ORDER BY crawled_at DESC
    """, conn, params=(since,))
    conn.close()
    return df

def demo_df():
    import random
    rows = []
    sentiments = ["positive","positive","positive","negative","neutral"]
    contents = {
        "positive": ["선생님이 정말 친절하고 설명도 자세해요.","시설이 깔끔하고 직원분들이 상냥해요.","재방문 의사 있어요. 꼼꼼하게 봐주셨어요."],
        "negative": ["대기 시간이 너무 길었어요.","직원 태도가 불친절했습니다.","설명이 부족하고 무성의했어요."],
        "neutral":  ["주차가 조금 불편했지만 진료는 괜찮았어요.","보통이었어요."],
    }
    for i in range(40):
        hosp = random.choice(HOSPITAL_NAMES)
        sent = random.choice(sentiments)
        rows.append({
            "hospital_name": hosp, "author": f"방문자 {'가나다라마바사아자차'[i%10]}*",
            "content": random.choice(contents[sent]), "visit_count": random.randint(1,5),
            "sentiment": sent,
            "created_at": (datetime.now()-timedelta(days=random.randint(0,30))).isoformat(),
            "crawled_at": (datetime.now()-timedelta(hours=random.randint(0,48))).isoformat(),
            "is_new": random.choice([0,1]),
        })
    return pd.DataFrame(rows)

# ── 사이드바 ─────────────────────────────────────────
with st.sidebar:
    st.markdown("### 🏥 리뷰 모니터")
    st.caption("네이버 플레이스 자동 수집")
    st.divider()

    sel_hospitals = st.multiselect("병원 필터", HOSPITAL_NAMES, default=HOSPITAL_NAMES)
    date_range = st.selectbox("기간", ["오늘","최근 7일","최근 30일","전체"], index=2)
    sent_filter = st.multiselect("감성 필터", ["positive","negative","neutral"],
                                  default=["positive","negative","neutral"],
                                  format_func=lambda x: {"positive":"😊 긍정","negative":"😟 부정","neutral":"😐 중립"}[x])
    only_new = st.checkbox("신규만 보기", False)
    st.divider()
    if st.button("🔄 새로고침", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.caption(f"업데이트: {datetime.now().strftime('%H:%M:%S')}")

# ── 데이터 로드 ───────────────────────────────────────
day_map = {"오늘":1,"최근 7일":7,"최근 30일":30,"전체":365}
df_all = load_reviews(day_map[date_range])
is_demo = df_all.empty
if is_demo:
    df_all = demo_df()
    st.info("⚠️ DB 없음 — 데모 데이터로 표시 중입니다.", icon="ℹ️")

df = df_all.copy()
if sel_hospitals:
    df = df[df["hospital_name"].isin(sel_hospitals)]
if sent_filter:
    df = df[df["sentiment"].isin(sent_filter)]
if only_new:
    df = df[df["is_new"]==1]

# ── 메트릭 ───────────────────────────────────────────
st.markdown("## 📊 리뷰 모니터링 대시보드")
c1,c2,c3,c4,c5 = st.columns(5)
today_cut = datetime.now().replace(hour=0,minute=0).isoformat()
today_df = df_all[df_all["crawled_at"] >= today_cut]

c1.metric("오늘 신규", f"{len(today_df)}건")
c2.metric("😊 긍정", f"{(df_all['sentiment']=='positive').sum()}건")
c3.metric("😟 부정", f"{(df_all['sentiment']=='negative').sum()}건")
c4.metric("😐 중립", f"{(df_all['sentiment']=='neutral').sum()}건")
c5.metric("총 수집", f"{len(df_all):,}건")

st.markdown("---")

# ── 병원별 현황 + 리뷰 목록 ──────────────────────────
left, right = st.columns([1, 1.6])

with left:
    st.markdown("**병원별 감성 현황**")
    hosp_stats = (
        df_all.groupby("hospital_name")
        .agg(total=("sentiment","count"),
             pos=("sentiment", lambda x:(x=="positive").sum()),
             neg=("sentiment", lambda x:(x=="negative").sum()))
        .reset_index().sort_values("neg", ascending=False)
    )
    for _, row in hosp_stats.iterrows():
        neg_str = f" 🔴{int(row['neg'])}" if row["neg"] else ""
        st.markdown(f"""
        <div style="margin-bottom:10px;">
          <div style="display:flex;justify-content:space-between;margin-bottom:3px;">
            <span style="font-size:13px;font-weight:500;">{row['hospital_name']}</span>
            <span style="font-size:12px;color:#6B7280;">총 {int(row['total'])}건 | 😊{int(row['pos'])} 😟{int(row['neg'])}{neg_str}</span>
          </div>
          <div style="background:#F3F4F6;border-radius:4px;height:6px;display:flex;">
            <div style="background:#10B981;width:{int(row['pos'])/max(int(row['total']),1)*100:.0f}%;border-radius:4px 0 0 4px;"></div>
            <div style="background:#EF4444;width:{int(row['neg'])/max(int(row['total']),1)*100:.0f}%;"></div>
          </div>
        </div>
        """, unsafe_allow_html=True)

with right:
    st.markdown("**최근 리뷰**")
    sent_label = {"positive":"😊 긍정","negative":"😟 부정","neutral":"😐 중립"}
    badge_cls   = {"positive":"badge-pos","negative":"badge-neg","neutral":"badge-neu"}

    for _, row in df.head(8).iterrows():
        sent = row["sentiment"]
        content = (row["content"] or "")
        preview = content[:80] + ("..." if len(content)>80 else "")
        new_badge = '<span class="badge badge-new">신규</span> ' if row["is_new"] else ""
        sent_badge = f'<span class="badge {badge_cls[sent]}">{sent_label[sent]}</span>'
        date_str = (row["created_at"] or "")[:10]

        st.markdown(f"""
        <div class="review-card {sent}">
          <div style="display:flex;justify-content:space-between;margin-bottom:6px;">
            <span style="font-size:13px;font-weight:600;">{row['hospital_name']}</span>
            <span>{new_badge}{sent_badge}</span>
          </div>
          <p style="font-size:13px;color:#374151;margin:0 0 4px;line-height:1.5;">{preview}</p>
          <span style="font-size:11px;color:#9CA3AF;">{row['author']} · {date_str}</span>
        </div>
        """, unsafe_allow_html=True)

# ── 차트 ─────────────────────────────────────────────
st.markdown("---")
ch1, ch2 = st.columns(2)

with ch1:
    st.markdown("**일별 리뷰 추이**")
    df_all["date"] = pd.to_datetime(df_all["crawled_at"]).dt.date
    daily = df_all.groupby("date").size().reset_index(name="건수").tail(14)
    st.bar_chart(daily.set_index("date"), color="#378ADD", height=220)

with ch2:
    st.markdown("**병원별 감성 비율**")
    pivot = df_all.groupby(["hospital_name","sentiment"]).size().unstack(fill_value=0)
    pivot = pivot.reindex(columns=["positive","negative","neutral"], fill_value=0)
    st.bar_chart(pivot, color=["#10B981","#EF4444","#9CA3AF"], height=220)

# ── 전체 테이블 ───────────────────────────────────────
st.markdown("---")
st.markdown("**전체 리뷰 테이블**")
disp = df[["hospital_name","sentiment","content","author","created_at","is_new"]].copy()
disp.columns = ["병원","감성","리뷰 내용","작성자","작성일","신규"]
disp["감성"] = disp["감성"].map({"positive":"😊 긍정","negative":"😟 부정","neutral":"😐 중립"})
disp["신규"] = disp["신규"].apply(lambda x: "🆕" if x else "")
disp["작성일"] = disp["작성일"].str[:10]
disp["리뷰 내용"] = disp["리뷰 내용"].str[:60] + "..."
st.dataframe(disp, use_container_width=True, height=300, hide_index=True)

st.caption(f"🤖 매 1시간 자동 수집 | {datetime.now().strftime('%Y-%m-%d %H:%M')} 기준")
