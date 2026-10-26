#!/usr/bin/env bash
set -euo pipefail

app_root="${EXE_DEV_APP_ROOT:-/home/exedev/apps/zippick}"
venv_dir="${EXE_DEV_VENV_DIR:-/home/exedev/maesuhalkkayo/.venv}"
expected_commit="${1:-}"
release_dir="$(readlink -f "$app_root/current")"
if [[ ! "$expected_commit" =~ ^[0-9a-f]{40}$ || "$(basename "$release_dir")" != "$expected_commit" ]]; then
  echo "오류: 운영 릴리스가 요청한 GitHub 커밋과 다릅니다." >&2
  exit 1
fi

"$venv_dir/bin/python" -m pip --disable-pip-version-check install \
  --requirement "$release_dir/requirements-future-transformation.txt"
"$venv_dir/bin/python" -c 'import shapely, pyproj; from shapely.strtree import STRtree; print("공간 분석 패키지 확인 완료")'

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=$XDG_RUNTIME_DIR/bus}"
systemctl --user restart zippick.service
for _ in {1..30}; do
  if curl --fail --silent --output /dev/null http://127.0.0.1:8766/; then
    echo "운영 실행 환경 준비 완료: ${expected_commit:0:12}"
    exit 0
  fi
  sleep 1
done
echo "오류: 실행 환경 준비 후 서비스 응답을 확인하지 못했습니다." >&2
exit 1
