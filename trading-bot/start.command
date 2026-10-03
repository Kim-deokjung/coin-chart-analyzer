#!/bin/bash
# 더블클릭으로 관리자 화면 실행 (macOS)
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "가상환경 생성 및 패키지 설치 중..."
  python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt
fi
PORT=$(.venv/bin/python -c "import yaml;print((yaml.safe_load(open('config.yaml')) or {}).get('dashboard',{}).get('port',8000))")
( sleep 2; open "http://127.0.0.1:${PORT}" ) &
echo "관리자 화면: http://127.0.0.1:${PORT}  (종료: Ctrl+C 또는 이 창 닫기)"
.venv/bin/python -W ignore main.py dashboard
