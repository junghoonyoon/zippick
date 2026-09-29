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

판단 뒤에는 바로 근거와 행동을 붙인다. 예를 들어 `최근 시장 흐름은 좋아요.
가격과 거래가 함께 늘었어요`처럼 쓴다. `전세가율이 낮습니다`, `출퇴근 시간이
보통입니다`, `가격이 올랐습니다`처럼 상태만 말하고 결론을 생략하지 않는다.

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
