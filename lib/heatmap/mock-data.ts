import type {
  HeatRegion,
  SpreadRoute,
  TimelineWeek
} from "@/lib/heatmap/types";
import { calculateHeatScore, getHeatState } from "@/lib/heatmap/utils";

type RegionSeed = Omit<HeatRegion, "currentScore" | "currentState" | "change4w">;

function makeRegion(region: RegionSeed): HeatRegion {
  const currentScore = calculateHeatScore(region);
  const change4w =
    region.weeklyHistory[region.weeklyHistory.length - 1] -
    region.weeklyHistory[region.weeklyHistory.length - 5];

  return {
    ...region,
    currentScore,
    currentState: getHeatState(currentScore),
    change4w
  };
}

export const heatmapWeeks: TimelineWeek[] = [
  { index: 0, label: "2026년 5월 3주", shortLabel: "5월 3주" },
  { index: 1, label: "2026년 5월 4주", shortLabel: "5월 4주" },
  { index: 2, label: "2026년 6월 1주", shortLabel: "6월 1주" },
  { index: 3, label: "2026년 6월 2주", shortLabel: "6월 2주" },
  { index: 4, label: "2026년 6월 3주", shortLabel: "6월 3주" },
  { index: 5, label: "2026년 6월 4주", shortLabel: "6월 4주" },
  { index: 6, label: "2026년 7월 1주", shortLabel: "7월 1주" },
  { index: 7, label: "2026년 7월 2주", shortLabel: "7월 2주" },
  { index: 8, label: "2026년 7월 3주", shortLabel: "7월 3주" },
  { index: 9, label: "2026년 7월 4주", shortLabel: "7월 4주" },
  { index: 10, label: "2026년 7월 5주", shortLabel: "7월 5주" },
  { index: 11, label: "2026년 8월 1주", shortLabel: "현재" }
];

