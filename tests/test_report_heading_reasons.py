"""Shared report headings explain their verdict with the selected apartment's facts."""
from pathlib import Path
import re
import shutil
import subprocess
import pytest

ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.skipif(not shutil.which('node'),reason='Node required')
def test_location_and_market_headings_use_verified_facts_and_keep_cautions():
    html=(ROOT/'앱화면/real-estate-search.html').read_text()
    names=['zpNum','zpPct','zpPartRatio','locationScorePartHasNoData','zpIsFundingPart','zpAllScoredParts','zpScoredParts',
           'zippickReportPartLabel','zippickLocationHeadingFact','zippickLocationHeading','zippickMarketVerdict',
           'zippickSignalHeading','zippickCommuteHeading']
    functions='\n'.join(re.search(r'    function '+name+r'\(.*?\n    \}',html,re.S).group() for name in names)
    script=functions+r'''
const assert=require('node:assert/strict');
const ZP_FUNDING_PART_KEYS=new Set(['jeonse']);
const ZP_COMMUTE_GOOD_MINUTES=30,ZP_COMMUTE_OK_MINUTES=45,ZP_COMMUTE_LONG_MINUTES=60;
const detail=(key,points,maxPoints,reason,more={})=>({key,points,maxPoints,reason,status:'ok',...more});
const demand={key:'demand',points:25.2,maxPoints:30,status:'ok',details:[
 detail('station',4.5,5,'광운대역 경춘선 · 직선 347m'),detail('education',3.8,4,'서울녹천초등학교 · 261m 거리')]};
const product={key:'product',points:3.6,maxPoints:10,status:'ok',details:[detail('age',.9,6,'1987년 사용승인')]};
const base={buildingAge:39,households:910,locationScore:{score:76,parts:[demand,product]}};
const before=JSON.stringify(base);
const title=zippickLocationHeading(base,{});
assert.match(title,/단지 조건은 좋아요.*347m.*261m.*39년차/);
assert.equal(JSON.stringify(base),before);
assert.match(zippickLocationHeading(base,{peakGuard:{atPeak:true}}),/347m.*2년 고점권/);
assert.match(zippickLocationHeading(base,{peakGuard:{atPeak:false}}),/347m.*가격이 빠르게/);
const missing={...base,locationScore:{score:76,parts:[{...demand,details:[detail('station',null,5,'확인되지 않은 역 10m',{status:'missing'})]}]}};
assert.match(zippickLocationHeading(missing,{}),/판단할 수 없어요.*자료가 부족/);
assert.doesNotMatch(zippickLocationHeading(missing,{}),/10m|가까워요|좋아요/);
assert.match(zippickLocationHeading({...base,locationScore:{score:40,parts:[product]}},{}),/아쉬워요.*39년차/);
const schoolOnly={...demand,details:[detail('station',null,5,'누락 역 10m',{status:'missing'}),detail('education',3.8,4,'학교 · 261m 거리')]};
assert.match(zippickLocationHeading({...base,locationScore:{score:76,parts:[schoolOnly]}},{}),/학교까지 261m/);
assert.doesNotMatch(zippickLocationHeading({...base,locationScore:{score:76,parts:[schoolOnly]}},{}),/10m|역은/);
const weakStation={...demand,points:9,details:[detail('station',1,5,'먼역 · 직선 1,450m')]};
assert.match(zippickLocationHeading({...base,locationScore:{score:40,parts:[weakStation]}},{}),/아쉬워요.*1,450m.*멀어요/);
const price={key:'price',points:24,maxPoints:30,details:[detail('leader_gap',6,7,'지역 대장보다 20.1% 낮음')]};
assert.match(zippickLocationHeading({...base,locationScore:{score:76,parts:[price]}},{}),/대장 단지보다 실거래가가 20.1% 낮아요/);
const unexplainedPrice={...price,points:28,details:[detail('estimate_range',5,8,'가격 자료 확인')]};
assert.match(zippickLocationHeading({...base,locationScore:{score:76,parts:[unexplainedPrice,demand,product]}},{}),/347m.*261m/);
assert.doesNotMatch(zippickLocationHeading({...base,locationScore:{score:76,parts:[unexplainedPrice,demand]}},{}),/점수가.*점이에요/);
assert.match(zippickLocationHeading({...base,locationScore:{score:76,parts:[unexplainedPrice]}},{}),/이유는 추가 확인/);
const down={signals:{momentumPct:16.9,turnoverRatio:.35}};
assert.match(zippickSignalHeading(down,{}),/아쉬워요.*가격은 올랐지만 거래가 줄었어요/);
const rising={signals:{momentumPct:10,turnoverRatio:1.3}};
assert.match(zippickSignalHeading(rising,{peakGuard:{atPeak:true}}),/가격과 거래가 함께 늘었지만.*고점권/);
assert.match(zippickCommuteHeading({}),/판단할 수 없어요.*이동시간 자료가 없어요/);
assert.match(zippickCommuteHeading({commuteProfile:{hubs:{광화문:{totalMinutes:70}}}}),/아쉬워요.*70분/);
'''
    run=subprocess.run(['node'],input=script,text=True,capture_output=True)
    assert run.returncode==0,run.stderr


@pytest.mark.skipif(not shutil.which('node'),reason='Node required')
def test_funding_and_liquidity_titles_explain_cause_or_missing_comparison():
    html=(ROOT/'앱화면/real-estate-search.html').read_text()
    functions='\n'.join(re.search(r'    function '+name+r'\(.*?\n    \}',html,re.S).group()
        for name in ['zpNum','zippickFundingHtml','zippickLiquidityHtml'])
    script=functions+r'''
const assert=require('node:assert/strict');
const esc=String;
const zpPct=value=>`${value}%`;
const transactionMoney=value=>`${value}억`;
const zippickJeonsePeerStat=item=>item.peer;
const zippickLiquidityStat=item=>item.stat;
const head=html=>html.match(/<h5>(.*?)<\/h5>/s)[1];
assert.match(head(zippickFundingHtml({jeonseRatioPct:33.4,latestJeonseDepositEok:3,jeonseSalePriceBasisEok:9})),/내 돈이 많이.*33.4%/);
assert.match(head(zippickFundingHtml({jeonseRatioPct:60,peer:{band:'low'},latestJeonseDepositEok:6,jeonseSalePriceBasisEok:10})),/아쉬워요.*다른 후보보다 낮아요/);
assert.match(head(zippickLiquidityHtml({stat:{band:'illiquid',windowMonths:24,silentTotal:16}})),/시간이 걸릴.*16개월.*거래가 없/);
assert.match(head(zippickLiquidityHtml({stat:{band:'no_downturn',windowMonths:24,downMonths:2}})),/판단하기 어려워요.*2개월/);
assert.match(head(zippickLiquidityHtml({stat:{band:'unknown',windowMonths:24,downMonths:4,downDeals:12}})),/판단할 수 없어요.*자료가 부족/);
const fair={band:'fair',windowMonths:24,downMonths:6,downDeals:18,downPerMonth:3,otherPerMonth:6,otherMonths:18,silentMonths:0,ratio:.5};
assert.match(head(zippickLiquidityHtml({stat:fair})),/아쉬워요.*평소의 50%/);
assert.match(head(zippickLiquidityHtml({stat:{...fair,band:'weak',downDeals:3}})),/아쉬워요.*6개월.*3건/);
'''
    run=subprocess.run(['node'],input=script,text=True,capture_output=True)
    assert run.returncode==0,run.stderr
