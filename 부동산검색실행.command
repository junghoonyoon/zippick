#!/bin/bash
# 집픽 웹앱을 실행한다.
ROOT="$(cd "$(dirname "$0")" && pwd)"
PARENT=""
PY=""

if [ -x "$ROOT/.venv/bin/python" ]; then
  PY="$ROOT/.venv/bin/python"
fi

for candidate in "${BEAVER_V2_ROOT:-}" "$ROOT/../beaver-v2" "$ROOT/../지금사도될까요?/beaver-v2" "$ROOT/.."; do
  if [ -n "$candidate" ] && [ -x "$candidate/pipeline/.venv/bin/python" ]; then
    PARENT="$(cd "$candidate" && pwd)"
    if [ -z "$PY" ]; then
      PY="$PARENT/pipeline/.venv/bin/python"
    fi
    break
  fi
done

cd "$ROOT/pipeline" || exit 1
clear
echo "집픽"
echo "──────────────────────────────"

if [ ! -x "$PY" ]; then
  echo "실행 환경(.venv)이 없어요. 부모 프로젝트의 로컬AI_준비.command 또는 기존 환경 준비를 먼저 해주세요."
  read -r -p "엔터를 누르면 닫혀요..."
  exit 1
fi

if ! "$PY" check_settings.py; then
  if [ -f "$ROOT/설정.txt" ]; then
    open -t "$ROOT/설정.txt"
  elif [ -n "$PARENT" ] && [ -f "$PARENT/설정.txt" ]; then
    open -t "$PARENT/설정.txt"
  fi
  read -r -p "설정.txt를 확인한 뒤 다시 실행하세요. 엔터를 누르면 닫혀요..."
  exit 1
fi

echo ""
echo "검색 화면을 여는 중이에요..."
if command -v curl >/dev/null 2>&1 && curl -fsS --max-time 1 "http://127.0.0.1:8766" 2>/dev/null | grep -q "집픽"; then
  echo "이미 실행 중이에요. 기존 화면을 열게요."
  open "http://127.0.0.1:8766"
  exit 0
fi

(sleep 1; open "http://127.0.0.1:8766") &
"$PY" search_server.py