export const heatRegions: HeatRegion[] = [
  makeRegion({
    id: "gangnam",
    name: "강남구",
    weeklyHistory: [60, 62, 64, 66, 68, 70, 73, 75, 78, 80, 82, 83],
    volumeStrength: 86,
    priceRiseRatio: 83,
    risingComplexRatio: 79,
    reasons: [
      "거래가 꾸준히 늘며 매수 관심이 먼저 모였어요.",
      "상승 거래 비율이 높아 가격 흐름이 단단해졌어요.",
      "주요 단지의 상승 흐름이 주변 구로 번지고 있어요."
    ],
    linkedRegions: ["서초구", "송파구", "성동구"],
    nextHeatCandidateScore: 67
  }),
  makeRegion({
    id: "seocho",
    name: "서초구",
    weeklyHistory: [54, 55, 57, 59, 62, 64, 67, 69, 71, 72, 73, 74],
    volumeStrength: 75,
    priceRiseRatio: 75,
    risingComplexRatio: 70,
    reasons: [
      "강남권 흐름과 함께 거래 문의가 늘어난 모습이에요.",
      "상승 거래가 최근 4주 동안 더 자주 보였어요.",
      "고가 단지 중심의 회복이 중간 가격대로 이어지고 있어요."
    ],
    linkedRegions: ["강남구", "동작구", "용산구"],
    nextHeatCandidateScore: 72
  }),
  makeRegion({
    id: "songpa",
    name: "송파구",
    weeklyHistory: [52, 54, 57, 60, 63, 66, 68, 71, 73, 74, 75, 76],
    volumeStrength: 78,
    priceRiseRatio: 76,
    risingComplexRatio: 73,
    reasons: [
      "대단지 거래가 살아나며 온기가 빠르게 올라왔어요.",
      "상승 거래 비율이 회복 구간을 넘어섰어요.",
      "강남구와 가까운 생활권에서 먼저 반응이 나왔어요."
    ],
    linkedRegions: ["강남구", "강동구", "광진구"],
    nextHeatCandidateScore: 75
  }),
  makeRegion({
    id: "yongsan",
    name: "용산구",
    weeklyHistory: [50, 52, 55, 57, 60, 63, 65, 67, 70, 72, 74, 75],
    volumeStrength: 77,
    priceRiseRatio: 74,
    risingComplexRatio: 72,
    reasons: [
      "중심 입지 관심이 이어지며 거래 온도가 올랐어요.",
      "상승 거래가 늘어 가격 하락 걱정이 줄었어요.",
      "성동구와 마포구로 관심이 이어질 여지가 있어요."
    ],
    linkedRegions: ["성동구", "마포구", "중구"],
    nextHeatCandidateScore: 76
  }),
  makeRegion({
    id: "seongdong",
    name: "성동구",
    weeklyHistory: [48, 50, 52, 55, 58, 61, 64, 67, 70, 73, 75, 77],
    volumeStrength: 80,
    priceRiseRatio: 77,
    risingComplexRatio: 73,
    reasons: [
      "핵심 생활권 주변으로 매수 관심이 넓어졌어요.",
      "최근 4주 상승 폭이 서울 평균보다 큰 편이에요.",
      "광진구와 동대문구가 다음 흐름을 볼 지역이에요."
    ],
    linkedRegions: ["용산구", "광진구", "동대문구"],
    nextHeatCandidateScore: 82
  }),
  makeRegion({
    id: "mapo",
    name: "마포구",
    weeklyHistory: [45, 47, 49, 51, 53, 55, 58, 61, 64, 66, 68, 70],
    volumeStrength: 71,
    priceRiseRatio: 70,
    risingComplexRatio: 68,
    reasons: [
      "여의도권과 도심 접근 지역의 관심이 함께 늘었어요.",
      "거래량 강도가 회복 구간을 넘어섰어요.",
      "서대문구와 은평구로 흐름이 이어질 수 있어요."
    ],
    linkedRegions: ["영등포구", "서대문구", "은평구"],
    nextHeatCandidateScore: 81
  }),
  makeRegion({
    id: "gwangjin",
    name: "광진구",
    weeklyHistory: [42, 44, 46, 49, 51, 54, 57, 60, 63, 66, 68, 71],
    volumeStrength: 74,
    priceRiseRatio: 70,
    risingComplexRatio: 67,
    reasons: [
      "성동구 온기가 가까운 생활권으로 옮겨오는 모습이에요.",
      "상승 단지 비율이 천천히 올라오고 있어요.",
      "송파구와 성동구 흐름을 함께 확인할 필요가 있어요."
    ],
    linkedRegions: ["성동구", "송파구", "중랑구"],
    nextHeatCandidateScore: 84
  }),
  makeRegion({
    id: "yeongdeungpo",
    name: "영등포구",
    weeklyHistory: [43, 45, 47, 50, 53, 56, 59, 61, 63, 66, 68, 69],
    volumeStrength: 72,
    priceRiseRatio: 68,
    risingComplexRatio: 65,
    reasons: [
      "여의도 주변 거래가 지역 온기를 끌어올렸어요.",
      "최근 상승 거래가 늘었지만 속도는 아직 완만해요.",
      "마포구와 동작구가 함께 움직이는지 볼 만해요."
    ],
    linkedRegions: ["마포구", "동작구", "양천구"],
    nextHeatCandidateScore: 78
  }),
  makeRegion({
    id: "dongjak",
    name: "동작구",
    weeklyHistory: [40, 42, 44, 47, 49, 51, 54, 57, 60, 63, 65, 67],
    volumeStrength: 69,
    priceRiseRatio: 67,
    risingComplexRatio: 64,
    reasons: [
      "서초구와 영등포구 사이의 이동 수요가 붙고 있어요.",
      "거래량은 늘었지만 단지별 차이는 아직 있어요.",
      "상승 단지가 더 넓어지는지 확인해야 해요."
    ],
    linkedRegions: ["서초구", "영등포구", "관악구"],
    nextHeatCandidateScore: 83
  }),
  makeRegion({
    id: "gangdong",
    name: "강동구",
    weeklyHistory: [39, 41, 43, 46, 48, 51, 54, 56, 59, 61, 63, 65],
    volumeStrength: 68,
    priceRiseRatio: 64,
    risingComplexRatio: 62,
    reasons: [
      "송파구 흐름 뒤에 거래 관심이 따라붙고 있어요.",
      "상승 거래 비율은 회복 중이지만 과열은 아니에요.",
      "대단지 거래가 더 늘면 온기가 강해질 수 있어요."
    ],
    linkedRegions: ["송파구", "광진구", "강남구"],
    nextHeatCandidateScore: 79
  }),
  makeRegion({
    id: "jongno",
    name: "종로구",
    weeklyHistory: [38, 39, 41, 43, 45, 47, 49, 51, 53, 55, 57, 58],
    volumeStrength: 59,
    priceRiseRatio: 58,
    risingComplexRatio: 56,
    reasons: [
      "도심 거래가 조금씩 살아나는 단계예요.",
      "상승 거래는 늘었지만 거래 표본은 많지 않아요.",
      "중구와 서대문구 흐름을 함께 보는 게 좋아요."
    ],
    linkedRegions: ["중구", "서대문구", "용산구"],
    nextHeatCandidateScore: 58
  }),
  makeRegion({
    id: "jung",
    name: "중구",
    weeklyHistory: [37, 38, 40, 42, 44, 46, 48, 50, 52, 54, 55, 57],
    volumeStrength: 58,
    priceRiseRatio: 57,
    risingComplexRatio: 55,
    reasons: [
      "도심 접근 수요가 서서히 회복되는 모습이에요.",
      "상승 단지는 일부 지역에 먼저 나타났어요.",
      "용산구와 종로구 흐름을 같이 봐야 해요."
    ],
    linkedRegions: ["종로구", "용산구", "성동구"],
    nextHeatCandidateScore: 57
  }),
  makeRegion({
    id: "dongdaemun",
    name: "동대문구",
    weeklyHistory: [36, 37, 39, 41, 43, 45, 48, 51, 54, 57, 59, 61],
    volumeStrength: 63,
    priceRiseRatio: 60,
    risingComplexRatio: 59,
    reasons: [
      "성동구와 가까운 구간에서 관심이 늘고 있어요.",
      "거래량 강도는 회복 구간에 들어왔어요.",
      "상승 단지가 더 넓어지면 확산 후보가 될 수 있어요."
    ],
    linkedRegions: ["성동구", "중랑구", "성북구"],
    nextHeatCandidateScore: 74
  }),
  makeRegion({
    id: "seodaemun",
    name: "서대문구",
    weeklyHistory: [35, 36, 38, 40, 42, 44, 47, 49, 51, 53, 55, 57],
    volumeStrength: 59,
    priceRiseRatio: 56,
    risingComplexRatio: 54,
    reasons: [
      "마포구 온기 뒤에 관심이 조금씩 붙고 있어요.",
      "아직은 회복 초입이라 단지별 확인이 중요해요.",
      "은평구와 종로구 흐름도 같이 봐야 해요."
    ],
    linkedRegions: ["마포구", "은평구", "종로구"],
    nextHeatCandidateScore: 71
  }),
  makeRegion({
    id: "yangcheon",
    name: "양천구",
    weeklyHistory: [34, 36, 38, 41, 44, 47, 50, 53, 56, 58, 60, 62],
    volumeStrength: 64,
    priceRiseRatio: 61,
    risingComplexRatio: 60,
    reasons: [
      "교육 수요가 있는 단지를 중심으로 거래가 늘었어요.",
      "최근 4주 상승 폭은 서울 중간 이상이에요.",
      "강서구와 영등포구로 흐름이 이어지는지 봐야 해요."
    ],
    linkedRegions: ["강서구", "영등포구", "구로구"],
    nextHeatCandidateScore: 77
  }),
  makeRegion({
    id: "gangseo",
    name: "강서구",
    weeklyHistory: [32, 34, 36, 38, 41, 44, 47, 50, 52, 54, 56, 58],
    volumeStrength: 60,
    priceRiseRatio: 57,
    risingComplexRatio: 56,
    reasons: [
      "서남권 회복 흐름이 천천히 들어오고 있어요.",
      "거래량은 늘었지만 상승 폭은 아직 크지 않아요.",
      "양천구 흐름을 같이 확인하면 좋아요."
    ],
    linkedRegions: ["양천구", "영등포구", "마포구"],
    nextHeatCandidateScore: 69
  }),
  makeRegion({
    id: "guro",
    name: "구로구",
    weeklyHistory: [31, 32, 34, 36, 38, 40, 43, 45, 48, 50, 52, 54],
    volumeStrength: 55,
    priceRiseRatio: 54,
    risingComplexRatio: 52,
    reasons: [
      "저가 매수 관심이 일부 단지에 먼저 나타났어요.",
      "상승 거래 비율은 관망 구간을 막 넘었어요.",
      "금천구와 양천구 흐름을 함께 봐야 해요."
    ],
    linkedRegions: ["금천구", "양천구", "영등포구"],
    nextHeatCandidateScore: 62
  }),
  makeRegion({
    id: "geumcheon",
    name: "금천구",
    weeklyHistory: [29, 30, 32, 34, 36, 38, 40, 42, 44, 46, 48, 50],
    volumeStrength: 51,
    priceRiseRatio: 50,
    risingComplexRatio: 49,
    reasons: [
      "거래가 조금씩 늘며 관망에서 회복으로 넘어왔어요.",
      "상승 단지는 아직 많지 않아 확인이 필요해요.",
      "구로구와 관악구 흐름이 같이 움직이는지 봐야 해요."
    ],
    linkedRegions: ["구로구", "관악구", "영등포구"],
    nextHeatCandidateScore: 55
  }),
  makeRegion({
    id: "gwanak",
    name: "관악구",
    weeklyHistory: [30, 31, 33, 35, 38, 40, 43, 45, 48, 50, 53, 55],
    volumeStrength: 57,
    priceRiseRatio: 54,
    risingComplexRatio: 53,
    reasons: [
      "동작구와 서초구 주변 흐름을 따라 회복 중이에요.",
      "거래량은 좋아졌지만 상승 단지는 아직 제한적이에요.",
      "다음 4주에도 거래가 이어지는지 봐야 해요."
    ],
    linkedRegions: ["동작구", "서초구", "금천구"],
    nextHeatCandidateScore: 64
  }),
  makeRegion({
    id: "eunpyeong",
    name: "은평구",
    weeklyHistory: [30, 31, 33, 35, 37, 39, 42, 44, 46, 48, 50, 52],
    volumeStrength: 53,
    priceRiseRatio: 52,
    risingComplexRatio: 50,
    reasons: [
      "마포구와 서대문구 흐름 뒤에 관심이 생기고 있어요.",
      "아직은 관망과 회복 사이의 모습이에요.",
      "거래량이 더 늘어야 온기가 뚜렷해져요."
    ],
    linkedRegions: ["마포구", "서대문구", "강북구"],
    nextHeatCandidateScore: 66
  }),
  makeRegion({
    id: "seongbuk",
    name: "성북구",
    weeklyHistory: [31, 32, 34, 36, 38, 40, 42, 45, 47, 49, 51, 53],
    volumeStrength: 54,
    priceRiseRatio: 53,
    risingComplexRatio: 51,
    reasons: [
      "도심과 동북권 사이에서 회복 흐름이 보이고 있어요.",
      "상승 거래는 늘었지만 속도는 차분해요.",
      "동대문구와 강북구 흐름을 같이 봐야 해요."
    ],
    linkedRegions: ["동대문구", "강북구", "종로구"],
    nextHeatCandidateScore: 61
  }),
  makeRegion({
    id: "gangbuk",
    name: "강북구",
    weeklyHistory: [28, 29, 31, 33, 35, 37, 39, 41, 43, 45, 47, 49],
    volumeStrength: 50,
    priceRiseRatio: 49,
    risingComplexRatio: 48,
    reasons: [
      "저가 구간에서 문의가 늘지만 아직 관망이 더 커요.",
      "상승 단지 비율은 천천히 오르는 중이에요.",
      "성북구와 도봉구 흐름을 함께 확인해야 해요."
    ],
    linkedRegions: ["성북구", "도봉구", "노원구"],
    nextHeatCandidateScore: 53
  }),
  makeRegion({
    id: "dobong",
    name: "도봉구",
    weeklyHistory: [26, 27, 29, 31, 33, 35, 37, 39, 41, 43, 45, 47],
    volumeStrength: 48,
    priceRiseRatio: 47,
    risingComplexRatio: 46,
    reasons: [
      "냉각 구간을 벗어나 관망 단계에 가까워졌어요.",
      "거래 회복은 보이지만 상승 폭은 아직 작아요.",
      "노원구와 강북구 움직임을 함께 봐야 해요."
    ],
    linkedRegions: ["노원구", "강북구"],
    nextHeatCandidateScore: 49
  }),
  makeRegion({
    id: "nowon",
    name: "노원구",
    weeklyHistory: [27, 29, 31, 33, 35, 38, 41, 44, 47, 50, 52, 54],
    volumeStrength: 56,
    priceRiseRatio: 53,
    risingComplexRatio: 51,
    reasons: [
      "동북권 대단지 거래가 다시 살아나는 모습이에요.",
      "4주 변화가 커서 관망에서 회복으로 넘어왔어요.",
      "도봉구와 중랑구로 퍼지는지 볼 만해요."
    ],
    linkedRegions: ["도봉구", "중랑구", "강북구"],
    nextHeatCandidateScore: 68
  }),
  makeRegion({
    id: "jungnang",
    name: "중랑구",
    weeklyHistory: [29, 30, 32, 34, 36, 39, 42, 45, 48, 50, 52, 55],
    volumeStrength: 57,
    priceRiseRatio: 54,
    risingComplexRatio: 53,
    reasons: [
      "광진구와 동대문구 주변 흐름을 따라 회복 중이에요.",
      "거래량이 늘며 점수가 올라왔어요.",
      "상승 단지가 더 넓어지는지 확인해야 해요."
    ],
    linkedRegions: ["광진구", "동대문구", "노원구"],
    nextHeatCandidateScore: 70
  })
];

