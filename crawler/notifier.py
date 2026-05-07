"""
슬랙 알림 모듈 (Supabase 연동 + 병원별 채널)
신규 리뷰만 알림, 없으면 조용
"""

import json
import os
import requests
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
CONFIG_PATH = BASE_DIR / "config" / "hospitals.json"

with open(CONFIG_PATH) as f:
    CONFIG = json.load(f)

SLACK_CONFIG = CONFIG["slack"]
WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL") or SLACK_CONFIG["webhook_url"]
ALERT_CHANNEL = SLACK_CONFIG.get("alert_channel", "#004-병원-리뷰-전체알림")
HOSPITAL_MAP = {h["id"]: h for h in CONFIG["hospitals"]}

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
SUPABASE_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=minimal"
}


def supabase_patch(table: str, filter_param: str, data: dict):
    url = f"{SUPABASE_URL}/rest/v1/{table}?{filter_param}"
    requests.patch(url, headers=SUPABASE_HEADERS, json=data, timeout=10)


def send_slack(blocks: list, channel: str = None, text: str = "리뷰 알림") -> bool:
    if not WEBHOOK_URL or WEBHOOK_URL == "YOUR_SLACK_WEBHOOK_URL":
        print(f"⚠️  Slack Webhook URL 미설정")
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


def notify_new_reviews(reviews: list):
    """신규 리뷰 슬랙 알림 — 없으면 조용"""
    if not reviews:
        print("📭 신규 리뷰 없음 — 알림 생략")
        return

    print(f"\n📣 슬랙 알림 전송 ({len(reviews)}건)...")

    for r in reviews:
        hospital_name = r.get("hospital_name", "병원")
        content = (r.get("content", "") or "내용 없음")[:200]
        review_id = r.get("id", "")

        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"🆕 새 리뷰 — {hospital_name}", "emoji": True}
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*병원*\n{hospital_name}"}
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*리뷰 내용*\n> {content}"}
            },
            {"type": "divider"}
        ]

        # 병원별 채널로 전송
        hosp_info = HOSPITAL_MAP.get(r.get("hospital_id", ""), {})
        channel = hosp_info.get("slack_channel")

        success = send_slack(blocks, channel=channel, text=f"새 리뷰 — {hospital_name}: {content[:50]}")

        if success and review_id:
            supabase_patch("reviews", f"id=eq.{review_id}", {"notified": 1})

        import time
        time.sleep(0.5)

    print("✅ 알림 전송 완료")


def send_daily_report():
    """매일 오전 9시 일간 리포트"""
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    url = f"{SUPABASE_URL}/rest/v1/reviews"
    params = {
        "crawled_at": f"gte.{yesterday}",
        "select": "hospital_name,hospital_id",
    }
    headers = {**SUPABASE_HEADERS, "Prefer": ""}
    resp = requests.get(url, headers=headers, params=params, timeout=10)
    rows = resp.json() if resp.status_code == 200 else []

    if not rows:
        print("📊 어제 수집된 리뷰 없음")
        return

    # 병원별 집계
    from collections import Counter
    counts = Counter(r["hospital_name"] for r in rows)
    total = len(rows)
    date_str = datetime.now().strftime("%Y년 %m월 %d일")
    row_lines = "\n".join([f"• *{name}* — {cnt}건" for name, cnt in counts.most_common()])

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"📊 일간 리뷰 리포트 — {date_str}", "emoji": True}},
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"*총 신규 리뷰*\n{total}건"},
        ]},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*병원별 현황*\n{row_lines}"}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f"📅 집계: {yesterday} | 🤖 자동 리포트"}]}
    ]

    send_slack(blocks, channel=ALERT_CHANNEL, text=f"[일간 리포트] 신규 {total}건")
    print("📊 일간 리포트 전송 완료")


if __name__ == "__main__":
    send_daily_report()
