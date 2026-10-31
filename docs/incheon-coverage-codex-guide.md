# 인천 데이터 커버리지 확장 작업 지침서

> 대상: Codex
> 작성일: 2026-10-26
> 목표: **인천 단지 리포트를 서울·경기와 같은 수준으로 만든다.**
> 가격 분석은 이미 되고 있다. 이 문서는 아직 인천이 빠진 학군, 지역 흐름,
> 재개발, 생활권 같은 분석을 채우는 작업을 다룬다.

---

## 0. 먼저 읽을 것

### 0-1. 지켜야 할 저장소 규칙
- 작업 전에 루트의 `AGENTS.md`를 읽는다. 특히 아래 규칙은 이번 작업에도 그대로 적용된다.
  - **화면 문구는 초등학생도 이해할 수 있게** 쓴다.
  - **판단 제목은 결론형**으로 쓴다.
  - **단지는 고유값으로 식별**한다(`apartmentId`, 법정동, 지번).
- 데이터 출처와 이용 허락은 `docs/data-licenses.md`를 따른다. 허락이 확인되지 않은 자료는 수집하거나 저장하지 않는다.
- **자료가 없으면 지어내지 않는다.** 인천 자료를 서울·경기 자료로 대신 채우지 않는다. 확인되지 않은 값은 `자료가 부족해 판단할 수 없어요` 같은 상태로 남긴다.

### 0-2. 작업 방식
- 아래 작업(T1~T9)은 **작업마다 커밋을 하나씩** 만든다. 커밋 메시지에 작업 번호를 붙인다(예: `T2: Add Incheon routes to market flow`).
- 작업 트리에 다른 사람이 아직 커밋하지 않은 변경이 있을 수 있다(특히 `앱화면/real-estate-search.html`). **자기 작업과 관계없는 변경은 커밋에 넣지 않는다.**
- 테스트는 프로젝트 가상환경으로 돌린다. 시스템 `python3`에는 `requests`가 없어 일부 테스트를 불러오지 못한다.

  ```bash
  .venv/bin/python -m unittest tests.<테스트_모듈>
  ```

- 화면 확인용 서버:

  ```bash
  cd pipeline && REAL_ESTATE_PORT=8767 BUDGET_PREWARM_ENABLED=0 ../.venv/bin/python search_server.py
  ```

### 0-3. 확인용 인천 단지
작업마다 아래 단지로 실제 API와 화면을 확인한다.

| 지역 | 단지 | apartment_id | 법정동 / 지번 |
|---|---|---|---|
| 연수구 (송도) | 송도 더샵 퍼스트파크 F15BL | `28185120358884` | 송도동 / 102 |
| 서구 (청라·검단) | 직접 검색해서 1곳 고르기 | `/api/apartment-suggest`로 확인 | |
| 부평구 | 직접 검색해서 1곳 고르기 | `/api/apartment-suggest`로 확인 | |
| 미추홀구 | 직접 검색해서 1곳 고르기 | `/api/apartment-suggest`로 확인 | |

```bash
curl -sS "http://127.0.0.1:8767/api/apartment-report?name=송도%20더샵%20퍼스트파크%20F15BL&region=연수구&households=872&area_label=전용%2084㎡&legal_dong=송도동&jibun=102&apartment_id=28185120358884"
```

---

## 1. 현재 상태 요약 (2026-10-26 확인)

### 이미 인천도 되는 것 (손대지 않아도 됨)
| 기능 | 근거 |
|---|---|
| 단지 검색 | `data/인천광역시_아파트_단지_목록_한국부동산원_20250918.csv` (2,236개 단지, `pipeline/build_incheon_complex_list.py`로 생성) |
| 실거래·예상 매수가·집픽 밴드 | 국토부 실거래는 전국 법정동 코드(인천 `28xxx`)로 받아 온다. 송도 단지로 84.9㎡, 38건, 적정가 판정 `ready` 확인 |
| 한국부동산원 지역 지수 | `pipeline/regional_price_index.py`가 시·도 전체를 다룬다 |
| 최근 시장 신호, 입지 점수(교통) | 송도 단지에서 각각 52점으로 정상 계산 |
| 철도 계획 | `pipeline/planned_rail.py`가 인천을 포함한다 |
| 구매력 지역 | `pipeline/purchase_capacity.py`의 `incheon`(비규제) |
| 인천 구 이름 처리 | `pipeline/budget_candidates.py`의 `INCHEON_DISTRICTS`, `인천중구`처럼 접두사를 붙이는 규칙 |

