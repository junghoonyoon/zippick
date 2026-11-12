# Real Estate Summary Style Direction

Source files:

- `design-md/coinbase/DESIGN.md`
- `design-md/airtable/DESIGN.md`

## Direction

Use a Korean financial-service visual language inspired by the clarity and comfort of Naver Pay, while keeping the product's existing blue identity. Use Airtable only as an information-architecture reference for repeated research results.

## Service Typography

- Default body and form values: 16px.
- Supporting copy and labels: 13–15px; never use 10–12px for essential information.
- Section titles: 23–26px; primary page title: 36–48px.
- Important prices, scores, and decisions should be one clear step larger than their surrounding metadata.
- Use generous 1.55–1.75 line-height for Korean body copy.

## Naver Pay-Inspired Qualities

- Use a very light gray service canvas with crisp white content cards.
- Keep inputs at least 54px high and primary actions at least 56px high.
- Use the existing blue for the primary CTA, focus states, links, and key financial emphasis.
- Prefer rounded 14–24px surfaces, subtle borders, and restrained shadows.
- Increase spacing together with type size so the interface feels calm rather than merely enlarged.

## Financial Product Base

- Use a clean, lightly tinted canvas with white surfaces and restrained blue accents.
- Keep the product feeling institutional, trustworthy, and financial.
- Use dark editorial sections sparingly for important summaries or featured result states.
- Prefer calm typography, clear hierarchy, and minimal decorative effects.
- Use blue for primary actions, links, focus states, and the strongest data emphasis only.

## Airtable Structure

- Organize search results as dense but readable information cards.
- Use filter rails, chips, tabs, and compact controls for query refinement.
- Make opinion labels easy to scan across repeated cards.
- Keep cards structured around title, source, stance, evidence, and action.
- Let the page behave like a research workspace rather than a marketing page.

## Product Mapping

- Search input: clean Korean financial-product search with comfortable touch targets.
- Popular keyword chips: Airtable-style compact filter chips.
- Result cards: Airtable layout density with Coinbase color discipline.
- Opinion labels:
  - `상승기대`: positive blue or green accent.
  - `관망`: neutral gray or muted blue.
  - `주의`: red or amber warning accent.
  - `단순언급`: low-emphasis gray.
- Summary area: calm financial insight panel with large decision text and readable evidence.
- Loading and progress states: restrained, direct, and status-oriented.

## 리포트 판단 문구

리포트의 각 섹션 제목은 숫자나 현상보다 **판단을 먼저** 보여준다. 사용자가
제목만 읽어도 이 항목이 매수에 유리한지 알 수 있어야 한다.

- 근거가 매수에 유리하면 `좋아요`로 시작한다.
- 강점과 주의점이 함께 있으면 `보통이에요`로 시작한다.
- 현재 조건이 매수에 불리하면 `아쉬워요`로 시작한다.
- 판단할 자료가 없으면 `판단할 수 없어요`라고 쓴다. 자료가 없다는 이유로
  `아쉬워요`라고 쓰지 않는다.

판단 뒤에는 바로 확인된 근거를 붙인다. 행동 안내는 제목 아래 본문에 따로 둔다.
예를 들어 `최근 시장 흐름은 좋아요.
가격과 거래가 함께 늘었어요`처럼 쓴다. `전세가율이 낮습니다`, `출퇴근 시간이
보통입니다`, `가격이 올랐습니다`처럼 상태만 말하고 결론을 생략하지 않는다.

- 제목을 `단지 조건은 좋아요`처럼 판단만으로 끝내지 않는다. 역·학교 거리,
  거래 변화, 건물 연식, 전세금 비중처럼 확인된 이유를 바로 붙인다.
- 강점과 약점이 함께 있으면 중요한 주의점도 짧게 보여준다. 점수가 같더라도
  단지별 근거에 따라 제목이 달라져야 한다.
- 근거가 없는 항목은 추측하지 않는다. 무엇을 확인하지 못했는지 제목에 쓴다.
- 가격 비교 제목은 `강서구 비교 단지 3곳보다 평균 실거래가가 5.5% 높아요`처럼
  비교 대상과 가격 차이를 바로 말한다. `가격은 아쉬워요. 참고 비교에서…` 같은
  평가 문구를 앞에 덧붙이지 않는다. 참고용 여부와 비교 한계는 표와 설명에서 밝힌다.
- 비교단지 표의 비교 기준은 항상 `직선거리 · 연식 차이 · 세대수 차이` 순서로 쓴다.
  거리는 m 단위로 통일하고, 정보가 없으면 해당 자리에 `거리 미확인`, `연식 미확인`,
  `세대수 미확인`을 표시한다. 항목을 생략하거나 행마다 순서를 바꾸지 않는다.
- 비교단지 가격 옆에는 선택 단지의 같은 기간 평균 실거래가 대비 차이를 표시한다.
  `(비교단지 평균 / 선택단지 평균 - 1) × 100`을 쓰고, 더 비싸면 빨간색 `+%`,
  더 저렴하면 파란색 `−%`, 같으면 회색 `0.0%`로 표시한다. 기준이 없으면 차이를
  계산하지 않는다. 표 위에 어느 단지 대비인지 밝히고 시간에 따른 상승률과 혼동하지 않는다.
