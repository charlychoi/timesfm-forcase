"""
TimesFM Crypto & KR Stock Forecast API
BTC/ETH/XRP + 삼성전자/SK하이닉스/현대차/KODEX200
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

app = FastAPI(title="TimesFM Forecast", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── 캐시 ─────────────────────────────────────────────────────────────────
_model = None
_model_loaded = False
_price_cache: dict = {}
_forecast_cache: dict = {}
CACHE_TTL    = 300   # 가격 5분
FORECAST_TTL = 600   # 예측 10분

# ── 자산 메타데이터 ───────────────────────────────────────────────────────
# 종류: "crypto" | "kr_stock"
ASSETS = {
    # 암호화폐
    "BTC": {"name": "Bitcoin",      "color": "#F7931A", "type": "crypto",   "id": "bitcoin",  "currency": "USD", "decimals": 0},
    "ETH": {"name": "Ethereum",     "color": "#627EEA", "type": "crypto",   "id": "ethereum", "currency": "USD", "decimals": 2},
    "XRP": {"name": "XRP",          "color": "#00AAE4", "type": "crypto",   "id": "ripple",   "currency": "USD", "decimals": 4},
    # 한국 주식
    "005930": {"name": "삼성전자",      "color": "#1428A0", "type": "kr_stock", "id": "005930.KS", "currency": "KRW", "decimals": 0},
    "000660": {"name": "SK하이닉스",    "color": "#0000C8", "type": "kr_stock", "id": "000660.KS", "currency": "KRW", "decimals": 0},
    "005380": {"name": "현대자동차",    "color": "#002C5F", "type": "kr_stock", "id": "005380.KS", "currency": "KRW", "decimals": 0},
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
                "User-Agent": "TimesFM-Forecast/2.0 (educational)",
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
    # 한국 주식은 평일만 (대략 계산, 실제 휴장일 제외 단순화)
    forecast_dates = [(today + timedelta(days=i+1)).isoformat() for i in range(30)]
    history_prices = prices[-90:].tolist()
    history_dates  = [(today - timedelta(days=89-i)).isoformat() for i in range(len(history_prices))]

    key_forecasts = {}
    for days in [1, 7, 14, 30]:
        idx = days - 1
        fc = pf_list[idx]
        pct = (fc / current_price - 1) * 100 if current_price else 0
        dec = meta["decimals"]
        key_forecasts[f"d{days}"] = {
            "days": days,
            "date": forecast_dates[idx],
            "price": round(fc, dec),
            "q10":   round(q10[idx], dec),
            "q90":   round(q90[idx], dec),
            "pct_change": round(pct, 2),
        }

    return {
        "symbol":        symbol,
        "name":          meta["name"],
        "color":         meta["color"],
        "type":          meta["type"],
        "currency":      meta["currency"],
        "current_price": round(current_price, meta["decimals"]),
        "change_24h":    change_24h,
        "forecast_dates":  forecast_dates,
        "forecast_prices": [round(p, meta["decimals"]) for p in pf_list],
        "q10":  [round(p, meta["decimals"]) for p in q10],
        "q90":  [round(p, meta["decimals"]) for p in q90],
        "history_dates":  history_dates,
        "history_prices": [round(p, meta["decimals"]) for p in history_prices],
        "key_forecasts":  key_forecasts,
        "elapsed_sec":    round(time.time() - t0, 2),
        "generated_at":   datetime.utcnow().isoformat() + "Z",
        "cached":         False,
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
        "forecast_cache": {s: bool(_forecast_cache.get(s)) for s in ASSETS},
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
    return {"message": "TimesFM Forecast API v2"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
