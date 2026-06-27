# HANDOVER.md — TimesFM Forecast 인수인계

> 최종 업데이트: 2026-06-27 18:07 KST  
> 인계자: OpenClaw (오프너)  
> 인수자: Claude Code 또는 다음 작업자  
> GitHub: https://github.com/charlychoi/timesfm-forcase

---

## 1. 프로젝트 개요

**TimesFM 2.5 기반 암호화폐 & 한국 주식 AI 예측 웹앱**

- 백엔드: FastAPI + TimesFM 2.5 (200M PyTorch)
- 프론트엔드: 단일 HTML (Chart.js, 프레임워크 없음)
- 데이터: CoinGecko (BTC/ETH/XRP) + Yahoo Finance (삼성전자/SK하이닉스/현대차/KOSPI)
- 배포: Vercel (프론트 정적) + Railway (백엔드) — **현재 로컬 테스트 모드**

---

## 2. 디렉토리 구조

```
timesfm-forecast/
├── api/
│   ├── main.py            # FastAPI 백엔드 (핵심 — 모든 로직)
│   ├── requirements.txt   # Python 의존성
│   ├── Procfile           # Railway 배포용
│   └── nixpacks.toml      # Railway 빌드 설정
├── frontend/
│   ├── index.html         # 단일 페이지 UI (CSS+JS 인라인)
│   └── api-unavailable.json  # Vercel 폴백용
├── vercel.json            # Vercel 정적 배포 설정
├── .vercelignore
├── start.sh               # 로컬 실행 스크립트
├── HANDOVER.md            # 이 파일
├── PRD.md                 # 제품 요구사항 문서
└── PROGRESS.md            # 작업 진행 현황
```

---

## 3. 로컬 실행

```bash
cd timesfm-forecast
./start.sh
# → http://localhost:8000
# → API 문서: http://localhost:8000/docs
# → 헬스체크: http://localhost:8000/api/health
```

**수동 실행:**
```bash
cd timesfm-forecast/api
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

> ⚠️ **첫 예측 시 TimesFM 모델(~315MB) 다운로드 + 로드에 1~3분 소요.** 그 이후는 캐시됨.

---

## 4. 백엔드 구조 (`api/main.py`)

### 전역 변수 / 캐시

```python
_model           # TimesFM 모델 싱글톤
_price_cache     # 가격 캐시  TTL: 5분  (CACHE_TTL=300)
_forecast_cache  # 예측 캐시  TTL: 10분 (FORECAST_TTL=600)
_backtest_cache  # 백테스트   TTL: 1시간 (BACKTEST_TTL=3600)
```

### 함수 목록

| 함수 | 역할 | 비고 |
|---|---|---|
| `get_model()` | TimesFM 모델 로드 싱글톤 | 첫 호출 시 1~3분 |
| `http_get(url)` | CoinGecko REST 호출 + retry | 429/5xx → backoff |
| `fetch_crypto_prices(coin_id)` | CoinGecko 365일 가격 | (prices, current, change_24h) |
| `fetch_kr_stock_prices(ticker)` | yfinance 1년 가격 | (prices, current, change_24h) |
| `calculate_mape(actual, predicted)` | MAPE 계산 | None·NaN 안전 처리 |
| `calculate_directional_accuracy(base, actual, predicted)` | 방향성 적중률 | % 반환 |
| `calculate_volatility_level(prices, asset_type)` | 변동성 등급 | 암호화폐/주식 기준 분리 |
| `calculate_confidence_score(mape, da, vol, range_pct, horizon)` | 신뢰도 0~100 + 레이블 | NaN/Inf 방어 처리 ✅ |
| `generate_interpretation(...)` | 한국어 해석 문장 생성 | 규칙 기반 |
| `run_backtest(symbol, prices, asset_type)` | 롤링 백테스트 | 슬라이딩 윈도우, TTL 1h |
| `_do_forecast(symbol)` | 메인 예측 실행 | 위 함수 모두 통합 |
| `run_forecast(symbol)` | 예측 캐시 래퍼 | TTL 10분 |

### API 엔드포인트

| 메서드 + 경로 | 설명 |
|---|---|
| `GET /` | 프론트엔드 index.html 서빙 |
| `GET /api/health` | 서버·모델·캐시 상태 |
| `GET /api/assets` | 지원 자산 목록 |
| `GET /api/forecast/{symbol}` | 예측 실행 (BTC·ETH·XRP·005930·000660·005380·KOSPI) |
| `GET /api/cache/clear` | 전체 캐시 초기화 |

### `/api/forecast/{symbol}` 응답 구조 (요약)

```json
{
  "symbol": "BTC",
  "name": "Bitcoin",
  "current_price": 107000,
  "change_24h": 1.23,
  "volatility": { "level": "높음", "avg_abs_change_pct": 3.2, "warning": "주의 필요" },
  "forecast_dates": ["2026-06-28", ...],
  "forecast_prices": [...],
  "q10": [...],
  "q90": [...],
  "history_dates": [...],
  "history_prices": [...],
  "key_forecasts": {
    "d7": {
      "days": 7, "date": "2026-07-04", "price": 110000,
      "q10": 105000, "q90": 115000, "pct_change": 2.8,
      "range_pct": 9.5,
      "mape": 4.2,
      "directional_accuracy": 57.0,
      "volatility_level": "높음",
      "volatility_warning": "주의 필요",
      "confidence_score": 48,
      "confidence_label": "제한적 참고 가능",
      "interpretation": "Bitcoin 7일 예측은 ..."
    }
  },
  "elapsed_sec": 1.2,
  "generated_at": "2026-06-27T09:00:00Z",
  "cached": false
}
```

---

## 5. 프론트엔드 구조 (`frontend/index.html`)

단일 파일. CSS·JS 모두 인라인.

### 주요 JS 함수

| 함수 | 역할 |
|---|---|
| `safeFetchJson(url, opts)` | fetch + Content-Type 검증 + JSON 파싱 |
| `checkHealth()` | 서버 상태 도트 업데이트 |
| `switchCat(cat)` | 암호화폐 ↔ 한국 주식 탭 전환 |
| `selectAsset(sym)` | 종목 선택 + 캐시 있으면 즉시 렌더링 |
| `runForecast()` | 단일 종목 예측 실행 |
| `runAll()` | 현재 탭 전체 종목 순차 예측 |
| `doForecast(sym, silent)` | API 호출 → 결과 렌더링 |
| `renderResult(data)` | 카드·차트·테이블 일괄 렌더링 |
| `updateCard(sym, data)` | 종목 카드 현재가·신뢰도 업데이트 |
| `renderCards(data)` | 1/7/14/30일 예측 카드 렌더링 |
| `renderChart(data)` | Chart.js 차트 렌더링 |
| `renderTable(data)` | 예측 테이블 렌더링 |
| `fmtPrice(currency, price, symbol)` | 통화별 가격 포맷 |

### 주요 CSS 클래스

| 클래스 | 용도 |
|---|---|
| `.conf-badge` | 신뢰도 배지 (기본) |
| `.conf-high / .conf-mid / .conf-low / .conf-vlow` | 신뢰도 등급별 색상 |
| `.vol-badge / .vol-high / .vol-vhigh` | 변동성 배지 |
| `.fc-meta` | 예측 카드 하단 메타 정보 |
| `#interpret-box` | AI 해석 박스 |

