# exe.dev 배포

배포 경로는 항상 아래 순서를 따른다.

```text
로컬 커밋 → GitHub origin/main 푸시 → exe.dev 배포
```

## 배포 명령

변경을 커밋하고 GitHub에 푸시한 뒤 저장소 루트에서 실행한다.

```bash
git push origin main
./scripts/deploy-exe-dev.sh
```

배포 스크립트는 다음 조건을 모두 확인한다.

- 현재 브랜치가 `main`인지
- 커밋되지 않은 변경이 없는지
- 로컬 `HEAD`와 GitHub `origin/main`이 정확히 같은지
- exe.dev가 GitHub에서 확인한 커밋과 배포 요청 커밋이 같은지

하나라도 다르면 배포하지 않는다. 로컬 파일을 exe.dev로 직접 복사하지 않는다.

## 서버 구성

- VM: `maesuhalkkayo.exe.xyz`
- GitHub 미러: `/home/exedev/zippick`
- 릴리스: `/home/exedev/apps/zippick/releases/<commit>`
- 현재 릴리스: `/home/exedev/apps/zippick/current`
- 서비스: `zippick.service` (사용자 systemd)
- 상태 확인: `http://127.0.0.1:8766/`

서버의 `설정.txt`, Python 가상환경, 런타임 캐시는 릴리스와 분리해 유지한다.
상태 확인에 실패하면 이전 릴리스로 자동 복구한다.
