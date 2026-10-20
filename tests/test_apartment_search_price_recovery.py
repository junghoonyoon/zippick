"""Search keeps exact identity, recovers verified parcel changes and retries failures."""
import json
from pathlib import Path
import re
import subprocess
import sys
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
import apartment_transaction_addresses as addresses
import molit_transactions as molit
import real_estate_search as search
import search_server as server


def graciel():
    return next(e for e in search.APARTMENT_MASTER if e["name"] == "청량리역 한양수자인 그라시엘")


def test_graciel_search_keeps_source_id_and_verified_changed_parcel():
    entity = graciel()
    assert entity["apartmentId"] == "11230120446536"
    suggestion = search.suggest_apartments(entity["name"])[0]
    assert suggestion["apartmentId"] == entity["apartmentId"]
    assert suggestion["approvedAt"] == "2023-06-02"
    rows = molit.source_rows_for_entity(entity, "동대문구")
    assert {r["지번"] for r in rows} == {"39-1", "798"}
    good = {"apartment": "청량리역한양수자인그라시엘", "legalDong": "용두동", "jibun": "798",
            "dealDate": "2026-09-13", "dealAmountEok": 17.5, "exclusiveArea": 84.97,
            "floor": "45", "dealType": "중개거래"}
    trades = [good, {**good, "jibun": "799"}, {**good, "legalDong": "전농동"},
              {**good, "cancellationDate": "2026-10-01"}, {**good, "dealType": "직거래"}]
    with mock.patch.object(molit, "_deal_months", return_value=["202609"]):
        matched = molit._matching_transactions(rows, entity["name"], "84.97", 24, {("11230", "202609"): trades})
    assert len(matched) == 1
    assert matched[0]["jibun"] == "798"
    assert matched[0]["transactionAddressCorrection"]["sourceUrl"]
    band = molit._price_band_payload(entity["name"], "동대문구", "84.97", 24, matched)
    assert band["latestDealPriceEok"] == 17.5
    assert band["transactionAddressCorrection"]["apartmentId"] == entity["apartmentId"]


@pytest.mark.parametrize("field,value", [("단지고유번호", "other"), ("법정동", "전농동"), ("지번", "39-2"), ("필지고유번호", "9999910200100390001")])
def test_parcel_correction_never_expands_a_different_identity(field, value):
    original = molit.source_rows_for_entity(graciel())[0]
    changed = {**original, field: value}
    assert addresses.expand_source_rows([changed]) == [changed]


def test_unverified_parcel_correction_is_ignored():
    row = molit.source_rows_for_entity(graciel())[0]
    entry = {**addresses.entries()[0], "sourceUrl": ""}
    with mock.patch.object(addresses, "entries", return_value=[entry]):
        assert addresses.expand_source_rows([row]) == [row]


def test_rental_subcomplex_does_not_make_the_sale_complex_ambiguous():
    assert search._is_rental_row({"단지명_공시가격": "서울숲리버뷰자이(임대)"})
    assert not search._is_rental_row({"단지명_공시가격": "서울숲리버뷰자이"})
    entity = server.budget_candidates._find_entity("서울숲 리버뷰 ZI")
    assert entity["apartmentId"] == "11200120372630"


def test_missing_source_id_merges_only_with_one_consistent_identity():
    base = {"name": "단지", "province": "서울특별시", "district": "동대문구", "legalDong": "용두동", "jibun": "1"}
    merged = search._merge_entities([{**base, "apartmentId": "A"}, {**base, "status": "분양권"}])
    assert len(merged) == 1
    assert merged[0]["apartmentId"] == "A" and merged[0]["status"] == "분양권"
    assert len(search._merge_entities([{**base, "apartmentId": "A"}, {**base, "apartmentId": "B"}, base])) == 3


def test_distinct_source_ids_keep_their_rows_and_price_caches():
    row = {"대표단지명": "단지", "법정동": "용두동", "지번": "1", "법정동코드": "11230"}
    assert len(molit._dedupe_rows([{**row, "단지고유번호": "A"}, {**row, "단지고유번호": "B"}])) == 2
    a = {"name": "단지", "legalDong": "용두동", "jibun": "1", "apartmentId": "A"}
    b = {**a, "apartmentId": "B"}
    assert molit._price_band_cache_key("단지", "동대문구", "84", 24, entity=a) != molit._price_band_cache_key("단지", "동대문구", "84", 24, entity=b)


