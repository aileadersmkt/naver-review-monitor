"""
슬랙 알림 모듈 (병원용 — 평점 없음, 감성 분석 기반)
"""

import json
import os
import requests
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
CONFIG_PATH = BASE_DIR / "config" / "hospitals.json"
DB_PATH = BASE_DIR / "data" / "reviews.db"

with open(CONFIG_PATH) as f:
    CONFIG = json.load(f)

SLACK_CONFIG = CONFIG["slack"]
WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL") or SLACK_CONFIG["webhook_url"]
ALERT_CHANNEL = SLACK_CONFIG.get("alert_channel", "#004-병원-리뷰-전체알림")
HOSPITAL_MAP = {h["id"]: h for h in CONFIG["hospitals"]}


def send_slack(blocks: list, channel: str = None, text: str = "리뷰 알림") -> bool:
    if not WEBHOOK_URL or WEBHOOK_URL == "YOUR_SLACK_WEBHOOK_URL":
        print(f"⚠️  Slack Webhook URL 미설정 | 메시지: {text}")
        return False
    payload = {"text": text, "blocks": blocks}
    if channel:
        payload["channel"] = channel
    try:
        resp = requests.post(WEBHOOK_URL, json=payload, timeout=10)
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"❌ Slack 전송 실패: {e}")
        return False


def sentiment_emoji(sentiment: str) -> str:
    return {"positive": "😊 긍정", "negative": "😟 부정", "neutral": "😐 중립"}.get(sentiment, "😐 중립")


def notify_new_review(review: dict):
    """신규 리뷰 1건 알림"""
    sentiment = review.get("sentiment", "neutral")
    content = (review.get("content", "") or "내용 없음")[:200]
    hospital_name = review.get("hospital_name", "병원")
    author = review.get("author", "익명")
    created_at = (review.get("created_at", "") or "")[:10]
    visit_count = review.get("visit_count", 0)

    is_negative = sentiment == "negative"
    header_emoji = "🚨" if is_negative else "🆕"
    header_text = f"{'🚨 부정 리뷰 감지' if is_negative else '🆕 새 리뷰'} — {hospital_name}"

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": header_text, "emoji": True}},
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*병원*\n{hospital_name}"},
                {"type": "mrkdwn", "text": f"*감성*\n{sentiment_emoji(sentiment)}"},
                {"type": "mrkdwn", "text": f"*작성자*\n{author}"},
                {"type": "mrkdwn", "text": f"*방문횟수*\n{visit_count}회"},
            ]
        },
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*리뷰 내용*\n> {content}"}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f"📅 작성일: {created_at}"}]},
        {"type": "divider"},
    ]

    hosp_info = HOSPITAL_MAP.get(review.get("hospital_id", ""), {})
    channel = hosp_info.get("slack_channel")

    success = send_slack(blocks, channel=channel, text=f"{header_text}: {content[:50]}")
    if success:
        mark_notified(review.get("id", ""))
    return success


def mark_notified(review_id: str):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE reviews SET notified = 1 WHERE id = ?", (review_id,))
    conn.commit()
    conn.close()


def notify_new_reviews(reviews: list):
    if not reviews:
        print("📭 신규 리뷰 없음")
        return
    print(f"\n📣 슬랙 알림 전송 ({len(reviews)}건)...")
    import time
    for r in reviews:
        notify_new_review(r)
        time.sleep(0.5)
    print("✅ 알림 완료")


def send_daily_report():
    """매일 오전 9시 — 부정/긍정/중립 구분 일간 리포트"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    today = datetime.now().strftime("%Y-%m-%d")

    stats = c.execute("""
        SELECT
            hospital_name,
            COUNT(*) as total,
            SUM(CASE WHEN sentiment = 'positive' THEN 1 ELSE 0 END) as pos,
            SUM(CASE WHEN sentiment = 'negative' THEN 1 ELSE 0 END) as neg,
            SUM(CASE WHEN sentiment = 'neutral'  THEN 1 ELSE 0 END) as neu
        FROM reviews
        WHERE crawled_at >= ? AND crawled_at < ?
        GROUP BY hospital_id, hospital_name
        ORDER BY neg DESC, total DESC
    """, (yesterday, today)).fetchall()

    # 부정 리뷰 샘플 (최대 3건)
    neg_samples = c.execute("""
        SELECT hospital_name, content
        FROM reviews
        WHERE crawled_at >= ? AND crawled_at < ? AND sentiment = 'negative'
        ORDER BY crawled_at DESC
        LIMIT 3
    """, (yesterday, today)).fetchall()

    conn.close()

    if not stats:
        print("📊 어제 수집된 리뷰 없음")
        return

    total_all = sum(s[1] for s in stats)
    total_pos = sum(s[2] for s in stats)
    total_neg = sum(s[3] for s in stats)
    date_str = datetime.now().strftime("%Y년 %m월 %d일")

    # 병원별 요약 줄
    rows = []
    for name, total, pos, neg, neu in stats:
        neg_str = f" 🔴부정 {neg}건" if neg else ""
        rows.append(f"• *{name}* — 총 {total}건 | 😊{pos} 😟{neg} 😐{neu}{neg_str}")

    # 부정 리뷰 샘플
    sample_text = ""
    if neg_samples:
        sample_lines = []
        for name, content in neg_samples:
            preview = (content or "")[:60]
            sample_lines.append(f"• [{name}] {preview}...")
        sample_text = "\n".join(sample_lines)

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"📊 일간 리뷰 리포트 — {date_str}", "emoji": True}},
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*총 신규 리뷰*\n{total_all}건"},
                {"type": "mrkdwn", "text": f"*😊 긍정*\n{total_pos}건"},
                {"type": "mrkdwn", "text": f"*😟 부정*\n{total_neg}건"},
            ]
        },
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*병원별 현황*\n" + "\n".join(rows)}},
    ]

    if sample_text:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*🚨 부정 리뷰 샘플*\n{sample_text}"}})

    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"📅 집계: {yesterday} | 🤖 자동 리포트"}]})

    send_slack(blocks, channel=ALERT_CHANNEL,
               text=f"[일간 리포트] 신규 {total_all}건 | 긍정 {total_pos} | 부정 {total_neg}")
    print("📊 일간 리포트 전송 완료")


def send_weekly_summary():
    """매주 월요일 주간 요약"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    today = datetime.now().strftime("%Y-%m-%d")

    stats = c.execute("""
        SELECT hospital_name,
               COUNT(*) as total,
               SUM(CASE WHEN sentiment='positive' THEN 1 ELSE 0 END) as pos,
               SUM(CASE WHEN sentiment='negative' THEN 1 ELSE 0 END) as neg
        FROM reviews
        WHERE crawled_at >= ? AND crawled_at < ?
        GROUP BY hospital_id, hospital_name
        ORDER BY neg DESC
    """, (week_ago, today)).fetchall()
    conn.close()

    if not stats:
        return

    rows = [f"• *{n}* | 총 {t}건 | 😊{p}건 😟{g}건" for n, t, p, g in stats]
    date_str = datetime.now().strftime("%Y년 %m월 %d일")

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"📈 주간 리뷰 요약 — {date_str}", "emoji": True}},
        {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(rows)}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f"📅 {week_ago} ~ {today}"}]},
    ]
    send_slack(blocks, channel=ALERT_CHANNEL, text="[주간 리뷰 요약]")
    print("📈 주간 요약 전송 완료")


if __name__ == "__main__":
    send_daily_report()
