#!/bin/bash
# 부동산 유튜브 요약 웹앱을 실행한다.
ROOT="$(cd "$(dirname "$0")" && pwd)"
PARENT=""
for candidate in "${BEAVER_V2_ROOT:-}" "$ROOT/../beaver-v2" "$ROOT/../지금사도될까요?/beaver-v2" "$ROOT/.."; do
  if [ -n "$candidate" ] && [ -x "$candidate/pipeline/.venv/bin/python" ]; then
    PARENT="$(cd "$candidate" && pwd)"
    break
  fi
done
PY="$PARENT/pipeline/.venv/bin/python"

cd "$ROOT/pipeline" || exit 1
clear
echo "부동산 유튜브 요약"
echo "──────────────────────────────"

if [ ! -x "$PY" ]; then
  echo "실행 환경(.venv)이 없어요. 부모 프로젝트의 로컬AI_준비.command 또는 기존 환경 준비를 먼저 해주세요."
  read -r -p "엔터를 누르면 닫혀요..."
  exit 1
fi

if ! "$PY" check_settings.py; then
  open -t "$PARENT/설정.txt"
  read -r -p "설정.txt를 확인한 뒤 다시 실행하세요. 엔터를 누르면 닫혀요..."
  exit 1
fi

echo ""
echo "최근 부동산 유튜브 검색 인덱스를 확인할게요."
echo "채널 ID가 비어 있어도 검색어 기반 최신 영상 보강으로 동작합니다."
echo ""
"$PY" sync_search_index.py

echo ""
echo "검색 화면을 여는 중이에요..."
(sleep 1; open "http://127.0.0.1:8766") &
"$PY" search_server.py
