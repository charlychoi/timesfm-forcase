# TimesFM Crypto Forecast

BTC / ETH / XRP 가격을 Google Research의 **TimesFM 2.5** (Zero-Shot) 로 예측하는 웹앱.

> ⚠️ 투자 권유 아님 — 참고용만

## 기술 스택

| Layer | 기술 |
|---|---|
| 예측 모델 | Google TimesFM 2.5 (200M, Zero-Shot) |
| 백엔드 | Python FastAPI + Uvicorn |
| 프론트엔드 | Vanilla HTML/JS + Chart.js |
| 데이터 | CoinGecko 무료 API |

## 로컬 실행

```bash
# 1. 의존성 설치
pip install -r requirements.txt

# 2. 서버 시작
cd api
python main.py
# 또는
uvicorn main:app --reload --port 8000

# 3. 브라우저 열기
open http://localhost:8000
```

**첫 실행 시** TimesFM 모델이 HuggingFace에서 다운로드됩니다 (약 800MB, 1~2분).

## 사용법

1. BTC / ETH / XRP 탭 선택
2. **예측 실행** 버튼 클릭
3. 1일 / 7일 / 14일 / 30일 예측 결과 확인
4. **전체 코인 예측** 으로 3개 동시 처리 가능

## API 엔드포인트

```
GET /api/health              # 상태 확인
GET /api/forecast/{symbol}   # BTC|ETH|XRP 예측
GET /api/model/load          # 모델 워밍업
GET /docs                    # Swagger UI
```

## 배포 (Vercel)

프론트엔드는 Vercel 정적 배포.  
백엔드는 Railway / Render / Google Cloud Run 권장.

## 참고

- [TimesFM GitHub](https://github.com/google-research/timesfm)
- [ICML 2024 논문](https://arxiv.org/abs/2310.10688)
- [YouTube @CharlyChoi](https://www.youtube.com/@CharlyChoi/)