- 비교단지는 가격과 무관하게 가까운 곳(직선거리 1km 이내, 좌표가 없으면 같은 법정동)부터 고른다.
  두 곳이 안 되면 같은 구로 넓히고, 그래도 부족하면 규모·연식 조건을 차례로 넓힌다.
  실제 선정 범위와 넓힌 조건을 표 위에 밝히고 `자료 적음`을 표시한다. 다른 동네는
  비교 단지와의 평소 가격 차이를 감안하며, 단순한 현재 가격 차이를 별점에 넣지 않는다.
  거리만 넓힌 경우와 규모·연식·면적·기간까지 넓힌 경우의 별점 적용은 아래 공통 판단 기준을 따른다.
- 비교단지 표와 실제 거래 표는 같은 회색 머리글 배경(`#f7f8fa`)과 구분선 색을 사용한다.
  비교표는 공간을 적게 쓰도록 셀 여백만 더 작게 둘 수 있다.

### 판단 제목의 결론형 원칙

매수 판단 대제목, 각 섹션 제목, 점수 옆 강조 문장에는 같은 원칙을 적용한다.
제목은 사용자가 할 일이 아니라 **자료로 내린 현재 결론**을 말한다.

| 피할 표현 | 결론형 예시와 적용 조건 |
| --- | --- |
| 거래 유동성을 확인하세요 | 하락기에도 거래가 유지됐어요 — 하락기 거래 유지가 확인된 경우 |
| 거래 유동성을 확인하세요 | 하락기 거래가 평소보다 줄었어요 — 비교 기간보다 거래가 줄어든 경우 |
| 약한 항목을 확인하세요 | 입지·교육 조건은 아쉬워요 — 해당 항목의 확인된 점수가 낮은 경우 |
| 구축이라는 점은 감안하세요 | 28년차로 연식은 약점이에요 — 실제 건물 연식이 확인된 경우 |
| 최근 흐름을 더 확인하세요 | 가격과 거래량 자료가 부족해 최근 흐름은 판단할 수 없어요 — 자료가 없는 경우 |

- `유동성`처럼 어려운 말은 `거래가 이어져요`, `거래가 뜸해요`로 풀어 쓴다.
- 상대적으로 가장 낮은 점수라는 이유만으로 `나빠요`라고 쓰지 않는다.
  관측된 상태와 해당 항목의 절대 기준으로 결론을 낸다.
- 6개월 가격 흐름과 최근 3개월 반등은 함께 성립할 수 있다. 기간을 밝혀 쓴다.
- 자료 부족은 부정적 결론과 구분한다. 과거 거래량으로 미래 매도 가능성을 보장하지 않는다.
- 하락기 거래는 차트의 2년 범위와 분리해 최근 5년의 같은 단지·선택 평형으로 계산한다. 이번 달은 제외하고 완료된 달만 비교한다. 원본이 확인된 연속 기간과 실제 시작·종료 월을 표시하며, 미수집 달을 거래 0건으로 채우지 않는다. 하락 달이 적다는 이유로 과거에 하락기를 겪지 않았거나 다음 하락장을 기다려야 한다고 단정하지 않는다.
- 행동 안내가 필요하면 아래 본문에 대상·자료·비교 기준을 적는다.
  예: `같은 전용면적의 최근 3개월 실거래 건수를 국토부 자료에서 직전 3개월과 비교하세요.`
- 검수할 때 제목만 읽고 결론이 보이는지, 좋음·보통·나쁨·자료 부족이 구분되는지 확인한다.

### 매수 판단 제목은 종합 결론을, 가격 근거는 비교 기준을 표시

