# 생활권 변화: 구현 및 운영 안내

> 2026-10-15 변경: 아래 내용은 이전 구현 기록입니다. 구 단위 별점은 공개 리포트에서 제거했습니다. 현재 단지별 모델과 데이터 제한은 [새 적용 안내](../living-area-implementation.md)를 따릅니다.

**현재 유료 리포트에는 법정동 전체의 건축물대장 집계, 반경 수치, 단지 수혜를 추정한 미래변화 점수를 표시하지 않는다.** 단지 위치 지도와 확인된 사업 사실을 출처·기준일과 함께 보여준다. 공식 사업 근거가 충분한 지역에는 별도의 **구 단위 생활권 변화 별점**을 표시한다. 건축물대장 집계와 내부 미래변화 산식은 검증 자료로 보존하지만 공개 응답에는 넣지 않는다.

## 사용자가 보는 변화

기존 아파트 리포트의 `생활권 변화`를 개선했다. 매수 후보·통합검색·지도 상세는 동일한 렌더러를 사용한다.

1. 지도 위 한 문장으로 **공식 사업 근거가 뒷받침하는 장기 변화 가능성**을 설명한다. 동대문구는 이문·청량리·전농·제기의 정비사업과 청량리역 GTX-B·C 계획을 함께 보여준다. 구 전체 흐름을 단지 바로 옆 개발이나 직접 수혜로 표현하지 않는다. 그 외 지역은 같은 법정동의 확인된 재개발·재건축 단계에 따라 문장을 만든다. 사업의 최신 상태나 지역 연결을 확인할 수 없으면 자료 부족을 표시한다. 새 상권·생활시설이나 가격 상승은 근거 없이 약속하지 않는다. 리포트 기준일을 반복하거나 평가 반경, 배점, 자료 충족률, 미래변화 점수를 표시하지 않는다.
2. 시범 지역의 공식 건축물대장 집계는 내부 검증용으로만 저장한다. 법정동 전체 기록을 단지 주변 현황처럼 보이게 하지 않는다.
3. 사업 6건을 먼저 보여주고 나머지는 접는다. 공식 원문, 사업 단계, 자료 기준일, 확인일을 표시한다. 계획 철도에는 사업 단계와 정차역의 공식 근거를 각각 연결한다.
4. 완료·취소·일정 미확인을 구분한다. 확인된 사업도 이 단지의 생활에 미치는 영향으로 단정하지 않는다.
5. 사업 목록이 없어도 생활권 변화에 지도 프레임을 보여준다. 이문4구역·성남 산성구역은 공식 자료의 대표 지번을 지도에 표시하되 정비구역 경계나 단지와의 실제 거리로 취급하지 않는다. 상업 이용이 금지된 OA-22712 경계 파일은 지도 API와 정비사업 영향 계산에서 제외한다. 큰 지도는 단지 위치를 확인하는 용도로 남긴다.

`ready`, `partial`, `insufficient_data`, `stale`, `error`의 내부 상태를 지원한다. 화면에는 내부 미래변화 점수나 반경 수치를 노출하지 않는다. 오류가 발생해도 기존 리포트는 계속 표시한다. 문구는 템플릿으로 생성하므로 LLM과 추가 인증키가 필요 없다. 구 단위 별점은 기존 종합점수나 가격·매수 추천 점수에 합산하지 않는다.

### 공식 계획 별점

생활권 변화 별점은 **공식 자료에서 확인한 구 전체의 개발 움직임**을 요약한다. 정비사업의 직접 거리·단지 수혜·가격 상승을 점수로 추정하지 않는다. 서로 다른 법정동에 진행 중인 재개발·재건축이 2곳 이상 있고, 공식 출처와 최근 366일 이내 확인일이 있을 때만 계산한다. 자료가 모자라면 별을 채우지 않고 `판단불가`를 표시한다.

