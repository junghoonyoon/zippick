import type {
  FlowEdge,
  MarketFlowSnapshot,
  MarketPeriod,
  MarketStatus,
  RegionNode,
  RegionScope
} from "@/lib/market-flow/types";

type SeedNode = Omit<RegionNode, "heatScore" | "propagationScore" | "propagationDelta" | "transactionChange" | "priceMomentum"> & {
  scores: Record<MarketPeriod, number>;
  propagation: Record<MarketPeriod, number>;
  deltas: Record<MarketPeriod, number>;
  transactions: Record<MarketPeriod, number>;
  momentum: Record<MarketPeriod, number>;
  capitalOnly?: boolean;
};

type EdgeSeed = Omit<FlowEdge, "propagationScore" | "strength"> & {
  scores: Record<MarketPeriod, number>;
  strengths: Record<MarketPeriod, number>;
  capitalOnly?: boolean;
};

const periodAdjustments: Record<
  MarketPeriod,
  Partial<Record<string, MarketStatus>>
> = {
  "3m": {},
  "6m": {
    mapo: "leader",
    yeongdeungpo: "leader",
    gwangjin: "spreading",
    guro: "early"
  },
  "1y": {
    gwacheon: "leader",
    suji: "spreading",
    hanam: "spreading",
    nowon: "early"
  }
};

