"""
TimesFM 한국 경제 AI 예측 대시보드
BTC/ETH/XRP + 삼성전자/SK하이닉스/현대차/KOSPI (일별)
+ USD/KRW · JPY/KRW — 한국은행 ECOS (일별 환율)
+ 서울/강남3구/노도강 아파트 — 국토교통부 실거래가 (월별)
+ 소비자물가지수 전체/식품/주거 — 한국은행 ECOS (월별)
v4.0.0
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
import math
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import requests as http_requests
import pandas as pd
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

torch.set_float32_matmul_precision("high")

app = FastAPI(title="TimesFM 한국경제 대시보드", version="4.0.0")

ECOS_API_KEY  = os.getenv("ECOS_API_KEY",  "SQIJXZ0X565GGLIGB4LM")
MOLIT_API_KEY = os.getenv("MOLIT_API_KEY", "")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── 캐시 ──────────────────────────────────────────────────────────────────
_model        = None
_model_loaded = False
_price_cache:    dict = {}
_forecast_cache: dict = {}
_backtest_cache: dict = {}

# 자산 유형별 TTL (초)
TTL = {
    "crypto":   {"price":   300, "forecast":   600, "backtest":  3600},
    "kr_stock": {"price":   300, "forecast":   600, "backtest":  3600},
    "exchange": {"price":  3600, "forecast":  3600, "backtest": 21600},
    "apt":      {"price": 21600, "forecast": 21600, "backtest": 86400},
    "cpi":      {"price": 21600, "forecast": 21600, "backtest": 86400},
}

# ── 자산 메타데이터 ───────────────────────────────────────────────────────
_D  = [1, 7, 14, 30]
_DL = ["1일 후", "7일 후", "14일 후", "30일 후"]
_M  = [1, 3, 6, 12]
_ML = ["1개월 후", "3개월 후", "6개월 후", "1년 후"]

ASSETS = {
    # ── 암호화폐 ──────────────────────────────────────────────────────────
    "BTC": {"name": "Bitcoin",       "color": "#F7931A", "type": "crypto",   "id": "bitcoin",   "currency": "USD", "decimals": 0, "source": "coingecko", "horizons": _D, "horizon_labels": _DL},
    "ETH": {"name": "Ethereum",      "color": "#627EEA", "type": "crypto",   "id": "ethereum",  "currency": "USD", "decimals": 2, "source": "coingecko", "horizons": _D, "horizon_labels": _DL},
    "XRP": {"name": "XRP",           "color": "#00AAE4", "type": "crypto",   "id": "ripple",    "currency": "USD", "decimals": 4, "source": "coingecko", "horizons": _D, "horizon_labels": _DL},
    # ── 한국 주식 ─────────────────────────────────────────────────────────
    "005930": {"name": "삼성전자",       "color": "#1428A0", "type": "kr_stock", "id": "005930.KS", "currency": "KRW", "decimals": 0, "source": "yfinance", "horizons": _D, "horizon_labels": _DL},
    "000660": {"name": "SK하이닉스",     "color": "#0000C8", "type": "kr_stock", "id": "000660.KS", "currency": "KRW", "decimals": 0, "source": "yfinance", "horizons": _D, "horizon_labels": _DL},
    "005380": {"name": "현대자동차",     "color": "#002C5F", "type": "kr_stock", "id": "005380.KS", "currency": "KRW", "decimals": 0, "source": "yfinance", "horizons": _D, "horizon_labels": _DL},
    "KOSPI":  {"name": "KOSPI 종합지수", "color": "#E8343D", "type": "kr_stock", "id": "^KS11",     "currency": "KRW", "decimals": 2, "source": "yfinance", "horizons": _D, "horizon_labels": _DL},
    # ── 환율 (한국은행 ECOS, 일별) ─────────────────────────────────────────
    "USDKRW": {
        "name": "미국 달러 / 원화", "color": "#10B981", "type": "exchange",
        "id": "USDKRW", "currency": "KRW", "decimals": 1, "source": "ecos",
        "ecos_stat_code": "731Y001", "ecos_item_code": "0000001",
        "freq": "D", "context_days": 730, "horizons": _D, "horizon_labels": _DL,
    },
    "JPYKRW": {
        "name": "일본 엔 / 원화 (100엔)", "color": "#EF4444", "type": "exchange",
        "id": "JPYKRW", "currency": "KRW", "decimals": 2, "source": "ecos",
        "ecos_stat_code": "731Y001", "ecos_item_code": "0000002",
        "freq": "D", "context_days": 730, "horizons": _D, "horizon_labels": _DL,
    },
    # ── 아파트 실거래가 (국토교통부, 월별) ────────────────────────────────
    "APT-SEOUL": {
        "name": "서울 아파트 평균", "color": "#8B5CF6", "type": "apt",
        "id": "APT-SEOUL", "currency": "KRW", "decimals": 0, "unit": "만원/㎡", "source": "molit",
        "lawd_cd_list": [
            "11110","11140","11170","11200","11215","11230","11260","11290",
            "11305","11320","11350","11380","11410","11440","11470","11500",
            "11530","11545","11560","11590","11620","11650","11680","11710","11740",
        ],
        "context_months": 36, "freq": "M", "horizons": _M, "horizon_labels": _ML,
    },
    "APT-GANGNAM": {
        "name": "강남3구 아파트", "color": "#F59E0B", "type": "apt",
        "id": "APT-GANGNAM", "currency": "KRW", "decimals": 0, "unit": "만원/㎡", "source": "molit",
        "lawd_cd_list": ["11680", "11650", "11710"],
        "context_months": 36, "freq": "M", "horizons": _M, "horizon_labels": _ML,
    },
    "APT-NOWON": {
        "name": "노도강 아파트", "color": "#06B6D4", "type": "apt",
        "id": "APT-NOWON", "currency": "KRW", "decimals": 0, "unit": "만원/㎡", "source": "molit",
        "lawd_cd_list": ["11350", "11320", "11305"],
        "context_months": 36, "freq": "M", "horizons": _M, "horizon_labels": _ML,
    },
    # ── 소비자물가지수 (한국은행 ECOS, 월별) ──────────────────────────────
    "CPI-TOTAL": {
        "name": "소비자물가지수 (전체)", "color": "#F97316", "type": "cpi",
        "id": "CPI-TOTAL", "currency": "INDEX", "decimals": 2, "unit": "", "source": "ecos",
        "ecos_stat_code": "901Y009", "ecos_item_code": "0",
        "freq": "M", "context_months": 60, "horizons": _M, "horizon_labels": _ML,
    },
    "CPI-FOOD": {
        "name": "식품·비주류음료 물가", "color": "#EC4899", "type": "cpi",
        "id": "CPI-FOOD", "currency": "INDEX", "decimals": 2, "unit": "", "source": "ecos",
        "ecos_stat_code": "901Y009", "ecos_item_code": "1",
        "freq": "M", "context_months": 60, "horizons": _M, "horizon_labels": _ML,
    },
    "CPI-HOUSING": {
        "name": "주거·수도·광열 물가", "color": "#14B8A6", "type": "cpi",
        "id": "CPI-HOUSING", "currency": "INDEX", "decimals": 2, "unit": "", "source": "ecos",
        "ecos_stat_code": "901Y009", "ecos_item_code": "4",
        "freq": "M", "context_months": 60, "horizons": _M, "horizon_labels": _ML,
    },
}

MONTHLY_TYPES    = {"apt", "cpi"}
CRYPTO_SYMBOLS   = [k for k, v in ASSETS.items() if v["type"] == "crypto"]
KR_STOCK_SYMBOLS = [k for k, v in ASSETS.items() if v["type"] == "kr_stock"]
EXCHANGE_SYMBOLS = [k for k, v in ASSETS.items() if v["type"] == "exchange"]
APT_SYMBOLS      = [k for k, v in ASSETS.items() if v["type"] == "apt"]
CPI_SYMBOLS      = [k for k, v in ASSETS.items() if v["type"] == "cpi"]

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
                "User-Agent": "TimesFM-Forecast/4.0 (educational)",
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
    now = time.time()
    cached = _price_cache.get(coin_id)
    if cached and (now - cached["ts"]) < TTL["crypto"]["price"]:
        return np.array(cached["prices"], dtype=np.float32), cached["current"], cached["change_24h"]

    data = http_get(
        f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart"
        f"?vs_currency=usd&days=365&interval=daily"
    )
    prices = [p[1] for p in data["prices"]]
    try:
        cur_data = http_get(
            f"https://api.coingecko.com/api/v3/simple/price"
            f"?ids={coin_id}&vs_currencies=usd&include_24hr_change=true"
        )
        current    = cur_data[coin_id]["usd"]
        change_24h = round(cur_data[coin_id].get("usd_24h_change", 0), 2)
    except Exception:
        current    = prices[-1]
        change_24h = 0.0

    _price_cache[coin_id] = {"prices": prices, "current": current, "change_24h": change_24h, "ts": now}
    print(f"[CoinGecko] {coin_id}: {len(prices)}일 로드")
    return np.array(prices, dtype=np.float32), current, change_24h


# ── yfinance (한국 주식) ───────────────────────────────────────────────────
def fetch_kr_stock_prices(ticker: str) -> tuple[np.ndarray, float, float]:
    now = time.time()
    cached = _price_cache.get(ticker)
    if cached and (now - cached["ts"]) < TTL["kr_stock"]["price"]:
        return np.array(cached["prices"], dtype=np.float32), cached["current"], cached["change_24h"]

    import yfinance as yf
    df = yf.download(ticker, period="1y", interval="1d", progress=False, auto_adjust=True)
    if df.empty:
        raise HTTPException(status_code=503, detail=f"{ticker} 데이터 수집 실패")

    closes = df["Close"].dropna()
    prices = closes.values.flatten().astype(np.float32)
    current    = float(prices[-1])
    change_24h = round((float(prices[-1]) / float(prices[-2]) - 1) * 100, 2) if len(prices) > 1 else 0.0

    _price_cache[ticker] = {"prices": prices.tolist(), "current": current, "change_24h": change_24h, "ts": now}
    print(f"[yfinance] {ticker}: {len(prices)}일 로드, 현재 {current:,.0f}")
    return prices, current, change_24h


# ── 한국은행 ECOS (환율·물가 — 범용) ────────────────────────────────────────
def fetch_ecos_timeseries(
    stat_code: str,
    item_code: str,
    freq: str,
    cache_key: str,
    context: int = 730,
) -> tuple[np.ndarray, float, float]:
    """한국은행 ECOS 범용 시계열 수집.
    freq='D': context=일수 / freq='M': context=개월수
    """
    asset_type = "exchange" if freq == "D" else "cpi"
    now = time.time()
    cached = _price_cache.get(cache_key)
    if cached and (now - cached["ts"]) < TTL[asset_type]["price"]:
        return np.array(cached["prices"], dtype=np.float32), cached["current"], cached["change_24h"]

    if freq == "M":
        end_dt   = datetime.now()
        # 개월 수만큼 과거 시작
        start_m  = end_dt.year * 12 + end_dt.month - 1 - context
        start_dt = datetime(start_m // 12, start_m % 12 + 1, 1)
        end_str   = end_dt.strftime("%Y%m")
        start_str = start_dt.strftime("%Y%m")
        date_fmt  = "%Y%m"
    else:
        end_str   = datetime.now().strftime("%Y%m%d")
        start_str = (datetime.now() - timedelta(days=context)).strftime("%Y%m%d")
        date_fmt  = "%Y%m%d"

    url = (
        f"https://ecos.bok.or.kr/api/StatisticSearch/"
        f"{ECOS_API_KEY}/json/kr/1/1000/"
        f"{stat_code}/{freq}/{start_str}/{end_str}/{item_code}"
    )

    data = None
    last_error = None
    for attempt in range(3):
        try:
            resp = http_requests.get(url, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if "RESULT" in data:
                raise HTTPException(
                    status_code=500,
                    detail=f"ECOS API 오류: {data['RESULT'].get('MESSAGE', '알 수 없는 오류')}"
                )
            break
        except HTTPException:
            raise
        except Exception as e:
            last_error = e
            if attempt < 2:
                time.sleep(2)
    if data is None:
        raise HTTPException(status_code=500, detail=f"ECOS API 연결 실패: {last_error}")

    rows = data.get("StatisticSearch", {}).get("row", [])
    if not rows:
        raise HTTPException(status_code=500, detail=f"ECOS 데이터 없음 ({stat_code}/{item_code})")

    df = pd.DataFrame(rows)[["TIME", "DATA_VALUE"]].copy()
    df.columns = ["date", "value"]
    df = df[
        df["value"].str.strip().notna() &
        (df["value"].str.strip() != "") &
        (df["value"].str.strip() != "-")
    ].copy()
    df["date"]  = pd.to_datetime(df["date"], format=date_fmt)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["value"]).sort_values("date").reset_index(drop=True)

    if freq == "D":
        full_range = pd.date_range(df["date"].min(), df["date"].max(), freq="D")
        df = df.set_index("date").reindex(full_range).ffill().reset_index()
        df.columns = ["date", "value"]

    min_req = 24 if freq == "M" else 128
    if len(df) < min_req:
        raise HTTPException(
            status_code=500,
            detail=f"데이터 부족: {len(df)}개 (최소 {min_req}개 필요)"
        )

    prices    = df["value"].values.astype(np.float32)
    current   = float(prices[-1])
    change_p  = round((float(prices[-1]) / float(prices[-2]) - 1) * 100, 2) if len(prices) > 1 else 0.0

    _price_cache[cache_key] = {
        "prices": prices.tolist(), "current": current, "change_24h": change_p, "ts": now
    }
    unit = "개월" if freq == "M" else "일"
    print(f"[ECOS] {cache_key}: {len(prices)}{unit} 로드, 최신 {current:.2f}")
    return prices, current, change_p


# ── 국토교통부 MOLIT (아파트 실거래가) ────────────────────────────────────────
def _fetch_one_district_month(lawd_cd: str, deal_ymd: str) -> list[float]:
    """단일 법정동 + 월 아파트 거래 ㎡당 가격(만원) 목록"""
    if not MOLIT_API_KEY:
        return []
    url = (
        "https://apis.data.go.kr/1613000/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade"
    )
    params = {
        "serviceKey": MOLIT_API_KEY,
        "LAWD_CD":    lawd_cd,
        "DEAL_YMD":   deal_ymd,
        "numOfRows":  "1000",
        "pageNo":     "1",
    }
    try:
        resp = http_requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        root  = ET.fromstring(resp.text)
        items = root.findall(".//item")
        result = []
        for item in items:
            # 신규 API: dealAmount(만원), excluUseAr(㎡)
            price_s = (item.findtext("dealAmount") or item.findtext("거래금액") or "").replace(",", "").strip()
            area_s  = (item.findtext("excluUseAr") or item.findtext("전용면적") or "").strip()
            if price_s and area_s:
                try:
                    price = float(price_s)
                    area  = float(area_s)
                    if area > 0:
                        result.append(price / area)
                except ValueError:
                    pass
        return result
    except Exception as e:
        print(f"[MOLIT] {lawd_cd} {deal_ymd} 오류: {e}")
        return []


def fetch_apt_monthly_price(symbol: str, lawd_cd_list: list, months: int = 36) -> tuple[np.ndarray, float, float]:
    """국토부 실거래가 API로 월별 ㎡당 평균가 수집"""
    if not MOLIT_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="MOLIT_API_KEY 미설정. data.go.kr에서 '아파트매매 실거래가 상세 자료' API 키 발급 후 .env에 추가하세요."
        )

    now = time.time()
    cached = _price_cache.get(symbol)
    if cached and (now - cached["ts"]) < TTL["apt"]["price"]:
        return np.array(cached["prices"], dtype=np.float32), cached["current"], cached["change_24h"]

    today = datetime.now()
    month_list = []
    for i in range(months, 0, -1):
        total = today.year * 12 + today.month - 1 - i
        month_list.append(f"{total // 12}{total % 12 + 1:02d}")

    monthly_prices = []
    for deal_ymd in month_list:
        with ThreadPoolExecutor(max_workers=5) as ex:
            results = list(ex.map(lambda c: _fetch_one_district_month(c, deal_ymd), lawd_cd_list))
        all_prices = [p for r in results for p in r]
        if len(all_prices) >= 10:
            arr = np.array(all_prices)
            q1, q3 = np.percentile(arr, [25, 75])
            iqr     = q3 - q1
            filt    = arr[(arr >= q1 - 1.5 * iqr) & (arr <= q3 + 1.5 * iqr)]
            monthly_prices.append(round(float(np.mean(filt)), 0) if len(filt) > 0 else None)
        else:
            monthly_prices.append(None)
        time.sleep(0.1)

    # ffill None
    for i in range(1, len(monthly_prices)):
        if monthly_prices[i] is None and monthly_prices[i - 1] is not None:
            monthly_prices[i] = monthly_prices[i - 1]
    valid = [p for p in monthly_prices if p is not None]
    if len(valid) < 12:
        raise HTTPException(status_code=500, detail=f"유효 아파트 데이터 부족: {len(valid)}개월")

    prices    = np.array(valid, dtype=np.float32)
    current   = float(prices[-1])
    change_1m = round((float(prices[-1]) / float(prices[-2]) - 1) * 100, 2) if len(prices) > 1 else 0.0

    _price_cache[symbol] = {
        "prices": prices.tolist(), "current": current, "change_24h": change_1m, "ts": now
    }
    print(f"[MOLIT] {symbol}: {len(prices)}개월 로드, 최신 {current:,.0f}만원/㎡")
    return prices, current, change_1m


# ── 분석 함수 ─────────────────────────────────────────────────────────────
def calculate_mape(actual: list, predicted: list) -> float | None:
    errors = []
    for a, p in zip(actual, predicted):
        if a and a != 0:
            errors.append(abs((a - p) / a) * 100)
    if not errors:
        return None
    result = sum(errors) / len(errors)
    return None if math.isnan(result) or math.isinf(result) else result


def calculate_directional_accuracy(base: list, actual: list, predicted: list) -> float | None:
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
    recent  = prices[-31:]
    changes = []
    for i in range(1, len(recent)):
        prev, curr = recent[i - 1], recent[i]
        if prev and curr:
            changes.append(abs((curr - prev) / prev) * 100)
    if not changes:
        return {"avg_abs_change_pct": None, "level": "계산 불가", "warning": ""}
    avg = sum(changes) / len(changes)

    thresholds = {
        "crypto":   [(2, "낮음"), (4, "보통"), (6, "높음")],
        "kr_stock": [(1, "낮음"), (2, "보통"), (3.5, "높음")],
        "exchange": [(0.3, "낮음"), (0.8, "보통"), (1.5, "높음")],
        "apt":      [(0.5, "낮음"), (1.5, "보통"), (3.0, "높음")],
        "cpi":      [(0.1, "낮음"), (0.3, "보통"), (0.8, "높음")],
    }
    labels  = [("낮음", "안정 구간"), ("보통", "일반 변동성"), ("높음", "주의 필요"), ("매우 높음", "예측 신뢰도 낮음")]
    bounds  = thresholds.get(asset_type, thresholds["exchange"])
    for bound, label in bounds:
        if avg < bound:
            idx = ["낮음", "보통", "높음"].index(label)
            return {"avg_abs_change_pct": round(avg, 2), "level": labels[idx][0], "warning": labels[idx][1]}
    return {"avg_abs_change_pct": round(avg, 2), "level": "매우 높음", "warning": "예측 신뢰도 낮음"}


def calculate_confidence_score(
    mape,
    directional_acc,
    volatility_level: str,
    range_pct,
    horizon: int,
    is_monthly: bool = False,
) -> dict:
    score = 100.0

    if mape is not None and not math.isnan(mape):
        score -= min(mape * 3, 40)
    else:
        score -= 25

    vol_penalty = {"낮음": 0, "보통": 5, "높음": 12, "매우 높음": 20, "계산 불가": 10}
    score -= vol_penalty.get(volatility_level, 10)

    if range_pct is not None:
        if range_pct >= 20:   score -= 20
        elif range_pct >= 10: score -= 10
        elif range_pct >= 5:  score -= 5
    else:
        score -= 10

    # 일별 및 월별 예측 기간 패널티
    if is_monthly:
        h_penalty = {1: 3, 3: 10, 6: 18, 12: 25}
    else:
        h_penalty = {1: 0, 7: 5, 14: 12, 30: 25}
    score -= h_penalty.get(horizon, 15)

    if directional_acc is not None and not math.isnan(directional_acc):
        if directional_acc >= 60:   score += 10
        elif directional_acc >= 55: score += 5
        elif directional_acc < 50:  score -= 5

    if math.isnan(score) or math.isinf(score):
        score = 30
    score = max(0, min(100, round(score)))

    if score >= 70:   label = "참고 가능"
    elif score >= 50: label = "제한적 참고 가능"
    elif score >= 30: label = "주의 필요"
    else:             label = "시나리오 참고 수준"

    return {"score": score, "label": label}


def generate_interpretation(
    asset_name: str,
    horizon: int,
    change_pct: float,
    confidence_score: int,
    confidence_label: str,
    volatility_level: str,
    directional_acc,
    range_pct,
    horizon_unit: str = "일",
) -> str:
    if change_pct > 1:    dir_text = "상승 흐름"
    elif change_pct < -1: dir_text = "하락 흐름"
    else:                 dir_text = "중립적인 흐름"

    msg = f"{asset_name} {horizon}{horizon_unit} 예측은 과거 패턴 기준으로 {dir_text}을 보입니다. "
    msg += f"현재 예측 신뢰도는 {confidence_score}/100으로, {confidence_label} 수준입니다. "

    if volatility_level in ("높음", "매우 높음"):
        msg += (
            f"최근 변동성이 {volatility_level} 상태이므로 단일 값보다 "
            f"예측 범위를 중심으로 해석하는 것이 좋습니다. "
        )
    if directional_acc is not None and directional_acc < 50:
        msg += "최근 백테스트 기준 방향성 적중률이 50% 미만이므로 상승·하락 판단에 신중한 해석이 필요합니다. "
    if range_pct is not None and range_pct >= 20:
        msg += "예측 범위가 넓어 장기 예측은 시나리오 참고 수준으로 보는 것이 적절합니다."

    return msg.strip()


def run_backtest(symbol: str, prices: np.ndarray, asset_type: str) -> dict:
    """롤링 백테스트: MAPE + 방향성 적중률"""
    now = time.time()
    cached = _backtest_cache.get(symbol)
    bt_ttl = TTL.get(asset_type, TTL["crypto"])["backtest"]
    if cached and (now - cached["ts"]) < bt_ttl:
        return cached["data"]

    meta       = ASSETS[symbol]
    is_monthly = asset_type in MONTHLY_TYPES
    horizons_list = meta.get("horizons", _M if is_monthly else _D)

    prices_list   = prices.tolist()
    n             = len(prices_list)
    MIN_TRAIN     = 24 if is_monthly else 180
    MODEL_HORIZON = 12 if is_monthly else 30

    MAX_SAMPLES = (
        {1: 10, 3: 8, 6: 6, 12: 4}
        if is_monthly else
        {1: 30, 7: 20, 14: 15, 30: 8}
    )

    results = {}
    for horizon in horizons_list:
        max_s = MAX_SAMPLES.get(horizon, 5)
        actuals, preds, bases = [], [], []

        end_limit = n - horizon
        start     = max(MIN_TRAIN, end_limit - max_s)

        for train_end in range(start, end_limit):
            context = np.array(prices_list[:train_end], dtype=np.float32)
            if len(context) < MIN_TRAIN:
                continue
            try:
                model = get_model()
                ctx   = context[-256:] if len(context) >= 256 else context
                pf, _ = model.forecast(horizon=min(horizon, MODEL_HORIZON), inputs=[ctx])
                idx          = min(horizon - 1, len(pf[0]) - 1)
                pred_price   = float(pf[0][idx])
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
            "horizon":              horizon,
            "mape":                 round(mape, 2) if mape is not None else None,
            "directional_accuracy": round(da,   1) if da   is not None else None,
            "sample_count":         len(actuals),
        }

    _backtest_cache[symbol] = {"data": results, "ts": now}
    return results


# ── 공통 예측 ─────────────────────────────────────────────────────────────
def _do_forecast(symbol: str) -> dict:
    meta       = ASSETS[symbol]
    asset_type = meta["type"]
    is_monthly = asset_type in MONTHLY_TYPES
    t0         = time.time()

    # ── 데이터 수집 ──────────────────────────────────────────────────────
    if asset_type == "crypto":
        prices, current_price, change_p = fetch_crypto_prices(meta["id"])
    elif asset_type == "kr_stock":
        prices, current_price, change_p = fetch_kr_stock_prices(meta["id"])
    elif asset_type == "exchange":
        prices, current_price, change_p = fetch_ecos_timeseries(
            meta["ecos_stat_code"], meta["ecos_item_code"],
            meta["freq"], symbol, meta.get("context_days", 730)
        )
    elif asset_type == "cpi":
        prices, current_price, change_p = fetch_ecos_timeseries(
            meta["ecos_stat_code"], meta["ecos_item_code"],
            meta["freq"], symbol, meta.get("context_months", 60)
        )
    elif asset_type == "apt":
        prices, current_price, change_p = fetch_apt_monthly_price(
            symbol, meta["lawd_cd_list"], meta.get("context_months", 36)
        )
    else:
        raise HTTPException(status_code=400, detail=f"지원하지 않는 자산 유형: {asset_type}")

    # ── 모델 추론 ─────────────────────────────────────────────────────────
    MODEL_HORIZON = 12 if is_monthly else 30
    model         = get_model()
    context       = prices[-256:] if len(prices) >= 256 else prices
    point_forecast, quantile_forecast = model.forecast(horizon=MODEL_HORIZON, inputs=[context])
    pf = point_forecast[0]

    if quantile_forecast is not None and not np.any(np.isnan(quantile_forecast[0, :, 1])):
        q10 = quantile_forecast[0, :, 1].tolist()
        q90 = quantile_forecast[0, :, 8].tolist()
    else:
        q10 = (pf * 0.95).tolist()
        q90 = (pf * 1.05).tolist()

    pf_list = pf.tolist()
    today   = datetime.utcnow().date()

    # ── 날짜 시퀀스 ───────────────────────────────────────────────────────
    if is_monthly:
        forecast_dates = []
        for i in range(1, MODEL_HORIZON + 1):
            total = today.year * 12 + today.month - 1 + i
            forecast_dates.append(f"{total // 12}-{total % 12 + 1:02d}-01")
        history_n = min(36, len(prices))
        history_prices = prices[-history_n:].tolist()
        history_dates  = []
        for i in range(history_n - 1, -1, -1):
            total = today.year * 12 + today.month - 1 - i
            history_dates.append(f"{total // 12}-{total % 12 + 1:02d}-01")
    else:
        forecast_dates = [(today + timedelta(days=i + 1)).isoformat() for i in range(MODEL_HORIZON)]
        history_prices = prices[-90:].tolist()
        history_dates  = [(today - timedelta(days=len(history_prices) - 1 - i)).isoformat()
                          for i in range(len(history_prices))]

    # ── 변동성 ────────────────────────────────────────────────────────────
    vol_info = calculate_volatility_level(prices.tolist(), asset_type)

    # ── 백테스트 ──────────────────────────────────────────────────────────
    try:
        backtest_data = run_backtest(symbol, prices, asset_type)
    except Exception as e:
        print(f"[backtest] 실패: {e}")
        backtest_data = {}

    # ── key_forecasts 생성 ────────────────────────────────────────────────
    # 키는 항상 d1/d7/d14/d30 사용 (일별·월별 공통)
    # 월별: d1=1개월, d7=3개월, d14=6개월, d30=12개월
    KF_KEYS    = ["d1", "d7", "d14", "d30"]
    horizons_list   = meta.get("horizons", _M if is_monthly else _D)
    horizon_labels  = meta.get("horizon_labels", _ML if is_monthly else _DL)
    horizon_unit    = "개월" if is_monthly else "일"
    dec             = meta["decimals"]

    key_forecasts = {}
    for kf_key, horizon, label in zip(KF_KEYS, horizons_list, horizon_labels):
        idx       = min(horizon - 1, len(pf_list) - 1)
        fc        = pf_list[idx]
        q10v      = q10[idx]
        q90v      = q90[idx]
        pct       = (fc / current_price - 1) * 100 if current_price else 0
        range_pct = round((q90v - q10v) / fc * 100, 1) if fc and fc > 0 else None

        bt_result = backtest_data.get(f"h{horizon}", {})
        mape_val  = bt_result.get("mape")
        da_val    = bt_result.get("directional_accuracy")

        conf = calculate_confidence_score(
            mape_val, da_val, vol_info["level"], range_pct, horizon, is_monthly
        )
        interp = generate_interpretation(
            meta["name"], horizon, round(pct, 2),
            conf["score"], conf["label"],
            vol_info["level"], da_val, range_pct,
            horizon_unit,
        )
        fc_date = forecast_dates[idx] if idx < len(forecast_dates) else ""

        key_forecasts[kf_key] = {
            "horizon":              horizon,
            "horizon_unit":         horizon_unit,
            "label":                label,
            "date":                 fc_date,
            "price":                round(fc,   dec),
            "q10":                  round(q10v, dec),
            "q90":                  round(q90v, dec),
            "pct_change":           round(pct,  2),
            "range_pct":            range_pct,
            "mape":                 mape_val,
            "directional_accuracy": da_val,
            "volatility_level":     vol_info["level"],
            "volatility_warning":   vol_info["warning"],
            "confidence_score":     conf["score"],
            "confidence_label":     conf["label"],
            "interpretation":       interp,
        }

    return {
        "symbol":          symbol,
        "name":            meta["name"],
        "color":           meta["color"],
        "type":            asset_type,
        "currency":        meta["currency"],
        "unit":            meta.get("unit", ""),
        "time_unit":       horizon_unit,
        "current_price":   round(current_price, dec),
        "change_24h":      change_p,
        "volatility":      vol_info,
        "forecast_dates":  forecast_dates,
        "forecast_prices": [round(p, dec) for p in pf_list],
        "q10":             [round(p, dec) for p in q10],
        "q90":             [round(p, dec) for p in q90],
        "history_dates":   history_dates,
        "history_prices":  [round(p, dec) for p in history_prices],
        "key_forecasts":   key_forecasts,
        "elapsed_sec":     round(time.time() - t0, 2),
        "generated_at":    datetime.utcnow().isoformat() + "Z",
        "cached":          False,
    }


def run_forecast(symbol: str) -> dict:
    now    = time.time()
    cached = _forecast_cache.get(symbol)
    fc_ttl = TTL.get(ASSETS.get(symbol, {}).get("type", "crypto"), TTL["crypto"])["forecast"]
    if cached and (now - cached["ts"]) < fc_ttl:
        result = dict(cached["data"])
        result["cached"]        = True
        result["cache_age_sec"] = round(now - cached["ts"], 0)
        return result
    result = _do_forecast(symbol)
    _forecast_cache[symbol] = {"data": result, "ts": now}
    return result


# ── 엔드포인트 ────────────────────────────────────────────────────────────
@app.get("/api/health")
def health():
    ecos_status = "ok"
    try:
        test_url = (
            f"https://ecos.bok.or.kr/api/StatisticSearch/{ECOS_API_KEY}"
            f"/json/kr/1/1/731Y001/D/20260101/20260101/0000001"
        )
        r = http_requests.get(test_url, timeout=5)
        ecos_status = "ok" if r.status_code == 200 else f"error({r.status_code})"
    except Exception:
        ecos_status = "unreachable"

    return {
        "status":          "ok",
        "model_loaded":    _model_loaded,
        "ecos_api":        ecos_status,
        "molit_api_key":   "설정됨" if MOLIT_API_KEY else "미설정 (아파트 예측 불가)",
        "forecast_cache":  {s: bool(_forecast_cache.get(s)) for s in ASSETS},
        "backtest_cache":  {s: bool(_backtest_cache.get(s)) for s in ASSETS},
    }


@app.get("/api/assets")
def list_assets():
    return {
        k: {
            "name": v["name"], "color": v["color"], "type": v["type"],
            "currency": v["currency"], "unit": v.get("unit", ""),
            "horizons": v.get("horizons"), "horizon_labels": v.get("horizon_labels"),
        }
        for k, v in ASSETS.items()
    }


@app.get("/api/forecast/{symbol}")
def forecast(symbol: str):
    symbol = symbol.upper()
    if symbol not in ASSETS:
        raise HTTPException(status_code=400, detail=f"지원 심볼: {list(ASSETS.keys())}")
    return run_forecast(symbol)


@app.get("/api/dashboard")
def dashboard():
    """대시보드 요약 — 캐시된 예측 결과를 카테고리별로 반환 (모델 추론 없음)"""
    categories = {
        "crypto":   CRYPTO_SYMBOLS,
        "kr_stock": KR_STOCK_SYMBOLS,
        "exchange": EXCHANGE_SYMBOLS,
        "apt":      APT_SYMBOLS,
        "cpi":      CPI_SYMBOLS,
    }
    summary = {}
    for cat, syms in categories.items():
        summary[cat] = []
        for sym in syms:
            fc_cached = _forecast_cache.get(sym)
            entry = {
                "symbol": sym,
                "name":   ASSETS[sym]["name"],
                "color":  ASSETS[sym]["color"],
                "type":   ASSETS[sym]["type"],
                "has_forecast": bool(fc_cached),
            }
            if fc_cached:
                d = fc_cached["data"]
                entry["current_price"] = d.get("current_price")
                entry["change_24h"]    = d.get("change_24h")
                entry["currency"]      = d.get("currency")
                entry["unit"]          = d.get("unit", "")
                kf = d.get("key_forecasts", {})
                entry["d30_confidence"] = kf.get("d30", {}).get("confidence_score")
                entry["d30_pct_change"] = kf.get("d30", {}).get("pct_change")
                entry["d30_label"]      = kf.get("d30", {}).get("label")
            summary[cat].append(entry)
    return {"categories": summary, "generated_at": datetime.utcnow().isoformat() + "Z"}


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
    return {"message": "TimesFM 한국경제 대시보드 API v4"}
