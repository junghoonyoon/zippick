#!/usr/bin/env bash
set -euo pipefail

readonly EXE_DEV_HOST="${EXE_DEV_HOST:-maesuhalkkayo.exe.xyz}"
readonly EXE_DEV_DEPLOY_COMMAND="${EXE_DEV_DEPLOY_COMMAND:-/home/exedev/bin/deploy-zippick}"
readonly REQUIRED_BRANCH="${EXE_DEV_BRANCH:-main}"

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

echo "[1/3] GitHub origin/${REQUIRED_BRANCH} 확인"
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

echo "[2/3] exe.dev에 GitHub 커밋 배포: ${local_commit:0:12}"
ssh -o BatchMode=yes "$EXE_DEV_HOST" "$EXE_DEV_DEPLOY_COMMAND" "$local_commit"

echo "[3/3] 배포 완료: ${local_commit:0:12}"