기준은 두 동 이상의 진행 사업 2점, 사업시행인가·관리처분인가·착공에 이른 사업 1점, 같은 구의 공식 계획역 0.5점, 해당 노선 착공 확인 0.5점, 공식 사업 위치가 단지 주변임을 검증한 경우 1점이다. 따라서 현재 동대문구는 **4.0/5**, 구성남 시범 지역은 **3.0/5**다. 이 별점은 구 단위로 같은 자료를 쓰는 단지끼리 같을 수 있다. 노선 출처와 정차역 출처를 각각 확인하고, 사업 취소·완료·오래된 확인일·다른 구 자료는 제외한다.

## 변경 파일

| 파일 | 역할 |
| --- | --- |
| `pipeline/future_transformation.py` | 입력 검증, 10개 항목 산식, 점수 공개 조건, 단지 식별, SQLite 등록·이력·스냅샷 |
| `pipeline/future_transformation_spatial.py` | EPSG:5179 반경 교차, 노후 주거용 토지 유니온, 중복 제거, 단계별 가중 면적 |
| `pipeline/import_future_transformation.py` | 공식 자료를 검토한 JSON의 등록 CLI |
| `data/future_transformation_scoring.json` | 배점·기간·반경·최신성·정규화 기준과 `fts-v1` 버전 |
| `data/future_transformation_pilots.json` | 직접 확인한 성남시·동대문구 사업 참고 사실. 점수 입력은 없음 |
| `data/dongdaemun_redevelopment_projects.json` | 동대문구청에서 확인한 청량리·전농·제기동 대표 정비사업의 단계·출처 |
| `data/planned_rail_metro.json`, `pipeline/planned_rail.py` | 국토교통부의 GTX-B·C 단계와 청량리 정차역 근거를 구 단위로 연결 |
| `pipeline/search_server.py` | 단지 ID API, 기존 리포트·입지 보강 응답 연결, 후보 캐시 무효화 |
| `pipeline/budget_candidates.py` | 공통 후보 자료에 같은 분석 연결 |
| `앱화면/real-estate-search.html` | 공통 리포트 렌더러·반응형 스타일·근거 링크 |
| `tests/test_future_transformation.py` | 점수·GIS·저장·API·화면 상태 자동 테스트 |
| `pipeline/building_hub.py` | 건축HUB 표제부를 정확한 필지로 조회하고 출처와 함께 SQLite에 저장 |
| `pipeline/import_building_hub.py` | 건축HUB 한 필지 또는 법정동 전체 수집 명령. 인증키가 없으면 명확히 실패 |
| `tests/test_building_hub.py` | 건축HUB 페이지·지번·중복·저장·키 누출 방지 검사 |
| `pipeline/vworld_cadastral.py` | 공식 연속지적도 필지 경계를 1.5km 반경에서 완전 수집·검증·SQLite 보관 |
| `pipeline/import_vworld_cadastral.py` | 두 시범 단지의 기존 위치 캐시를 써서 필지 경계를 수집하는 명령 |
| `tests/test_vworld_cadastral.py` | 타일·전체 페이지·필지 중복·오류·키 비노출 검사 |
| `tests/fixtures/future_transformation_ready.json` | 가상 데이터만 담은 ready 테스트 예시. 운영 등록은 단지 ID 검사에서 거절 |
| `tests/test_frontend_apartment_search.py` | 종전 생활권 별점/물량 중심 기대값을 새 기준으로 갱신 |
| `requirements-future-transformation.txt` | 선택적 공간 계산 의존성 |

기존 작업 중이던 파일의 다른 변경은 보존했다. 기존 결제·권한·지도 조작 코드는 수정하지 않았다.

## 시범 단지와 공식 자료

기존 단지 목록의 `apartmentId`가 비어 있어 **대장 API가 이미 사용하는 `_entity_id`**를 재사용했다. 이름만으로 새로운 단지를 만들지 않았다. ID가 충돌하면 등록을 거절하고, 등록할 때 지역·법정동·지번도 대조한다.

