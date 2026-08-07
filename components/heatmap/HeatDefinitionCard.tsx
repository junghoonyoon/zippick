const heatDefinitionItems = [
  {
    title: "현재 순위",
    body: "2년 시작 대비 많이 오른 순서예요.",
    weight: "비교"
  },
  {
    title: "2년 지수",
    body: "시작을 100으로 놓고 흐름을 봐요.",
    weight: "흐름"
  },
  {
    title: "표본 안정성",
    body: "거래가 적은 곳은 조심해서 봐요.",
    weight: "신뢰"
  }
];

export function HeatDefinitionCard() {
  return (
    <section className="rounded-lg border border-zippick-line bg-white px-5 py-4 shadow-sm">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <div className="max-w-2xl">
          <h2 className="text-[18px] font-bold text-zippick-ink">
            지도는 상승 흐름 순위로 먼저 보여줘요.
          </h2>
          <p className="mt-1 text-[14px] leading-6 text-zippick-body">
            퍼센트는 상세에서 근거로 확인해요. 순위, 지수, 표본을 함께 봐야 해요.
          </p>
        </div>
        <div className="grid gap-2 md:grid-cols-3 xl:w-[620px]">
          {heatDefinitionItems.map((item) => (
            <div
              className="rounded-md border border-slate-200 bg-slate-50 px-3 py-3"
              key={item.title}
            >
              <div className="flex items-center justify-between gap-3">
                <strong className="text-[14px] text-zippick-ink">
                  {item.title}
                </strong>
                <span className="text-[13px] font-bold text-orange-700">
                  {item.weight}
                </span>
              </div>
              <p className="mt-1 text-[13px] leading-5 text-zippick-muted">
                {item.body}
              </p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