def test_price_request_passes_selected_id_into_the_common_candidate():
    with mock.patch.object(server.budget_candidates, "apartment_candidate_result", return_value=None) as build, \
         mock.patch.object(server.budget_candidates, "_price_lookup_entity", return_value=None):
        result, _ = server._apartment_affordability({"name": "단지", "region": "동대문구", "apartment_id": "A"})
    assert result["state"] == "unavailable"
    assert build.call_args.kwargs["apartment_id"] == "A"


@pytest.mark.parametrize("area,expected", [("84.97", "전용 84.97㎡"), ("59.98", "전용 59.98㎡"), ("84", "전용 84㎡")])
def test_selected_area_does_not_round_into_a_different_unit_type(area, expected):
    assert server.budget_candidates._display_area_label(area) == expected


def test_empty_price_cache_expires_quickly_and_outage_is_not_cached(tmp_path):
    with mock.patch.object(molit, "PRICE_BAND_CACHE_DIR", tmp_path), mock.patch.object(molit, "last_error", return_value=""):
        with mock.patch.object(molit.time, "time", return_value=100):
            molit._write_cached_price_band("empty", None)
            assert molit._read_cached_price_band("empty") == (True, None)
        with mock.patch.object(molit.time, "time", return_value=131):
            assert molit._read_cached_price_band("empty") == (False, None)
        with mock.patch.object(molit, "last_error", return_value="timeout"):
            molit._write_cached_price_band("outage", None)
            assert not (tmp_path / "outage.json").exists()


def test_comparison_index_failure_preserves_verified_price():
    band = {"minPriceEok": 17, "midPriceEok": 17.5, "maxPriceEok": 18,
            "latestDealPriceEok": 17.5, "latestDealDate": "2026-09-13", "transactionCount": 5}
    with mock.patch.object(molit, "price_band_for_apartment", return_value=band), \
         mock.patch.object(molit, "transactions_for_apartment", return_value=[]), \
         mock.patch.object(server, "_regional_index_for_apartment", side_effect=RuntimeError("unavailable")):
        result = server._molit_affordability_estimate("테스트단지", "동대문구", "84", 24, entity=graciel())
    assert result["estimate"]["midPriceEok"] == 17.5
    assert result["index"] == {}


def test_exact_price_uses_verified_older_trade_when_recent_window_is_empty():
    entity = graciel()
    band = {
        "minPriceEok": 17.0,
        "midPriceEok": 17.5,
        "maxPriceEok": 18.0,
        "latestDealPriceEok": 17.5,
        "latestDealDate": "2024-09-13",
        "latestDealExclusiveArea": 84.97,
        "latestDealFloor": "45",
        "transactionCount": 1,
    }
    calls = []

    def price_band(*_args, **kwargs):
        calls.append(kwargs["lookback_months"])
        return band if kwargs["lookback_months"] == 36 else None

    with mock.patch.object(server.config, "MOLIT_STALE_TRANSACTION_LOOKBACK_MONTHS", 36), \
         mock.patch.object(molit, "price_band_for_apartment", side_effect=price_band), \
         mock.patch.object(molit, "transactions_for_apartment", return_value=[{
             "dealDate": "2024-09-13", "dealAmountEok": 17.5,
             "exclusiveArea": 84.97, "floor": "45",
         }]), \
         mock.patch.object(server, "_regional_index_for_apartment", return_value=None):
        result = server._molit_affordability_estimate(
            entity["name"], entity["district"], "84.97", 24, entity=entity,
        )

    assert calls == [24, 24, 36]
    assert result["lookbackMonths"] == 36
    assert result["estimate"]["latestTradeDate"] == "2024-09-13"
    assert result["estimate"]["latestTradeAgeDays"] > 180


