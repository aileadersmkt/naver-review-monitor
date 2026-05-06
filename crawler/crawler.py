"""
네이버 플레이스 리뷰 크롤러 (병원용 — 평점 없음)
병원 8개 리뷰 자동 수집 + SQLite 저장
"""

import requests
import json
import time
import sqlite3
import os
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

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
]

def get_headers(place_id: str) -> dict:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Referer": f"https://map.naver.com/p/entry/place/{place_id}",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Origin": "https://map.naver.com",
    }


def analyze_sentiment(content: str) -> str:
    """키워드 기반 감성 분석 — positive / negative / neutral"""
    if not content:
        return "neutral"
    neg = sum(1 for kw in NEG_KEYWORDS if kw in content)
    pos = sum(1 for kw in POS_KEYWORDS if kw in content)
    if neg > pos:
        return "negative"
    elif pos > neg:
        return "positive"
    elif pos == neg and pos > 0:
        return "neutral"
    return "neutral"


def init_db():
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            id              TEXT PRIMARY KEY,
            hospital_id     TEXT NOT NULL,
            hospital_name   TEXT NOT NULL,
            place_id        TEXT NOT NULL,
            author          TEXT,
            content         TEXT,
            visit_count     INTEGER DEFAULT 0,
            sentiment       TEXT DEFAULT 'neutral',
            created_at      TEXT,
            crawled_at      TEXT,
            is_new          INTEGER DEFAULT 1,
            notified        INTEGER DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS crawl_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            hospital_id     TEXT,
            crawled_at      TEXT,
            new_count       INTEGER DEFAULT 0,
            total_count     INTEGER DEFAULT 0,
            status          TEXT,
            error_msg       TEXT
        )
    """)
    conn.commit()
    conn.close()
    print("✅ DB 초기화 완료")


def fetch_reviews(hospital: dict, page: int = 1, page_size: int = 10) -> list:
    place_id = hospital["place_id"]
    url = (
        f"https://place.map.naver.com/hospital/v1/summary/{place_id}/visitorReview"
        f"?page={page}&pageSize={page_size}&type=visit&isPhotoUsed=false"
    )
    try:
        resp = requests.get(url, headers=get_headers(place_id), timeout=10)
        resp.raise_for_status()
        data = resp.json()
        result = data.get("result", {})
        reviews_raw = result.get("visitorReviews", []) or result.get("reviews", [])
        reviews = []
        for r in reviews_raw:
            writer = r.get("writerInfo", {})
            author = writer.get("nickname", "익명") if isinstance(writer, dict) else r.get("authorName", "익명")
            content = r.get("body", r.get("content", "")) or ""
            reviews.append({
                "id": str(r.get("id", "")),
                "author": author,
                "content": content,
                "visit_count": r.get("visitCount", 0),
                "created_at": r.get("created", r.get("createdAt", "")),
            })
        return reviews
    except requests.exceptions.HTTPError as e:
        print(f"  ⚠️  HTTP 에러 [{hospital['name']}]: {e}")
        return []
    except Exception as e:
        print(f"  ❌ 수집 실패 [{hospital['name']}]: {e}")
        return []


def fetch_all_reviews(hospital: dict, max_pages: int = 5) -> list:
    all_reviews = []
    for page in range(1, max_pages + 1):
        reviews = fetch_reviews(hospital, page=page)
        if not reviews:
            break
        all_reviews.extend(reviews)
        time.sleep(REQUEST_DELAY + random.uniform(0, 1.5))
    return all_reviews


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
    print(f"🏥 네이버 플레이스 리뷰 크롤러 시작")
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}\n")

    init_db()
    all_new_reviews = []

    for i, hospital in enumerate(HOSPITALS):
        print(f"[{i+1}/{len(HOSPITALS)}] {hospital['name']} 수집 중...")
        try:
            reviews = fetch_all_reviews(hospital, max_pages=5)
            new_reviews = save_reviews(hospital, reviews)
            log_crawl(hospital["id"], len(new_reviews), len(reviews), "success")
            print(f"  ✅ 전체: {len(reviews)}개 | 신규: {len(new_reviews)}개")
            if new_reviews:
                all_new_reviews.extend(new_reviews)
        except Exception as e:
            log_crawl(hospital["id"], 0, 0, "error", str(e))
            print(f"  ❌ 오류: {e}")

        if i < len(HOSPITALS) - 1:
            delay = REQUEST_DELAY + random.uniform(1, 3)
            print(f"  ⏳ {delay:.1f}초 대기...\n")
            time.sleep(delay)

    print(f"\n✅ 크롤링 완료 | 신규 리뷰 총 {len(all_new_reviews)}개\n")
    return all_new_reviews


if __name__ == "__main__":
    new_reviews = run_crawler()