| 기존 단지 | 기존 대장 API ID | 주소 확인 기준 |
| --- | --- | --- |
| 산성역 헤리스톤 | `484457631ccb1633` | 성남수정구 산성동 1336 |
| 이문 아이파크 자이 | `449db7d556b8ba86` | 동대문구 이문동 149-8 |

- 성남시: [2026-02-24 상대원3구역 사업시행협약 발표](https://snvision.seongnam.go.kr/22380)와 [2026-08-31 생활권 재개발 5개 구역 지정 발표](https://snvision.seongnam.go.kr/sub_read.html?uid=23299)를 연결했다. 상대원3과 상대원1·3은 별도 사업으로 보존한다. 원문·사진을 재배포하지 않는다.
- 동대문구: [이문4 관리처분계획인가 고시](https://www.ddm.go.kr/www/selectBbsNttView.do?bbsNo=53&integrDeptCode=&key=239&nttNo=148911&pageIndex=8&searchCnd=all&searchCtgry=&searchKrwd=), [2026년 변경안 공람](https://www.ddm.go.kr/www/selectEminwonWebView.do?key=3291&notAncmtMgtNo=22316&pageIndex=31&pageUnit=10&searchCnd=notAncmtSj&searchNotAncmtSeCode=01%2C02%2C04%2C05%2C06%2C07), [휘경3 준공인가 현황](https://www.ddm.go.kr/www/contents.do?key=967)을 연결했다. 휘경3은 2025-06-26 준공인가로 정정했다. 변경안의 확정 여부와 이문4 준공 예정일은 확인하지 못했다.
- 동대문구 전체 흐름: [청량리제8구역](https://www.ddm.go.kr/www/contents.do?key=932), [전농제9구역](https://www.ddm.go.kr/www/contents.do?key=927), [제기제4구역](https://www.ddm.go.kr/www/contents.do?key=930)의 단계와 법정동을 별도 근거 목록으로 연결했다. [국토교통부 GTX-B 업무계획](https://www.molit.go.kr/2026plan/sub5_public.html), [GTX-C 착공 발표](https://www.molit.go.kr/USR/NEWS/dtl.jsp?id=95092420), [청량리역 노선 자료](https://www.molit.go.kr/2024plan_traffic/news/bodo_2.pdf)를 함께 사용한다. 대표 사업을 선별한 것으로 동대문구 모든 정비사업의 전수 목록은 아니다. 검색 카드에서 리포트를 열어도 이 근거가 빠지지 않도록 상세 API의 생활권·계획 철도 자료를 전달한다.
- 기존 이문·휘경 시범 자료의 확인일은 2026-10-12, 새 구 단위 사업·철도 자료의 확인일은 2026-10-14다. 오래된 발표를 최신 사업 상태로 오해하지 않도록 기준일과 확인일을 함께 표시한다.
- 위 사업은 좌표/경계를 검증하지 못했으므로 **같은 지역 참고**로만 보여준다. 반경 안 사업이나 직접 수혜로 취급하지 않는다. 시범 단지에 반경 기반 미래변화 점수는 부여하지 않았다. 구 단위 공식 계획 별점은 별도로 계산한다.
- 공식 조사 시작점: [서울 정비사업 정보몽땅](https://cleanup.seoul.go.kr/), [성남 개발톡톡](https://dept.seongnam.go.kr/talktalk/), [건축HUB](https://www.data.go.kr/data/15134735/openapi.do). 사이트를 대량 수집하지 않는다.
- [공식 자료 확보 기록](source-acquisition-2026-10-12.md)에 확인한 사실, 정정 근거, 서울시 공간자료의 이용 제한, 남은 자료를 정리했다.

## 실행 및 등록

```bash
# 공간 계산을 사용할 때만 설치. 없으면 해당 항목은 자료 부족 처리.
.venv/bin/python -m pip install -r requirements-future-transformation.txt

# 공식 시범 사실을 SQLite에 등록. 같은 파일을 반복 등록해도 중복되지 않음.
PYTHONPATH=pipeline .venv/bin/python pipeline/import_future_transformation.py --pilots

# 검토한 새 JSON 등록
PYTHONPATH=pipeline .venv/bin/python pipeline/import_future_transformation.py /path/to/reviewed.json

# 건축HUB 활용신청 승인 후, 정확한 한 필지의 표제부를 별도 저장
# 설정.txt에 건축HUB키=... 또는 환경변수 BUILDING_HUB_API_KEY를 사용한다.
# 예시는 형식 설명용이며 실제 법정동·지번 코드를 확인하고 실행한다.
PYTHONPATH=pipeline .venv/bin/python pipeline/import_building_hub.py 11230 11000 0028 0004

# 법정동 전체 조회(시범 코드: 산성동 41131/10500, 이문동 11230/11000, 휘경동 11230/10900)
PYTHONPATH=pipeline .venv/bin/python pipeline/import_building_hub.py 41131 10500 --dong

# 브이월드의 상업적 이용 허락과 API 데이터 저장 승낙을 받은 뒤에만 실행한다.
# 인증키 발급만으로 두 허락을 받은 것은 아니다. 아래 변수에는 실제 허락 문서의 확인 번호를 넣는다.
# 설정.txt에 브이월드키=... 또는 환경변수 VWORLD_API_KEY를 사용한다.
PYTHONPATH=pipeline .venv/bin/python pipeline/import_vworld_cadastral.py all \
  --commercial-approval "$VWORLD_COMMERCIAL_APPROVAL_REF" \
  --storage-approval "$VWORLD_STORAGE_APPROVAL_REF"

# 검증된 입력이 모인 뒤 점수 공개를 켜는 방법. 기본값은 0(OFF).
ZIPPICK_FUTURE_TRANSFORMATION_SCORES=1 ./부동산검색실행.command
```

등록 명령은 기존 단지 ID와 시범 지역을 검증한다. 시범 JSON을 별도로 등록하지 않아도 서버는 버전 관리된 시범 사실을 읽을 수 있다. 외부 자료를 화면 요청마다 가져오지 않는다.

건축HUB 수집기는 페이지 전체와 건물 ID·법정동 또는 지번을 확인한 뒤 `pipeline/cache/building_hub.sqlite3`에 조회 시각, 공식 출처, 원본 속성을 저장한다. 인증키는 저장하지 않는다. 2026-10-12 승인된 개발계정으로 산성동 385건, 이문동 3,457건, 휘경동 2,309건을 조회·저장했다. 이는 **각 법정동의 건물 정보**이며 단지 반경 1.5km의 토지 면적이 아니다. 반경 기반 미래변화 점수에 필요한 **토지 경계와 면적**이 없으므로 이 자료만으로 노후 주거지 전환 점수를 만들거나 공개하지 않는다.

연속지적도 수집기는 [브이월드 2D 데이터 API](https://www.vworld.kr/dev/v4dv_2ddataguide2_s002.do?svcIde=cadastral)의 `LP_PA_CBND_BUBUN`을 사용한다. 1.5km 원을 1km 격자로 나눠 2km² 요청 제한을 지키고, 각 격자의 모든 페이지를 받아 필지번호로 중복을 없앤다. 페이지 누락·필지 경계 충돌·API 오류가 있으면 해당 단지의 결과를 저장하지 않는다. 수집 결과는 `pipeline/cache/vworld_cadastral.sqlite3`에 보관하며 인증키와 호출 URL은 남기지 않는다. 수집 후 필지번호와 기존 건축HUB 표제부를 대조해 **자료가 빠진 법정동 코드**를 출력한다. **이것은 필지 경계 원본일 뿐** 건물 용도·사용승인일이나 정비구역·준공 일정이 아니다. 그래서 이 자료를 수집해도 점수는 자동으로 채워지지 않는다. 브이월드 키는 건축HUB에 사용한 공공데이터포털 키와 다르다.

브이월드 인증키 발급 화면의 오픈API 약관은 제10조 ⑧에서 **상업적 이용의 별도 허락**, 제12조 ④에서 **API 데이터 저장의 사전 승낙**을 요구한다. 집픽의 필지 수집 명령은 두 허락 확인 번호가 모두 없으면 API를 호출하지 않는다. 허락 전에는 필지 면적과 반경 기반 미래변화 점수를 계속 자료 부족으로 표시한다. 별도의 공식 계획 별점은 이 API를 사용하지 않는다. 두 확인 번호 입력은 허락 사실을 운영자가 확인하는 절차이며, 코드가 허락을 대신 발급하거나 검증하지 않는다.

실제 API:

```text
GET /api/apartments/484457631ccb1633/future-transformation
GET /api/apartments/449db7d556b8ba86/future-transformation
```

기존 `/api/apartment-report`와 후보 응답의 `futureTransformation`에도 같은 사실형 구조가 들어간다. 공개 응답은 반경·거리·점수·배점·자료 충족률을 제외한다. 내부 산식과 스냅샷은 보존한다. 존재하지 않거나 주소 충돌이 있는 ID는 전용 API에서 404다. 사용자 입력으로 점수를 재계산하는 공개 쓰기 API는 없다.

점수 계산 플래그가 OFF여도 현황 UI와 출처는 제공한다. ON으로 바꿔 내부 점수가 계산되더라도 현재 리포트 화면에는 표시하지 않는다. 산식의 좌표·범위·공식 근거·최신성 검증은 향후 작업을 위해 보존한다.

## 데이터 계약과 저장

`schemaVersion: 1`, `scoringVersion: fts-v1`, `apartmentId`, `identity`, `asOfDate`, `radiusMeters`, `horizonYears`, `sources`, `projects`, `measurements`가 기본 구조다. 실측값을 넣으면 `center`도 필요하다. 완성된 가상 구조는 테스트 fixture에서 확인할 수 있다.

- `sources`: `id`, `publisher`, `documentId`, `documentTitle`, 공식 HTTPS `url`, `publishedAt`, `observedAt`, `verifiedAt`, `verificationStatus: verified`, `licenseStatus: reviewed`. 날짜는 `YYYY-MM-DD`다. 평가일 이후 알게 된 자료는 거절한다. `reviewed`는 등록자가 원문과 재사용 조건을 검토했다는 선언이며 자동 사실 검증을 뜻하지 않는다.
- `projects`: 고유 ID, 이름, 유형, 공식 단계, 완료 예정일 또는 null, 좌표 또는 null, 출처 ID. 원문 표현을 보존하는 `stageLabel`을 지원한다. 준공/취소를 미래 변화에 더하지 않는다.
- `factCorrections`: 이전에 같은 날짜로 저장한 사업 사실을 공식 근거로 바로잡을 때 사업 ID, 정정 이유, 새로운 출처 ID를 보존한다. 이전 revision과 event는 남는다.
- `measurements`: 항목 키별 `inputs`, `method`, `explanation`, `evidenceIds`, `verificationStatus`. 미래 개선 항목은 공식 `effectiveDate`가 필수이며 5년 범위 밖이면 계산하지 않는다. 숫자만 넣은 완성 점수나 임의 비율을 받지 않는다.
- 공간 입력의 필지·사업에는 각각 출처 ID가 필요하다. 필지 도형은 `geometryBasis: residential_land`여야 한다. 토지 도형과 건축물 연면적을 섞을 수 없다.

기존 파일 기반 캐시 구조에 맞춰 `config.CACHE_DIR/future_transformation.sqlite3`를 사용한다. 첫 등록 때 비파괴적으로 테이블을 만든다. 별도 ORM이나 PostGIS 마이그레이션은 없다.

- `revisions`: 단지별 원본 JSON 전체와 내용 해시, 등록 시각. 프로젝트와 출처의 원본 사실을 보존한다.
- `project_events`: 단계·예정일·출처가 포함된 사업 상태 이력. 중복 이벤트는 저장하지 않는다.
- `snapshots`: 분석 결과 전체, 단지 ID, 스냅샷 ID. 같은 입력은 같은 결과와 최초 계산 시각으로 재생한다.

이전 날짜 자료가 최신 자료를 덮어쓰지 않는다. 동일하거나 더 오래된 원문으로 사업 단계·완료일·세대수가 충돌하면 등록을 거절하고 검토를 요구한다. 별도 관리자 검토 화면은 아직 없다. 실패한 등록은 원본 JSON을 수정하기 전까지 재시도하지 않는다.

스냅샷 키에는 단지 ID, 날짜, 점수 설정, 데이터 버전, 반경, 좌표, 플래그가 반영된다. 후보 캐시에도 원천 자료 변경을 반영한다. 스냅샷 저장만으로 후보 캐시를 무효화하지 않는다. 오류는 로깅하고 해당 항목만 error로 반환한다.

## 산식과 제한

지역 배점은 30+15+15+15+15+10=100, 단지 배점은 35+25+20+20=100이다. 최종 점수는 지역 60% + 단지 40%를 반올림한다. 6개+4개 모두 검증되어야 공개한다. 자료 충족률은 동일한 최종 배점 비중으로 계산하며 빈 항목을 100점으로 재환산하지 않는다.

| 항목 | 검증된 입력과 정규화 |
| --- | --- |
| 노후 주거지 전환 | 30년 이상 주거용 토지의 반경 내 유니온이 분모. 공식 일정이 5년 안인 미완료 사업과 교차한 토지에 단계 계수를 적용. 중복 면적은 높은 단계부터 한 번만 적용. 가중 전환 비율 50%에서 30점 |
| 새 주거지 연결 | 실제 보행망의 연결 길이 증가 / 조사한 연결망 길이 |
| 교통 개선 | 검증된 경로의 이동시간 감소 / 20분 |
| 생활시설 개선 | 접근 가능한 시설 증가 / 확인한 새 시설 수. 공식 운영 일정 확인 필수 |
| 사업 진행 | 공식 단계 계수의 사업 토지 면적 가중 평균 / 0.9. 반경과 공식 일정을 대조. 검증된 전수 조사에서 사업이 없을 때만 0점 가능 |
| 수요·공급 | 5년 입주량과 관측 연간 흡수량×5의 차이를 기존 가구수로 나눔. 초과 비율 10% 및 거래·임대료 하락을 부담으로 반영 |
| 단지 접근 | 1 − 새 시설까지 거리 / 1,500m. 직선거리 대체 시 화면에 명시하고 신뢰도 낮춤 |
| 단지 연결 | 장벽을 검토한 연결 경로 수 / 조사 경로 수 |
| 생활 동선 | 검증된 도보 시간 감소 / 15분 |
| 공사 등 부담 | 1 − 검토된 소음·동선 단절·입주 집중 노출(각 0~1)의 평균 |

각 비율은 0~1로 제한한다. 이 기준은 **초기 참고 산식**이다. 통계적으로 검증된 성공률·가격 상승률이 아니다. 현재 수준과 앞으로의 추가 변화는 분리한다. 토지/보행망/수요 데이터가 자동으로 확보된 것처럼 표시하지 않는다.

Shapely·PyProj는 WGS84 도형을 EPSG:5179로 변환한다. 반경 바깥·겹치는 필지·겹치는 사업을 처리한다. 잘못된 도형·빈 분모·미확인 일정은 계산하지 않는다. 작은 시범 범위의 배치/등록에 적합하다. 전국 규모에는 공간 인덱스나 PostGIS와 사전 계산이 필요하다.

## 검증

집중 검사:

```bash
PYTHONPATH=pipeline .venv/bin/python -m pytest \
  tests/test_future_transformation.py tests/test_paid_report.py \
  tests/test_report_store.py tests/test_redevelopment_zones_api.py \
  tests/test_development_evidence.py tests/test_supply_forecast.py -q
```

현재 결과: **71개 통과, 추가 하위 검사 53개 통과**. 생활권 UI 연결 검사도 별도로 3개 통과했다. 가중치·0/null·최댓값·67/78점 예시·미래 시점 유입 차단·오래됨·공간 교차/중복·준공/취소·일정·위치 누락·저장 이력·근거가 남는 상태 정정·충돌 거절·캐시·공식 링크·API 404를 확인했다.

전체 검사(`PYTHONPATH=pipeline .venv/bin/python -m pytest -q --tb=no`)에서는 **749개 통과, 21개 실패, 추가 하위 검사 151개 통과**했다. 새 기능 관련 검사는 통과했다. 남은 실패는 후보 가격/식별 관련 3개와 기존 화면 문구·구조 기대값 관련 18개다. 전체 테스트가 통과했다고 볼 수 없으며, 관련 없는 작업 중 변경을 덮어써 해결하지 않았다. 실패 목록은 `regression-results.txt`에 보관한다. 후보 관련 3개를 개별 재실행했을 때 식별 검사는 통과했고, 가격 관련 2개는 신규 분석 호출을 비활성화해도 실패했다. 전체 검사 후 추가한 일정·충돌·GIS 일치 검사 3개도 위 집중 검사에 포함된다.

상태별 화면은 아래 명령으로 생성한다. 실제 사업 자료와 가상 테스트임을 화면에서 구분한다.

```bash
.venv/bin/python scripts/preview-future-transformation.py
.venv/bin/python -m http.server 8891 --bind 127.0.0.1 --directory outputs/future-transformation
# http://127.0.0.1:8891/review.html
```

직접 확인:

- 실제 로컬 검색 → 산성역 헤리스톤 → 집픽 분석 → 생활권 변화 연결.
- 실제 단지 2개의 전용 HTTP API와 공식 원문 링크.
- 390px 모바일 및 1280px 데스크톱에서 동일 렌더러 확인. 줄바꿈·펼치기·가로 넘침 없음.
- ready 가상 fixture와 partial/insufficient/stale/error 표시. 테스트 화면은 운영 경로와 분리.
- 인라인 JavaScript 구문 검사 및 `git diff --check` 통과.
- 실제 시범 자료 등록을 두 번 실행해 같은 revision이 유지됨.

## 남은 자료와 후속 작업

1. 건축HUB 표제부는 확보했다. 브이월드 별도 키로 필지 경계를 수집한 뒤 필지번호(PNU)로 건물 용도·사용승인일을 대조하고, 반경 안 모든 법정동의 건물 자료를 확보해야 한다.
2. 사업별 최신 공식 고시·경계·완료 예정일, 실제 보행망·개통 후 경로, 시설 운영일, 지역 가구수·흡수량 자료가 필요하다. 자료를 사람이 검증해 등록하는 경로는 동작한다.
3. 두 시범 단지의 기존 카카오 위치 캐시에 좌표가 있다. 필지·건물·사업 경계의 정확한 연결을 검증하기 전에는 반경/직접 수혜 점수를 공개하지 않는다.
4. 정기 자동 수집, 관리자 오류 검토 화면, 역사 자료를 이용한 검증, 반경·기간 민감도 연구와 전국 확대는 후속 작업이다.
5. 소음·단절·입주 집중의 0~1 입력 기준과 수요·공급 정규화는 실제 자료와 전문가 검토로 보정해야 한다. 현재 실제 단지 점수 공개를 기본 OFF로 둔 이유다.

**운영 서버에는 배포하지 않았다.** 기존 작업 내용이 섞인 상태로 커밋·푸시하지 않았다. 점수 공개 기본 OFF이며, 공식 자료가 충분해진 뒤 플래그를 켜도 공개 조건을 다시 통과해야 한다.