매수 판단 상단은 `가격`과 `단지 조건` 두 문단으로 나눈다. 두 문단의 라벨과 본문에 각각 같은 크기와 굵기를 적용한다. 가격 문단에는 다른 단지와 비교한 평균 거래 가격만 쓴다. 최근 한 건의 단지 내 가격 판단은 기존 집픽 밴드에 둔다. 단지 조건 문단의 첫 문장에 세대수와 규모를 쓰고, 확인된 핵심 장점과 이어 쓴다. 기존 규모 구간에 맞춰 2,000세대 이상은 대단지, 500~1,999세대는 중간 규모 단지, 500세대 미만은 소단지로 표시한다. 세대수가 없으면 확인되지 않았다고 쓴다. 장점과 주의점은 확인된 역·학교·연식, 주요 업무지구 예상 이동시간, 최근 가격·거래량, 하락기 거래, 공식 개발·교통 사업 단계에서 하나씩 고른다. 역·학교는 이름과 확인된 직선거리를 쓰고, 거래 급감은 직전·최근 6개월 건수를 함께 쓴다. 주의점이 있으면 다음 문장에 쓴다. 거래가 줄었어도 실제 거래 건수가 5점 기준을 충족한 경우, 거래 감소를 언급할 때 그 건수도 함께 밝힌다. 거래 급감·확인되지 않은 단지 조건·연식 등 중요한 주의점이 있으면 좋은 사실만 나열하지 않는다. 하락기 거래는 기존 리포트와 같은 5년 원자료·계산을 사용하고, 개발 계획은 단지 일치·공식 출처·진행 단계를 확인한다. 자료 없음은 나쁜 조건이 아니며, 향후 가격·매도 가능성은 예측하지 않는다. `이 단지의 평균 거래 가격은 비슷한 주변 단지와 비교하면 평소보다 높아요`처럼 쓴다. 시·군·구 단위로 넓혀 비교하면 실제 지역 이름을 써서 `남양주시 내 비슷한 단지`처럼 표시한다. 규모·연식 기준도 완화했으면 `남양주시 내 다른 단지`라고 쓴다. 평소 대비 판단은 어렵지만 최근 가격을 비교할 수 있는 단지가 한 곳 이상 있으면 비교 기간과 현재 가격 차이(%)를 제목에 쓰고, 평소 대비 판단은 자료 부족으로 따로 표시한다. 두 가격 판단이 엇갈려도 같은 단지 내 가격 비교는 대타이틀에서 제외하고 집픽 밴드와 상세 판단 근거에 유지한다. 한쪽 자료가 없으면 그 비교의 자료 부족·로딩·오류를 밝히고, 다른 쪽의 확인된 판단은 표시한다. 같은 단지의 과거 거래만 쓴 경우 집픽 밴드와 상세 근거에 과거 기준임을 쓴다. 검토 의견의 입지·연식·거래량 판정 사유는 상세 판단 근거에 둔다.

