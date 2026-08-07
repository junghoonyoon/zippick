type MarketFlowHeaderProps = {
  baseDate: string;
};

export function MarketFlowHeader({ baseDate }: MarketFlowHeaderProps) {
  return (
    <header className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
      <div className="min-w-0">
        <h1 className="text-[32px] font-black leading-tight text-zippick-ink md:text-[42px]">
          부동산 온기 흐름
        </h1>
        <p className="mt-3 max-w-2xl text-[16px] leading-7 text-zippick-body md:text-[17px]">
          서울과 수도권의 가격 모멘텀이 퍼지는 흐름을 한눈에 확인하세요.
        </p>
      </div>
      <div className="w-fit rounded-lg border border-zippick-line bg-white px-4 py-3 text-[14px] font-semibold text-zippick-body shadow-sm">
        {baseDate}
      </div>
    </header>
  );
}