### 인천이 빠진 것 (이 문서의 작업 대상)
| 기능 | 빠진 이유 | 작업 |
|---|---|---|
| 학군·교육 환경 | 허용 지역이 서울·경기만 | **T1** |
| 지역 흐름 (지금 볼 곳) | 비교 경로를 사람이 정한 목록에 인천이 없음 | **T2** |
| 서버 시작 시 실거래 미리 받기 | 기본값이 `서울특별시,경기도` | **T3** |
| 분양권·입주예정 보강 | 생성 스크립트가 서울·경기만 거름 | **T4** |
| 생활권 지하철 계획 목록 | 불러오는 스크립트가 서울·경기만 거름 | **T5** |
| 재개발·정비구역 지도와 영향 점수 | 원본이 서울시 공간정보뿐 | **T6** |
| 생활권 변화·미래 변화 점수 | 사람이 검토한 시범 자료만 있음 | **T7** |
| 네이버 단지 연결, 전세가율 미리 만든 자료 | 인천 단지가 거의 없음 | **T8** |
| 화면 안내 문구 | `서울·경기`라고 고정돼 있음 | **T9** |

---

## 2. 1단계: 설정만 바꾸면 되는 작업

### T1. 학군·교육 환경을 인천까지 계산한다

**현재**
- `pipeline/education_environment.py:21`

  ```python
  SUPPORTED_REGIONS = {"서울특별시", "경기도"}
  ```

- 인천 단지는 `education_environment_for_entity()`에서 바로 `{"status": "unsupported_region"}`을 돌려준다(361줄 근처).
- `pipeline/location_scores.py:360`은 이 상태를 받아 `서울·경기 밖이라 교육 접근성 점수는 제공하지 않아요`라고 쓴다.
- 서울·경기도 공식 학구도를 쓰지 않는다. 데이터 파일 `data/education_environment_seoul_gyeonggi.json`을 보면 `zones` 0개, `schools` 0개, `source: kakao-local-v2`다. **카카오 장소 검색으로 주변 초·중학교와 학원 수를 계산하고**, 단지별로 `records`에 저장한다(현재 605건).

**할 일**
1. `SUPPORTED_REGIONS`에 `"인천광역시"`를 넣는다.
2. 모듈 맨 위 설명과 `location_scores.py:360`의 안내 문구에서 `서울·경기`를 `서울·경기·인천`으로 고친다.
3. 데이터 파일 이름(`education_environment_seoul_gyeonggi.json`)은 **바꾸지 않는다.** 다른 코드와 배포가 이 경로를 쓴다. 대신 상수 근처에 "파일 이름과 달리 인천도 담는다"는 주석을 단다.
4. 인천 단지 하나로 처음 조회할 때 카카오 검색이 일어나 `records`에 저장되는지 확인한다. 카카오 키가 없으면 어떻게 표시되는지도 확인한다.
5. 저장된 레코드의 `source` 값이 `한국교육시설안전원 학구도 ...`로 나오는 경우가 있다. 실제 기준(`basis: nearby_school_access`)과 맞는지 확인한다. 화면에 **"배정 학교가 아니라 주변 학교 접근성 기준"**이라고 나오는지도 확인한다. 틀리면 이슈로 남기고, 이번 작업에서 출처를 지어내지 않는다.

**완료 기준**
- 송도 단지 리포트에서 `educationEnvironment.status`가 `ok`이고 점수가 나온다.
- 서울·경기 단지의 기존 점수는 바뀌지 않는다.

**테스트**
- `tests/test_education_environment.py`에 인천 단지가 `unsupported_region`이 아닌지 확인하는 사례를 추가한다. 카카오 호출은 모킹한다.
- `.venv/bin/python -m unittest tests.test_education_environment tests.test_apartment_affordability`

---

### T2. 지역 흐름(지금 볼 곳)에 인천 경로를 넣는다

**현재**
- `pipeline/market_flow.py:58`의 `FLOW_ROUTES`는 사람이 정한 3개 지역짜리 경로 8개다. 지역마다 국토부 법정동 코드를 적는다.
- `pipeline/market_flow.py:126`의 `FLOW_ADJACENT_REGION_PAIRS`는 서로 붙어 있는 지역 쌍이다.
- 실거래는 전국 단위로 받으므로 **새로 수집할 자료는 없다.** 과거 10년 순서 검증(`HISTORY_MONTHS = 120`)도 자동으로 된다.