def test_shared_transaction_scope_is_kept_in_the_price_basis():
    entity = next(
        item for item in search.APARTMENT_MASTER
        if item.get("apartmentId") == "zippick:1123011000:imun-ipark-xi:1"
    )
    scope = {
        "id": "imun-ipark-xi-3-1bl",
        "label": "이문아이파크자이 1·2단지 통합 거래",
    }
    band = {
        "minPriceEok": 12.1,
        "midPriceEok": 12.5,
        "maxPriceEok": 12.9,
        "latestDealPriceEok": 12.9,
        "latestDealDate": "2026-08-18",
        "transactionCount": 3,
        "transactionScope": scope,
    }
    with mock.patch.object(molit, "price_band_for_apartment", return_value=band), \
         mock.patch.object(molit, "transactions_for_apartment", return_value=[]), \
         mock.patch.object(server, "_regional_index_for_apartment", return_value=None):
        result = server._molit_affordability_estimate(
            entity["name"], entity["district"], "84.95", 24, entity=entity,
        )
    assert result["transactionScope"] == scope
    assert result["areaBasis"].startswith("이문아이파크자이 1·2단지 통합 거래 · 전용 84.95㎡")
    assert result["naverMarketReference"] == {
        "provider": "KB부동산",
        "asOf": "2026-10-12",
        "areaSqm": 84.95,
        "minPriceEok": 18.5,
        "midPriceEok": 19.5,
        "maxPriceEok": 20.3,
        "sourceUrl": "https://fin.land.naver.com/complexes/174562",
    }


def test_exact_no_trade_is_labeled_as_no_recent_official_transaction():
    entity = graciel()
    with mock.patch.object(
        server.budget_candidates,
        "apartment_candidate_result",
        return_value={"name": entity["name"], "priceIdentityVerified": False},
    ), \
         mock.patch.object(server.budget_candidates, "_price_lookup_entity", return_value=entity), \
         mock.patch.object(server.rone_estimates, "estimate", return_value=({"error": "없음"}, 404)), \
         mock.patch.object(server, "_molit_affordability_estimate", return_value=None), \
         mock.patch.object(molit, "last_error", return_value=""):
        payload, status = server._apartment_affordability({
            "name": entity["name"], "region": entity["district"],
            "legal_dong": entity["legalDong"], "jibun": entity["jibun"],
            "apartment_id": entity["apartmentId"],
        })
    assert status == 200
    assert payload["priceStatus"] == "no_recent_official_trades"
    assert "최근 36개월" in payload["error"]
    assert payload["candidate"]["priceIdentityVerified"] is True
    assert payload["candidate"]["marketDataStatus"] == "no_recent_trade"


def test_no_trades_preserves_known_candidate_metadata():
    candidate = {"name": "검증단지", "region": "동대문구", "households": 1152, "approvedAt": "2023-06-02"}
    with mock.patch.object(server.budget_candidates, "apartment_candidate_result", return_value=candidate), \
         mock.patch.object(server.budget_candidates, "_price_lookup_entity", return_value=None), \
         mock.patch.object(server.budget_candidates, "_find_entities", return_value=[]), \
         mock.patch.object(server.rone_estimates, "estimate", side_effect=RuntimeError("unavailable")), \
         mock.patch.object(server, "_molit_affordability_estimate", return_value=None):
        payload, status = server._apartment_affordability({"name": "검증단지", "region": "동대문구"})
    assert status == 200
    assert payload["candidate"]["households"] == 1152
    assert payload["priceStatus"] == "no_verified_trades"


