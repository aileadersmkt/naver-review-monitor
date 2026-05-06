"""
메인 실행 파일
크롤링 → 슬랙 알림 → 리포트 통합 실행
"""

import sys
import time
import schedule
import json
from pathlib import Path
from datetime import datetime

# 경로 설정
sys.path.insert(0, str(Path(__file__).parent))

from crawler.crawler import run_crawler, init_db
from crawler.notifier import notify_new_reviews, send_daily_report, send_weekly_summary


def crawl_and_notify():
    """크롤링 + 슬랙 알림 통합 실행"""
    print(f"\n🚀 [{datetime.now().strftime('%H:%M:%S')}] 크롤링 시작...")
    try:
        new_reviews = run_crawler()
        notify_new_reviews(new_reviews)
        print(f"✅ 완료 — 신규 {len(new_reviews)}건 알림 전송\n")
    except Exception as e:
        print(f"❌ 실행 오류: {e}")


def run_scheduler():
    """스케줄러 실행 (1시간마다 크롤링, 매일 9시 리포트)"""
    print("⏰ 스케줄러 모드 시작")
    print("  - 크롤링: 매 1시간")
    print("  - 일간 리포트: 매일 오전 9:00")
    print("  - 주간 요약: 매주 월요일 오전 9:10")

    # 즉시 1회 실행
    crawl_and_notify()

    # 스케줄 등록
    schedule.every(1).hours.do(crawl_and_notify)
    schedule.every().day.at("09:00").do(send_daily_report)
    schedule.every().monday.at("09:10").do(send_weekly_summary)

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "once"

    init_db()

    if mode == "scheduler":
        run_scheduler()
    elif mode == "report":
        send_daily_report()
    elif mode == "weekly":
        send_weekly_summary()
    else:
        # 1회 실행 (GitHub Actions용)
        crawl_and_notify()
