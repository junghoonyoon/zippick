"""Regression checks for interrupted score loading and recovery.

Exercise the production JavaScript with controlled API responses. The tests do
not depend on live market data or arbitrary browser delays.
"""
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "앱화면" / "real-estate-search.html"


class BudgetScoreLifecycleTest(unittest.TestCase):
    def run_js(self, names, script):
        html = APP.read_text(encoding="utf-8")
        functions = []
        for name in names:
            match = re.search(
                r"^    (?:async )?function " + re.escape(name) + r"\([^\n]*\) \{.*?^    \}",
                html, re.M | re.S,
            )
            self.assertIsNotNone(match, name)
            functions.append(match.group())
        result = subprocess.run(
            ["node"], input="\n".join(functions) + "\n" + script,
            text=True, capture_output=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_reload_restarts_unfinished_scores_but_preserves_complete_results(self):
        self.run_js(["budgetStateNeedsRefresh"], """
          const assert=require('node:assert/strict');
          const CANDIDATE_RESULT_SCHEMA_VERSION=33;
          const locationScoreNeedsRefresh=row=>!!row.stale;
          const complete={candidateResultSchemaVersion:33,budgetEok:9.2,
            enrichmentPending:false,candidateScoreDataReady:true,candidates:[{stale:false}]};
          const saved={currentPurchasePower:{budgetEok:9.2},currentBudgetData:complete};
          assert.equal(budgetStateNeedsRefresh(saved),false);
          for (const flags of [{enrichmentPending:true},{initialStage:true},
                              {candidateScoreDataReady:false,enrichmentStage:'score_error'},
                              {candidateScoreDataReady:false,enrichmentStage:'timeout'}]) {
            assert.equal(budgetStateNeedsRefresh({...saved,currentBudgetData:{...complete,...flags}}),true);
          }
          assert.equal(budgetStateNeedsRefresh({...saved,currentBudgetData:{...complete,budgetEok:8}}),true);
          assert.equal(budgetStateNeedsRefresh({...saved,currentBudgetData:{...complete,candidates:[{stale:true}]}}),true);
        """)
        html = APP.read_text(encoding="utf-8")
        restore = re.search(r"function restoreNaverReturnState\(\) \{.*?\n    \}", html, re.S).group()
        self.assertLess(restore.index("budgetStateNeedsRefresh(saved)"), restore.index("renderBudgetCandidates(saved.currentBudgetData"))
        self.assertIn("void loadBudgetCandidates();", restore)

    def test_verified_rows_are_followed_by_completed_scores(self):
        self.run_js(["waitForCompletedBudgetCandidates"], """
          const assert=require('node:assert/strict');
          const controller=new AbortController();let budgetSearchController=controller;
          const budgetLoadingTimer=null;const waitForBudgetPoll=async()=>{};
          const rendered=[],cached=[];const renderBudgetCandidates=d=>rendered.push(d);
          const updateBudgetEnrichmentProgress=()=>{};const writeBudgetBrowserCache=(url,d)=>cached.push(d);
          const verified={verifiedResultReady:true,candidateScoreDataReady:false,candidates:[{name:'후보'}]};
          const final={done:true,enrichmentPending:false,candidateScoreDataReady:true,candidates:[{name:'후보',locationScore:{score:68}}]};
          const replies=[{done:false,verifiedResult:verified},final];
          const getBudgetProgress=async()=>replies.shift();
          (async()=>{
            const result=await waitForCompletedBudgetCandidates({enrichmentPending:true,enrichmentJobId:'job'},'/candidates',controller);
            assert.equal(rendered.length,1);assert.equal(rendered[0].candidateScoreDataReady,false);
            assert.equal(result.data,final);assert.equal(result.verifiedShown,true);
            assert.equal(cached.length,1);assert.equal(cached[0].enrichmentPending,false);
          })().catch(e=>{console.error(e);process.exitCode=1});
        """)

    def test_resumed_verified_job_can_finish_without_replacing_selection(self):
        self.run_js(["waitForCompletedBudgetCandidates"], """
          const assert=require('node:assert/strict');const controller=new AbortController();
          let budgetSearchController=controller;const budgetLoadingTimer=null;
          const waitForBudgetPoll=async()=>{};const updateBudgetEnrichmentProgress=()=>{};
          const writeBudgetBrowserCache=()=>{};const options=[];
          const renderBudgetCandidates=(data,opts)=>options.push(opts);
          const getBudgetProgress=async()=>({done:true,enrichmentPending:false,candidateScoreDataReady:true});
          (async()=>{
            const result=await waitForCompletedBudgetCandidates({enrichmentPending:true,enrichmentJobId:'resumed',
              verifiedResultReady:true,candidateScoreDataReady:false},'/candidates',controller);
            assert.equal(result.data.candidateScoreDataReady,true);
            assert.equal(options[0].preserveSelection,true);
          })().catch(e=>{console.error(e);process.exitCode=1});
        """)

    def test_terminal_score_failure_has_no_spinner(self):
        self.run_js(["candidateScorePendingHtml", "budgetBackgroundStatusHtml"], """
          const assert=require('node:assert/strict');const spinnerHtml=()=>'<i class="spinner"></i>';
          let currentBudgetData={enrichmentPending:true,candidateScoreDataReady:false};
          assert.match(candidateScorePendingHtml(),/spinner/);
          for(const stage of ['score_error','timeout']) {
            currentBudgetData={enrichmentPending:false,candidateScoreDataReady:false,enrichmentStage:stage};
            for(const html of [candidateScorePendingHtml(),budgetBackgroundStatusHtml(currentBudgetData)]) {
              assert.doesNotMatch(html,/spinner|계산하고 있어요/);assert.match(html,/다시 검색/);
            }
          }
          assert.equal(budgetBackgroundStatusHtml({candidateScoreDataReady:true}),'');
        """)

    def test_progress_request_timeout_and_user_cancellation_are_distinct(self):
        self.run_js(["getBudgetProgress"], """
          const assert=require('node:assert/strict');const parent=new AbortController();
          let triggerTimeout;let cleared=0;
          const setTimeout=(callback,ms)=>{assert.equal(ms,15000);triggerTimeout=callback;return 1};
          const clearTimeout=()=>cleared++;
          const getJson=(_,options)=>new Promise((_,reject)=>{
            const abort=()=>reject(new DOMException('aborted','AbortError'));
            if(options.signal.aborted) abort();else options.signal.addEventListener('abort',abort,{once:true});
          });
          (async()=>{
            const timed=getBudgetProgress('job','',parent.signal);triggerTimeout();
            await assert.rejects(timed,e=>e.error.includes('상태를 확인하지 못했어요'));
            const cancelled=getBudgetProgress('job','',parent.signal);parent.abort();
            await assert.rejects(cancelled,e=>e.name==='AbortError');assert.equal(cleared,2);
          })().catch(e=>{console.error(e);process.exitCode=1});
        """)

    def test_refresh_storage_quota_falls_back_to_search_conditions(self):
        self.run_js(["saveRefreshPageState"], """
          const assert=require('node:assert/strict');
          const refreshPageName=()=> 'budget-result';
          const budgetReturnStatePayload=()=>({currentBudgetData:{large:'trade data'}});
          const window={scrollY:123};const currentPurchasePower={budgetEok:14};
          const activeRegion='seoul',activeRegionQuery='서울',activeLeaderCategory='price',activeLeaderAreaBucket='84';
          const leaderSido={value:'서울'},leaderSigungu={value:'중랑구'},aptSearchInput={value:''};
          const refreshPageStateKey='refresh';let saved;let calls=0;
          const sessionStorage={setItem(key,value){
            calls++;if(calls===1) throw new Error('QuotaExceededError');saved=JSON.parse(value);
          }};
          saveRefreshPageState();
          assert.equal(calls,2);assert.equal(saved.page,'condition-results');
          assert.equal(saved.budgetState,null);assert.equal(saved.currentPurchasePower.budgetEok,14);
          assert.equal(saved.scrollY,123);
        """)

    def test_reload_before_verified_cards_reconnects_the_search(self):
        self.run_js(["restoreRefreshPageState"], """
          const assert=require('node:assert/strict');
          const refreshPageStateKey='refresh',refreshPageStateTtlMs=1800000;
          const state={savedAt:Date.now(),page:'condition-results',currentPurchasePower:{budgetEok:14},scrollY:0};
          const sessionStorage={getItem:()=>JSON.stringify(state),removeItem(){}};
          let currentPurchasePower=null,searches=0,view='';
          const renderPurchasePower=()=>{},closePurchasePowerSheet=()=>{},setActiveView=v=>view=v;
          const loadBudgetCandidates=async()=>{searches++};
          const requestAnimationFrame=f=>f();const window={scrollTo(){}};
          (async()=>{
            assert.equal(await restoreRefreshPageState(),true);
            assert.equal(searches,1);assert.equal(view,'condition');assert.equal(currentPurchasePower.budgetEok,14);
            state.page='flow';assert.equal(await restoreRefreshPageState(),true);
            assert.equal(searches,1);assert.equal(view,'flow');
          })().catch(e=>{console.error(e);process.exitCode=1});
        """)

    def test_heatmap_tab_stays_to_right_of_leader_and_report_badges_stay_readonly(self):
        html = APP.read_text(encoding="utf-8")
        self.assertLess(html.index('id="leaderEntry"'), html.index('id="flowEntry"'))
        self.assertIn('aria-controls="flowView"', html)
        for name in ("candidateReadonlyScoreBadgeHtml", "candidateReadonlyFlowScoreBadgeHtml"):
            body = re.search(r"function " + name + r"\(item\) \{.*?\n    \}", html, re.S).group()
            self.assertIn("<span", body)
            self.assertNotIn("<button", body)
            self.assertNotIn("-open", body)
