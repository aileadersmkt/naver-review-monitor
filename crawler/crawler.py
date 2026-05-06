"""
네이버 플레이스 리뷰 크롤러 (병원용 — 다중 API 엔드포인트 시도)
"""

import requests
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

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

# 시도할 API 엔드포인트 목록
API_ENDPOINTS = [
    "https://m.place.naver.com/hospital/{place_id}/review/visitor",
    "https://api.place.naver.com/graphql",
    "https://place.map.naver.com/hospital/v1/summary/{place_id}/visitorReview",
    "https://map.naver.com/p/api/place/summary/{place_id}/visitorReview",
]

def get_headers(place_id: str) -> dict:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Referer": f"https://map.naver.com/p/entry/place/{place_id}",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Origin": "https://map.naver.com",
        "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
    }

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

def fetch_reviews_v2(hospital: dict, page: int = 1) -> list:
    """모바일 API로 리뷰 수집"""
    place_id = hospital["place_id"]
    
    # 모바일 API 시도
    urls = [
        f"https://m.place.naver.com/hospital/{place_id}/review/visitor?page={page}",
        f"https://place.map.naver.com/place/v1/summary/{place_id}/visitorReview?page={page}&pageSize=10&type=visit",
        f"https://place.map.naver.com/hospital/v1/summary/{place_id}/visitorReview?page={page}&pageSize=10&type=visit&isPhotoUsed=false",
    ]
    
    mobile_headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
        "Referer": f"https://m.place.naver.com/hospital/{place_id}/review/visitor",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ko-KR,ko;q=0.9",
    }
    
    for url in urls:
        try:
            resp = requests.get(url, headers=mobile_headers, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                result = data.get("result", data)
                reviews_raw = (
                    result.get("visitorReviews") or
                    result.get("reviews") or
                    result.get("items") or []
                )
                if reviews_raw:
                    reviews = []
                    for r in reviews_raw:
                        writer = r.get("writerInfo", {})
                        author = writer.get("nickname", "익명") if isinstance(writer, dict) else "익명"
                        content = r.get("body", r.get("content", r.get("text", ""))) or ""
                        reviews.append({
                            "id": str(r.get("id", r.get("reviewId", ""))),
                            "author": author,
                            "content": content,
                            "visit_count": r.get("visitCount", 0),
                            "created_at": r.get("created", r.get("createdAt", r.get("visitDate", ""))),
                        })
                    print(f"  ✅ API 성공: {url[:60]}...")
                    return reviews
        except Exception as e:
            print(f"  ⚠️  {url[:60]}... → {str(e)[:50]}")
            continue
    
    return []

def save_reviews(hospital: dict, reviews: list) -> list:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    new_reviews = []
    now = datetime.now().isoformat()

    for r in reviews:
        review_id = f"{hospital['place_id']}_{r['id']}"
        existing = c.execute("SELECT id FROM reviews WHERE id = ?", (review_id,)).fetchone()
        if not existing and r['id']:
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
            reviews = []
            for page in range(1, 4):
                page_reviews = fetch_reviews_v2(hospital, page=page)
                if not page_reviews:
                    break
                reviews.extend(page_reviews)
                time.sleep(REQUEST_DELAY + random.uniform(0, 2))

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
    run_crawler()
