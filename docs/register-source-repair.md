# 건축물대장 연결과 미확인 자료 보완

단지 고유번호와 주소를 먼저 확인한다. 이름이 비슷하다는 이유로 다른 단지나
다른 차수의 자료를 연결하지 않는다.

## 행정구역 변경

`data/building_register_code_changes.json`은 행정안전부가 공개한 화성·인천의
변경 전·후 법정동 코드와 시행일을 보존한다. 단지의 원래 식별값은 유지하고
공식적으로 같은 주소인 코드로만 건축물대장을 조회한다. 지번은 바꾸지 않는다.
하나의 법정동이 여러 구역으로 나뉜 경우에는 자동 연결하지 않는다.
다만 공식 기본정보의 고유번호·원래 필지·세대수와 새 구역 총괄대장의
지번·단지명·전체 세대수가 한 건으로 맞으면 그 단지만 `parcelChanges`에
기록한다. 다른 지번이나 차수에 같은 연결을 확대하지 않는다.

블록 주소나 잘못 연결된 옛 지번을 실제 지번으로 고친 단지는 `data/apartment_identity_corrections.json`에
원래 단지번호·지역·법정동·세대수와 공식 기본정보 원문을 함께 남긴다.
공식 주소의 지번과 필지고유번호가 서로 다른 경우는 수정하지 않는다.
이 보정은 공통 검색 원본에 적용해 카드·지도·리포트가 같은 단지를 사용한다.

공식 단지번호가 아직 없는 경우에도 이름·주소·전체 세대수가 한 총괄대장과
일치하면 `apartment_register_identity_links.csv`로 내부 식별자를 연결한다.
`zippick:register:` 접두사는 정부 단지번호와 구분한다. 원문 대장과 해시는
동명의 JSON에 보존한다. 오래된 다른 지번의 분양권 기록은 합치지 않는다.

## 이름 없는 표제부

원본 표제부에 건물 이름이 비어 있으면 공식 기본정보의 고유번호·필지번호·
단지명·세대수를 추가로 대조한다. 표제부 한 건이 전체 세대수를 포함하고,
부속 필지·부속 건물이 명시적으로 0이며, 비율과 면적 계산이 맞아야 한다.
기본정보의 일치만으로 부속 필지 범위나 비율의 충돌을 해결하지 않는다.

## 운영 수집

수집 코드를 커밋하고 GitHub main에 올린 뒤 정식 배포 스크립트로 배포한다.
그 배포의 디렉터리에서만 다음 명령을 실행한다. 로컬 복제본은 수집하지 않는다.

```sh
python pipeline/import_building_register_bulk.py /tmp/official-recap.zip --as-of 2026-09
python pipeline/repair_register_sources.py migrate-identities --apply
python pipeline/import_building_register_bulk.py /tmp/official-title.zip --record-type title --as-of 2026-09
python pipeline/repair_register_sources.py official-basic --source /tmp/official-basic.csv --source-date 2026-08-31 --apply
python pipeline/repair_register_sources.py title-gaps --limit 1000 --apply
python pipeline/repair_register_sources.py planning-gaps --limit 1000 --apply
# 미리 검증한 공개 페이지를 사용할 때는 원문·해시·주소를 다시 대조한다.
python pipeline/repair_register_sources.py planning-pages --source /tmp/planning-pages/manifest.json --apply
```

`repair_register_sources.py`에서 `--apply`를 빼면 대상 건수만 확인한다.
API 이용 권한이나 할당량 오류가 나오면 수집을 중단한다. 기존 정상 원본은
실패·빈 응답으로 덮어쓰지 않는다. 오래된 식별값은 이력으로 보존한다.
원본의 기준 월과 내려받은 날짜를 구분한다. 월간 자료를 임의의 말일 자료로
표시하지 않는다.

## 계속 보류하는 경우

공식 원본의 누락·0·상충 값, 다른 범위의 세대수, 부속 필지의 전체 범위,
확인되지 않은 동의율·공사비는 추정으로 채우지 않는다. 연한이 안 된 경우와
자료가 없는 경우를 검사 결과에서 구분한다.
