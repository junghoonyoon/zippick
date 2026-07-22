# Repository instructions

## 작업 전 필수 콘텐츠 구성 원칙

모든 작업을 시작하기 전에, 사용자가 보게 될 글과 화면이 초등학생도 쉽게
이해할 수 있도록 구성되어 있는지 먼저 생각한다. 구현을 바로 시작하지 말고
아래 항목을 작업 계획과 결과물에 반드시 반영한다.

1. 글의 목적과 가장 중요한 내용을 먼저 파악한다.
2. 제목, 소제목, 본문, 목록의 순서를 명확하게 나누고 읽기 쉬운 정렬을 사용한다.
3. 중요한 문장은 눈에 잘 띄는 위치에 짧고 분명하게 작성한다.
4. 핵심 단어는 **볼드체**로 강조하고, 꼭 기억해야 할 내용만 형광펜 효과를 사용한다.
5. 볼드체와 형광펜을 지나치게 사용하지 않는다. 무엇이 중요한지 한눈에 구분될
   정도로만 사용한다.
6. 어려운 단어, 전문 용어, 길고 복잡한 문장을 피한다. 꼭 필요한 용어는 쉬운
   말로 바로 설명한다.
7. 한 문장에는 가급적 하나의 내용만 담고, 긴 문단은 짧은 문단이나 목록으로
   나눈다.
8. 작업을 마친 뒤에는 정렬, 강조, 글의 순서, 표현의 난이도를 다시 확인하여
   초등학생이 처음 읽어도 핵심 내용을 이해할 수 있는지 검토한다.

이 원칙은 화면 문구, 설명문, 안내문, 콘텐츠 페이지 등 사용자가 읽는 모든 글에
항상 적용한다.

## exe.dev deployment

Deployments to exe.dev must always use this order:

1. Commit the intended changes locally.
2. Push the commit to `origin/main` on GitHub.
3. Run `./scripts/deploy-exe-dev.sh`.

Never copy an uncommitted local workspace directly to exe.dev with `scp`, `rsync`,
or a similar command. The exe.dev release must be built from the exact commit
already present on GitHub.
