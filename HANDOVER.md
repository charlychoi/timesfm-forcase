# HANDOVER.md — TimesFM Forecast 인수인계

> 작성일: 2026-06-27  
> 인계자: OpenClaw (오프너)  
> 인수자: Claude Code 또는 다음 작업자  
> GitHub: https://github.com/charlychoi/timesfm-forcase

---

## 1. 프로젝트 개요

**TimesFM 2.5 기반 암호화폐 & 한국 주식 AI 예측 웹앱**

- 백엔드: FastAPI + TimesFM 2.5 (200M PyTorch)
- 프론트엔드: 단일 HTML (Chart.js, 프레임워크 없음)
- 데이터: CoinGecko (BTC/ETH/XRP) + Yahoo Finance (삼성전자/SK하이닉스/현대차/KOSPI)
- 배포: Vercel (프론트 정적) + Railway (백엔드) — 현재 로컬 테스트 모드

---

## 2. 디렉토리 구조

```
timesfm-forecast/
├── api/
│   ├── main.py            # FastAPI 백엔드 (핵심)
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
```

**수동 실행:**
```bash
cd timesfm-forecast/api
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

**API 문서:** http://localhost:8000/docs  
**헬스체크:** http://localhost:8000/api/health

---

## 4. 현재 구현 상태 (2026-06-27 기준)

### 백엔드 함수 목록 (`api/main.py`)

| 함수 | 역할 | 상태 |
|---|---|---|
| `get_model()` | TimesFM 모델 로드 (싱글톤) | ✅ 완료 |
| `http_get()` | CoinGecko HTTP with retry | ✅ 완료 |
| `fetch_crypto_prices()` | BTC/ETH/XRP 365일 가격 | ✅ 완료 |
| `fetch_kr_stock_prices()` | KR 주식 1년 가격 (yfinance) | ✅ 완료 |
| `calculate_mape()` | MAPE 계산 | ✅ 완료 |
| `calculate_directional_accuracy()` | 방향성 적중률 | ✅ 완료 |
| `calculate_volatility_level()` | 변동성 등급 (암호화폐/주식 기준 분리) | ✅ 완료 |
| `calculate_confidence_score()` | 신뢰도 점수 0-100 + 등급 레이블 | ✅ 완료 |
| `generate_interpretation()` | 한국어 규칙 기반 해석 문장 | ✅ 완료 |
| `run_backtest()` | 롤링 백테스트 (캐시 1시간) | ✅ 완료 |
| `_do_forecast()` | 메인 예측 로직 (위 함수 통합) | ✅ 완료 |
| `run_forecast()` | 캐시 래퍼 (TTL 10분) | ✅ 완료 |

### API 엔드포인트

| 엔드포인트 | 설명 |
|---|---|
| `GET /` | 프론트엔드 서빙 |
| `GET /api/health` | 서버/모델/캐시 상태 |
| `GET /api/assets` | 지원 자산 목록 |
| `GET /api/forecast/{symbol}` | 예측 실행 (BTC/ETH/XRP/005930 등) |
| `GET /api/cache/clear` | 캐시 전체 초기화 |

### 프론트엔드 주요 기능

| 기능 | 상태 |
|---|---|
| 암호화폐 / 한국주식 탭 전환 | ✅ |
| 종목 카드 (현재가 + 24h 변화율) | ✅ |
| 1/7/14/30일 예측 카드 | ✅ |
| 신뢰도 배지 (conf-badge) | ✅ |
| 백테스트 MAPE 표시 | ✅ |
| 방향성 적중률 표시 | ✅ |
| 변동성 등급 표시 | ✅ |
| AI 해석 박스 (#interpret-box) | ✅ |
| 예측 차트 (Chart.js) | ✅ |
| 예측 테이블 (4개 컬럼 추가) | ✅ |
| `safeFetchJson()` 오류 처리 | ✅ |

---

## 5. 캐시 구조

```python
_price_cache     # 가격 캐시: TTL 5분
_forecast_cache  # 예측 캐시: TTL 10분
_backtest_cache  # 백테스트 캐시: TTL 1시간
```

---

## 6. 알려진 제한사항 & 주의점

1. **TimesFM 모델 로드**: 첫 예측 시 모델 다운로드+로드에 1~3분 소요
2. **백테스트 시간**: 첫 실행 시 종목당 3~10분 소요 (특히 BTC). 캐시 후 즉시 반환
3. **CoinGecko Rate Limit**: 429 에러 시 자동 retry (최대 3회, backoff 2초)
4. **한국 주식 휴장일**: yfinance 기준, 실제 거래일만 포함됨. 예측 날짜는 캘린더 기준으로 계산되어 주말 포함됨 (개선 필요)
5. **Vercel 정적 배포**: 백엔드 없이 Vercel만 접속 시 `api-unavailable.json` 폴백 반환
6. **Railway 백엔드**: `api/Procfile` + `api/nixpacks.toml` 으로 배포 가능 (현재 비활성)

---

## 7. 다음 작업 목록 (PRD.md 참조)

자세한 내용은 `PRD.md`와 `PROGRESS.md` 참조.

**우선순위 높음:**
- [ ] 백테스트 진행률 스트리밍 (SSE or WebSocket) — 첫 실행 시 UI 피드백 없음 문제
- [ ] 한국 주식 공휴일 처리 — 예측 날짜가 주말/공휴일 포함됨
- [ ] 로딩 상태 개선 — 백테스트 중 "분석 중..." 진행 상태 표시

**우선순위 중간:**
- [ ] `/api/backtest/{symbol}` 독립 엔드포인트 분리
- [ ] 최근 예측 vs 실제 비교 섹션 (과거 예측 정확도 시각화)
- [ ] 다크/라이트 모드 토글

**우선순위 낮음:**
- [ ] Railway 백엔드 재배포 및 Vercel 연동 업데이트
- [ ] 모바일 UI 최적화

---

## 8. 환경 정보

- Python: 3.12
- 주요 패키지: `timesfm[torch]==2.0.1`, `fastapi==0.111.0`, `uvicorn[standard]==0.30.1`
- Node: 불필요 (순수 HTML 프론트엔드)
- Git remote: `origin → https://github.com/charlychoi/timesfm-forcase.git`

---

## 9. 커밋 이력 (최근 5개)

```
7829916 feat: add confidence scoring, backtest, volatility analysis & UI improvements
7ac30f2 fix: add requirements.txt + Procfile + nixpacks.toml in api/ for Railway deploy
a652570 fix: vercel - exclude api/ and requirements.txt via .vercelignore
ce61ebd fix: vercel - static only, skip python build (torch 4.7GB exceeds 500MB limit)
ec83877 fix: handle backend unavailable gracefully on Vercel
```
