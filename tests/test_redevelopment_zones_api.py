import unittest

import search_server


class RedevelopmentZonesApiTest(unittest.TestCase):
    def test_map_api_excludes_completed_and_background_districts(self):
        cases = [
            {"name": "길음재정비촉진지구", "projectType": "재정비촉진지구", "stage": "지구지정"},
            {"name": "길음2구역", "projectType": "재정비촉진구역", "stage": "준공"},
            {"name": "길음1존치", "projectType": "존치관리구역", "stage": "단계 확인 필요"},
            {"name": "노량진재정비촉진지구 노량진10구역", "projectType": "존치관리구역", "stage": "단계 확인 필요"},
            {"name": "역세권 청년안심주택", "projectType": "청년안심주택", "stage": "사업계획승인"},
            {"name": "장기전세주택 예정지", "projectType": "장기전세주택", "stage": "지구계획승인"},
            {"name": "상도두산위브 트레지움", "projectType": "미리내집", "stage": "입주자 모집공고 완료"},
            {"id": "11000UQ120PS202411014108", "name": "신사1", "projectType": "재건축(단독)", "stage": "착공"},
        ]

        for zone in cases:
            with self.subTest(zone=zone["name"]):
                self.assertFalse(search_server._redevelopment_zone_active(zone))

    def test_map_api_keeps_active_project_zones(self):
        cases = [
            {"name": "길음5구역", "projectType": "재정비촉진구역", "stage": "조합설립인가"},
            {"name": "신길음", "projectType": "재개발(도시정비형)", "stage": "사업시행인가"},
            {"name": "장위14구역", "projectType": "재정비촉진구역", "stage": "건축심의"},
        ]

        for zone in cases:
            with self.subTest(zone=zone["name"]):
                self.assertTrue(search_server._redevelopment_zone_active(zone))

    def test_map_api_sorts_project_zones_before_broad_reference_rows(self):
        zones = [
            {"name": "초기 후보", "projectType": "정비사업", "stage": "구역지정", "areaSqm": 3000},
            {"name": "진행 재개발", "projectType": "재개발(주택정비형)", "stage": "사업시행인가", "areaSqm": 2000},
            {"name": "진행 촉진구역", "projectType": "재정비촉진구역", "stage": "관리처분계획인가", "areaSqm": 1000},
        ]

        sorted_zones = sorted(zones, key=search_server._redevelopment_zone_sort_key)

        self.assertEqual(sorted_zones[0]["name"], "진행 재개발")
        self.assertEqual(sorted_zones[1]["name"], "진행 촉진구역")

    def test_map_api_allows_full_visible_zone_payload(self):
        payload = search_server._redevelopment_zones_payload({
            "bbox": ["126.7,37.4,127.3,37.8"],
            "limit": ["3000"],
        })

        self.assertLessEqual(payload["count"], 3000)
        self.assertIn("limited", payload)


if __name__ == "__main__":
    unittest.main()