---

## 6. 알려진 이슈 & 제한사항

| # | 이슈 | 심각도 | 파일 | 설명 |
|---|---|---|---|---|
| 1 | 백테스트 첫 실행 무응답 | 중 | main.py | 3~10분 동안 API 응답 없음. UI 피드백 없음 |
| 2 | KR 주식 예측 날짜 | 낮 | main.py | 주말·공휴일 포함 캘린더 기준 날짜 표시 |
| 3 | 백테스트 mape=None | 낮 | main.py | 백테스트 샘플 부족 시 mape=None → 신뢰도 패널티 25점 적용 (정상 동작) |
| 4 | Railway 비활성 | 낮 | Procfile | 현재 Railway 백엔드 미배포 상태 |

---

## 7. 버그픽스 이력

### [2026-06-27] `calculate_confidence_score` NaN 오류
- **증상:** KR 주식(KOSPI, 005930 등) 예측 시 500 Internal Server Error
- **원인:** `mape` 값이 `float NaN`으로 유입 → `round(NaN)` → `ValueError: cannot convert float NaN to integer`
- **수정:**
  - `import math` 추가
  - `calculate_mape()`: 결과가 NaN/Inf이면 `None` 반환
  - `calculate_confidence_score()`: `math.isnan()` 체크, score 최종값 NaN/Inf 방어
- **커밋:** `8a7724a`

---

## 8. 커밋 이력 (전체)

```
8a7724a fix: handle NaN in calculate_confidence_score (ValueError on KR stocks)
b69be6f docs: add HANDOVER.md, PRD.md, PROGRESS.md for Claude Code handover
7829916 feat: add confidence scoring, backtest, volatility analysis & UI improvements
7ac30f2 fix: add requirements.txt + Procfile + nixpacks.toml in api/ for Railway deploy
a652570 fix: vercel - exclude api/ and requirements.txt via .vercelignore
ce61ebd fix: vercel - static only, skip python build (torch 4.7GB exceeds 500MB limit)
ec83877 fix: handle backend unavailable gracefully on Vercel
dafbc35 feat: add vercel.json for static frontend deploy + responsive UI fix + KOSPI unit fix
```

---

## 9. 환경 정보

- Python: 3.12
- 주요 패키지: `timesfm[torch]==2.0.1`, `fastapi==0.111.0`, `uvicorn[standard]==0.30.1`, `yfinance>=1.4.0`
- Node: 불필요 (순수 HTML 프론트엔드)
- Git remote: `origin → https://github.com/charlychoi/timesfm-forcase.git`
- 로컬 경로: `/Users/charlychoi/.openclaw/workspace/timesfm-forecast`