**할 일**
1. 인천 경로를 2~3개 추가한다. 아래는 예시다. **실제로 붙어 있는 지역인지 지도로 확인한 뒤** 정한다.

   | id (예) | 경로 (예) | 인천 법정동 코드 |
   |---|---|---|
   | `bucheon-bupyeong` | 구로구 → 부천시 → 부평구 → 계양구 | 부평구 `28237`, 계양구 `28245` |
   | `gimpo-incheon-west` | 강서구 → 김포시 → 서구(청라·검단) | 서구 `28260` |
   | `songdo-namdong` | 연수구 → 남동구 → 미추홀구 | 연수구 `28185`, 남동구 `28200`, 미추홀구 `28177` |

   - 경로는 지금처럼 **노드 3개**를 기본으로 한다. 4개가 필요하면 화면이 깨지지 않는지 먼저 확인한다.
   - 좌표(위도·경도)는 각 구청 위치처럼 근거가 분명한 값을 쓴다.
   - 노드 이름은 화면에 그대로 나온다. 서울 `중구`·`동구`·`서구`와 헷갈리지 않게 `인천 서구`처럼 쓰는 것을 검토한다. 이름을 바꾸면 `FLOW_ADJACENT_REGION_PAIRS`도 같은 이름을 써야 한다.
   - 색(`color`)은 기존 경로와 겹치지 않게 고른다.
2. 새 노드끼리, 그리고 기존 노드와 실제로 붙어 있는 쌍을 `FLOW_ADJACENT_REGION_PAIRS`에 추가한다(예: `("부천시", "부평구")`, `("김포시", "서구")`).
3. `MIN_WINDOW_DEALS = 8` 때문에 거래가 적은 구는 분석에서 빠질 수 있다. **강화군·옹진군·동구·중구는 넣지 않는 것**을 기본으로 한다.
4. 스냅샷 구조를 바꾸면 `SNAPSHOT_SCHEMA_VERSION`을 올린다. 경로만 추가했다면 올리지 않아도 되는지 캐시 코드를 읽고 판단한다.

**완료 기준**
- `/api/market-flow` 응답에 인천 지역이 나오고, 지역 흐름 지도에 인천 노드가 그려진다.
- 기존 서울·경기 경로의 결과는 바뀌지 않는다.

**테스트**
- `.venv/bin/python -m unittest tests.test_market_flow`
- 인천 경로가 들어 있는지, 인접 쌍의 이름이 모두 `FLOW_ROUTES`에 있는지 확인하는 테스트를 추가한다.

---

### T3. 서버 시작 시 인천 실거래도 미리 받아 둔다

**현재**
- `pipeline/config.py:202`

  ```python
  BUDGET_PREWARM_REGIONS = tuple(... os.environ.get("BUDGET_PREWARM_REGIONS", "서울특별시,경기도") ...)
  ```

- 그래서 인천 단지는 처음 검색할 때 실거래를 그때 받아야 해서 느릴 수 있다.

**할 일**
1. 기본값을 `"서울특별시,경기도,인천광역시"`로 바꾸고 바로 위 주석도 고친다.
2. 미리 받기 코드(`pipeline/search_server.py:3126` 근처)는 단지 목록의 `시도`·`자치구`·`시군구`·`일반구` 열이 설정값과 맞는 단지의 법정동 코드를 모은다. 인천 단지 목록 CSV의 `시도` 열이 `인천광역시`로 들어 있어서, 인천 구·군 코드 10개(`28110` 중구, `28140` 동구, `28177` 미추홀구, `28185` 연수구, `28200` 남동구, `28237` 부평구, `28245` 계양구, `28260` 서구, `28710` 강화군, `28720` 옹진군)가 모두 모이는지 확인한다.
3. 배포 환경변수(`docs/exe-dev-deployment.md`, `deploy/`)에 `BUDGET_PREWARM_REGIONS`를 따로 지정한 곳이 있는지 확인하고, 있으면 같이 고친다.
4. 국토부 API 호출량이 얼마나 늘어나는지 로그로 확인해서 결과에 적는다.

**완료 기준**
- 서버를 시작하고 미리 받기가 끝난 뒤, 인천 단지를 처음 검색해도 저장된 실거래로 바로 계산된다.