const seedNodes: SeedNode[] = [
  {
    id: "gangnam",
    name: "강남",
    shortName: "강남",
    x: 520,
    y: 395,
    status: "leader",
    scores: { "3m": 91, "6m": 86, "1y": 82 },
    propagation: { "3m": 81, "6m": 76, "1y": 72 },
    deltas: { "3m": 4, "6m": 2, "1y": 1 },
    transactions: { "3m": 18, "6m": 12, "1y": 9 },
    momentum: { "3m": 21, "6m": 18, "1y": 14 }
  },
  {
    id: "seongdong",
    name: "성동구",
    shortName: "성동",
    x: 565,
    y: 260,
    status: "spreading",
    scores: { "3m": 72, "6m": 69, "1y": 66 },
    propagation: { "3m": 78, "6m": 71, "1y": 63 },
    deltas: { "3m": 6, "6m": 4, "1y": 2 },
    transactions: { "3m": 23, "6m": 17, "1y": 10 },
    momentum: { "3m": 14, "6m": 11, "1y": 8 }
  },
  {
    id: "yeongdeungpo",
    name: "영등포구",
    shortName: "영등포",
    x: 405,
    y: 350,
    status: "leader",
    scores: { "3m": 86, "6m": 88, "1y": 79 },
    propagation: { "3m": 66, "6m": 73, "1y": 68 },
    deltas: { "3m": 3, "6m": 5, "1y": 2 },
    transactions: { "3m": 11, "6m": 16, "1y": 9 },
    momentum: { "3m": 18, "6m": 19, "1y": 12 }
  },
  {
    id: "yongsan",
    name: "용산",
    shortName: "용산",
    x: 485,
    y: 300,
    status: "leader",
    scores: { "3m": 79, "6m": 75, "1y": 71 },
    propagation: { "3m": 62, "6m": 66, "1y": 61 },
    deltas: { "3m": 2, "6m": 3, "1y": 1 },
    transactions: { "3m": 9, "6m": 12, "1y": 7 },
    momentum: { "3m": 16, "6m": 14, "1y": 10 }
  },
  {
    id: "mapo",
    name: "마포",
    shortName: "마포",
    x: 345,
    y: 295,
    status: "spreading",
    scores: { "3m": 68, "6m": 77, "1y": 69 },
    propagation: { "3m": 65, "6m": 74, "1y": 64 },
    deltas: { "3m": 3, "6m": 6, "1y": 2 },
    transactions: { "3m": 14, "6m": 20, "1y": 8 },
    momentum: { "3m": 10, "6m": 17, "1y": 9 }
  },
  {
    id: "gwangjin",
    name: "광진구",
    shortName: "광진",
    x: 655,
    y: 275,
    status: "spreading",
    scores: { "3m": 63, "6m": 70, "1y": 58 },
    propagation: { "3m": 68, "6m": 72, "1y": 57 },
    deltas: { "3m": 3, "6m": 5, "1y": 1 },
    transactions: { "3m": 17, "6m": 19, "1y": 6 },
    momentum: { "3m": 8, "6m": 12, "1y": 5 }
  },
  {
    id: "eunpyeong",
    name: "은평구",
    shortName: "은평",
    x: 365,
    y: 205,
    status: "spreading",
    scores: { "3m": 59, "6m": 63, "1y": 55 },
    propagation: { "3m": 58, "6m": 64, "1y": 52 },
    deltas: { "3m": 2, "6m": 4, "1y": 1 },
    transactions: { "3m": 10, "6m": 15, "1y": 5 },
    momentum: { "3m": 6, "6m": 9, "1y": 4 }
  },
  {
    id: "dongjak",
    name: "동작구",
    shortName: "동작",
    x: 445,
    y: 420,
    status: "spreading",
    scores: { "3m": 57, "6m": 61, "1y": 54 },
    propagation: { "3m": 55, "6m": 61, "1y": 51 },
    deltas: { "3m": 2, "6m": 3, "1y": 1 },
    transactions: { "3m": 9, "6m": 13, "1y": 5 },
    momentum: { "3m": 5, "6m": 8, "1y": 4 }
  },
  {
    id: "gwacheon",
    name: "과천",
    shortName: "과천",
    x: 500,
    y: 515,
    status: "early",
    scores: { "3m": 54, "6m": 67, "1y": 78 },
    propagation: { "3m": 74, "6m": 70, "1y": 76 },
    deltas: { "3m": 4, "6m": 3, "1y": 5 },
    transactions: { "3m": 18, "6m": 15, "1y": 19 },
    momentum: { "3m": 7, "6m": 10, "1y": 16 },
    capitalOnly: true
  },
  {
    id: "guri",
    name: "구리",
    shortName: "구리",
    x: 745,
    y: 205,
    status: "early",
    scores: { "3m": 49, "6m": 53, "1y": 57 },
    propagation: { "3m": 54, "6m": 56, "1y": 58 },
    deltas: { "3m": 2, "6m": 2, "1y": 2 },
    transactions: { "3m": 8, "6m": 9, "1y": 8 },
    momentum: { "3m": 4, "6m": 5, "1y": 6 },
    capitalOnly: true
  },
  {
    id: "hanam",
    name: "하남",
    shortName: "하남",
    x: 760,
    y: 335,
    status: "early",
    scores: { "3m": 51, "6m": 56, "1y": 65 },
    propagation: { "3m": 57, "6m": 59, "1y": 67 },
    deltas: { "3m": 2, "6m": 3, "1y": 4 },
    transactions: { "3m": 10, "6m": 12, "1y": 14 },
    momentum: { "3m": 5, "6m": 6, "1y": 9 },
    capitalOnly: true
  },
  {
    id: "suji",
    name: "수지",
    shortName: "수지",
    x: 610,
    y: 520,
    status: "early",
    scores: { "3m": 53, "6m": 58, "1y": 70 },
    propagation: { "3m": 60, "6m": 63, "1y": 73 },
    deltas: { "3m": 1, "6m": 2, "1y": 6 },
    transactions: { "3m": 7, "6m": 10, "1y": 17 },
    momentum: { "3m": 4, "6m": 6, "1y": 13 },
    capitalOnly: true
  },
  {
    id: "nowon",
    name: "노원구",
    shortName: "노원",
    x: 595,
    y: 145,
    status: "early",
    scores: { "3m": 48, "6m": 51, "1y": 59 },
    propagation: { "3m": 50, "6m": 54, "1y": 60 },
    deltas: { "3m": 1, "6m": 2, "1y": 3 },
    transactions: { "3m": 6, "6m": 8, "1y": 11 },
    momentum: { "3m": 3, "6m": 5, "1y": 7 }
  },
  {
    id: "gangdong",
    name: "강동구",
    shortName: "강동",
    x: 700,
    y: 360,
    status: "early",
    scores: { "3m": 50, "6m": 54, "1y": 57 },
    propagation: { "3m": 56, "6m": 58, "1y": 59 },
    deltas: { "3m": 2, "6m": 2, "1y": 2 },
    transactions: { "3m": 9, "6m": 10, "1y": 9 },
    momentum: { "3m": 4, "6m": 5, "1y": 6 }
  },
  {
    id: "guro",
    name: "구로구",
    shortName: "구로",
    x: 310,
    y: 430,
    status: "early",
    scores: { "3m": 47, "6m": 60, "1y": 53 },
    propagation: { "3m": 51, "6m": 62, "1y": 50 },
    deltas: { "3m": 1, "6m": 4, "1y": 1 },
    transactions: { "3m": 5, "6m": 14, "1y": 5 },
    momentum: { "3m": 3, "6m": 8, "1y": 4 }
  },
  {
    id: "gangbuk",
    name: "강북구",
    shortName: "강북",
    x: 510,
    y: 115,
    status: "early",
    scores: { "3m": 46, "6m": 50, "1y": 55 },
    propagation: { "3m": 49, "6m": 53, "1y": 56 },
    deltas: { "3m": 1, "6m": 2, "1y": 2 },
    transactions: { "3m": 5, "6m": 8, "1y": 8 },
    momentum: { "3m": 3, "6m": 4, "1y": 5 }
  },
  {
    id: "seocho",
    name: "서초구",
    shortName: "서초",
    x: 545,
    y: 480,
    status: "early",
    scores: { "3m": 56, "6m": 59, "1y": 62 },
    propagation: { "3m": 57, "6m": 60, "1y": 62 },
    deltas: { "3m": 2, "6m": 2, "1y": 2 },
    transactions: { "3m": 8, "6m": 10, "1y": 11 },
    momentum: { "3m": 6, "6m": 7, "1y": 8 }
  },
  {
    id: "songpa",
    name: "송파구",
    shortName: "송파",
    x: 695,
    y: 425,
    status: "early",
    scores: { "3m": 55, "6m": 58, "1y": 61 },
    propagation: { "3m": 56, "6m": 59, "1y": 61 },
    deltas: { "3m": 2, "6m": 2, "1y": 2 },
    transactions: { "3m": 9, "6m": 11, "1y": 12 },
    momentum: { "3m": 6, "6m": 7, "1y": 8 }
  },
  {
    id: "jung",
    name: "중구",
    shortName: "중구",
    x: 505,
    y: 322,
    status: "early",
    scores: { "3m": 44, "6m": 47, "1y": 49 },
    propagation: { "3m": 45, "6m": 48, "1y": 50 },
    deltas: { "3m": 1, "6m": 1, "1y": 1 },
    transactions: { "3m": 4, "6m": 5, "1y": 6 },
    momentum: { "3m": 3, "6m": 4, "1y": 5 }
  },
  {
    id: "jongno",
    name: "종로구",
    shortName: "종로",
    x: 476,
    y: 258,
    status: "early",
    scores: { "3m": 43, "6m": 46, "1y": 49 },
    propagation: { "3m": 44, "6m": 47, "1y": 50 },
    deltas: { "3m": 1, "6m": 1, "1y": 1 },
    transactions: { "3m": 4, "6m": 5, "1y": 6 },
    momentum: { "3m": 3, "6m": 4, "1y": 5 }
  },
  {
    id: "seodaemun",
    name: "서대문구",
    shortName: "서대문",
    x: 415,
    y: 281,
    status: "early",
    scores: { "3m": 45, "6m": 48, "1y": 50 },
    propagation: { "3m": 46, "6m": 49, "1y": 51 },
    deltas: { "3m": 1, "6m": 1, "1y": 1 },
    transactions: { "3m": 5, "6m": 6, "1y": 7 },
    momentum: { "3m": 3, "6m": 4, "1y": 5 }
  },
  {
    id: "seongbuk",
    name: "성북구",
    shortName: "성북",
    x: 539,
    y: 225,
    status: "early",
    scores: { "3m": 46, "6m": 49, "1y": 52 },
    propagation: { "3m": 47, "6m": 50, "1y": 53 },
    deltas: { "3m": 1, "6m": 2, "1y": 2 },
    transactions: { "3m": 5, "6m": 7, "1y": 8 },
    momentum: { "3m": 3, "6m": 4, "1y": 5 }
  },
  {
    id: "dongdaemun",
    name: "동대문구",
    shortName: "동대문",
    x: 601,
    y: 274,
    status: "early",
    scores: { "3m": 45, "6m": 48, "1y": 51 },
    propagation: { "3m": 46, "6m": 49, "1y": 52 },
    deltas: { "3m": 1, "6m": 1, "1y": 2 },
    transactions: { "3m": 5, "6m": 6, "1y": 7 },
    momentum: { "3m": 3, "6m": 4, "1y": 5 }
  },
  {
    id: "jungnang",
    name: "중랑구",
    shortName: "중랑",
    x: 656,
    y: 240,
    status: "early",
    scores: { "3m": 44, "6m": 47, "1y": 50 },
    propagation: { "3m": 45, "6m": 48, "1y": 51 },
    deltas: { "3m": 1, "6m": 1, "1y": 2 },
    transactions: { "3m": 4, "6m": 6, "1y": 7 },
    momentum: { "3m": 3, "6m": 4, "1y": 5 }
  },
  {
    id: "dobong",
    name: "도봉구",
    shortName: "도봉",
    x: 561,
    y: 100,
    status: "early",
    scores: { "3m": 42, "6m": 45, "1y": 48 },
    propagation: { "3m": 43, "6m": 46, "1y": 49 },
    deltas: { "3m": 1, "6m": 1, "1y": 1 },
    transactions: { "3m": 4, "6m": 5, "1y": 6 },
    momentum: { "3m": 2, "6m": 3, "1y": 4 }
  },
  {
    id: "gangseo",
    name: "강서구",
    shortName: "강서",
    x: 228,
    y: 313,
    status: "early",
    scores: { "3m": 45, "6m": 48, "1y": 50 },
    propagation: { "3m": 46, "6m": 49, "1y": 51 },
    deltas: { "3m": 1, "6m": 1, "1y": 1 },
    transactions: { "3m": 5, "6m": 6, "1y": 7 },
    momentum: { "3m": 3, "6m": 4, "1y": 5 }
  },
  {
    id: "yangcheon",
    name: "양천구",
    shortName: "양천",
    x: 286,
    y: 384,
    status: "early",
    scores: { "3m": 46, "6m": 49, "1y": 51 },
    propagation: { "3m": 47, "6m": 50, "1y": 52 },
    deltas: { "3m": 1, "6m": 1, "1y": 1 },
    transactions: { "3m": 5, "6m": 6, "1y": 7 },
    momentum: { "3m": 3, "6m": 4, "1y": 5 }
  },
  {
    id: "geumcheon",
    name: "금천구",
    shortName: "금천",
    x: 356,
    y: 516,
    status: "early",
    scores: { "3m": 43, "6m": 46, "1y": 48 },
    propagation: { "3m": 44, "6m": 47, "1y": 49 },
    deltas: { "3m": 1, "6m": 1, "1y": 1 },
    transactions: { "3m": 4, "6m": 5, "1y": 6 },
    momentum: { "3m": 2, "6m": 3, "1y": 4 }
  },
  {
    id: "gwanak",
    name: "관악구",
    shortName: "관악",
    x: 426,
    y: 498,
    status: "early",
    scores: { "3m": 44, "6m": 47, "1y": 50 },
    propagation: { "3m": 45, "6m": 48, "1y": 51 },
    deltas: { "3m": 1, "6m": 1, "1y": 2 },
    transactions: { "3m": 4, "6m": 6, "1y": 7 },
    momentum: { "3m": 3, "6m": 4, "1y": 5 }
  }
];

