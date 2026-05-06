# 🏥 네이버 플레이스 리뷰 모니터링 MVP

병원 8개의 네이버 플레이스 리뷰를 자동 수집하고, 신규 리뷰 및 저평점 리뷰 발생 시 **슬랙으로 즉시 알림**을 보내는 시스템입니다.

---

## 📁 프로젝트 구조

```
naver-review-monitor/
├── .github/
│   └── workflows/
│       └── monitor.yml       # GitHub Actions 자동화
├── config/
│   └── hospitals.json        # 병원 설정 (Place ID, 슬랙 채널)
├── crawler/
│   ├── crawler.py            # 리뷰 수집 + DB 저장
│   └── notifier.py           # 슬랙 알림 (신규/저평점/일간리포트)
├── data/
│   └── reviews.db            # SQLite DB (자동 생성)
├── main.py                   # 메인 실행 파일
├── requirements.txt
└── README.md
```

---

## 🚀 세팅 방법 (5단계)

### 1단계 — 네이버 플레이스 ID 확인

병원 8곳의 네이버 플레이스 ID를 구해야 합니다.

```
방법: 네이버 지도에서 병원 검색 → URL 확인
예시 URL: https://map.naver.com/p/entry/place/1234567890
                                                 ↑ 이 숫자가 Place ID
```

### 2단계 — config/hospitals.json 수정

`config/hospitals.json`에서 병원 이름과 Place ID를 실제 값으로 교체하세요.

```json
{
  "hospitals": [
    {
      "id": "hospital_A",
      "name": "리더스영상의학과",
      "place_id": "여기에_실제_PLACE_ID",
      "type": "hospital",
      "slack_channel": "#리뷰-리더스"
    }
    ...
  ]
}
```

`type` 값 안내:
- 병원/의원: `"hospital"`
- 음식점: `"restaurant"`
- 그 외: `"place"`

### 3단계 — 슬랙 Webhook URL 생성

1. [api.slack.com/apps](https://api.slack.com/apps) → **Create New App**
2. **Incoming Webhooks** → **On** → **Add New Webhook to Workspace**
3. 알림 받을 채널 선택 → Webhook URL 복사

### 4단계 — 로컬 테스트

```bash
# 패키지 설치
pip install -r requirements.txt

# 환경변수 설정
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/xxx/yyy/zzz"

# 1회 실행 (크롤링 + 슬랙 알림)
python main.py

# 일간 리포트만 전송
python main.py report

# 주간 요약만 전송
python main.py weekly

# 스케줄러 모드 (로컬 상시 실행, 1시간마다 자동 수집)
python main.py scheduler
```

### 5단계 — GitHub Actions 자동화 세팅

GitHub 저장소에 업로드 후:

1. **Repository → Settings → Secrets and variables → Actions**
2. **New repository secret** 추가:
   - Name: `SLACK_WEBHOOK_URL`
   - Value: 슬랙 Webhook URL

자동 실행 스케줄:
| 작업 | 주기 |
|------|------|
| 리뷰 수집 + 신규 알림 | 매 1시간 |
| 일간 리포트 | 매일 오전 9:00 KST |
| 주간 요약 | 매주 월요일 오전 9:10 KST |

---

## 📣 슬랙 알림 종류

### 1. 신규 리뷰 알림 (실시간)
```
🆕 새 리뷰 - 리더스영상의학과
병원: 리더스영상의학과     평점: 🟢 ⭐⭐⭐⭐⭐ (5점)
작성자: 방문자 김*         작성일: 2025-06-05
리뷰 내용
> 선생님이 정말 친절하시고 설명도 자세하게 해주셨어요.
```

### 2. 저평점 경고 알림 (3점 이하 즉시)
```
🚨 저평점 리뷰 경고 - 리더스영상의학과
병원: 리더스영상의학과     평점: 🔴 ⭐⭐ (2점)
...
```

### 3. 일간 리포트 (매일 오전 9시)
```
📊 일간 리뷰 리포트 — 2025년 6월 5일
총 신규 리뷰: 24건    저평점 리뷰: 3건 🔴
병원별 현황
• 리더스영상의학과 — 5건 | 평균 4.7점
• 병원 B — 4건 | 평균 4.4점
• 병원 C — 3건 | 평균 3.2점 🔴×1
```

---

## ⚠️ 주의사항

- 네이버는 빠른 반복 요청 시 IP 차단 가능 → 요청 간격 4초 유지
- GitHub Actions 무료 플랜: 월 2,000분 제공 (1시간 주기 = 약 720분/월 → 무료 범위 내)
- DB는 GitHub Actions 캐시에 저장되며, 캐시 만료(7일) 시 초기화될 수 있음
  - 장기 운영 시 Supabase (무료) 연동 권장

---

## 🔧 업그레이드 옵션

| 기능 | 방법 |
|------|------|
| DB 영구 보관 | Supabase PostgreSQL 연동 |
| 리뷰 감성 분석 | Claude API 연동 |
| 키워드 트렌드 | 형태소 분석 (konlpy) |
| 대시보드 웹 앱 | Streamlit 배포 |
| 카카오 알림톡 | 카카오 비즈메시지 API |