- 상단에는 판단 태그를 제목 위에 놓고, 확인된 이유를 담은 제목을 23~28px로 표시한다. `매수는 신중히 검토하세요.` 같은 별도 안내 문장은 제목 아래에 반복하지 않는다. `매수 판단 3/5` 숫자는 표시하지 않으며 내부 판단 계산과 항목별 별점은 유지한다.
- 대타이틀에는 같은 단지 내 최근·과거 거래와의 가격 비교와 `같은 단지 거래로만 비교할 수 있어요` 같은 비교 방식 설명을 넣지 않는다. 주변 단지와 비교한 평균 가격과 입지·단지 조건의 종합 결론을 쓴다. 주변 단지 가격 판단이 없으면 가격이 괜찮다고 쓰지 않고 확인된 입지·단지 조건을 요약한다. 기존 집픽 밴드와 상세 근거의 가격 판단·자료 한계·별점·등급은 유지한다.
- 가격·단지 조건은 박스 없이 각각 한 줄 요약으로 표시한다. 라벨·기존 별점·짧은 결론 순서를 유지한다. 모바일에서 폭이 모자라면 자연스럽게 줄바꿈하며 말줄임으로 내용을 자르지 않는다. 상세 비교 기준과 원지표는 기존 상세 구간에 유지한다. 가격·단지 조건·주의·종합점수·시장 신호의 순서와 계산은 유지한다.
- 가격 별점은 다른 단지와의 평소 가격 차이를 확인할 수 있을 때 매긴다. 평소 차이에서 −6포인트 이하는 5점, −6포인트 초과~−3포인트 미만은 4점, ±3포인트 이내는 3점, 3포인트 초과~6포인트 이하는 2점, 6포인트 초과는 1점이다.
- 단지 조건 별점은 역·교육 점수 평균과 규모·연식 점수 평균에 같은 비중을 적용한다. 평균을 5점 만점으로 환산하고 소수점 첫째 자리까지 쓴다. 확인된 항목이 세 개 이상이고 두 쪽에 자료가 있어야 계산한다. 가격과 단지 조건 별점은 각각 확인된 경우에 표시하며 상단 문단과 해당 상세 섹션에 같은 값을 쓴다.
- 상단 판단, 종합 점수 아래의 단지 설명, 상세 단지 조건 제목은 모두 위의 네 항목에서 내린 단지 조건 판단을 재사용한다. 상세 단지 조건에는 네 원지표를 표시한다. 종합 100점은 가격·전세·입지·단지·거래 흐름을 함께 반영하며, 리포트의 점수표는 해당 리포트에 표시한 점수와 근거를 보여준다.
- 해당 단지의 재건축·리모델링은 기존 `단지 변화`의 식별 결과와 공식 단계표를 상단 판단·단지 조건 제목에도 재사용한다. 현재 건물이 오래됐다는 사실과 확인된 추진 상황을 함께 쓴다. 가격 부담·거래 감소·자료 부족 등 기존 판정 이유를 사업 소식으로 가리지 않는다.
- 추진 단계별로 확인된 사실과 남은 불확실성을 함께 쓴다. 초기 계획은 일정이 불확실하고, 조합 설립이나 사업 승인을 받았어도 남은 절차와 일정을 구분한다. 리모델링의 안전진단·도시계획·건축 심의는 조합 설립 뒤 진행될 수 있으므로 무조건 초기라고 쓰지 않는다. [서울시 공동주택 리모델링 사업시행절차](https://cleanup.seoul.go.kr/cleanup/view/remodeling.do)
- 단지 자체 사업은 종합점수·연식 점수·매수 별점에 넣지 않는다. `단지 변화` 별점은 사업 종류별 진행 단계로 계산하고 화면 위치·순서는 유지한다. 인가 신청·예정·단계 충돌은 승인 완료로 쓰지 않는다. 기사만 있으면 공식 단계 미확인으로 표시하며, 다른 단지·주변 사업·준공·취소된 사업은 추진 중이라는 제목에 넣지 않는다.
- `단지 변화`는 서울시 공식 절차를 참고한 집픽의 단계 비교 점수다. 재건축은 계획·진단 1점, 후보지 선정·도시계획 심의 1.5점, 정비구역 지정·추진위원회 구성 2점, 추진위원회 승인 2.5점, 조합 설립·건축 심의·사업시행자 지정 3점, 사업시행 인가·관리처분 준비 3.5점, 관리처분 인가 4점, 이주·철거 4.5점, 착공 5점이다. 리모델링은 계획·제안 1점, 추진 준비 1.5점, 조합 설립 2점, 1차 안전진단 2.5점, 도시계획 심의 3점, 건축 심의 3.5점, 리모델링 허가·사업계획 승인 4점, 이주·부분철거·2차 안전진단 4.5점, 착공 5점이다. 사업 방식에 따라 일부 절차는 생략될 수 있다. 리모델링의 차수가 없는 안전진단, 사업 종류가 불명확한 자료, 신청·예정·취소·준공 단계는 임의로 점수를 매기지 않는다. 새 기준을 받기 전의 이전 별점은 표시하지 않는다. [서울시 재건축 절차](https://cleanup.seoul.go.kr/cleanup/view/rebuild.do) · [서울시 리모델링 절차](https://cleanup.seoul.go.kr/cleanup/view/remodeling.do)
- 상단 가격 설명과 상세 가격 비교는 같은 판단을 사용한다. 최근 가격 차이만 확인한 경우 상세 표에도 현재 가격 차이만 표시한다. 집픽 밴드는 평가 대상 거래를 제외한 같은 면적대의 다른 실거래로 산정한 가격대를 최근 거래와 대조한다. 거래 급감과 두 가격 판단이 엇갈리는 경우는 별도의 주의 문구로 밝힌다.
- 공통 매수 판단은 시장 신호 총점을 등급 조건으로 쓰지 않는다. 신호가 낮아도
  비교 가격과 단지 조건이 받쳐주면 매수 검토가 가능하다. 낮은 신호를 저점으로 단정하지 않는다.
- 상세 판단 근거에는 비교 가격 부담, 확인된 단지 약점, 실제 거래 급감 중 별점 판정 원인을 말한다.
  가격 하락·횡보만으로 매수 보류라고 쓰지 않는다.
- 개인 예산·전세가율·개인 통근 조건은 공통 매수 판단과 별점에 합산하지 않는다.
  같은 단지·면적·가격 근거이면 통합 검색과 매수 후보의 공통 판단은 같다.
- 상단에 실거래 비교 기간을 표시한다. 현재 매물 호가나 개인 예산을 평가했다고 쓰지 않는다.
- 역·교육·규모·연식 중 세 항목 이상이고 입지와 단지 양쪽에 자료가 있으면 확인된 항목으로 판단한다. 없는 항목을 0점으로 넣지 않고 별도로 표시한다.
- 비교 단지 자료가 부족하면 평가할 최근 거래를 뺀 같은 단지의 다른 실거래 3건 이상으로 만든 집픽 밴드를 보조 기준으로 사용한다. 최근 거래가 밴드보다 낮은지, 안에 있는지, 높은지는 집픽 밴드의 제목에서 결론을 낸다. 리포트 대타이틀에는 이 비교를 넣지 않는다. 이 기준만으로는 최대 조건부 검토이며, 자료 수·비교 기간·층 차이는 본문에 밝힌다.
- 집픽 밴드 제목은 계산 과정 대신 가격 결론을 먼저 말한다. 자료가 적어도 실제 비교 범위 안에서 결론을 내며, 현재 매물의 저평가나 미래 수익을 확정하지 않는다. 사용할 실거래가 실제로 없을 때만 가격 판단이 어렵다고 밝힌다. 확인된 입지·단지 두 축이 모두 약하면 매수 보류로 판단한다.
- 집픽 밴드는 최근 6→12→24개월 순으로 같은 면적의 다른 거래 3건이 모이는 가장 짧은 기간을 먼저 고른다. 그 기간 안에서 비슷한 층 3건이 있으면 사용하고, 없으면 최근 여러 층 거래를 사용하며 층 차이를 미보정으로 밝힌다. 층을 맞추려고 최신 거래를 버리고 오래된 거래만 고르지 않는다.
- 거래별 한국부동산원 주간 지수 보정 여부, 가격대 중심의 보정률, 지수 기준일은 밴드 본문에 표시한다. 미적용이면 이유를 표시한다. 단지·역 지도는 리포트 최상단에 두고, 해당 단지 실거래 보기는 집픽 밴드 안에 둔다. 사용자의 명시적인 이동 요청 전까지 이 위치를 유지한다.
- 같은 구까지 거리만 넓힌 평소 가격 차이 비교는 범위 확대와 자료 적음 안내를 유지한다. 규모·연식 조건과 같은 면적을 유지하고, 대상 단지와 비교 단지 2곳 이상 모두 최근 6개월 거래가 5건 이상이며 각 비교 단지와 최근 4년 중 2년 이상의 과거 가격 차이를 확인했다면 거리만으로 검토 의견을 조건부 검토로 제한하지 않는다. 가격·입지·단지 조건과 거래 급감 기준을 충족하면 매수 검토가 가능하다.
- 범위를 넓혀 실제 비교가 끝났으면 대제목에 `가까운 비교 단지가 부족해요`를 판정 이유로 쓰지 않는다. 확인된 가격 비교 결과와 실제 한계(거래 수·과거 가격 차이·기간·조건)를 함께 말한다. 범위를 넓힌 과정은 가격 비교 근거에 유지한다. 예: `단지 조건은 좋고 비교 가격은 평소 수준이지만, 비교 단지의 거래가 적어요.` 비교 완료와 자료 없음은 구분하며, 이 문구 수정으로 별점 기준을 완화하지 않는다.
- 가까운 비교 단지 2곳 이상과 대상 단지 모두 같은 면적·최근 6개월 거래 3건 이상, 각 비교 단지와 최근 4년 중 2년 이상의 실제 가격 비율이 있으면 거래 수가 5건 미만이어도 매수 검토까지 판단한다. 비교 범위를 넓힌 다른 한계가 없어야 하며 자료 적음과 실제 거래 수는 계속 표시한다. 이 예외는 우선 검토와 다른 후보 우선에 적용하지 않는다.
- 같은 구까지 거리만 넓힌 경우는 기존의 대상·비교 단지 각각 5건 이상 기준을 유지한다. 규모·연식·면적·기간 조건까지 넓히거나 그보다 거래·과거 비교 자료가 부족하면 최대 조건부 검토로 사용한다. 확인된 가격 부담과 단지 약점으로 매수 보류에 해당하면 그 의견을 표시한다. 단순 현재 가격 비교는 가격 별점에서 제외하고, 같은 단지 가격대로도 판단할 수 없으면 검토 의견은 판단 보류로 표시한다.
- 비교 단지 대비 가격 부담과 같은 단지 집픽 밴드의 방향이 다르면 두 기준을 함께 설명하고 조건부로 판단한다. 서로 다른 비교 대상을 하나의 쌈·비쌈 결론으로 섞지 않는다.
- 검토 의견은 우선 검토, 매수 검토, 조건부 검토, 매수 보류, 다른 후보 우선, 판단 보류로 구분한다. 근거가 부족하면 판단 보류로 표시한다. 특정 단지·가격대·표본 내 순위로 등급을 배분하지 않는다.
- 다른 후보 우선과 우선 검토는 단지 일치 확인과 입지·단지 원지표 네 항목이 모두 필요하다. 대상과 비교 단지 2곳 이상 모두 최근 6개월 거래 5건 이상, 각 비교 단지와 최근 4년 중 2년 이상의 실제 가격 비율이 필요하다. 규모·연식·면적·기간 조건 확대, 거래 자료 부족, 두 가격 기준의 방향 불일치가 있으면 극단 등급을 부여하지 않는다. 거리만 확대한 경우는 기존 안내를 유지한다.
- 연식만 약점인 21년차 이상 대단지는 규모 90점 이상, 입지 축 65점 이상, 다른 세 원지표 50점 이상을 확인한다. 대상과 비교 단지의 최근 6개월 거래가 각각 5건 이상이고 과거 가격 차이가 2년 이상 확인되며, 규모·연식·면적·기간 조건을 넓히지 않은 가격 비교에서 적정하거나 저렴하면 매수 검토까지 판단한다. 가격 부담, 다른 원지표의 약점, 거래 절반 초과 감소가 있으면 이 예외를 적용하지 않는다. 연식 약점은 단지 조건과 상세 판단 근거에 그대로 표시하고 이 예외는 우선 검토에 적용하지 않는다.
- 우선 검토는 매수 검토의 충분한 비교 근거에 더해 두 경로 중 하나를 충족한다. 첫째는 입지와 단지 축 각각 75점 이상·각 원지표 50점 이상, 평소 가격 차이 대비 3포인트 넘게 저렴하고 최근 6개월 거래 5건 이상이 직전 6개월 이상 유지된 경우다. 둘째는 두 축 각각 85점 이상·각 원지표 50점 이상, 가격이 평소 수준 이하이고 최근 6개월 거래가 20건 이상이며 절반 넘게 줄지 않은 경우다. 두 경로 모두 최근 한 건이 같은 단지의 6개월 이내 다른 거래 3건 이상으로 계산한 가격대 이하여야 한다. 참고용·기간 확대 가격대는 우선 검토 근거로 쓰지 않는다. 직전 거래 수보다 감소했다면 그 사실을 그대로 표시한다. 추가 조건이 빠져도 매수 검토 기준을 충족하면 매수 검토로 표시한다.
- 다른 후보 우선은 충분한 가격 근거에서 평소 가격 차이 대비 3포인트 넘게 비싸며 입지·단지 두 축 모두 50점 미만인 경우다. 또는 강점과 아쉬움이 섞인 단지에서 가격 부담이 평소보다 10포인트를 초과하거나, 비싼 가격과 최근 6개월 거래의 절반 초과 감소가 겹친 경우다. 거래 감소는 이전 거래 5건 이상인 정상 자료로만 판정한다. 일반적인 가격 부담·단지 약점만 있으면 매수 보류, 단지 조건이 좋지만 가격 부담 또는 거래 급감이 있으면 조건부 검토로 표시한다. 75점·10포인트 등은 집픽의 비교 정책이며 수익 예측이나 통계적으로 검증된 투자모형으로 설명하지 않는다.
- 확인된 단지 항목이 세 개 미만이거나 거래 자료의 단지 일치 여부에 문제가 있을 때 판단을 보류한다. 시장 신호 점수만 없다는 이유로 매수 판단을 보류하지 않는다.
- 대제목은 한두 문장으로 제한한다. 매수가·할인 금액·가격 하단·수리비 조건은 넣지 않는다.
  가격 범위와 숫자는 집픽 밴드 등 해당 근거 섹션에서 설명한다.
- 모든 제목은 실제 판정 원인에 맞춰 쓴다. 강점만 나열해 조건부라는 결론과 모순되지 않게 한다.
- 상단 매수 판단 문장 뒤의 가격 문단은 다른 단지와 비교한 평균 거래 가격을 설명한다. 같은 단지 내 가격 비교는 집픽 밴드에서 설명한다.
- `비교 근거는 제한돼요`로 여러 사유를 묶지 않는다. 거래가 적음, 가까운 비교 단지 부족, 비교 기간 확대, 규모·연식 조건 확대, 면적 환산 중 실제 적용된 이유를 쓴다. 여러 이유가 겹치면 아래 근거에 모두 밝힌다.
- 확인된 가격 부담·단지 약점·거래 급감을 자료 부족 설명으로 가리지 않는다. 제목에서 생략한 가격 비교 결과와 자료 수·기간은 바로 아래 근거에 남긴다.
- `다른 단지와의 가격 차이는 평소와 비슷해요`는 적정 가격이라는 뜻이 아니다. 같은 단지 거래만 쓴 경우에는 그 안에서의 가격 위치와 다른 단지의 평소 가격 차이를 판단하지 못했다는 점을 함께 설명한다.

## Loading Spinner Convention

Use a spinner for every state where the user is waiting for data, calculation, or map/chart rendering.

- `small`: 14px spinner for compact inline states such as button labels, badges, chips, and short one-line loading text.
- `default`: 20px spinner for card or panel-level loading such as affordability calculations, report loading, and bottom-sheet content loading.
- `large`: 32px spinner for full loading blocks, map placeholders, search result loading, and page-level progress states.

Keep the spinner next to a short Korean status sentence. Do not show a spinner by itself unless the surrounding card already says what is being loaded.

Use **판단불가** for data that cannot be scored because there is no usable source data. Do not label missing data as **낮음**, because that makes it sound like the apartment performed poorly.

## Candidate Chart

Use this chart treatment for the expanded price-flow chart inside apartment result cards.

- Keep the chart visually attached to the card width. The SVG should fill the available card width instead of sitting as a narrow centered chart.
- Do not put the chart inside another card or framed box.
- Keep chart labels calm and research-like: gray axis labels, light grid lines, blue as the selected apartment emphasis, and restrained secondary comparison lines.
- Keep the summary row above the chart compact: basis label at 16px, apartment/region/leader names and rate values at 14px on web.
- The `spark-axis-label` text is a chart-axis exception to the general essential-label rule. Use a fixed 12px size for x/y axis labels so date and percentage ticks stay stable.
- On web, use a wider chart viewBox than mobile, currently `510 x 292`, with the rendered chart capped by the card layout and `max-height: 400px`.
- On mobile, use the compact chart viewBox, currently `420 x 292`, and keep axis labels at the same fixed 12px size.
- Keep the x-axis date labels close to the plot baseline; avoid large blank space between the bottom chart line and dates.

## Avoid

- Do not make the page look like a landing page.
- Do not overuse gradients, oversized hero text, or decorative cards.
- Do not make every card blue; reserve blue for emphasis.
- Do not copy either brand literally. Use the design md files as inspiration only.

## Chart Analysis Copy

- All apartment cards use the shared chart analysis renderer: a short bold trend title, then a regular-weight comparison line. Use a neutral chart icon.
- Comparison format: `최근 2년 가격 변화율 · 노원구 평균보다 높음 · 상계동 대장보다 낮음`. Use the actual chart window, not a fixed two-year label.
- Use `높음 / 비슷 / 낮음` with a shared ±1.5 percentage-point threshold. Compare values from the same month and the chart's common baseline.
- Prefer the local leader; use the district leader when the local comparison is unavailable. Never choose a leader just because its growth rate is higher.
- Show gap changes only inside the expanded chart, explicitly as `상승률 차이`. Sparse observations mean unknown, not unchanged.
- Fewer than eight recorded transactions: `거래가 적어 흐름 판단 어려움`. Stale data takes priority: `최근 거래 뜸함`. Missing comparison data does not become a negative comparison.
- High/low position is distinct from direction. Do not describe a price near its high as automatically rising.
- Let comparison text wrap on mobile; never truncate the meaning with an ellipsis.

## 주변 시세와 대안 단지 비교

- 가격 비교 영역에 `주변 시세 비교 · 반경 1km`와 `비슷한 가격대의 대안 · 다른 동네 포함`을 구분해서 배치한다.
- 주변 시세는 거리·연식·세대수로 후보를 고른 뒤 같은 면적·기간의 가격을 비교한다.
  가격이 비슷하다는 이유로 후보를 고르거나, 가격 차이가 크다는 이유로 제외하지 않는다.
- 입지(역 접근), 단지 조건(세대수·연식), 거래(기간·건수)를 작은 근거 행으로 보여준다.
  이 사실만으로 주변 단지보다 입지가 좋다고 추정하지 않는다.
- 대안 단지는 현재 단지의 대표 가격 ±25%, 면적 ±10%인 같은 구의 후보를 최대 3곳 보여준다.
  실제 구매 가능 예산을 계산한 결과가 아니므로 `예산 안에 살 수 있어요`라고 쓰지 않는다.
  대안의 가격을 주변 시세 평균에 섞지 않는다. 범위를 벗어나는 후보로 빈자리를 채우지 않는다.
- 대안 표에는 단지명·동·면적, 실제 거래 가격·날짜, 선택 단지와의 연식·세대수 차이를 표시한다.
  출처가 없는 조건은 `미확인`으로 표시한다. 모든 표 머리글은 기존 회색 배경을 공유한다.
- 송희구 작가의 공개 인터뷰에서 다룬 예산·입지·단지 조건·거래·매물 가격의 관점을 참고한
  제품 구성이다. 거리와 수치 기준 및 선정 가중치는 집픽의 구현 기준이며 작가의 공식 산식이나
  작가가 추천한 단지로 표현하지 않는다.
  참고: https://v.daum.net/v/20241004090102977 , https://v.daum.net/v/z9WWdBMVeO

- 가격 요약과 제목에서 `단지 평균은 평소 수준`처럼 비교 대상을 생략하지 않는다. `이 단지의 평균 거래 가격은 비슷한 주변 단지와 비교하면 평소 수준이에요`처럼 대상·지표·결과를 함께 쓴다. 같은 구로 범위를 넓혔으면 실제 비교 지역을 재사용한다.

- 상단 `가격` 한 줄은 다른 단지와 비교한 평균 거래 가격만 설명한다. 최근 거래 한 건이 적정·저렴·비싸다는 문장은 가격 요약에 반복하지 않고 기존 집픽 밴드에 표시한다.
- 단지 규모가 판단의 약점이면 `단지 규모 점수가 낮아요` 대신 `180세대로 단지 규모가 작아요`처럼 실제 세대수와 크기를 쓴다. 중간 규모는 작은 단지와 구분한다. 세대수만으로 관리비나 매도·거래의 어려움을 단정하지 않는다.
- 리포트를 대표하는 대타이틀은 가격·입지·단지 조건의 관계를 종합해서 말한다. `연식 점수가 보통이라 매수는 신중히 검토하세요`, `180세대로 단지 규모가 작아요`처럼 한 항목으로 리포트 전체를 대표하지 않는다. 예: `가격과 입지는 괜찮지만, 단지 조건은 보통이에요.` 세대수·연식과 항목별 점수는 아래 단지 조건과 판단 근거에서 설명한다. 가격 부담·거래 감소·자료 부족이 실제 원인이면 그 한계도 대타이틀에 유지한다. 이 표현 변경으로 점수와 판정 기준을 바꾸지 않는다.

## 공통 매수 판단 별점

- 같은 구까지 거리만 넓힌 평소 가격 차이 비교는 범위 확대와 자료 적음 안내를 유지한다. 규모·연식 조건과 같은 면적을 유지하고, 대상 단지와 비교 단지 2곳 이상 모두 최근 6개월 거래가 5건 이상이며 각 비교 단지와 최근 4년 중 2년 이상의 과거 가격 차이를 확인했다면 거리만으로 별점을 3점에 묶지 않는다. 가격·입지·단지 조건과 거래 급감 기준을 충족하면 매수 검토(4점)가 가능하다.
- 가까운 비교 단지 2곳 이상과 대상 단지 모두 같은 면적·최근 6개월 거래 3건 이상, 각 비교 단지와 최근 4년 중 2년 이상의 실제 가격 비율이 있으면 거래 수가 5건 미만이어도 4점까지 판단한다. 비교 범위를 넓힌 다른 한계가 없어야 하며 자료 적음과 실제 거래 수는 계속 표시한다. 이 예외로 1·5점을 부여하지 않는다.
- 같은 구까지 거리만 넓힌 경우는 기존의 대상·비교 단지 각각 5건 이상 기준을 유지한다. 규모·연식·면적·기간 조건까지 넓히거나 그보다 거래·과거 비교 자료가 부족하면 최대 조건부 검토로 사용한다. 확인된 가격 부담과 단지 약점으로 매수 보류에 해당하면 2점을 유지한다. 단순 현재 가격 비교는 별점에서 제외하고, 같은 단지 가격대로도 판단할 수 없으면 별점 없는 판단 보류로 표시한다.
- 비교 단지 대비 가격 부담과 같은 단지 집픽 밴드의 방향이 다르면 두 기준을 함께 설명하고 조건부로 판단한다. 서로 다른 비교 대상을 하나의 쌈·비쌈 결론으로 섞지 않는다.
- 공통 별점은 5점 우선 검토, 4점 매수 검토, 3점 조건부 검토, 2점 매수 보류, 1점 다른 후보 우선으로 구분한다. 자료 부족은 별점 없는 판단 보류이며 1점으로 대체하지 않는다. 특정 단지·가격대·표본 내 순위로 등급을 배분하지 않는다.
- 1점과 5점은 단지 일치 확인과 입지·단지 원지표 네 항목이 모두 필요하다. 대상과 비교 단지 2곳 이상 모두 최근 6개월 거래 5건 이상, 각 비교 단지와 최근 4년 중 2년 이상의 실제 가격 비율이 필요하다. 규모·연식·면적·기간 조건 확대, 거래 자료 부족, 두 가격 기준의 방향 불일치가 있으면 극단 등급을 부여하지 않는다. 거리만 확대한 경우는 기존 안내를 유지한다.
- 연식만 약점인 21년차 이상 대단지는 규모 90점 이상, 입지 축 65점 이상, 다른 세 원지표 50점 이상을 확인한다. 대상과 비교 단지의 최근 6개월 거래가 각각 5건 이상이고 과거 가격 차이가 2년 이상 확인되며, 규모·연식·면적·기간 조건을 넓히지 않은 가격 비교에서 적정하거나 저렴하면 4점까지 판단한다. 가격 부담, 다른 원지표의 약점, 거래 절반 초과 감소가 있으면 이 예외를 적용하지 않는다. 연식 약점은 제목과 근거에 그대로 표시하고 이 예외로 5점을 부여하지 않는다.
- 5점은 4점의 충분한 비교 근거에 더해 두 경로 중 하나를 충족한다. 첫째는 입지와 단지 축 각각 75점 이상·각 원지표 50점 이상, 평소 가격 차이 대비 3포인트 넘게 저렴하고 최근 6개월 거래 5건 이상이 직전 6개월 이상 유지된 경우다. 둘째는 두 축 각각 85점 이상·각 원지표 50점 이상, 가격이 평소 수준 이하이고 최근 6개월 거래가 20건 이상이며 절반 넘게 줄지 않은 경우다. 두 경로 모두 최근 한 건이 같은 단지의 6개월 이내 다른 거래 3건 이상으로 계산한 가격대 이하여야 한다. 참고용·기간 확대 가격대는 5점 근거로 쓰지 않는다. 직전 거래 수보다 감소했다면 그 사실을 그대로 표시한다. 추가 조건이 빠져도 4점 기준을 충족하면 4점을 유지한다.
- 1점은 충분한 가격 근거에서 평소 가격 차이 대비 3포인트 넘게 비싸며 입지·단지 두 축 모두 50점 미만인 경우다. 또는 강점과 아쉬움이 섞인 단지에서 가격 부담이 평소보다 10포인트를 초과하거나, 비싼 가격과 최근 6개월 거래의 절반 초과 감소가 겹친 경우다. 거래 감소는 이전 거래 5건 이상인 정상 자료로만 판정한다. 일반적인 가격 부담·단지 약점만 있으면 기존 2점, 단지 조건이 좋지만 가격 부담 또는 거래 급감이 있으면 기존 3점을 유지한다. 75점·10포인트 등은 집픽의 비교 정책이며 수익 예측이나 통계적으로 검증된 투자모형으로 설명하지 않는다.
- 확인된 단지 항목이 세 개 미만이거나 거래 자료의 단지 일치 여부에 문제가 있을 때 판단을 보류한다. 시장 신호 점수만 없다는 이유로 매수 판단을 보류하지 않는다.
