"""
네이버 플레이스 리뷰 크롤러 (Playwright + Supabase)
"""

import json
import time
import os
import random
import requests
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
CONFIG_PATH = BASE_DIR / "config" / "hospitals.json"

with open(CONFIG_PATH) as f:
    CONFIG = json.load(f)

HOSPITALS = CONFIG["hospitals"]
REQUEST_DELAY = CONFIG.get("request_delay_seconds", 4)

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
SUPABASE_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=minimal"
}


def supabase_get(table: str, params: dict = None) -> list:
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    resp = requests.get(url, headers=SUPABASE_HEADERS, params=params, timeout=10)
    return resp.json() if resp.status_code == 200 else []


def supabase_insert(table: str, data: dict) -> bool:
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    resp = requests.post(url, headers=SUPABASE_HEADERS, json=data, timeout=10)
    return resp.status_code in [200, 201]


def review_exists(review_id: str) -> bool:
    result = supabase_get("reviews", {"id": f"eq.{review_id}", "select": "id"})
    return len(result) > 0


def fetch_reviews_playwright(hospital: dict) -> list:
    from playwright.sync_api import sync_playwright
    place_id = hospital["place_id"]
    url = f"https://m.place.naver.com/hospital/{place_id}/review/visitor"
    reviews = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
            viewport={"width": 390, "height": 844},
            locale="ko-KR",
        )
        page = context.new_page()
        try:
            page.goto(url, wait_until="networkidle", timeout=30000)
            time.sleep(3)

            review_items = page.query_selector_all("li.place_apply_pui")
            print(f"  📋 리뷰 항목 감지: {len(review_items)}개")

            for i, item in enumerate(review_items[:20]):
                try:
                    # 리뷰 내용
                    content = ""
                    for sel in ["a.pui__GStJHb", "a[data-pui-click-code='rvshowmore']", "a[data-pui-click-code='rvshowless']"]:
                        el = item.query_selector(sel)
                        if el:
                            text = el.inner_text().strip()
                            if text and len(text) > 5:
                                content = text
                                break

                    if not content:
                        full = item.inner_text().strip()
                        lines = [l.strip() for l in full.split('\n') if l.strip() and len(l.strip()) > 10]
                        if lines:
                            content = lines[0]

                    if content:
                        reviews.append({
                            "id": f"{place_id}_{i}_{hash(content) % 100000}",
                            "content": content,
                        })
                except:
                    continue

        except Exception as e:
            print(f"  ❌ 페이지 로드 실패: {e}")
        finally:
            browser.close()
    return reviews


def save_reviews(hospital: dict, reviews: list) -> list:
    new_reviews = []
    now = datetime.now().isoformat()

    for r in reviews:
        review_id = f"{hospital['place_id']}_{r['id']}"
        if not review_exists(review_id):
            data = {
                "id": review_id,
                "hospital_id": hospital["id"],
                "hospital_name": hospital["name"],
                "place_id": hospital["place_id"],
                "content": r["content"],
                "crawled_at": now,
                "is_new": 1,
                "notified": 0,
            }
            if supabase_insert("reviews", data):
                new_reviews.append({**r, "hospital_name": hospital["name"], "hospital_id": hospital["id"]})

    return new_reviews


def log_crawl(hospital_id, new_count, total_count, status, error_msg=""):
    supabase_insert("crawl_log", {
        "hospital_id": hospital_id,
        "crawled_at": datetime.now().isoformat(),
        "new_count": new_count,
        "total_count": total_count,
        "status": status,
        "error_msg": error_msg,
    })


def run_crawler():
    print(f"\n{'='*50}")
    print(f"🏥 네이버 플레이스 리뷰 크롤러 시작 (Playwright + Supabase)")
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}\n")

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