def test_frontend_retries_unavailable_response_and_shows_dated_last_trade():
    html = (ROOT / "앱화면/real-estate-search.html").read_text()
    functions = "\n".join(re.search(r"    (?:async )?function " + name + r"\(.*?\n    \}", html, re.S).group()
                          for name in ["fetchAptAffordability", "aptAffordabilityHtml"])
    script = functions + '''
const assert = require('node:assert/strict');
const aptAffordabilityCache = new Map();
const currentPurchasePower = null, budgetMinArea = {value:0};
const aptPurchaseProfile = () => null;
const APARTMENT_PRICE_TIMEOUT_MS = 1000;
const esc = v => String(v), policyMoney = v => `${v}억`;
let calls = 0;
const getJson = async () => (++calls === 1 ? {state:'unavailable'} : {state:'ready',estimate:{minPriceEok:17.5}});
(async () => {
 const item = {name:'단지',region:'동대문구',jibun:'39-1'};
 assert.equal((await fetchAptAffordability(item)).state,'unavailable');
 assert.equal((await fetchAptAffordability(item)).state,'ready');
 await fetchAptAffordability(item);
 assert.equal(calls,2);
 const result = aptAffordabilityHtml({state:'unavailable',candidate:{lastObservedDealPriceEok:17.5,lastObservedDealDate:'2023-06-01'}});
 assert.match(result,/17.5억/); assert.match(result,/2023-06-01/);
 assert.match(result,/data-apt-price-retry/);
 assert.match(result,/현재 가격과 다를 수/);
})().catch(error => {console.error(error);process.exitCode=1;});
'''
    result = subprocess.run(["node"], input=script, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


def test_frontend_shows_naver_listing_range_separately_from_missing_official_trades():
    html = (ROOT / "앱화면/real-estate-search.html").read_text()
    function = re.search(r"    function aptAffordabilityHtml\(.*?\n    \}", html, re.S).group()
    script = function + r'''
const assert = require('node:assert/strict');
const esc = value => String(value);
const policyMoney = value => `${value}억`;
const aptMoneyRange = (minimum, maximum) => `${minimum}억~${maximum}억`;
const result = aptAffordabilityHtml({
  state:'unavailable', priceStatus:'no_recent_official_trades',
  naverListingReference:{saleMinPriceEok:12.7,saleMaxPriceEok:18,saleListingCount:8,asOf:'2026-10-19'},
});
assert.match(result,/최근 공식 거래 없음/);
assert.match(result,/네이버 매물 호가 12.7억~18억 · 매매 8건 · 2026-10-19 확인/);
assert.match(result,/매물 호가는 실제 계약 가격이 아니에요/);
'''
    result = subprocess.run(["node"], input=script, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


def test_search_price_waits_past_auxiliary_timeout_and_distinguishes_failures():
    html = (ROOT / "앱화면/real-estate-search.html").read_text()
    functions = "\n".join(re.search(r"    (?:async )?function " + name + r"\(.*?\n    \}", html, re.S).group()
                          for name in ["fetchAptAffordability", "aptPriceLookupFailure", "aptAffordabilityHtml"])
    timeout = re.search(r"const APARTMENT_PRICE_TIMEOUT_MS = \d+;", html).group()
    script = timeout + functions + r'''
const assert = require('node:assert/strict');
const aptAffordabilityCache = new Map();
const currentPurchasePower = null, budgetMinArea = {value:0};
const aptPurchaseProfile = () => null;
const esc = v => String(v), policyMoney = v => `${v}억`;
let timer, signal, complete, calls = 0;
const setTimeout = (fn, delay) => (timer = {fn,delay});
const clearTimeout = () => {};
const getJson = (_url, options) => {
 calls++;
 signal = options.signal;
 return new Promise((resolve,reject) => {
   complete = resolve;
   signal.addEventListener('abort', () => reject(new DOMException('aborted','AbortError')));
 });
};
(async () => {
 const item = {name:'거래가 있는 단지',region:'동대문구',jibun:'1'};
 const pending = fetchAptAffordability(item);
 // A valid 13-second price response must survive the auxiliary 12-second deadline.
 if (timer.delay <= 13000) timer.fn();
 assert.equal(signal.aborted,false);
 assert.ok(timer.delay <= 60000, 'price requests remain bounded');
 complete({state:'ready',estimate:{minPriceEok:10}});
 assert.equal((await pending).state,'ready');
 const failedItem = {...item,jibun:'2'};
 const failed = fetchAptAffordability(failedItem);
 const rejected = assert.rejects(failed, {name:'AbortError'});
 timer.fn(); await rejected;
 const retry = fetchAptAffordability(failedItem);
 assert.equal(calls,3,'timed-out request must be retried, not cached');
 complete({state:'ready',estimate:{minPriceEok:11}}); await retry;
 const timeoutHtml = aptAffordabilityHtml(aptPriceLookupFailure({name:'AbortError'}));
 assert.match(timeoutHtml,/실거래 조회 지연/);
 assert.doesNotMatch(timeoutHtml,/거래 자료 확인 필요/);
 assert.match(aptAffordabilityHtml(aptPriceLookupFailure(new Error('network'))),/실거래 조회 실패/);
 assert.match(aptAffordabilityHtml({state:'unavailable',priceStatus:'no_verified_trades'}),/공식 거래 확인 중/);
 assert.match(aptAffordabilityHtml({state:'unavailable',priceStatus:'no_recent_official_trades'}),/최근 공식 거래 없음/);
})().catch(error => {console.error(error);process.exitCode=1;});
'''
    result = subprocess.run(["node"], input=script, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
