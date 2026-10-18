"""시범 단지의 반경 1.5km 공식 필지 경계를 수집한다. 점수는 계산하지 않는다."""

import argparse

from kakao_station_distances import cached_record
from future_transformation import registry_entity
from vworld_cadastral import CadastralError, audit_building_join, fetch_radius, store_snapshot


PILOTS = {
    "seongnam": "484457631ccb1633",  # 산성역 헤리스톤
    "imun": "449db7d556b8ba86",      # 이문 아이파크 자이
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pilot", choices=tuple(PILOTS) + ("all",))
    parser.add_argument("--domain", help="브이월드 인증키에 등록된 도메인(필요한 경우)")
    parser.add_argument("--commercial-approval", help="브이월드 상업적 이용 허락의 확인 번호")
    parser.add_argument("--storage-approval", help="브이월드 API 데이터 저장 승낙의 확인 번호")
    args = parser.parse_args()
    if not (args.commercial_approval or "").strip() or not (args.storage_approval or "").strip():
        parser.error("집픽 서비스에 사용하려면 브이월드의 상업적 이용 허락과 데이터 저장 승낙을 각각 확인해 주세요.")
    names = PILOTS if args.pilot == "all" else {args.pilot: PILOTS[args.pilot]}
    for name, apartment_id in names.items():
        entity = registry_entity(apartment_id)
        position = cached_record(entity) if entity else None
        if (not position or position.get("status") != "ok"
                or not position.get("latitude") or not position.get("longitude")):
            parser.exit(1, f"{name}: 기존 단지의 위치 좌표를 확인할 수 없습니다.\n")
        try:
            snapshot = fetch_radius(apartment_id, position["latitude"], position["longitude"],
                                    domain=args.domain)
            snapshot["centerSource"] = {"source": position["source"],
                                        "matchedAddress": position.get("matchedAddress"),
                                        "fetchedAt": position["fetchedAt"]}
            store_snapshot(snapshot)
        except (CadastralError, ValueError) as exc:
            parser.exit(1, f"{name}: {exc}\n")
        print(f"{name}: 반경 1.5km 필지 {len(snapshot['features'])}개 저장 "
              f"({len(snapshot['tileCounts'])}개 구역 조회). 점수는 아직 계산하지 않습니다.")
        audit = audit_building_join(snapshot)
        if audit["missingDongCodes"]:
            print(f"{name}: 건축HUB 법정동 자료가 더 필요합니다: "
                  f"{', '.join(audit['missingDongCodes'])}")
        else:
            print(f"{name}: 필지번호로 연결한 건축물 표제부 "
                  f"{audit['buildingRecordCountOnMatchedParcels']}건. "
                  "용도·연식·사업 경계 검증 전에는 점수를 매기지 않습니다.")


if __name__ == "__main__":
    main()
