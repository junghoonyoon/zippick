#!/usr/bin/env bash
set -euo pipefail

readonly EXE_DEV_HOST="${EXE_DEV_HOST:-maesuhalkkayo.exe.xyz}"
readonly EXE_DEV_DEPLOY_COMMAND="${EXE_DEV_DEPLOY_COMMAND:-/home/exedev/bin/deploy-zippick}"
readonly EXE_DEV_PREPARE_RUNTIME_COMMAND="${EXE_DEV_PREPARE_RUNTIME_COMMAND:-/home/exedev/apps/zippick/current/deploy/exe-dev/prepare-runtime.sh}"
readonly REQUIRED_BRANCH="${EXE_DEV_BRANCH:-main}"
readonly EXE_DEV_PUBLIC_URL="${EXE_DEV_PUBLIC_URL:-https://maesuhalkkayo.exe.xyz}"

repo_root="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "오류: Git 저장소 안에서 실행해야 합니다." >&2
  exit 1
}
cd "$repo_root"

current_branch="$(git branch --show-current)"
if [[ "$current_branch" != "$REQUIRED_BRANCH" ]]; then
  echo "오류: ${REQUIRED_BRANCH} 브랜치에서만 배포할 수 있습니다. 현재: ${current_branch:-detached HEAD}" >&2
  exit 1
fi

if [[ -n "$(git status --porcelain)" ]]; then
  echo "오류: 커밋되지 않은 변경이 있습니다. 먼저 변경을 커밋하세요." >&2
  git status --short >&2
  exit 1
fi

echo "[1/5] GitHub origin/${REQUIRED_BRANCH} 확인"
git fetch --quiet origin "$REQUIRED_BRANCH"

local_commit="$(git rev-parse HEAD)"
github_commit="$(git rev-parse "origin/${REQUIRED_BRANCH}")"
if [[ "$local_commit" != "$github_commit" ]]; then
  echo "오류: 로컬 HEAD가 GitHub origin/${REQUIRED_BRANCH}와 다릅니다." >&2
  echo "로컬:  $local_commit" >&2
  echo "GitHub: $github_commit" >&2
  echo "먼저 git push origin ${REQUIRED_BRANCH}를 실행하세요." >&2
  exit 1
fi

echo "[2/5] exe.dev에 GitHub 커밋 배포: ${local_commit:0:12}"
ssh -o BatchMode=yes "$EXE_DEV_HOST" "$EXE_DEV_DEPLOY_COMMAND" "$local_commit"

echo "[3/5] 공간 분석 실행 환경 준비"
ssh -o BatchMode=yes "$EXE_DEV_HOST" "$EXE_DEV_PREPARE_RUNTIME_COMMAND" "$local_commit"

echo "[4/5] 운영 API 확인"
python3 scripts/verify-exe-dev-apis.py "$EXE_DEV_PUBLIC_URL"

echo "[5/5] 배포 완료: ${local_commit:0:12}"
