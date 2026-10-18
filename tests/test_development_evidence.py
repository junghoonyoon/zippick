"""Shared regressions for news, cached data, cards and the complex report."""
import datetime
import json
import re
import shutil
import subprocess
import unittest
from unittest import mock

from tests.test_news_catalysts import ROOT, _article, news_catalysts


class DevelopmentEvidenceTest(unittest.TestCase):
    def cases(self):
        year = datetime.date.today().year
        return [
            ({"buildingAge": 5}, False),
            ({"buildingAge": "5"}, False),
            ({"buildingAge": 0}, False),
            ({"buildYear": year - 5}, False),
            ({"approvedAt": f"{year - 5}-04-07"}, False),
            ({"buildingAge": 40, "buildYear": year - 5}, False),
            ({"buildingAge": 40, "status": "분양권"}, False),
            ({"buildingAge": "unknown"}, False),
            ({"buildingAge": "Infinity"}, False),
            ({}, False),
            ({"buildingAge": 19}, False),
            ({"buildingAge": 20}, True),
            ({"buildYear": year - 40}, True),
            ({"approvedAt": f"{year - 40}-04-07"}, True),
        ]

    def test_backend_rejects_unknown_young_conflicting_and_presale_metadata(self):
        for metadata, allowed in self.cases():
            for title in ("재개발 추진", "재건축 조합설립인가", "재개발 현장"):
                with self.subTest(metadata=metadata, title=title):
                    apartment = {"name": "평촌어바인퍼스트", **metadata}
                    articles = [_article(f"평촌어바인퍼스트 {title}")]
                    self.assertEqual(news_catalysts._own_development_allowed(apartment), allowed)
                    if not allowed:
                        self.assertIsNone(news_catalysts._select_catalyst(articles, apartment))
                        self.assertEqual(news_catalysts._select_related_news(articles, apartment), [])

    def test_cached_bundle_is_revalidated_and_area_transport_news_survives(self):
        own = {"scope": "complex", "title": "검증아파트 재개발 추진", "label": "재개발 추진"}
        area = {"scope": "area", "title": "옆 단지 재개발 추진"}
        transport = {"scope": "complex", "title": "검증아파트 GTX 개통", "category": "transport"}
        cached = {"catalyst": own, "news": [own, area, transport]}
        with mock.patch.object(news_catalysts, "configured", return_value=True), \
             mock.patch.object(news_catalysts, "_read_cache", return_value=cached), \
             mock.patch.object(news_catalysts, "_search_articles") as search:
            result = news_catalysts.news_bundle_for_apartment({"buildingAge": 5})
        self.assertEqual(result, {"catalyst": None, "news": [area, transport]})
        search.assert_not_called()
        self.assertNotEqual(news_catalysts._cache_key({"name": "검증아파트"}),
                            news_catalysts._cache_key({"name": "검증아파트", "buildingAge": 5}))

    @unittest.skipUnless(shutil.which("node"), "Node.js required")
    def test_frontend_blocks_stale_news_and_official_zone_in_all_shared_outputs(self):
        html = (ROOT / "앱화면" / "real-estate-search.html").read_text(encoding="utf-8")
        names = [
            "zippickDevelopmentArticleSignalAllowed", "zippickOwnDevelopmentNewsAllowed",
            "zippickValidatedNewsBundle", "zippickDevelopmentEvidenceText",
            "zippickDevelopmentExclusionText", "zippickDevelopmentRows",
            "zippickConfirmedOwnDevelopmentRow", "zippickOwnDevelopmentProgressRow",
            "zippickOwnDevelopmentRows", "zippickOwnDevelopmentZones",
            "zippickDevelopmentSelfMatch", "zippickDevelopmentHtml",
            "candidateChoiceCatalyst", "candidateRelatedNewsHtml",
            "zippickDevelopmentCompletedOfficialZone", "zippickActiveOfficialDevelopmentZones",
            "zippickDevelopmentIdentityKeys", "zippickDevelopmentOfficialZoneSelfMatch", "zippickOwnDevelopmentWord",
            "zippickConfirmedOwnDevelopmentRows",
        ]
        functions = []
        for name in names:
            functions.append(re.search(
                rf"    function {name}\(.*?\n    \}}", html, re.DOTALL,
            ).group(0))
        constants = re.findall(r"    const ZIPPICK_(?:DEVELOPMENT_PATTERN|DEVELOPMENT_EXCLUDED_PATTERN|MINIMUM_ARTICLE_RECONSTRUCTION_AGE|OWN_DEVELOPMENT_BOUNDARY_TOLERANCE_METERS) = .*?;", html)
        script = "\n".join(constants + functions) + r"""
          const assert = require('node:assert/strict');
          function compactText(value) { return String(value || '').replace(/\s+/g, ''); }
          function candidateDisplayName(item) { return item.name; }
          const own = {scope:'complex', status:'confirmed', title:'검증아파트 재개발 조합설립인가',
            label:'재개발 조합설립인가', eventLabel:'재개발 조합설립인가', url:'https://example.com/own'};
          const zone = {inside:true, name:'검증아파트 재개발', projectType:'재개발', stage:'조합설립인가'};
          const area = {...own, scope:'area', title:'옆 단지 재개발', url:'https://example.com/area'};
          const transport = {scope:'complex', category:'transport', title:'GTX 개통'};
        """ + f"const cases = {json.dumps(self.cases())};" + """
          for (const [metadata, allowed] of cases) {
            const item = {name:'검증아파트', ...metadata, newsCatalyst:own, relatedNews:[own],
              zippickDevelopmentInsight:{zones:[zone]}};
            assert.equal(zippickDevelopmentArticleSignalAllowed(item), allowed);
            assert.equal(zippickDevelopmentSelfMatch(item, [own], [zone]), allowed);
            assert.equal(zippickOwnDevelopmentZones(item, [zone]).length > 0, allowed);
            if (!allowed) {
              assert.equal(zippickDevelopmentHtml(item), '');
              assert.equal(zippickOwnDevelopmentWord(item), '');
              assert.equal(candidateChoiceCatalyst(item), null);
              assert.equal(candidateRelatedNewsHtml(item), '');
              assert.deepEqual(zippickDevelopmentRows(item), []);
              item.relatedNews = [own, area, transport];
              assert.deepEqual(zippickValidatedNewsBundle(item), {catalyst:null, news:[area, transport]});
            }
          }
          const namseong = {name:'남성', aliases:['남성맨션아파트', '문래동 남성'], buildingAge:43};
          const namseongZone = {inside:true, distanceMeters:0, name:'문래동남성아파트',
            projectType:'재건축(공동)', stage:'사업시행인가'};
          assert.equal(zippickDevelopmentOfficialZoneSelfMatch(namseong, namseongZone), true);
          assert.equal(zippickOwnDevelopmentZones(namseong, [namseongZone]).length, 1);

          const boundaryGeocode = {...namseongZone, inside:false, distanceMeters:35};
          assert.equal(zippickOwnDevelopmentZones(namseong, [boundaryGeocode]).length, 1);
          assert.equal(zippickOwnDevelopmentZones(namseong, [
            {...boundaryGeocode, distanceMeters:51},
          ]).length, 0);
          assert.equal(zippickOwnDevelopmentZones(namseong, [
            {...namseongZone, name:'문래동국화아파트'},
          ]).length, 0);

          const rainbow = {name:'무지개', aliases:['무지개아파트', '시흥무지개아파트'], buildingAge:40};
          assert.equal(zippickOwnDevelopmentZones(rainbow, [{inside:true, distanceMeters:0,
            name:'시흥무지개아파트', projectType:'재건축(공동)', stage:'사업시행인가'}]).length, 1);

          const daerimShindonga = {name:'신동아', aliases:['신동아아파트'], buildingAge:40};
          assert.equal(zippickOwnDevelopmentZones(daerimShindonga, [{inside:false, distanceMeters:2793,
            name:'양평동신동아아파트', projectType:'재건축(공동)', stage:'조합설립인가'}]).length, 0);
        """
        subprocess.run(["node"], input=script, text=True, capture_output=True, check=True)
