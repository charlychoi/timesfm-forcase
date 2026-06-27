#!/bin/bash
# TimesFM Crypto Forecast — 로컬 실행 스크립트

echo "🚀 TimesFM Crypto Forecast 서버 시작..."
echo "   URL: http://localhost:8000"
echo "   API: http://localhost:8000/docs"
echo "   종료: Ctrl+C"
echo ""

cd "$(dirname "$0")/api"
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