export {
  seoulMapSource,
  seoulRegionMapShapes as regionMapShapes
} from "@/lib/heatmap/seoul-map-shapes";

export const spreadRoutes: SpreadRoute[] = [
  {
    id: "gangnam-seocho",
    from: "gangnam",
    to: "seocho",
    strength: 86,
    description: "강남구에서 서초구로 가까운 생활권 온기가 이어져요."
  },
  {
    id: "gangnam-songpa",
    from: "gangnam",
    to: "songpa",
    strength: 82,
    description: "강남구의 상승 거래 흐름이 송파구 대단지로 번져요."
  },
  {
    id: "songpa-gangdong",
    from: "songpa",
    to: "gangdong",
    strength: 76,
    description: "송파구 회복 흐름이 강동구 대단지 관심으로 이어져요."
  },
  {
    id: "songpa-gwangjin",
    from: "songpa",
    to: "gwangjin",
    strength: 72,
    description: "송파구와 가까운 동부 생활권으로 관심이 넓어져요."
  },
  {
    id: "yeouido-mapo",
    from: "yeongdeungpo",
    to: "mapo",
    strength: 74,
    description: "여의도권 관심이 마포구로 이어지는 흐름을 가정했어요."
  },
  {
    id: "yeongdeungpo-dongjak",
    from: "yeongdeungpo",
    to: "dongjak",
    strength: 70,
    description: "영등포구 회복 흐름이 동작구로 천천히 이어져요."
  },
  {
    id: "yeongdeungpo-yangcheon",
    from: "yeongdeungpo",
    to: "yangcheon",
    strength: 68,
    description: "서남권 거래 관심이 양천구 쪽으로 넓어져요."
  },
  {
    id: "mapo-seodaemun",
    from: "mapo",
    to: "seodaemun",
    strength: 71,
    description: "마포구 온기가 서대문구 회복 신호로 이어져요."
  },
  {
    id: "mapo-eunpyeong",
    from: "mapo",
    to: "eunpyeong",
    strength: 66,
    description: "마포구와 가까운 서북권으로 관심이 퍼지는 흐름이에요."
  },
  {
    id: "yangcheon-gangseo",
    from: "yangcheon",
    to: "gangseo",
    strength: 69,
    description: "양천구 회복 흐름이 강서구로 번지는 모습을 가정했어요."
  },
  {
    id: "yangcheon-guro",
    from: "yangcheon",
    to: "guro",
    strength: 63,
    description: "양천구 주변 온기가 구로구 저가 구간으로 이어져요."
  },
  {
    id: "guro-geumcheon",
    from: "guro",
    to: "geumcheon",
    strength: 58,
    description: "구로구 관망 흐름이 금천구 회복 후보로 이어져요."
  },
  {
    id: "dongjak-gwanak",
    from: "dongjak",
    to: "gwanak",
    strength: 64,
    description: "동작구 거래 회복이 관악구 관심으로 이어질 수 있어요."
  },
  {
    id: "seocho-dongjak",
    from: "seocho",
    to: "dongjak",
    strength: 73,
    description: "서초구 온기가 가까운 동작구로 옮겨가는 경로예요."
  },
  {
    id: "yongsan-seongdong",
    from: "yongsan",
    to: "seongdong",
    strength: 79,
    description: "용산구 중심 입지 온기가 성동구로 확산되는 경로예요."
  },
  {
    id: "yongsan-jung",
    from: "yongsan",
    to: "jung",
    strength: 67,
    description: "용산구 관심이 도심 중구로 이어지는 흐름이에요."
  },
  {
    id: "seongdong-gwangjin",
    from: "seongdong",
    to: "gwangjin",
    strength: 77,
    description: "성동구 회복 흐름이 광진구로 넘어가는 후보 경로예요."
  },
  {
    id: "seongdong-dongdaemun",
    from: "seongdong",
    to: "dongdaemun",
    strength: 74,
    description: "성동구 온기가 동대문구 회복 신호로 이어져요."
  },
  {
    id: "dongdaemun-jungnang",
    from: "dongdaemun",
    to: "jungnang",
    strength: 61,
    description: "동대문구 주변 회복이 중랑구로 천천히 퍼져요."
  },
  {
    id: "jongno-jung",
    from: "jongno",
    to: "jung",
    strength: 62,
    description: "도심권 거래 흐름이 종로구와 중구 사이에서 이어져요."
  },
  {
    id: "jongno-seongbuk",
    from: "jongno",
    to: "seongbuk",
    strength: 59,
    description: "종로구 회복 신호가 성북구로 번지는 흐름이에요."
  },
  {
    id: "seongbuk-gangbuk",
    from: "seongbuk",
    to: "gangbuk",
    strength: 56,
    description: "성북구 흐름이 강북구 관망 구간으로 이어져요."
  },
  {
    id: "nowon-dobong",
    from: "nowon",
    to: "dobong",
    strength: 60,
    description: "노원구 대단지 회복이 도봉구로 이어지는 경로예요."
  },
  {
    id: "nowon-jungnang",
    from: "nowon",
    to: "jungnang",
    strength: 62,
    description: "노원구 회복 흐름이 중랑구 쪽으로 넓어져요."
  },
  {
    id: "nowon-gangbuk",
    from: "nowon",
    to: "gangbuk",
    strength: 57,
    description: "노원구 온기가 강북구 저가 구간 관심으로 이어져요."
  }
];
