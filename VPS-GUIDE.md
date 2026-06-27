# VPS-GUIDE.md — TimesFM VPS 설치 운영 가이드

> 작성일: 2026-06-27  
> VPS: Hostinger `srv1716579.hstgr.cloud` (Ubuntu 24.04 LTS)  
> 작성자: OpenClaw (오프너)

---

## 1. 전체 구조

```
[사용자 브라우저]
       ↓ HTTPS
[Vercel] https://timesfm-forcase.vercel.app
  → 프론트엔드(HTML/JS) 서빙
       ↓ API 요청 (HTTPS)
[Traefik 리버스 프록시] :443
  → srv1716579.hstgr.cloud/timesfm/*
  → Let's Encrypt 인증서 자동 관리
       ↓ HTTP (내부)
[TimesFM FastAPI] 127.0.0.1:8100
  → systemd 서비스로 상시 실행
       ↓ 데이터
[CoinGecko API]     — BTC / ETH / XRP
[Yahoo Finance API] — 삼성전자 / SK하이닉스 / 현대차 / KOSPI
```

---

## 2. 서버 정보

| 항목 | 값 |
|---|---|
| 호스팅 | Hostinger VPS |
| IP | `187.127.106.130` |
| 도메인 | `srv1716579.hstgr.cloud` |
| OS | Ubuntu 24.04.4 LTS |
| Python | 3.12.3 (venv) |
| 내부 포트 | `8100` |
| 외부 URL | `https://srv1716579.hstgr.cloud/timesfm` |
| SSH | `ssh root@187.127.106.130` |

---

## 3. 설치 경로

```
/opt/timesfm/
├── app/                    # 소스코드 (GitHub clone)
│   ├── api/
│   │   ├── main.py         # FastAPI 백엔드 핵심
│   │   ├── requirements.txt
│   │   └── ...
│   └── frontend/
│       └── index.html      # (Vercel에서 서빙, VPS에서 미사용)
└── venv/                   # Python 가상환경
    └── bin/
        ├── python3
        ├── uvicorn
        └── pip

/etc/systemd/system/timesfm.service   # systemd 서비스 파일
/docker/traefik/conf/timesfm.yml      # Traefik 라우팅 설정
/docker/traefik/docker-compose.yml    # Traefik 실행 설정
```

---

## 4. API 엔드포인트

**베이스 URL:** `https://srv1716579.hstgr.cloud/timesfm`

