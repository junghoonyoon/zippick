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

## 단지 카드 지도 매핑 원칙

모든 단지 카드에서 `지도`를 클릭하면, 카드에 표시된 단지와 지도에 표시되는
단지가 반드시 같아야 한다. 단지명만으로 매핑하지 말고 아래 값을 함께 사용한다.

1. `apartmentId`, `kaptCode`, `complexNo` 같은 단지 고유값
2. 지역명
3. 법정동
4. 지번
5. 단지명
6. 평형 또는 표시 면적

지역대장 리스트, 지역대장 지도 팝업, 매수 후보 카드, 통합검색 카드, 비교 카드,
지도 미리보기는 모두 같은 단지 식별 기준을 써야 한다. 지번이 없는 데이터는
`apartmentId` 같은 고유값으로 먼저 고정한다. 고유값도 없을 때만 단지명,
지역명, 법정동을 함께 비교한다.

지도 클릭, 단지 상세보기, 차트 범례의 대장 단지 클릭처럼 다른 화면으로 단지를
넘기는 모든 버튼은 가능한 한 `apartmentId`, 법정동, 지번을 함께 넘긴다. 같은
이름의 단지가 있더라도 법정동이나 지번이 다르면 같은 단지로 합치지 않는다.

## 지도 기본 조작 보장 원칙

지도 화면을 수정할 때는 새 기능보다 **지도 기본 조작**을 먼저 보장한다. 지도 위에
마커, 폴리곤, 라벨, 바텀시트, 툴바, 범례, 토글을 추가하더라도 아래 동작은 절대
깨지면 안 된다.

1. 모바일과 데스크톱에서 지도를 드래그해 이동할 수 있어야 한다.
2. 모바일과 데스크톱에서 확대·축소가 가능해야 한다.
3. 마커나 경계 라벨을 눌러도 지도 이동, 확대·축소, 바텀시트 조작이 막히면 안 된다.
4. 지도 위 폴리곤이나 면 레이어는 기본적으로 터치 이벤트를 가로채지 않게 만든다.
   꼭 눌러야 하는 기능이 필요하면 지도 클릭 위치를 계산하거나 작은 별도 버튼을
   사용한다.
5. 모바일에서는 바텀시트 드래그와 지도 드래그가 서로 충돌하지 않아야 한다.
6. 지도 위 텍스트는 `...`로 핵심 정보가 잘리지 않게 줄바꿈하거나 충분한 폭을 둔다.
7. 여러 경계가 겹치는 곳을 누를 때는 큰 참고 구역보다 사용자가 기대하는 실제
   정비사업 구역을 먼저 보여준다. 재개발·재건축·신속통합기획·모아타운·가로주택처럼
   매수 판단에 직접 영향을 주는 구역을 도시재생·청년안심주택·장기전세주택 같은 넓은
   참고 구역보다 우선한다. 같은 성격이면 더 작은 면적의 구역을 우선한다.
8. 외부 서비스와 구역명이 다를 때는 공식 공간정보를 원본으로 두고, 화면용 별칭은
   별도 보정값으로 관리한다. 지도 위의 짧은 말풍선에는 출처를 생략할 수 있지만,
   상세 화면이나 데이터 구조에는 출처와 보정 여부를 남긴다.
9. 새 지도 기능을 넣은 뒤에는 최소한 모바일 폭과 데스크톱 폭에서 지도 이동,
   확대·축소, 마커 선택, 바텀시트 열고 닫기를 확인한다.

## exe.dev deployment

Deployments to exe.dev must always use this order:

1. Commit the intended changes locally.
2. Push the commit to `origin/main` on GitHub.
3. Run `./scripts/deploy-exe-dev.sh`.
4. Confirm that the local API tests or local API smoke checks for the changed
   behavior passed before deployment.
5. After deployment, confirm that the production API is reachable and that the
   changed behavior is connected in production. Use the deployment verifier when
   available, and add a targeted production smoke check when the change touches a
   specific API route or user flow.

Never copy an uncommitted local workspace directly to exe.dev with `scp`, `rsync`,
or a similar command. The exe.dev release must be built from the exact commit
already present on GitHub.
