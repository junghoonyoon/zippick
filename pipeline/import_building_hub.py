"""건축HUB 표제부를 한 필지씩 가져온다. 점수는 계산하지 않는다."""

import argparse

from building_hub import (BuildingHubError, fetch_dong_records, fetch_title_records,
                          store_dong_snapshot, store_snapshot)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sigungu_cd", help="시군구 5자리 코드")
    parser.add_argument("bjdong_cd", help="법정동 5자리 코드")
    parser.add_argument("bun", nargs="?", help="본번 4자리 (예: 0028)")
    parser.add_argument("ji", nargs="?", help="부번 4자리 (예: 0004)")
    parser.add_argument("--dong", action="store_true", help="법정동 전체 표제부 조회")
    parser.add_argument("--plat-gb-cd", default="0", choices=("0", "1", "2"), help="0 대지, 1 산, 2 블록")
    args = parser.parse_args()
    if args.dong and (args.bun or args.ji):
        parser.error("--dong에는 본번·부번을 넣지 않습니다.")
    if not args.dong and (not args.bun or not args.ji):
        parser.error("한 필지를 조회할 때는 본번과 부번이 모두 필요합니다.")
    try:
        if args.dong:
            snapshot = fetch_dong_records(args.sigungu_cd, args.bjdong_cd)
            scope_id = store_dong_snapshot(snapshot)
        else:
            snapshot = fetch_title_records(args.sigungu_cd, args.bjdong_cd, args.bun, args.ji,
                                           plat_gb_cd=args.plat_gb_cd)
            scope_id = store_snapshot(snapshot)
    except (BuildingHubError, ValueError) as exc:
        parser.exit(1, f"자료 저장 실패: {exc}\n")
    print(f"건축HUB 표제부 저장 완료: {'법정동' if args.dong else '필지'} {scope_id}, 건물 {snapshot['totalCount']}건")


if __name__ == "__main__":
    main()