| 엔드포인트 | 설명 | 예시 |
|---|---|---|
| `GET /api/health` | 서버·모델·캐시 상태 | [링크](https://srv1716579.hstgr.cloud/timesfm/api/health) |
| `GET /api/assets` | 지원 자산 목록 | [링크](https://srv1716579.hstgr.cloud/timesfm/api/assets) |
| `GET /api/forecast/{symbol}` | 예측 실행 | `/api/forecast/BTC` |
| `GET /api/cache/clear` | 캐시 초기화 | — |
| `GET /docs` | FastAPI Swagger UI | [링크](https://srv1716579.hstgr.cloud/timesfm/docs) |

**지원 심볼:** `BTC` `ETH` `XRP` `005930` `000660` `005380` `KOSPI`

---

## 5. 서비스 관리 명령어

### SSH 접속
```bash
ssh root@187.127.106.130
```

### TimesFM 서비스 (systemd)
```bash
# 상태 확인
systemctl status timesfm

# 시작 / 중지 / 재시작
systemctl start timesfm
systemctl stop timesfm
systemctl restart timesfm

# 실시간 로그
journalctl -fu timesfm

# 최근 100줄 로그
journalctl -u timesfm -n 100 --no-pager

# 오늘 로그 전체
journalctl -u timesfm --since today --no-pager
```

### Traefik (리버스 프록시)
```bash
cd /docker/traefik

# 상태 확인
docker compose ps

# 재시작
docker compose restart

# 로그
docker compose logs -f --tail=50
```

### 포트 확인
```bash
ss -tlnp | grep -E '8100|80|443'
```

---

## 6. 소스코드 업데이트 (배포)

GitHub에 push하면 VPS에 수동으로 pull 해야 합니다.

```bash
ssh root@187.127.106.130 "
  cd /opt/timesfm/app &&
  git pull origin main &&
  systemctl restart timesfm
"
```

**또는 맥에서 한 줄로:**
```bash
ssh timesfm-vps "cd /opt/timesfm/app && git pull && systemctl restart timesfm"
```

> ⚠️ `requirements.txt`가 변경됐을 때는 pip install도 함께:
> ```bash
> ssh timesfm-vps "
>   cd /opt/timesfm/app &&
>   git pull &&
>   /opt/timesfm/venv/bin/pip install -r api/requirements.txt -q &&
>   systemctl restart timesfm
> "
> ```

---

## 7. 로컬 맥에서 VPS 접속 설정

`~/.ssh/config`에 등록돼 있습니다:
```
Host timesfm-vps
  HostName 187.127.106.130
  User root
  IdentityFile ~/.ssh/timesfm_vps
  IdentitiesOnly yes
  ServerAliveInterval 30
  ServerAliveCountMax 3
```

```bash
# 접속
ssh timesfm-vps

# 헬스체크
curl https://srv1716579.hstgr.cloud/timesfm/api/health

# 실시간 로그 모니터링
ssh timesfm-vps "journalctl -fu timesfm"
```

---

## 8. 패키지 정보

| 패키지 | 버전 | 역할 |
|---|---|---|
| `timesfm[torch]` | 2.0.1 | Google TimesFM 예측 모델 |
| `fastapi` | 0.111.0 | REST API 프레임워크 |
| `uvicorn[standard]` | 0.30.1 | ASGI 서버 |
| `yfinance` | 1.4.1 | 한국 주식 데이터 |
| `numpy` | 2.5.0 | 수치 연산 |
| `pandas` | 3.0.3 | 데이터 처리 |

---

## 9. 리소스 현황 (2026-06-27 기준)

| 항목 | 현황 |
|---|---|
| RAM 전체 | 7.8 GB |
| RAM 사용 중 | ~5.1 GB (TimesFM 모델 ~2.3 GB 포함) |
| 디스크 전체 | 96 GB |
| 디스크 사용 | ~47 GB (여유 50 GB) |
| CPU | 2코어 |

> ⚠️ **Swap 없음** — 메모리 부족 시 OOM 위험 있음  
> 필요 시 Swap 추가 권장:
> ```bash
> fallocate -l 2G /swapfile && chmod 600 /swapfile
> mkswap /swapfile && swapon /swapfile
> echo '/swapfile none swap sw 0 0' >> /etc/fstab
> ```

---

## 10. Traefik 라우팅 설정

파일 위치: `/docker/traefik/conf/timesfm.yml`

```yaml
http:
  routers:
    timesfm:
      rule: 'Host(`srv1716579.hstgr.cloud`) && PathPrefix(`/timesfm`)'
      entryPoints:
        - websecure        # HTTPS :443
      middlewares:
        - timesfm-strip    # /timesfm 경로 제거 후 백엔드 전달
      service: timesfm
      tls:
        certResolver: letsencrypt  # Let's Encrypt 자동 인증서

  middlewares:
    timesfm-strip:
      stripPrefix:
        prefixes:
          - /timesfm

  services:
    timesfm:
      loadBalancer:
        servers:
          - url: 'http://127.0.0.1:8100'  # 내부 FastAPI
```

> **새 서비스 추가 시:** `/docker/traefik/conf/` 에 yml 파일 추가하면 자동 반영 (watch=true)

---

## 11. 문제 해결

### 예측이 안 될 때
```bash
# 1. 서비스 상태 확인
ssh timesfm-vps "systemctl status timesfm"

# 2. 로그에서 에러 확인
ssh timesfm-vps "journalctl -u timesfm -n 50 --no-pager"

# 3. 헬스체크
curl https://srv1716579.hstgr.cloud/timesfm/api/health

# 4. 서비스 재시작
ssh timesfm-vps "systemctl restart timesfm"
```

### 메모리 부족 (OOM) 발생 시
```bash
ssh timesfm-vps "free -h && dmesg | grep -i 'oom' | tail -5"
# → Swap 추가 또는 캐시 초기화
curl https://srv1716579.hstgr.cloud/timesfm/api/cache/clear
```

### Traefik HTTPS 안 될 때
```bash
ssh timesfm-vps "
  cd /docker/traefik &&
  docker compose logs --tail=30
"
```

### 소스 최신화 안 됐을 때
```bash
ssh timesfm-vps "cd /opt/timesfm/app && git log --oneline -3"
# 최신 커밋이 아니면:
ssh timesfm-vps "cd /opt/timesfm/app && git pull && systemctl restart timesfm"
```

---

## 12. Railway 비교 (마이그레이션 이유)

| 항목 | Railway (구) | VPS (현재) |
|---|---|---|
| 비용 | $5/월 추가 | 기존 VPS 비용에 포함 |
| HTTPS | 자동 | Traefik + Let's Encrypt |
| 슬립 | 없음 | 없음 |
| 모델 캐시 | 재배포마다 재다운로드 | 영구 로컬 캐시 |
| 제어권 | 제한적 | 완전 통제 |
| 포트 | Railway 자동 할당 | 8100 고정 |
| Hermes와 공존 | 불가 | 동일 서버에서 공존 ✅ |

---

## 13. 관련 URL 모음

| 구분 | URL |
|---|---|
| 프론트엔드 (Vercel) | https://timesfm-forcase.vercel.app |
| 백엔드 베이스 | https://srv1716579.hstgr.cloud/timesfm |
| 헬스체크 | https://srv1716579.hstgr.cloud/timesfm/api/health |
| API 문서 | https://srv1716579.hstgr.cloud/timesfm/docs |
| GitHub | https://github.com/charlychoi/timesfm-forcase |