---

### T4. 분양권·입주예정 보강 자료에 인천을 넣는다

**현재**
- `pipeline/build_presale_supplement.py:289`

  ```python
  if len(cells) < 4 or cells[3] not in {"서울특별시", "경기도"}:
  ```

- 모듈 설명(1줄)과 252줄 설명도 `서울·경기`로 돼 있다.
- 참고: `pipeline/applyhome_supply.py`는 전국 입주 예정 물량을 오픈API로 받는 별도 경로다. 이미 `인천광역시 → 인천` 변환이 있다.

**할 일**
1. 필터에 `"인천광역시"`를 넣고 설명 문구를 고친다.
2. 스크립트를 실행해서 `data/분양권_입주예정_아파트_보강.csv`를 다시 만든다. 인천 행이 추가됐는지 확인한다(현재 인천 1건).
3. 인천 행의 지역 표기가 `budget_candidates.py`의 인천 규칙(`연수구`, 서울과 겹치는 이름은 `인천중구`)과 맞는지 확인한다.
4. `pipeline/supply_calibration.py:113`에 "준공 자료는 서울·경기만 있다"는 주석이 있다. 인천 준공 자료가 없는 상태에서 인천 분양 물량만 늘면 공급 계수가 틀어지는지 확인한다. 같은 지역 집합으로만 나누는 코드가 이미 있으니 그대로 유지되는지 확인한다.

**완료 기준**
- 보강 CSV에 인천 분양권·입주예정 단지가 들어 있다.
- 인천 분양권 단지가 검색되고, 분양권 실거래로 가격이 나온다.

**테스트**
- `.venv/bin/python -m unittest tests.test_build_presale_supplement`

---

### T5. 생활권 지하철 계획 목록에 인천을 넣는다

**현재**
- `pipeline/import_living_area_metro.py:186`

  ```python
  if province not in ('서울특별시','경기도') or not month ...: continue
  ```

**할 일**
1. 조건에 `'인천광역시'`를 넣는다.
2. 스크립트를 실행해서 `data/living_area_metro_catalog.json`을 다시 만든다. 이 스크립트의 원칙("좌표는 지번 주소가 완전히 일치할 때만 받는다")은 그대로 지킨다.
3. 인천 행이 늘었는지(현재 인천 언급 74건) 확인한다.

**완료 기준 / 테스트**
- `.venv/bin/python -m unittest tests.test_living_area_metro`

---

## 3. 2단계: 인천 공식 자료를 새로 모아야 하는 작업

> 이 단계는 **자료 출처와 이용 허락 확인이 먼저**다. 확인 결과를 `docs/data-licenses.md`에 적은 뒤에 코드를 쓴다.

### T6. 재개발·정비구역 지도와 영향 점수

**현재**
- 원본은 서울시 공간정보 하나뿐이다(`data/redevelopment_zones.geojson`).
- `pipeline/redevelopment_analysis.py:90`의 `_supported_region()`은 주소에 `서울`이 있어야만 `True`를 돌려준다. 주석에 "다른 지역을 서울 자료와 비교해 '주변 사업 0건'으로 단정하지 않는다"고 돼 있다. **이 원칙은 유지한다.**
- `pipeline/map_zone_policy.py:50`은 인천을 `'missing'`, 안내를 `인천 경계 미연결`로 표시한다.
- 변환 스크립트: `scripts/import-map-zone-boundaries.py`. 공식 ZIP을 경계를 고치지 않고 그대로 변환한다. `pyshp`, `pyproj`가 필요하다.

**할 일**
1. 인천 정비구역 경계 원본을 찾는다. 후보는 아래와 같고, 상업 이용이 가능한 출처를 우선한다.
   - 인천광역시 정비사업 공개 자료(인천시 도시정비 관련 공개 데이터)
   - 국토교통부 도시계획정보서비스(토지이음, UPIS)
   - 브이월드 공간정보. README에 따르면 **집픽의 상업적 이용과 데이터 저장에는 브이월드의 별도 허락이 필요하다.** 허락 전에는 수집하지 않는다.