const edgeSeeds: EdgeSeed[] = [
  {
    id: "gangnam-seongdong",
    sourceRegionId: "gangnam",
    targetRegionId: "seongdong",
    lagMinMonths: 2,
    lagMaxMonths: 3,
    scores: { "3m": 78, "6m": 71, "1y": 63 },
    strengths: { "3m": 94, "6m": 75, "1y": 58 },
    confidence: "high",
    active: true,
    evidence: [
      {
        id: "gangnam-momentum",
        type: "source_price_momentum",
        label: "강남의 가격 모멘텀이 최근 상승했어요."
      },
      {
        id: "seongdong-volume",
        type: "target_transaction_growth",
        label: "성동구는 가격보다 거래가 먼저 늘고 있어요."
      },
      {
        id: "seongdong-ratio",
        type: "rising_complex_ratio",
        label: "일부 단지에서 상승 흐름이 주변 단지로 번지고 있어요."
      }
    ],
    risks: [
      {
        id: "delay",
        type: "reporting_delay",
        label: "최신 실거래 신고가 아직 모두 반영되지 않았어요."
      },
      {
        id: "single-complex",
        type: "single_complex_bias",
        label: "일부 대장 단지 거래가 지역 평균에 영향을 줄 수 있어요."
      }
    ]
  },
  {
    id: "gangnam-gwacheon",
    sourceRegionId: "gangnam",
    targetRegionId: "gwacheon",
    lagMinMonths: 2,
    lagMaxMonths: 4,
    scores: { "3m": 74, "6m": 70, "1y": 76 },
    strengths: { "3m": 78, "6m": 68, "1y": 86 },
    confidence: "medium",
    active: true,
    capitalOnly: true,
    evidence: [
      {
        id: "gwacheon-gap",
        type: "price_gap",
        label: "강남과 가까운 생활권에서 가격 차이를 보는 수요가 있어요."
      },
      {
        id: "gwacheon-volume",
        type: "target_transaction_growth",
        label: "과천은 거래 회복 신호가 먼저 확인돼요."
      }
    ],
    risks: [
      {
        id: "gwacheon-sample",
        type: "small_sample",
        label: "거래 표본이 적은 달은 점수가 크게 움직일 수 있어요."
      }
    ]
  },
  {
    id: "seongdong-gwangjin",
    sourceRegionId: "seongdong",
    targetRegionId: "gwangjin",
    lagMinMonths: 1,
    lagMaxMonths: 2,
    scores: { "3m": 68, "6m": 72, "1y": 57 },
    strengths: { "3m": 70, "6m": 82, "1y": 45 },
    confidence: "medium",
    active: true,
    evidence: [
      {
        id: "gwangjin-volume",
        type: "target_transaction_growth",
        label: "광진구 거래량이 직전 기간보다 늘었어요."
      },
      {
        id: "seongdong-link",
        type: "source_transaction_growth",
        label: "성동구와 가까운 축에서 관심 이동이 보여요."
      }
    ],
    risks: [
      {
        id: "gwangjin-delay",
        type: "reporting_delay",
        label: "최근 계약은 신고 지연으로 나중에 바뀔 수 있어요."
      }
    ]
  },
  {
    id: "yeongdeungpo-mapo",
    sourceRegionId: "yeongdeungpo",
    targetRegionId: "mapo",
    lagMinMonths: 2,
    lagMaxMonths: 4,
    scores: { "3m": 65, "6m": 74, "1y": 64 },
    strengths: { "3m": 66, "6m": 88, "1y": 61 },
    confidence: "high",
    active: true,
    evidence: [
      {
        id: "mapo-office",
        type: "price_gap",
        label: "여의도 업무지구와 가까운 지역으로 관심이 옮겨가요."
      },
      {
        id: "mapo-ratio",
        type: "rising_complex_ratio",
        label: "마포 일부 단지의 상승 단지 비율이 늘었어요."
      }
    ],
    risks: [
      {
        id: "mapo-bias",
        type: "single_complex_bias",
        label: "한두 단지의 고가 거래가 평균을 밀어 올릴 수 있어요."
      }
    ]
  },
  {
    id: "mapo-eunpyeong",
    sourceRegionId: "mapo",
    targetRegionId: "eunpyeong",
    lagMinMonths: 2,
    lagMaxMonths: 3,
    scores: { "3m": 58, "6m": 64, "1y": 52 },
    strengths: { "3m": 52, "6m": 72, "1y": 40 },
    confidence: "medium",
    active: true,
    evidence: [
      {
        id: "eunpyeong-volume",
        type: "target_transaction_growth",
        label: "은평구는 낮은 가격대 단지에서 거래가 살아나요."
      }
    ],
    risks: [
      {
        id: "eunpyeong-supply",
        type: "supply_risk",
        label: "입주 물량이 늘면 흐름이 약해질 수 있어요."
      }
    ]
  },
  {
    id: "yeongdeungpo-dongjak",
    sourceRegionId: "yeongdeungpo",
    targetRegionId: "dongjak",
    lagMinMonths: 2,
    lagMaxMonths: 3,
    scores: { "3m": 55, "6m": 61, "1y": 51 },
    strengths: { "3m": 54, "6m": 66, "1y": 39 },
    confidence: "medium",
    active: true,
    evidence: [
      {
        id: "dongjak-volume",
        type: "target_transaction_growth",
        label: "동작구 거래가 가격보다 먼저 움직이고 있어요."
      }
    ],
    risks: [
      {
        id: "dongjak-sample",
        type: "small_sample",
        label: "거래가 적은 단지는 최신 매물 확인이 필요해요."
      }
    ]
  },
  {
    id: "gangnam-suji",
    sourceRegionId: "gangnam",
    targetRegionId: "suji",
    lagMinMonths: 3,
    lagMaxMonths: 5,
    scores: { "3m": 60, "6m": 63, "1y": 73 },
    strengths: { "3m": 49, "6m": 56, "1y": 83 },
    confidence: "medium",
    active: true,
    capitalOnly: true,
    evidence: [
      {
        id: "suji-gap",
        type: "price_gap",
        label: "강남보다 낮은 가격대의 남부 생활권을 함께 봐요."
      }
    ],
    risks: [
      {
        id: "suji-delay",
        type: "reporting_delay",
        label: "수도권 외곽 거래는 신고 시차를 더 확인해야 해요."
      }
    ]
  },
  {
    id: "gwangjin-guri",
    sourceRegionId: "gwangjin",
    targetRegionId: "guri",
    lagMinMonths: 2,
    lagMaxMonths: 4,
    scores: { "3m": 54, "6m": 56, "1y": 58 },
    strengths: { "3m": 43, "6m": 50, "1y": 55 },
    confidence: "low",
    active: true,
    capitalOnly: true,
    evidence: [
      {
        id: "guri-volume",
        type: "target_transaction_growth",
        label: "구리는 낮은 가격대에서 거래 회복이 보이기 시작했어요."
      }
    ],
    risks: [
      {
        id: "guri-sample",
        type: "small_sample",
        label: "표본이 작아서 다음 달 보정이 필요해요."
      }
    ]
  }
];

