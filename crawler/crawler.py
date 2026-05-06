"""
네이버 플레이스 리뷰 크롤러 (Playwright 브라우저 방식)
실제 브라우저처럼 페이지를 열어서 리뷰를 수집
"""

import json
import time
import sqlite3
import random
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
CONFIG_PATH = BASE_DIR / "config" / "hospitals.json"
DB_PATH = BASE_DIR / "data" / "reviews.db"

with open(CONFIG_PATH) as f:
    CONFIG = json.load(f)

HOSPITALS = CONFIG["hospitals"]
REQUEST_DELAY = CONFIG.get("request_delay_seconds", 4)
NEG_KEYWORDS = CONFIG["sentiment"]["negative_keywords"]
POS_KEYWORDS = CONFIG["sentiment"]["positive_keywords"]


def analyze_sentiment(content: str) -> str:
    if not content:
        return "neutral"
    neg = sum(1 for kw in NEG_KEYWORDS if kw in content)
    pos = sum(1 for kw in POS_KEYWORDS if kw in content)
    if neg > pos:
        return "negative"
    elif pos > neg:
        return "positive"
    return "neutral"


def init_db():
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            id TEXT PRIMARY KEY,
            hospital_id TEXT NOT NULL,
            hospital_name TEXT NOT NULL,
            place_id TEXT NOT NULL,
            author TEXT,
            content TEXT,
            visit_count INTEGER DEFAULT 0,
            sentiment TEXT DEFAULT 'neutral',
            created_at TEXT,
            crawled_at TEXT,
            is_new INTEGER DEFAULT 1,
            notified INTEGER DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS crawl_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hospital_id TEXT,
            crawled_at TEXT,
            new_count INTEGER DEFAULT 0,
            total_count INTEGER DEFAULT 0,
            status TEXT,
            error_msg TEXT
        )
    """)
    conn.commit()
    conn.close()
    print("✅ DB 초기화 완료")


def fetch_reviews_playwright(hospital: dict) -> list:
    from playwright.sync_api import sync_playwright
    place_id = hospital["place_id"]
    url = f"https://m.place.naver.com/hospital/{place_id}/review/visitor"
    reviews = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox","--disable-setuid-sandbox","--disable-dev-shm-usage","--disable-gpu"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
            viewport={"width": 390, "height": 844},
            locale="ko-KR",
        )
        page = context.new_page()
        try:
            page.goto(url, wait_until="networkidle", timeout=30000)
            time.sleep(2)
            review_items = page.query_selector_all("li.place_review_item, div.review_item, li[class*='review']")
            if not review_items:
                review_items = page.query_selector_all("[class*='ReviewItem'], [class*='review_item'], [data-review-id]")
            print(f"  📋 리뷰 항목 감지: {len(review_items)}개")
            for i, item in enumerate(review_items[:20]):
                try:
                    author_el = item.query_selector("[class*='nickname'], [class*='author'], [class*='writer']")
                    author = author_el.inner_text().strip() if author_el else "익명"
                    content_el = item.query_selector("[class*='body'], [class*='content'], [class*='text'], p")
                    content = content_el.inner_text().strip() if content_el else ""
                    date_el = item.query_selector("[class*='date'], [class*='time'], time")
                    created_at = date_el.inner_text().strip() if date_el else ""
                    visit_el = item.query_selector("[class*='visit'], [class*='count']")
                    visit_text = visit_el.inner_text().strip() if visit_el else "0"
                    visit_count = int(''.join(filter(str.isdigit, visit_text)) or 0)
                    if content:
                        reviews.append({
                            "id": f"{place_id}_{i}_{hash(content) % 100000}",
                            "author": author,
                            "content": content,
                            "visit_count": visit_count,
                            "created_at": created_at,
                        })
                except:
                    continue
        except Exception as e:
            print(f"  ❌ 페이지 로드 실패: {e}")
        finally:
            browser.close()
    return reviews


def save_reviews(hospital: dict, reviews: list) -> list:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    new_reviews = []
    now = datetime.now().isoformat()
    for r in reviews:
        review_id = f"{hospital['place_id']}_{r['id']}"
        existing = c.execute("SELECT id FROM reviews WHERE id = ?", (review_id,)).fetchone()
        if not existing:
            sentiment = analyze_sentiment(r["content"])
            c.execute("""
                INSERT INTO reviews
                    (id, hospital_id, hospital_name, place_id, author, content, visit_count, sentiment, created_at, crawled_at, is_new, notified)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0)
            """, (
                review_id, hospital["id"], hospital["name"], hospital["place_id"],
                r["author"], r["content"], r["visit_count"],
                sentiment, r["created_at"], now,
            ))
            new_reviews.append({**r, "hospital_name": hospital["name"], "hospital_id": hospital["id"], "sentiment": sentiment})
    conn.commit()
    conn.close()
    return new_reviews


def log_crawl(hospital_id, new_count, total_count, status, error_msg=""):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO crawl_log (hospital_id, crawled_at, new_count, total_count, status, error_msg)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (hospital_id, datetime.now().isoformat(), new_count, total_count, status, error_msg))
    conn.commit()
    conn.close()


def run_crawler():
    print(f"\n{'='*50}")
    print(f"🏥 네이버 플레이스 리뷰 크롤러 시작 (Playwright)")
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}\n")
    init_db()
    all_new_reviews = []
    for i, hospital in enumerate(HOSPITALS):
        print(f"[{i+1}/{len(HOSPITALS)}] {hospital['name']} 수집 중...")
        try:
            reviews = fetch_reviews_playwright(hospital)
            new_reviews = save_reviews(hospital, reviews)
            log_crawl(hospital["id"], len(new_reviews), len(reviews), "success")
            print(f"  ✅ 전체: {len(reviews)}개 | 신규: {len(new_reviews)}개")
            if new_reviews:
                all_new_reviews.extend(new_reviews)
        except Exception as e:
            log_crawl(hospital["id"], 0, 0, "error", str(e))
            print(f"  ❌ 오류: {e}")
        if i < len(HOSPITALS) - 1:
            delay = REQUEST_DELAY + random.uniform(2, 4)
            print(f"  ⏳ {delay:.1f}초 대기...\n")
            time.sleep(delay)
    print(f"\n✅ 크롤링 완료 | 신규 리뷰 총 {len(all_new_reviews)}개\n")
    return all_new_reviews


if __name__ == "__main__":
    run_crawler()
