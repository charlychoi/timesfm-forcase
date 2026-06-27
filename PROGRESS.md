# PROGRESS.md — 작업 진행 현황

> 최종 업데이트: 2026-06-27

---

## 완료된 작업

### [2026-06-27] v1.1 — 신뢰도 분석 + 백테스트 + UI 개선
**커밋:** `7829916`

**백엔드:**
- `calculate_mape()` — MAPE 계산
- `calculate_directional_accuracy()` — 방향성 적중률
- `calculate_volatility_level()` — 변동성 등급 (암호화폐/주식 기준 분리)
- `calculate_confidence_score()` — 신뢰도 점수 0~100 + 등급 레이블
- `generate_interpretation()` — 규칙 기반 한국어 해석 문장
- `run_backtest()` — 롤링 백테스트 (슬라이딩 윈도우, TTL 1시간)
- `/api/forecast/{symbol}` 응답에 `volatility` + horizon별 신뢰도 필드 추가
- `/api/health` 에 `backtest_cache` 상태 추가

**프론트엔드:**
- `safeFetchJson()` — Content-Type 검증 후 JSON 파싱
- `.conf-badge` / `.vol-badge` / `.fc-meta` CSS 클래스
- `#interpret-box` — AI 해석 박스
- 종목 카드: 7일 신뢰도 + 변동성 표시
- 예측 카드: 신뢰도/MAPE/방향성/변동성 표시
- 예측 테이블: 4개 컬럼 추가
- 모델 안내 배너 문구 개선

---

### [이전] v1.0 — 초기 구현
- TimesFM 2.5 Zero-Shot 예측
- BTC/ETH/XRP + 삼성전자/SK하이닉스/현대차/KOSPI
- Vercel 정적 배포 + Railway 백엔드
- Chart.js 예측 차트
- 1/7/14/30일 예측 카드

---

## 현재 작업 중

없음 (2026-06-27 기준)

---

## 다음 작업 (Claude Code 인수 후)

### 즉시 처리 권장

1. **백테스트 진행률 스트리밍**
   - 문제: 백테스트 첫 실행 시 (3~10분) UI 피드백 없음
   - 해결책: SSE (Server-Sent Events) 엔드포인트 `/api/backtest/stream/{symbol}`
   - 파일: `api/main.py` + `frontend/index.html`

2. **한국 주식 거래일 필터**
   - 문제: 예측 날짜 계산이 캘린더 기준 (주말/공휴일 포함)
   - 해결책: `pandas_market_calendars` 또는 직접 KRX 공휴일 리스트
   - 파일: `api/main.py` → `_do_forecast()` 내 `forecast_dates` 생성 로직

3. **로딩 메시지 개선**
   - 문제: 모델 첫 로드 시 (1~2분) 단순 스피너만 표시
   - 해결책: 로딩 단계별 메시지 ("모델 로드 중...", "데이터 수집 중...", "예측 실행 중...")
   - 파일: `frontend/index.html` → `doForecast()` + `loading-txt`

### 다음 단계

4. `/api/backtest/{symbol}` 독립 엔드포인트 분리
5. 과거 예측 vs 실제 비교 시각화
6. Railway 재배포

---

## 알려진 버그 / 이슈

| 이슈 | 심각도 | 파일 | 설명 |
|---|---|---|---|
| 백테스트 무응답 | 중간 | main.py | 첫 실행 시 3~10분 동안 API 응답 없음 (진행 피드백 없음) |
| KR 주식 예측 날짜 | 낮음 | main.py | 주말/공휴일 포함된 날짜로 예측일 표시 |
| KOSPI 단위 | 낮음 | index.html | 일부 극단적 수치에서 소수점 표시 이슈 가능성 |

---

## 개발 환경 세팅 (Claude Code용)

```bash
# 1. 레포 클론 (이미 있으면 스킵)
git clone https://github.com/charlychoi/timesfm-forcase.git
cd timesfm-forcase

# 2. Python 의존성
pip install -r api/requirements.txt

# 3. 로컬 실행
./start.sh
# → http://localhost:8000

# 4. API 확인
curl http://localhost:8000/api/health
```

---

## 파일별 역할 요약

| 파일 | 역할 |
|---|---|
| `api/main.py` | 전체 백엔드 로직 (예측 + 분석 + API) |
| `frontend/index.html` | 전체 프론트엔드 (CSS + JS 인라인) |
| `api/requirements.txt` | Python 패키지 목록 |
| `api/Procfile` | Railway 배포 진입점 |
| `api/nixpacks.toml` | Railway 빌드 설정 |
| `vercel.json` | Vercel 정적 배포 설정 |
| `start.sh` | 로컬 실행 스크립트 |
| `HANDOVER.md` | 전체 인수인계 문서 |
| `PRD.md` | 제품 요구사항 |
| `PROGRESS.md` | 이 파일 (진행 현황) |
