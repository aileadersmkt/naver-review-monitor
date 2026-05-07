"""
메인 실행 파일
크롤링 → 슬랙 알림 통합 실행
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from crawler.crawler import run_crawler
from crawler.notifier import notify_new_reviews, send_daily_report


def crawl_and_notify():
    from datetime import datetime
    print(f"\n🚀 [{datetime.now().strftime('%H:%M:%S')}] 크롤링 시작...")
    try:
        new_reviews = run_crawler()
        notify_new_reviews(new_reviews)
        print(f"✅ 완료 — 신규 {len(new_reviews)}건\n")
    except Exception as e:
        print(f"❌ 실행 오류: {e}")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "once"

    if mode == "report":
        send_daily_report()
    elif mode == "once":
        crawl_and_notify()
