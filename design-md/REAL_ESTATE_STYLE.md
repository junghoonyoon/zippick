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