2. 원본이 서울 ZIP과 형식이 다르면 `import-map-zone-boundaries.py`를 고치지 말고, 인천용 변환 함수나 스크립트를 따로 만든다. 출처, 다운로드 날짜, 코드 정의를 함께 남기는 기존 규칙을 따른다.
3. 단계 코드(조합설립, 관리처분 등)는 `data/map_zone_stage_codes.json`, `scripts/refresh-map-zone-stage-codes.py`와 맞춘다.
4. 인천 자료가 들어오면 `_supported_region()`이 인천 주소도 허용하게 바꾼다. 이때 **인천 자료가 실제로 들어온 경우에만** 허용해야 한다.
5. `map_zone_policy.coverage()`의 인천 상태를 실제 범위에 맞게 `partial` 또는 `complete`로 바꾼다.

**완료 기준**
- 송도·부평·미추홀 단지 리포트에서 주변 정비사업이 나온다.
- 정비사업이 실제로 없는 곳은 `0건`으로, 자료 범위 밖은 `제공 범위 밖`으로 구분돼 나온다.

**테스트**
- `tests/test_map_zone_*`, `tests/test_redevelopment_*`, `tests/test_redevelopment_zones_api.py`
- `scripts/audit-map-zones.py`를 실행하고 결과 JSON을 `docs/`에 남긴다.

---

### T7. 생활권 변화·미래 변화 점수

**현재**
- 사람이 공식 자료를 검토한 기록만 쓴다. 자동 수집은 없다.
  - `pipeline/import_future_transformation.py`: "Import a manually reviewed JSON dossier; no credentials or remote fetching."
  - `pipeline/import_living_area.py`: 공식 내보내기 자료나 검토를 마친 단지별 관찰값만 받는다.
- 지금은 성남 원도심, 이문·휘경 같은 시범 지역만 있다(`data/future_transformation_pilots.json`). 그래서 송도 단지는 `futureTransformation.status = insufficient_data`로 나온다.
- 참고 문서: `docs/living-area-implementation.md`, `docs/future-transformation/`

**할 일**
1. 인천 주요 사업 후보 목록을 만든다. 아래는 조사 시작점이다. **각 사업의 공식 출처(시·국토부 고시, 공식 보도자료)를 확인한 것만** 등록한다.
   - 송도국제도시 (연수구), 청라국제도시·검단신도시 (서구)
   - 제물포 르네상스, 루원시티
   - GTX-B (송도~마석), 인천 2호선 연장, 서울 7호선 청라 연장
2. 사업마다 기존 시범 자료와 같은 JSON 형식으로 검토 기록을 만든다. 출처 URL, 고시일, 사업 단계, 영향 반경 근거가 들어가야 한다.
3. `import_future_transformation.py` / `import_living_area.py`로 등록한다. 형식 검사에 실패하면 자료를 고친다. 검사 규칙을 느슨하게 바꾸지 않는다.
4. 시범 지역을 늘리면 화면의 "현재는 성남 원도심과 이문·휘경의 공식 자료를 먼저 확인하고 있어요" 문구(`pipeline/future_transformation.py:478`)도 고친다.

**완료 기준**
- 인천 시범 지역 1곳 이상에서 미래 변화 점수가 계산된다.
- 등록한 모든 사실에 공식 출처가 붙어 있다.

**테스트**
- `tests/test_future_transformation.py`, `tests/test_living_area*.py`
- `scripts/preview-future-transformation.py`로 결과를 확인한다.

> 이 작업은 조사량이 많다. **T7은 사업 1~2개로 먼저 끝까지 해 보고**, 사용자에게 결과를 보여준 뒤 범위를 늘린다.

---

### T8. 네이버 단지 연결과 전세가율

**네이버 단지 연결**
- `pipeline/build_naver_complex_overrides.py`는 후보 단지를 법정동 단지 목록으로 맞춰 정적 매핑 파일(`data/naver_complex_overrides.json`)을 만든다. 운영 서버에서 네이버를 직접 부르면 느리거나 막히기 때문이다.
- 인천 단지를 대상에 넣어 실행하고 인천 매핑 수를 확인한다(현재 `송도` 16건 정도).
- 테스트: `tests/test_naver_complex.py`

