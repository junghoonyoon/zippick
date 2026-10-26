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
            "zippickOwnDevelopmentModel",
            "candidateChoiceCatalyst", "candidateRelatedNewsHtml",
            "zippickDevelopmentCompletedOfficialZone", "zippickActiveOfficialDevelopmentZones",
            "zippickDevelopmentIdentityKeys", "zippickDevelopmentOfficialZoneSelfMatch", "zippickOwnDevelopmentWord",
            "zippickConfirmedOwnDevelopmentRows",
            "zippickDevelopmentStageTier", "zippickDevelopmentProjectWord",
            "zippickDevelopmentRatingView", "zippickDevelopmentRatingBasisHtml",
            "zippickSectionRatingData", "zippickSectionRatingHtml", "zippickNumberSteps",
        ]
        functions = []
        for name in names:
            functions.append(re.search(
                rf"    function {name}\(.*?\n    \}}", html, re.DOTALL,
            ).group(0))
        constants = re.findall(r"    const ZIPPICK_(?:DEVELOPMENT_PATTERN|DEVELOPMENT_EXCLUDED_PATTERN|MINIMUM_ARTICLE_RECONSTRUCTION_AGE|OWN_DEVELOPMENT_BOUNDARY_TOLERANCE_METERS) = .*?;", html)
        constants.append(re.search(r"    const ZIPPICK_DEVELOPMENT_STAGE_RATINGS = \[.*?\n    \];", html, re.S).group())
        script = "\n".join(constants + functions) + r"""
          const assert = require('node:assert/strict');
          function compactText(value) { return String(value || '').replace(/\s+/g, ''); }
          function candidateDisplayName(item) { return item.name; }
          const own = {scope:'complex', status:'confirmed', title:'검증아파트 재개발 조합설립인가',
            label:'재개발 조합설립인가', eventLabel:'재개발 조합설립인가', url:'https://example.com/own'};
          const zone = {inside:true, name:'검증아파트 재개발', projectType:'재개발', stage:'조합설립인가'};
          const area = {...own, scope:'area', title:'옆 단지 재개발', url:'https://example.com/area'};
          const transport = {scope:'complex', category:'transport', title:'GTX 개통'};
        """ + f"const cases = {json.dumps(self.cases())};" + r"""
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

          // Official planning areas must survive when the separate news request is absent.
          const misung = {apartmentId:'11380100000585', name:'미성아파트', displayName:'미성',
            legalDong:'불광동', jibun:'248', buildingAge:38};
          const misungZone = {id:'11000UQ120PS202407010944', name:'불광미성',
            districtCode:'11380', projectType:'신속통합기획', stage:'대상지선정(추진중)',
            inside:true, distanceMeters:0, source:'서울시 공식 공간정보'};
          assert.equal(zippickOwnDevelopmentZones(misung, [misungZone]).length, 1);
          assert.equal(zippickOwnDevelopmentZones({...misung, name:'미성'}, [misungZone]).length, 1);
          for (const otherZone of [
            {...misungZone, districtCode:'11710'},
            {...misungZone, name:'불광미성2차'},
            {...misungZone, name:'월계미성'},
            {...misungZone, inside:false, distanceMeters:51},
            {...misungZone, stage:'준공'},
            {...misungZone, projectType:'도시재생활성화지역'},
          ]) assert.equal(zippickOwnDevelopmentZones(misung, [otherZone]).length, 0);
          function esc(value) { return String(value); }
          function zpJosa(word, a, b) { return word + a; }
          function zippickDevelopmentDistanceText() { return '단지와 맞닿음'; }
          function zippickDevelopmentOfficialType(value) { return value; }
          const report = zippickDevelopmentHtml({...misung, zippickDevelopmentInsight:{zones:[misungZone]}});
          assert.match(report, /data-zpr-step="단지 변화"/);
          assert.match(report, /불광미성/);
          assert.match(report, /대상지선정\(추진중\)/);
          assert.doesNotMatch(report, /이 단지가 재건축 대상입니다/);
          const reference = {id:misungZone.id, name:'불광미성', districtCode:'11380',
            projectTypeLabel:'신속통합기획', stage:'planning', stageLabel:'대상지선정(추진중)',
            containsSubject:true, zoneKind:'renewal', businessNameConfirmed:true,
            distanceMeters:0, sourceUrl:'https://data.seoul.go.kr/official', sourceDate:'2026-09-10'};
          const withoutExtraRequests = {...misung, futureTransformation:{apartmentId:misung.apartmentId, subjectZoneReferences:[reference]}};
          const initialReport = zippickDevelopmentHtml(withoutExtraRequests);
          assert.match(initialReport, /data-zpr-step="단지 변화"/);
          assert.match(initialReport, /불광미성/);
          assert.equal(zippickOwnDevelopmentZones(withoutExtraRequests, [misungZone]).length, 1);
          for (const invalid of [
            {...reference, containsSubject:false}, {...reference, zoneKind:'reference'},
            {...reference, businessNameConfirmed:false}, {...reference, districtCode:'11710'},
            {...reference, stage:'completed'},
          ]) assert.equal(zippickDevelopmentHtml({...misung,
            futureTransformation:{apartmentId:misung.apartmentId, subjectZoneReferences:[invalid]}}), '');
          assert.equal(zippickDevelopmentHtml({...misung,
            futureTransformation:{apartmentId:'another-complex', subjectZoneReferences:[reference]}}), '');
          const today = new Date().toISOString().slice(0,10);
          const rated = stage => ({...withoutExtraRequests, futureTransformation:{apartmentId:misung.apartmentId,
            subjectZoneReferences:[{...reference, stageLabel:stage, sourceDate:today}]}});
          for (const [stage, points] of [
            ['정비계획수립',1], ['대상지선정(추진중)',1.5], ['정비구역 지정',2],
            ['추진위구성',2.5], ['조합설립인가',3], ['사업시행계획인가',3.5],
            ['관리처분계획인가',4], ['이주중',4.5], ['착공',5],
          ]) {
            assert.equal(zippickDevelopmentRatingView(rated(stage)).points, points, stage);
            assert.equal(zippickSectionRatingData(rated(stage),'단지 변화').stars, points.toFixed(1));
          }
          const numbered = zippickNumberSteps(zippickDevelopmentHtml(rated('대상지선정(추진중)')),
            rated('대상지선정(추진중)'));
          assert.match(numbered, /단지 변화 · 추진 단계 1.5\/5/);
          assert.match(numbered, /기본 1.0점 \+ 단계 가점 0.5점/);
          for (const stage of ['착공 예정','조합설립인가 신청','조합설립인가 추진중(연번부여)',
            '진행 단계 확인 중','해제','취소','준공']) {
            assert.equal(zippickDevelopmentRatingView(rated(stage)).points,null,stage);
          }
          assert.equal(zippickDevelopmentRatingView({...misung, newsCatalyst:own}).points,null);
          const stale = rated('착공');
          stale.futureTransformation.subjectZoneReferences[0].sourceDate = '2000-01-01';
          assert.equal(zippickDevelopmentRatingView(stale).state,'missing');
          const untrusted = rated('착공');
          untrusted.futureTransformation.subjectZoneReferences[0].sourceUrl = 'https://example.com/news';
          assert.equal(zippickDevelopmentRatingView(untrusted).points,null);
          const conflicted = rated('조합설립인가');
          conflicted.futureTransformation.subjectZoneReferences.push({...reference,id:'another-boundary',
            stageLabel:'착공',sourceDate:today});
          assert.equal(zippickDevelopmentRatingView(conflicted).points,null);
          conflicted.futureTransformation.subjectZoneReferences[1].sourceDate = '2000-01-01';
          assert.equal(zippickDevelopmentRatingView(conflicted).points,3);
        """
        subprocess.run(["node"], input=script, text=True, capture_output=True, check=True)
