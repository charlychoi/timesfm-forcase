"""
TimesFM Crypto & KR Stock Forecast API
BTC/ETH/XRP + 삼성전자/SK하이닉스/현대차/KODEX200
v3.0.0 — 신뢰도/백테스트/변동성/해석 추가
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import numpy as np
import torch
import ssl
import json
import urllib.request
import urllib.error
import time
import os
from datetime import datetime, timedelta

torch.set_float32_matmul_precision("high")

app = FastAPI(title="TimesFM Forecast", version="3.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── 캐시 ─────────────────────────────────────────────────────────────────
_model = None
_model_loaded = False
_price_cache: dict = {}
_forecast_cache: dict = {}
_backtest_cache: dict = {}
CACHE_TTL    = 300    # 가격 5분
FORECAST_TTL = 600    # 예측 10분
BACKTEST_TTL = 3600   # 백테스트 1시간

# ── 자산 메타데이터 ───────────────────────────────────────────────────────
# 종류: "crypto" | "kr_stock"
ASSETS = {
    # 암호화폐
    "BTC": {"name": "Bitcoin",       "color": "#F7931A", "type": "crypto",   "id": "bitcoin",   "currency": "USD", "decimals": 0},
    "ETH": {"name": "Ethereum",      "color": "#627EEA", "type": "crypto",   "id": "ethereum",  "currency": "USD", "decimals": 2},
    "XRP": {"name": "XRP",           "color": "#00AAE4", "type": "crypto",   "id": "ripple",    "currency": "USD", "decimals": 4},
    # 한국 주식
    "005930": {"name": "삼성전자",       "color": "#1428A0", "type": "kr_stock", "id": "005930.KS", "currency": "KRW", "decimals": 0},
    "000660": {"name": "SK하이닉스",     "color": "#0000C8", "type": "kr_stock", "id": "000660.KS", "currency": "KRW", "decimals": 0},
    "005380": {"name": "현대자동차",     "color": "#002C5F", "type": "kr_stock", "id": "005380.KS", "currency": "KRW", "decimals": 0},
    "KOSPI":  {"name": "KOSPI 종합지수", "color": "#E8343D", "type": "kr_stock", "id": "^KS11",     "currency": "KRW", "decimals": 2},
}

CRYPTO_SYMBOLS   = [k for k, v in ASSETS.items() if v["type"] == "crypto"]
KR_STOCK_SYMBOLS = [k for k, v in ASSETS.items() if v["type"] == "kr_stock"]

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE


# ── 모델 ──────────────────────────────────────────────────────────────────
def get_model():
    global _model, _model_loaded
    if not _model_loaded:
        import timesfm
        print("[TimesFM] 모델 로드 중...")
        _model = timesfm.TimesFM_2p5_200M_torch.from_pretrained(
            "google/timesfm-2.5-200m-pytorch"
        )
        _model.compile(timesfm.ForecastConfig(
            max_context=256,
            max_horizon=30,
            normalize_inputs=True,
            use_continuous_quantile_head=True,
            fix_quantile_crossing=True,
            infer_is_positive=True,
        ))
        _model_loaded = True
        print("[TimesFM] 모델 로드 완료")
    return _model


# ── CoinGecko (암호화폐) ──────────────────────────────────────────────────
def http_get(url: str, retries: int = 3, backoff: float = 2.0) -> dict:
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "TimesFM-Forecast/3.0 (educational)",
                "Accept": "application/json",
            })
            with urllib.request.urlopen(req, timeout=20, context=SSL_CTX) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code in (429, 500, 502, 503):
                wait = backoff * (attempt + 1)
                print(f"[CoinGecko] HTTP {e.code} — {wait:.1f}s 대기 ({attempt+1}/{retries})")
                time.sleep(wait)
            else:
                raise HTTPException(status_code=e.code, detail=f"CoinGecko 오류: {e}")
        except Exception as e:
            last_err = e
            time.sleep(backoff)
    raise HTTPException(status_code=503, detail=f"CoinGecko 요청 실패: {last_err}")


def fetch_crypto_prices(coin_id: str) -> tuple[np.ndarray, float, float]:
    """반환: (일별 가격 배열, 현재가, 24h변화율)"""
    now = time.time()
    cached = _price_cache.get(coin_id)
    if cached and (now - cached["ts"]) < CACHE_TTL:
        return np.array(cached["prices"], dtype=np.float32), cached["current"], cached["change_24h"]

    data = http_get(
        f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart"
        f"?vs_currency=usd&days=365&interval=daily"
    )
    prices = [p[1] for p in data["prices"]]

    # 현재가 + 24h 변화율
    try:
        cur_data = http_get(
            f"https://api.coingecko.com/api/v3/simple/price"
            f"?ids={coin_id}&vs_currencies=usd&include_24hr_change=true"
        )
        current = cur_data[coin_id]["usd"]
        change_24h = round(cur_data[coin_id].get("usd_24h_change", 0), 2)
    except Exception:
        current = prices[-1]
        change_24h = 0.0

    _price_cache[coin_id] = {"prices": prices, "current": current, "change_24h": change_24h, "ts": now}
    print(f"[CoinGecko] {coin_id}: {len(prices)}일 로드")
    return np.array(prices, dtype=np.float32), current, change_24h


# ── yfinance (한국 주식) ───────────────────────────────────────────────────
def fetch_kr_stock_prices(ticker: str) -> tuple[np.ndarray, float, float]:
    """반환: (일별 가격 배열, 현재가, 1일변화율)"""
    now = time.time()
    cached = _price_cache.get(ticker)
    if cached and (now - cached["ts"]) < CACHE_TTL:
        return np.array(cached["prices"], dtype=np.float32), cached["current"], cached["change_24h"]

    import yfinance as yf
    df = yf.download(ticker, period="1y", interval="1d", progress=False, auto_adjust=True)
    if df.empty:
        raise HTTPException(status_code=503, detail=f"{ticker} 데이터 수집 실패")

    closes = df["Close"].dropna()
    prices = closes.values.flatten().astype(np.float32)
    current = float(prices[-1])
    change_24h = round((float(prices[-1]) / float(prices[-2]) - 1) * 100, 2) if len(prices) > 1 else 0.0

    _price_cache[ticker] = {"prices": prices.tolist(), "current": current, "change_24h": change_24h, "ts": now}
    print(f"[yfinance] {ticker}: {len(prices)}일 로드, 현재 {current:,.0f}")
    return prices, current, change_24h


# ── 분석 함수 ─────────────────────────────────────────────────────────────

def calculate_mape(actual: list, predicted: list) -> float | None:
    """MAPE (Mean Absolute Percentage Error) 계산"""
    errors = []
    for a, p in zip(actual, predicted):
        if a and a != 0:
            errors.append(abs((a - p) / a) * 100)
    if not errors:
        return None
    return sum(errors) / len(errors)


def calculate_directional_accuracy(base: list, actual: list, predicted: list) -> float | None:
    """방향성 적중률 계산 (상승/하락 방향 일치율)"""
    correct = total = 0
    for b, a, p in zip(base, actual, predicted):
        if not (b and a and p):
            continue
        actual_dir = 1 if a > b else (-1 if a < b else 0)
        pred_dir   = 1 if p > b else (-1 if p < b else 0)
        if actual_dir == 0:
            continue
        if actual_dir == pred_dir:
            correct += 1
        total += 1
    return (correct / total * 100) if total else None


def calculate_volatility_level(prices: list, asset_type: str) -> dict:
    """최근 30일 일별 변동성 등급 계산"""
    recent = prices[-31:]
    changes = []
    for i in range(1, len(recent)):
        prev, curr = recent[i-1], recent[i]
        if prev and curr:
            changes.append(abs((curr - prev) / prev) * 100)
    if not changes:
        return {"avg_abs_change_pct": None, "level": "계산 불가", "warning": ""}
    avg = sum(changes) / len(changes)
    if asset_type == "crypto":
        if avg < 2:   return {"avg_abs_change_pct": round(avg, 2), "level": "낮음",    "warning": "안정 구간"}
        if avg < 4:   return {"avg_abs_change_pct": round(avg, 2), "level": "보통",    "warning": "일반 변동성"}
        if avg < 6:   return {"avg_abs_change_pct": round(avg, 2), "level": "높음",    "warning": "주의 필요"}
        return              {"avg_abs_change_pct": round(avg, 2), "level": "매우 높음", "warning": "예측 신뢰도 낮음"}
    else:  # kr_stock
        if avg < 1:   return {"avg_abs_change_pct": round(avg, 2), "level": "낮음",    "warning": "안정 구간"}
        if avg < 2:   return {"avg_abs_change_pct": round(avg, 2), "level": "보통",    "warning": "일반 변동성"}
        if avg < 3.5: return {"avg_abs_change_pct": round(avg, 2), "level": "높음",    "warning": "주의 필요"}
        return              {"avg_abs_change_pct": round(avg, 2), "level": "매우 높음", "warning": "예측 신뢰도 낮음"}


def calculate_confidence_score(
    mape,
    directional_acc,
    volatility_level: str,
    range_pct,
    horizon: int
) -> dict:
    """예측 신뢰도 점수(0~100) + 등급 레이블 계산"""
    score = 100

    # MAPE 패널티
    if mape is not None:
        score -= min(mape * 3, 40)
    else:
        score -= 25

    # 변동성 패널티
    vol_penalty = {"낮음": 0, "보통": 5, "높음": 12, "매우 높음": 20, "계산 불가": 10}
    score -= vol_penalty.get(volatility_level, 10)

    # 예측 범위 폭 패널티
    if range_pct is not None:
        if range_pct >= 20:  score -= 20
        elif range_pct >= 10: score -= 10
        elif range_pct >= 5:  score -= 5
    else:
        score -= 10

    # 예측 기간 패널티
    horizon_penalty = {1: 0, 7: 5, 14: 12, 30: 25}
    score -= horizon_penalty.get(horizon, 15)

    # 방향성 정확도 보너스/패널티
    if directional_acc is not None:
        if directional_acc >= 60:    score += 10
        elif directional_acc >= 55:  score += 5
        elif directional_acc < 50:   score -= 5

    score = max(0, min(100, round(score)))

    if score >= 70:    label = "참고 가능"
    elif score >= 50:  label = "제한적 참고 가능"
    elif score >= 30:  label = "주의 필요"
    else:              label = "시나리오 참고 수준"

    return {"score": score, "label": label}


def generate_interpretation(
    asset_name: str,
    horizon: int,
    change_pct: float,
    confidence_score: int,
    confidence_label: str,
    volatility_level: str,
    directional_acc,
    range_pct
) -> str:
    """규칙 기반 한국어 해석 문장 생성"""
    if change_pct > 1:
        dir_text = "상승 흐름"
    elif change_pct < -1:
        dir_text = "하락 흐름"
    else:
        dir_text = "중립적인 흐름"

    msg = f"{asset_name} {horizon}일 예측은 과거 가격 패턴 기준으로 {dir_text}을 보입니다. "
    msg += f"현재 예측 신뢰도는 {confidence_score}/100으로, {confidence_label} 수준입니다. "

    if volatility_level in ("높음", "매우 높음"):
        msg += (
            f"최근 변동성이 {volatility_level} 상태이므로 단일 가격보다 "
            f"예측 범위를 중심으로 해석하는 것이 좋습니다. "
        )

    if directional_acc is not None and directional_acc < 50:
        msg += (
            "최근 백테스트 기준 방향성 적중률이 50% 미만이므로 "
            "상승·하락 판단용으로는 신중한 해석이 필요합니다. "
        )

    if range_pct is not None and range_pct >= 20:
        msg += (
            "예측 범위가 넓어 장기 예측은 시나리오 참고 수준으로 "
            "보는 것이 적절합니다."
        )

    return msg.strip()


def run_backtest(symbol: str, prices: np.ndarray, asset_type: str) -> dict:
    """롤링 백테스트: MAPE + 방향성 적중률 계산 (캐시 1시간)"""
    now = time.time()
    cached = _backtest_cache.get(symbol)
    if cached and (now - cached["ts"]) < BACKTEST_TTL:
        return cached["data"]

    prices_list = prices.tolist()
    n = len(prices_list)
    MIN_TRAIN = 180

    # 성능 보호를 위한 샘플 수 제한
    MAX_SAMPLES = {1: 30, 7: 20, 14: 15, 30: 8}

    results = {}
    for horizon in [1, 7, 14, 30]:
        max_s = MAX_SAMPLES[horizon]
        actuals, preds, bases = [], [], []

        # 슬라이딩 윈도우 (최대 max_s 샘플)
        end_limit = n - horizon
        start = max(MIN_TRAIN, end_limit - max_s)

        for train_end in range(start, end_limit):
            context = np.array(prices_list[:train_end], dtype=np.float32)
            if len(context) < MIN_TRAIN:
                continue
            try:
                model = get_model()
                ctx = context[-256:] if len(context) >= 256 else context
                pf, _ = model.forecast(horizon=horizon, inputs=[ctx])
                pred_price   = float(pf[0][horizon - 1])
                actual_price = prices_list[train_end + horizon - 1]
                base_price   = prices_list[train_end - 1]
                preds.append(pred_price)
                actuals.append(actual_price)
                bases.append(base_price)
            except Exception as e:
                print(f"[backtest] {symbol} h={horizon} err: {e}")
                continue

        mape = calculate_mape(actuals, preds)
        da   = calculate_directional_accuracy(bases, actuals, preds)
        results[f"h{horizon}"] = {
            "horizon": horizon,
            "mape": round(mape, 2) if mape is not None else None,
            "directional_accuracy": round(da, 1) if da is not None else None,
            "sample_count": len(actuals),
        }

    _backtest_cache[symbol] = {"data": results, "ts": now}
    return results


# ── 공통 예측 ─────────────────────────────────────────────────────────────
def _do_forecast(symbol: str) -> dict:
    meta = ASSETS[symbol]
    t0 = time.time()

    # 데이터 수집
    if meta["type"] == "crypto":
        prices, current_price, change_24h = fetch_crypto_prices(meta["id"])
    else:
        prices, current_price, change_24h = fetch_kr_stock_prices(meta["id"])

    # 모델 추론
    model = get_model()
    context = prices[-256:] if len(prices) >= 256 else prices
    point_forecast, quantile_forecast = model.forecast(horizon=30, inputs=[context])
    pf = point_forecast[0]

    if quantile_forecast is not None and not np.any(np.isnan(quantile_forecast[0, :, 1])):
        q10 = quantile_forecast[0, :, 1].tolist()
        q90 = quantile_forecast[0, :, 8].tolist()
    else:
        q10 = (pf * 0.95).tolist()
        q90 = (pf * 1.05).tolist()

    pf_list = pf.tolist()
    today = datetime.utcnow().date()
    forecast_dates = [(today + timedelta(days=i+1)).isoformat() for i in range(30)]
    history_prices = prices[-90:].tolist()
    history_dates  = [(today - timedelta(days=89-i)).isoformat() for i in range(len(history_prices))]

    # ── 변동성 계산 ──────────────────────────────────────────────────────
    vol_info = calculate_volatility_level(prices.tolist(), meta["type"])

    # ── 백테스트 (캐시 활용) ──────────────────────────────────────────────
    try:
        backtest_data = run_backtest(symbol, prices, meta["type"])
    except Exception as e:
        print(f"[backtest] 실패: {e}")
        backtest_data = {}

    # ── key_forecasts 생성 ────────────────────────────────────────────────
    key_forecasts = {}
    for days in [1, 7, 14, 30]:
        idx = days - 1
        fc  = pf_list[idx]
        pct = (fc / current_price - 1) * 100 if current_price else 0
        dec = meta["decimals"]

        # 예측 범위 폭 (%)
        range_pct = None
        if fc and fc > 0:
            range_pct = round((q90[idx] - q10[idx]) / fc * 100, 1)

        # 백테스트 결과
        bt_result = backtest_data.get(f"h{days}", {})
        mape_val = bt_result.get("mape")
        da_val   = bt_result.get("directional_accuracy")

        # 신뢰도 점수
        conf = calculate_confidence_score(mape_val, da_val, vol_info["level"], range_pct, days)

        # 해석 문장
        interp = generate_interpretation(
            meta["name"], days, round(pct, 2),
            conf["score"], conf["label"],
            vol_info["level"], da_val, range_pct
        )

        key_forecasts[f"d{days}"] = {
            "days":                days,
            "date":                forecast_dates[idx],
            "price":               round(fc, dec),
            "q10":                 round(q10[idx], dec),
            "q90":                 round(q90[idx], dec),
            "pct_change":          round(pct, 2),
            "range_pct":           range_pct,
            "mape":                mape_val,
            "directional_accuracy": da_val,
            "volatility_level":    vol_info["level"],
            "volatility_warning":  vol_info["warning"],
            "confidence_score":    conf["score"],
            "confidence_label":    conf["label"],
            "interpretation":      interp,
        }

    return {
        "symbol":          symbol,
        "name":            meta["name"],
        "color":           meta["color"],
        "type":            meta["type"],
        "currency":        meta["currency"],
        "current_price":   round(current_price, meta["decimals"]),
        "change_24h":      change_24h,
        "volatility":      vol_info,
        "forecast_dates":  forecast_dates,
        "forecast_prices": [round(p, meta["decimals"]) for p in pf_list],
        "q10":  [round(p, meta["decimals"]) for p in q10],
        "q90":  [round(p, meta["decimals"]) for p in q90],
        "history_dates":   history_dates,
        "history_prices":  [round(p, meta["decimals"]) for p in history_prices],
        "key_forecasts":   key_forecasts,
        "elapsed_sec":     round(time.time() - t0, 2),
        "generated_at":    datetime.utcnow().isoformat() + "Z",
        "cached":          False,
    }


def run_forecast(symbol: str) -> dict:
    now = time.time()
    cached = _forecast_cache.get(symbol)
    if cached and (now - cached["ts"]) < FORECAST_TTL:
        result = dict(cached["data"])
        result["cached"] = True
        result["cache_age_sec"] = round(now - cached["ts"], 0)
        return result
    result = _do_forecast(symbol)
    _forecast_cache[symbol] = {"data": result, "ts": now}
    return result


# ── 엔드포인트 ────────────────────────────────────────────────────────────
@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "model_loaded": _model_loaded,
        "forecast_cache":  {s: bool(_forecast_cache.get(s))  for s in ASSETS},
        "backtest_cache":  {s: bool(_backtest_cache.get(s))  for s in ASSETS},
    }

@app.get("/api/assets")
def list_assets():
    return {
        k: {"name": v["name"], "color": v["color"], "type": v["type"], "currency": v["currency"]}
        for k, v in ASSETS.items()
    }

@app.get("/api/forecast/{symbol}")
def forecast(symbol: str):
    symbol = symbol.upper()
    if symbol not in ASSETS:
        raise HTTPException(status_code=400, detail=f"지원 심볼: {list(ASSETS.keys())}")
    return run_forecast(symbol)

@app.get("/api/cache/clear")
def clear_cache():
    _price_cache.clear()
    _forecast_cache.clear()
    _backtest_cache.clear()
    return {"status": "cleared"}

# ── 프론트엔드 서빙 ───────────────────────────────────────────────────────
frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.exists(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

@app.get("/")
def root():
    index = os.path.join(os.path.dirname(__file__), "..", "frontend", "index.html")
    if os.path.exists(index):
        return FileResponse(index)
    return {"message": "TimesFM Forecast API v3"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