**전세가율**
- `pipeline/molit_transactions.py`는 미리 만든 전세 자료(`data/jeonse_rent_snapshots.json`, `_bundled_jeonse_index()`)와 실시간 조회(`jeonse_ratio_for_apartment()`)를 함께 쓴다. 미리 만든 자료에는 인천이 없다.
- **먼저 확인할 것**: 실시간 전월세 조회가 인천 법정동 코드(`28xxx`)에서도 값을 돌려주는지 송도 단지로 확인한다. 송도 단지 후보 데이터에는 `jeonseRatio`가 비어 있었다.
- 미리 만든 자료를 만드는 스크립트를 찾아 인천을 넣고 다시 만든다. 스크립트가 없으면 어떻게 만들었는지 이력(`git log -- data/jeonse_rent_snapshots.json`)을 보고 정리한다.

---

## 4. 화면 문구

### T9. `서울·경기`로 고정된 안내를 실제 범위에 맞춘다

**현재 문구 위치** (`앱화면/real-estate-search.html`)

| 줄 (근처) | 문구 |
|---|---|
| 5830, 8389 | `서울·경기 지도를 불러오고 있어요.` |
| 5829 | `aria-label="서울과 경기의 주택 가격 흐름 지도"` |
| 8572 | `` `서울·경기 ${...}곳` `` |
| 8742 | `` `국토부 실거래 기준 · 선정한 서울·경기 ${...}곳 분석 · ...` `` |

**할 일**
1. T2가 끝나서 인천 노드가 실제로 들어간 뒤에만 `서울·경기·인천` 또는 `수도권`으로 바꾼다. 데이터보다 문구가 먼저 바뀌면 안 된다.
2. T6, T7처럼 시간이 걸리는 작업이 끝나기 전에는, 인천 단지 리포트에서 해당 섹션을 빈칸으로 두지 않는다. 결론형으로 상태를 알린다. 예: `인천 정비구역 자료는 아직 연결하지 않았어요`.
3. `AGENTS.md`의 판단 제목 원칙을 지킨다. `확인하세요`로 끝내지 않는다.

**테스트**
- `.venv/bin/python -m unittest tests.test_frontend_apartment_search`
- 모바일(375px)과 데스크톱에서 지역 흐름 화면을 직접 열어 확인한다.

---

## 5. 마지막 검증

모든 작업이 끝나면 아래를 실행하고 결과를 남긴다.

1. 관련 테스트 전체

   ```bash
   .venv/bin/python -m unittest tests.test_education_environment tests.test_market_flow tests.test_build_presale_supplement tests.test_living_area_metro tests.test_naver_complex tests.test_future_transformation tests.test_apartment_affordability tests.test_frontend_apartment_search tests.test_report_price_check
   ```

2. 점검 스크립트: `scripts/audit-apartment-price-coverage.py`, `scripts/audit-apartment-sections.py`, `scripts/audit-map-zones.py`
3. 0-3의 인천 단지 4곳으로 단지 리포트를 열고 아래 표를 채워 결과에 붙인다.

   | 섹션 | 송도 | 서구 | 부평 | 미추홀 |
   |---|---|---|---|---|
   | 가격 비교·집픽 밴드 | | | | |
   | 학군·교육 환경 | | | | |
   | 입지 점수 | | | | |
   | 최근 시장 신호 | | | | |
   | 주변 정비사업 | | | | |
   | 미래 변화 | | | | |
   | 전세가율 | | | | |

4. 같은 표를 서울 1곳, 경기 1곳으로도 채워서 **기존 지역 결과가 바뀌지 않았는지** 확인한다.

---

## 6. 작업 순서 요약

| 순서 | 작업 | 난이도 | 새 자료 수집 |
|---|---|---|---|
| 1 | T1 학군 | 쉬움 | 없음 (카카오 API 키 필요) |
| 2 | T2 지역 흐름 | 보통 | 없음 |
| 3 | T3 실거래 미리 받기 | 쉬움 | 없음 |
| 4 | T4 분양권 보강 | 쉬움 | 기존 스크립트 재실행 |
| 5 | T5 지하철 계획 | 쉬움 | 기존 스크립트 재실행 |
| 6 | T9 화면 문구 (1단계분) | 쉬움 | 없음 |
| 7 | T8 네이버·전세가율 | 보통 | 스크립트 재실행, 확인 필요 |
| 8 | T6 재개발 경계 | 어려움 | **인천 공식 자료 + 이용 허락** |
| 9 | T7 미래 변화 | 어려움 | **사업별 공식 자료 조사** |

**1~6번을 먼저 끝내고 결과를 보고한다.** 7~9번은 자료 출처와 이용 허락을 확인한 결과를 먼저 보고하고, 승인을 받은 뒤 진행한다.
