import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path
APP_HTML = Path(__file__).resolve().parents[1] / "앱화면/real-estate-search.html"

class FrontendRemoteRegressionTest(unittest.TestCase):
    def test_report_refresh_keeps_complex_identity_and_repaints_open_report(self):
        html = APP_HTML.read_text(encoding="utf-8")
        fetch_start = html.index("    async function fetchAptReport(name, region, context = {}) {")
        fetch_end = html.index("    async function ensureCandidateCommuteProfile", fetch_start)
        fetch = html[fetch_start:fetch_end]
        self.assertIn('params.set("apartment_id", context.apartmentId)', fetch)
        self.assertIn('params.set("kapt_code", context.kaptCode)', fetch)
        self.assertIn('params.set("complex_no", context.complexNo)', fetch)
        self.assertIn("void refreshLocationScoreSheet(report, rerender, {force:true});", html)
        self.assertIn("stillSelected() && currentAptReportItem === report", html)
        self.assertIn("rowsToRefresh.forEach(row => Object.assign(row, payload.candidate))", html)
        self.assertIn("repaintCandidateScoreBadges(item, originalKey, previousRowKeys)", html)
        payload_start = html.index("    function locationScoreRefreshPayload(item) {")
        payload_end = html.index("    async function refreshLocationScoreSheet", payload_start)
        payload = html[payload_start:payload_end]
        for identity in ("apartmentId", "kaptCode", "complexNo"):
            self.assertIn(f"{identity}:item?.{identity}", payload)

    def test_location_score_refresh_repaints_matching_search_and_budget_cards(self):
        html = APP_HTML.read_text(encoding="utf-8")
        identity_start = html.index("    function candidateScoreAreaIdentity(item) {")
        identity_end = html.index("    function syncAptSearchCandidateData", identity_start)
        identity_helpers = html[identity_start:identity_end]
        start = html.index("    function repaintCandidateScoreBadges(item, originalKey, previousRowKeys = []) {")
        end = html.index("    function aptSearchMapRows()", start)
        repaint_body = html[start:end]
        script = f"""
          const candidate = {{apartmentId:'complex-1',name:'송도',region:'연수구',legalDong:'송도동',jibun:'308-1',displayAreaLabel:'전용 84.9㎡',locationScore:{{score:74}}}};
          const currentAptSearchItems = [
            {{...candidate,displayAreaLabel:'84㎡',locationScore:{{score:69}}}},
            {{...candidate,displayAreaLabel:'74.99㎡',locationScore:{{score:62}}}},
          ];
          const candidateRowsForLookup = () => currentAptSearchItems;
          const compactText = value => String(value || '').replace(/\\s+/g,'').toLowerCase();
          const candidateDisplayName = row => row.displayName || row.name || '';
          const parcelIdentityKey = value => String(value || '').replace(/\\s+/g,'');
          const candidateIdentityKey = row => `${{row.apartmentId}}|${{row.displayAreaLabel}}`;
          const sameCandidateIdentity = (left,right) => left.apartmentId === right.apartmentId
            && left.region === right.region && left.legalDong === right.legalDong && left.jibun === right.jibun;
          {identity_helpers}
          const rowsToRefresh = candidateRowsForLookup().filter(row => sameCandidateScoreIdentity(row,candidate));
          rowsToRefresh.forEach(row => Object.assign(row,{{locationScore:candidate.locationScore}}));
          const candidateTopScoreBadgesHtml = row => `score:${{row.locationScore.score}}`;
          const searchBadges = [{{innerHTML:''}},{{innerHTML:'score:62'}}];
          const aptSearchResults = {{querySelector:selector => ({{querySelector:() => searchBadges[Number(selector.match(/\\d+/)[0])]}})}};
          const budgetBadges = [{{innerHTML:''}},{{innerHTML:'score:62'}}];
          const budgetCards = [
            {{dataset:{{candidateKey:candidateIdentityKey(currentAptSearchItems[0])}},querySelector:() => budgetBadges[0]}},
            {{dataset:{{candidateKey:candidateIdentityKey(currentAptSearchItems[1])}},querySelector:() => budgetBadges[1]}},
          ];
          const budgetResultEl = {{querySelectorAll:() => budgetCards}};
          {repaint_body}
          repaintCandidateScoreBadges(candidate, 'complex-1');
          console.log(JSON.stringify([rowsToRefresh.length,searchBadges.map(row => row.innerHTML),budgetBadges.map(row => row.innerHTML)]));
        """
        result = subprocess.run(["node"], input=script, text=True, capture_output=True, check=True)
        self.assertEqual(json.loads(result.stdout), [1, ["score:74", "score:62"], ["score:74", "score:62"]])

    def test_report_scores_sync_to_same_search_complex_and_area(self):
        html = APP_HTML.read_text(encoding="utf-8")
        identity_start = html.index("    function candidateScoreAreaIdentity(item) {")
        identity_end = html.index("    function syncAptSearchCandidateData", identity_start)
        identity_helpers = html[identity_start:identity_end]
        sync_start = html.index("    function syncCandidateReportScores(item) {")
        sync_end = html.index("    async function refreshLocationScoreSheet", sync_start)
        sync_body = html[sync_start:sync_end]
        script = f"""
          const report = {{apartmentId:'complex-1',name:'송도',region:'연수구',legalDong:'송도동',jibun:'308-1',displayAreaLabel:'전용 84.9㎡',locationScore:{{score:74}},signals:{{score:33}}}};
          const currentAptSearchItems = [
            {{...report,displayAreaLabel:'84㎡',locationScore:{{score:69}},signals:{{score:69}}}},
            {{...report,displayAreaLabel:'59㎡',locationScore:{{score:62}},signals:{{score:61}}}},
          ];
          const compactText = value => String(value || '').replace(/\\s+/g,'').toLowerCase();
          const candidateDisplayName = row => row.displayName || row.name || '';
          const parcelIdentityKey = value => String(value || '').replace(/\\s+/g,'');
          const candidateIdentityKey = row => `${{row.apartmentId}}|${{row.displayAreaLabel}}`;
          const sameCandidateIdentity = (left,right) => left.apartmentId === right.apartmentId
            && left.region === right.region && left.legalDong === right.legalDong && left.jibun === right.jibun;
          {identity_helpers}
          const candidateRowsForLookup = () => currentAptSearchItems;
          let refreshedKeys = [];
          const repaintCandidateScoreBadges = (item,key,previousKeys) => {{ refreshedKeys = previousKeys; }};
          {sync_body}
          syncCandidateReportScores(report);
          console.log(JSON.stringify([
            currentAptSearchItems.map(row => [row.locationScore.score,row.signals.score]),
            refreshedKeys,
          ]));
        """
        result = subprocess.run(["node"], input=script, text=True, capture_output=True, check=True)
        self.assertEqual(
            json.loads(result.stdout),
            [[[74, 33], [62, 61]], ["complex-1|84㎡"]],
        )

    def test_location_heading_labels_school_distance_as_straight_line(self):
        html = APP_HTML.read_text(encoding="utf-8")
        start = html.index("    function zippickLocationHeadingFact(item, part, positive) {")
        end = html.index("    // 공통 제목:", start)
        heading_body = html[start:end]
        script = f"""
          const zpNum = value => Number(value);
          const zpPartRatio = row => zpNum(row.points) / zpNum(row.maxPoints);
          {heading_body}
          const good = zippickLocationHeadingFact({{}}, {{key:'demand',details:[
            {{key:'station',status:'ok',points:12,maxPoints:15,reason:'신정네거리역 2호선 · 직선 725m'}},
            {{key:'education',status:'ok',points:12,maxPoints:15,reason:'서울남명초등학교 · 186m 거리'}},
          ]}}, true);
          const weak = zippickLocationHeadingFact({{}}, {{key:'demand',details:[
            {{key:'education',status:'ok',points:4,maxPoints:15,reason:'서울남명초등학교 · 186m 거리'}},
          ]}}, false);
          console.log(JSON.stringify([good, weak]));
        """
        result = subprocess.run(["node"], input=script, text=True, capture_output=True, check=True)
        good, weak = json.loads(result.stdout)
        self.assertEqual(good, "역은 직선 725m, 학교는 직선 186m로 가까워요")
        self.assertEqual(weak, "학교까지 직선 186m로 통학 거리를 확인해야 해요")
