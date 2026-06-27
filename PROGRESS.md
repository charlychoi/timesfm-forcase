# PROGRESS.md — 작업 진행 현황

> 최종 업데이트: 2026-06-27 18:07 KST

---

## ✅ 완료된 작업

### [2026-06-27] v1.1-fix — NaN 버그픽스
**커밋:** `8a7724a`

- `calculate_confidence_score()`: MAPE NaN 유입 시 ValueError 발생 수정
- `calculate_mape()`: 결과 NaN/Inf → None 반환으로 안전 처리
- `import math` 추가
- **영향 종목:** KOSPI, 삼성전자 등 KR 주식 전체 (백테스트 캐시 없는 첫 실행 시)

---

### [2026-06-27] v1.1 — 신뢰도 분석 + 백테스트 + UI 개선
**커밋:** `7829916`

**백엔드 (`api/main.py`):**
- `calculate_mape()` — MAPE 계산
- `calculate_directional_accuracy()` — 방향성 적중률
- `calculate_volatility_level()` — 변동성 등급 (암호화폐/주식 기준 분리)
- `calculate_confidence_score()` — 신뢰도 점수 0~100 + 등급 레이블
- `generate_interpretation()` — 규칙 기반 한국어 해석 문장
- `run_backtest()` — 롤링 백테스트 (슬라이딩 윈도우, TTL 1시간)
- `/api/forecast/{symbol}` 응답에 `volatility` + horizon별 신뢰도 필드 추가
- `/api/health` 에 `backtest_cache` 상태 추가

**프론트엔드 (`frontend/index.html`):**
- `safeFetchJson()` — Content-Type 검증 후 JSON 파싱
- `.conf-badge` / `.vol-badge` / `.fc-meta` CSS 클래스
- `#interpret-box` — AI 해석 박스
- 종목 카드: 7일 신뢰도 + 변동성 표시
- 예측 카드: 신뢰도/MAPE/방향성/변동성 표시
- 예측 테이블: 신뢰도·MAPE·방향성·변동성 컬럼 4개 추가
- 모델 안내 배너 문구 개선

---

### [이전] v1.0 — 초기 구현
- TimesFM 2.5 Zero-Shot 예측 (BTC/ETH/XRP + KR 4종목)
- Vercel 정적 배포 + Railway 백엔드 구조
- Chart.js 예측 차트 (과거 90일 + 예측 30일)
- 1/7/14/30일 예측 카드 + 신뢰 구간(q10/q90)

---

## 🔲 다음 작업 (Claude Code 인수 후)

### 🔴 즉시 처리 권장

#### 1. 백테스트 진행률 스트리밍
- **문제:** 첫 백테스트 실행 시 3~10분 동안 API 무응답 → 사용자 이탈 위험
- **해결책:** SSE(Server-Sent Events) 엔드포인트 `/api/backtest/stream/{symbol}`
- **구현 포인트:**
  ```python
  from fastapi.responses import StreamingResponse
  import asyncio

  @app.get("/api/backtest/stream/{symbol}")
  async def backtest_stream(symbol: str):
      async def generator():
          # 진행상황을 yield로 스트리밍
          yield f"data: {json.dumps({'step': 1, 'total': 8, 'msg': '데이터 준비 중...'})}\n\n"
          ...
      return StreamingResponse(generator(), media_type="text/event-stream")
  ```
- **파일:** `api/main.py` + `frontend/index.html`

#### 2. 한국 주식 거래일 필터
- **문제:** 예측 날짜 계산이 캘린더 기준 → 주말·공휴일 포함됨
- **해결책 A(간단):** `pandas_market_calendars` 설치 후 `XKRX` 캘린더 사용
  ```python
  import pandas_market_calendars as mcal
  krx = mcal.get_calendar('XKRX')
  schedule = krx.schedule(start_date=today, end_date=today + timedelta(days=60))
  trading_days = schedule.index.strftime('%Y-%m-%d').tolist()
  ```
- **해결책 B(간단):** 주말만 제거 (공휴일 제외 생략)
- **파일:** `api/main.py` → `_do_forecast()` 내 `forecast_dates` 생성 로직

#### 3. 로딩 단계 메시지
- **문제:** 모델 첫 로드 시(1~3분) 단순 스피너만 표시
- **해결책:** 단계별 메시지 ("모델 로드 중...", "데이터 수집 중...", "예측 실행 중...")
- **파일:** `frontend/index.html` → `#loading-txt` 요소 + `doForecast()` 함수

---

### 🟡 다음 우선순위

#### 4. `/api/backtest/{symbol}` 독립 엔드포인트
- 예측과 분리된 백테스트 전용 API
- 프론트에서 예측과 백테스트를 별도 버튼으로 트리거 가능

#### 5. 과거 예측 vs 실제 비교 섹션
- 최근 30일간 예측값과 실제 종가 비교 차트
- 모델 정확도를 사용자가 직접 확인 가능

#### 6. Railway 백엔드 재배포
- `api/Procfile` + `api/nixpacks.toml` 준비돼 있음
- Railway 대시보드에서 배포 후 `RAILWAY_API_URL` 업데이트 필요

---

### 🟢 낮은 우선순위

- 다크/라이트 모드 토글
- 모바일 UX 세밀 최적화
- 자산 추가 UI (사용자가 직접 티커 입력)
- 예측 히스토리 저장 (localStorage)

---

## 🐛 알려진 버그 / 이슈

| # | 이슈 | 심각도 | 상태 | 설명 |
|---|---|---|---|---|
| 1 | 백테스트 첫 실행 무응답 | 중 | 미해결 | 3~10분 API 무응답, UI 피드백 없음 |
| 2 | KR 주식 예측 날짜 주말 포함 | 낮 | 미해결 | 캘린더 기준 날짜 계산 |
| 3 | Railway 백엔드 비활성 | 낮 | 미해결 | 현재 로컬 모드만 동작 |

---

## 🛠 개발 환경 세팅 (Claude Code 시작 시)

```bash
# 1. 레포 확인 (이미 클론돼 있으면 스킵)
cd /Users/charlychoi/.openclaw/workspace/timesfm-forecast

# 2. 의존성 (이미 설치돼 있으면 스킵)
pip install -r api/requirements.txt

# 3. 서버 실행
./start.sh
# → http://localhost:8000

# 4. 상태 확인
curl http://localhost:8000/api/health

# 5. 문법 검사
python3 -c "import ast; ast.parse(open('api/main.py').read()); print('OK')"
```

---

## 📁 파일별 역할 요약

| 파일 | 역할 |
|---|---|
| `api/main.py` | 전체 백엔드 로직 (예측 + 분석 + API) |
| `frontend/index.html` | 전체 프론트엔드 (CSS + JS 인라인 단일 파일) |
| `api/requirements.txt` | Python 패키지 목록 |
| `api/Procfile` | Railway 배포 진입점 |
| `api/nixpacks.toml` | Railway 빌드 설정 |
| `vercel.json` | Vercel 정적 배포 설정 |
| `start.sh` | 로컬 실행 스크립트 |
| `HANDOVER.md` | 프로젝트 구조 + 함수 레퍼런스 |
| `PRD.md` | 제품 요구사항 + 로드맵 |
| `PROGRESS.md` | 이 파일 (작업 이력 + 다음 할 일) |
