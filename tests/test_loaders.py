import pandas as pd
import pytest

from data.sec_edgar import normalize_name, parse_company_facts, find_predecessors
from data.tiingo import parse_prices_csv, us_stock_listings


def fact(start, end, val, filed, form='10-Q'):
    return {'start': start, 'end': end, 'val': val, 'filed': filed, 'form': form}


def facts(us_gaap, dei=None):
    return {'facts': {'us-gaap': us_gaap, 'dei': dei or {}}}


def test_quarters_q4_derivation_and_versions():
    revenue = {'units': {'USD': [
        fact('2020-01-01', '2020-03-31', 10, '2020-05-01'),
        fact('2020-04-01', '2020-06-30', 11, '2020-08-01'),
        fact('2020-07-01', '2020-09-30', 12, '2020-11-01'),
        fact('2020-01-01', '2020-09-30', 33, '2020-11-01'),           # nine months YTD
        fact('2020-01-01', '2020-12-31', 50, '2021-02-15', '10-K'),   # full year -> Q4 = 17
        fact('2020-04-01', '2020-06-30', 11, '2021-08-01'),           # comparative, unchanged
        fact('2020-07-01', '2020-09-30', 13, '2021-11-01'),           # restated
        fact('2020-01-01', '2020-12-31', 52, '2022-02-15', '10-K'),   # restated full year: no new Q4
    ]}}
    rows = parse_company_facts(facts({'Revenues': revenue}), 'AAA')
    rev = rows[rows['field'] == 'revenue'].set_index(['period_end', 'available_date'])['value']
    assert rev[(pd.Timestamp('2020-12-31'), pd.Timestamp('2021-02-15'))] == 17
    assert len(rows[(rows['field'] == 'revenue') & (rows['period_end'] == '2020-12-31')]) == 1
    assert rev[(pd.Timestamp('2020-09-30'), pd.Timestamp('2021-11-01'))] == 13     # restatement kept
    assert len(rows[(rows['field'] == 'revenue') & (rows['period_end'] == '2020-06-30')]) == 1  # no dup


def test_tag_priority_and_q4_from_three_quarters():
    new = {'units': {'USD': [fact('2021-01-01', '2021-03-31', 100, '2021-05-01')]}}
    old = {'units': {'USD': [
        fact('2021-01-01', '2021-03-31', 999, '2021-05-01'),          # same period: lower priority tag loses
        fact('2020-01-01', '2020-03-31', 1, '2020-05-01'), fact('2020-04-01', '2020-06-30', 2, '2020-08-01'),
        fact('2020-07-01', '2020-09-30', 3, '2020-11-01'), fact('2020-01-01', '2020-12-31', 10, '2021-02-01', '10-K'),
    ]}}
    rows = parse_company_facts(facts({'RevenueFromContractWithCustomerExcludingAssessedTax': new,
                                      'SalesRevenueNet': old}), 'AAA')
    rev = rows[rows['field'] == 'revenue'].set_index('period_end')['value']
    assert rev[pd.Timestamp('2021-03-31')] == 100
    assert rev[pd.Timestamp('2020-12-31')] == 4      # 10 - (1 + 2 + 3)


def test_share_counts_get_no_derived_q4():
    shares = {'units': {'shares': [
        fact('2020-07-01', '2020-09-30', 100, '2020-11-01'),
        fact('2020-01-01', '2020-09-30', 98, '2020-11-01'),
        fact('2020-01-01', '2020-12-31', 99, '2021-02-15', '10-K'),
    ]}}
    rows = parse_company_facts(facts({'WeightedAverageNumberOfDilutedSharesOutstanding': shares}), 'AAA')
    assert rows['period_end'].tolist() == [pd.Timestamp('2020-09-30')]


def test_instant_shares_outstanding():
    dei = {'EntityCommonStockSharesOutstanding': {'units': {'shares': [
        {'end': '2021-01-20', 'val': 5e9, 'filed': '2021-02-01', 'form': '10-K'}]}}}
    rows = parse_company_facts(facts({}, dei), 'AAA')
    assert rows[['field', 'value']].values.tolist() == [['shares_outstanding', 5e9]]


def test_normalize_name():
    assert normalize_name('CELGENE CORP /DE/') == normalize_name('Celgene Corp')
    assert normalize_name('ExxonMobil Holdings Corp') == normalize_name('EXXON MOBIL CORP')
    assert normalize_name('Twitter, Inc.') == 'twitter'


def test_predecessor_requires_same_industry_and_stopped_filing():
    def sub(name, sic, reports):
        return {'name': name, 'sic': sic, 'formerNames': [],
                'filings': {'recent': {'form': ['10-Q'] * len(reports), 'filingDate': reports}}}

    subs = {1: sub('Newco Holdings Inc', '7370', ['2020-05-01']),
            2: sub('Newco Inc', '7370', ['2015-05-01', '2019-11-01']),       # real predecessor
            3: sub('Newco Corp', '2833', ['2015-05-01', '2019-11-01']),      # other industry
            4: sub('Newco Co', '7370', ['2015-05-01', '2026-05-01'])}        # still filing: sister company

    class Sec:
        def submissions(self, cik):
            return subs[cik]

    lookup = pd.DataFrame({'name_key': [normalize_name(subs[c]['name']) for c in subs], 'cik': list(subs)})
    assert find_predecessors(Sec(), 1, '2020-05-01', '2012-01-01', lookup) == [2]
    assert find_predecessors(Sec(), 1, '2012-06-01', '2012-01-01', lookup) == []   # history already covered


def test_tiingo_prices_and_listing_filters():
    csv = ("date,close,high,low,open,volume,adjClose,adjHigh,adjLow,adjOpen,adjVolume,divCash,splitFactor\n"
           "2020-01-02T00:00:00.000Z,300,301,299,300,100,75,75.25,74.75,75,400,0,1\n"
           "2020-01-03T00:00:00.000Z,302,303,300,301,120,75.5,75.75,75,75.25,480,0,4\n")
    df = parse_prices_csv(csv)
    assert df.loc[0, ['open', 'high', 'low', 'close', 'volume']].tolist() == [75, 75.25, 74.75, 75, 400]
    assert df['timestamp'].tolist() == [pd.Timestamp('2020-01-02'), pd.Timestamp('2020-01-03')]
    assert df['split_factor'].tolist() == [1, 4]

    listings = pd.DataFrame({
        'ticker': ['AAPL', 'AAC', 'AAC', 'AAC-U', 'XYZ-P-A', 'SPY', 'OLD', 'OTCX'],
        'exchange': ['NASDAQ', 'NYSE', 'NYSE', 'NYSE', 'NYSE', 'NYSE ARCA', 'NYSE', 'PINK'],
        'assetType': ['Stock', 'Stock', 'Stock', 'Stock', 'Stock', 'ETF', 'Stock', 'Stock'],
        'priceCurrency': ['USD'] * 8,
        'startDate': pd.to_datetime(['1980-12-12', '2014-10-02', '2021-03-25', '2021-02-02', '2020-01-01',
                                     '1993-01-29', '1990-01-01', '2010-01-01']),
        'endDate': pd.to_datetime(['2026-10-02', '2021-04-19', '2023-11-06', '2026-06-30', '2026-10-02',
                                   '2026-10-02', '2005-01-01', '2026-10-02']),
    })
    out = us_stock_listings(listings, active_since='2008-01-01')
    assert sorted(out['symbol']) == ['AAC', 'AAC', 'AAPL', 'SPY']
    assert out.loc[out['symbol'] == 'AAC', 'reused'].all()
