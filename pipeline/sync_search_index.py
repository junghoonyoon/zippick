#!/usr/bin/env python3
"""부동산 채널 로스터 기반 검색 인덱스를 갱신한다."""
import config
import real_estate_search


def main():
    channels = config.ready_channels()
    if not channels:
        real_estate_search.save_index([])
        print("채널 ID가 아직 없어 빈 인덱스를 저장했어요. 검색 시 YouTube 최신 검색으로 보강합니다.")
        return 0
    real_estate_search.sync_index(channels)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