function buildNodes(period: MarketPeriod, scope: RegionScope): RegionNode[] {
  return seedNodes
    .filter((node) => scope === "capital" || !node.capitalOnly)
    .map((node) => ({
      id: node.id,
      name: node.name,
      shortName: node.shortName,
      x: node.x,
      y: node.y,
      status: periodAdjustments[period][node.id] ?? node.status,
      heatScore: node.scores[period],
      propagationScore: node.propagation[period],
      propagationDelta: node.deltas[period],
      transactionChange: node.transactions[period],
      priceMomentum: node.momentum[period]
    }));
}

function buildEdges(period: MarketPeriod, scope: RegionScope): FlowEdge[] {
  const visibleNodeIds = new Set(buildNodes(period, scope).map((node) => node.id));

  return edgeSeeds
    .filter(
      (edge) =>
        visibleNodeIds.has(edge.sourceRegionId) &&
        visibleNodeIds.has(edge.targetRegionId)
    )
    .map((edge) => ({
      id: edge.id,
      sourceRegionId: edge.sourceRegionId,
      targetRegionId: edge.targetRegionId,
      lagMinMonths: edge.lagMinMonths,
      lagMaxMonths: edge.lagMaxMonths,
      propagationScore: edge.scores[period],
      confidence: edge.confidence,
      strength: edge.strengths[period],
      active: edge.active,
      evidence: edge.evidence,
      risks: edge.risks
    }))
    .sort((a, b) => b.strength - a.strength)
    .slice(0, 7);
}

export const marketFlowSnapshots: MarketFlowSnapshot[] = (
  ["3m", "6m", "1y"] as MarketPeriod[]
).flatMap((period) =>
  (["seoul", "capital"] as RegionScope[]).map((scope) => ({
    period,
    regionScope: scope,
    baseDate: "2026년 7월 실거래 기준",
    nodes: buildNodes(period, scope),
    edges: buildEdges(period, scope)
  }))
);
