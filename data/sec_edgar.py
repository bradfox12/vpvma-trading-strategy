"""
SEC EDGAR fundamentals (free) -> point-in-time quarterly rows

Source: XBRL "company facts" (https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json,
or the nightly bulk file companyfacts.zip). Every reported value carries the
date of the filing it came from ('filed'), so each value is stored with
available_date = filed. A value reported again in a later filing (comparatives,
restatements) becomes a new version only if the number changed.

Normalisation:
- Each standard field maps to several XBRL tags (companies and the taxonomy
  change tags over time, e.g. SalesRevenueNet -> RevenueFromContractWithCustomer...).
  For each period and filing, the highest-priority tag present wins.
- Quarterly values come from 3-month facts. Companies file no Q4 10-Q, so Q4 is
  derived from the 10-K: Q4 = full year - nine-month year-to-date (or - Q1-Q3),
  using only values public by the 10-K filing date and only from the FIRST
  filed annual value (a later restated annual value minus an unrestated
  nine-month value would give a wrong Q4). Q4 EPS derived this way is an
  approximation; share counts are averages and get no derived Q4.
- Per-share values and share counts are as filed, NOT adjusted for later stock
  splits (prices are). Compare EPS across a split only after adjusting it.

SEC fair-access rules: identify yourself (SEC_USER_AGENT="Name email") and stay
under 10 requests/second.
"""

import json
import logging
import os
import re
import time
import zipfile
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / 'data' / 'cache'

TICKERS_URL = 'https://www.sec.gov/files/company_tickers.json'
COMPANYFACTS_URL = 'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json'
SUBMISSIONS_URL = 'https://data.sec.gov/submissions/CIK{cik:010d}.json'
COMPANYFACTS_ZIP_URL = 'https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip'
CIK_LOOKUP_URL = 'https://www.sec.gov/Archives/edgar/cik-lookup-data.txt'

# Standard field -> (unit, XBRL us-gaap tags in priority order)
# Fields whose Q4 cannot be derived as full year minus nine months
NON_ADDITIVE = {'shares_diluted'}
DURATION_FIELDS: Dict[str, tuple] = {
    'revenue': ('USD', ['RevenueFromContractWithCustomerExcludingAssessedTax',
                        'RevenueFromContractWithCustomerIncludingAssessedTax',
                        'Revenues', 'SalesRevenueNet', 'SalesRevenueGoodsNet',
                        'SalesRevenueServicesNet', 'RevenuesNetOfInterestExpense',
                        # real estate companies
                        'RealEstateRevenueNet', 'OperatingLeaseLeaseIncome',
                        'OperatingLeasesIncomeStatementLeaseRevenue']),
    'cost_of_revenue': ('USD', ['CostOfGoodsAndServicesSold', 'CostOfRevenue', 'CostOfGoodsSold',
                                'CostOfServices']),
    'gross_profit': ('USD', ['GrossProfit']),
    'operating_income': ('USD', ['OperatingIncomeLoss']),
    'net_income': ('USD', ['NetIncomeLoss', 'ProfitLoss']),
    'eps_diluted': ('USD/shares', ['EarningsPerShareDiluted', 'EarningsPerShareBasicAndDiluted']),
    'eps_basic': ('USD/shares', ['EarningsPerShareBasic', 'EarningsPerShareBasicAndDiluted']),
    'shares_diluted': ('shares', ['WeightedAverageNumberOfDilutedSharesOutstanding']),
    # Banks report these instead of a revenue line (bank revenue = the two combined)
    'net_interest_income': ('USD', ['InterestIncomeExpenseNet']),
    'noninterest_income': ('USD', ['NoninterestIncome']),
}
# Point-in-time ("instant") facts: field -> (taxonomy, unit, tags)
INSTANT_FIELDS: Dict[str, tuple] = {
    'shares_outstanding': ('dei', 'shares', ['EntityCommonStockSharesOutstanding']),
}

QUARTER_DAYS = (80, 100)
NINE_MONTH_DAYS = (260, 285)
YEAR_DAYS = (350, 380)


# --------------------------------------------------------------------- client

class SecClient:
    """Rate-limited HTTP client that identifies the caller as the SEC requires"""

    def __init__(self, user_agent: Optional[str] = None, min_interval: float = 0.12, session=None):
        self.user_agent = user_agent or os.getenv('SEC_USER_AGENT')
        if not self.user_agent or '@' not in self.user_agent:
            raise ValueError('SEC_USER_AGENT must be set to "Your Name your@email" in .env')
        self.session = session or requests.Session()
        self.min_interval = min_interval
        self._last = 0.0

    def get(self, url: str, stream: bool = False):
        wait = self.min_interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        for attempt in range(1, 4):
            self._last = time.monotonic()
            response = self.session.get(url, headers={'User-Agent': self.user_agent},
                                        timeout=120, stream=stream)
            if response.status_code in (429, 503):
                time.sleep(10 * attempt)
                continue
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response
        raise RuntimeError(f"SEC still rate limiting after retries: {url}")

    def json(self, url: str):
        response = self.get(url)
        return None if response is None else response.json()

    def company_facts(self, cik: int) -> Optional[dict]:
        return self.json(COMPANYFACTS_URL.format(cik=int(cik)))

    def submissions(self, cik: int) -> Optional[dict]:
        return self.json(SUBMISSIONS_URL.format(cik=int(cik)))

    def download(self, url: str, dest: Path) -> Path:
        """Download a (large) file once into the cache"""
        dest.parent.mkdir(parents=True, exist_ok=True)
        response = self.get(url, stream=True)
        tmp = dest.with_suffix(dest.suffix + '.part')
        with open(tmp, 'wb') as fh:
            for chunk in response.iter_content(chunk_size=1 << 20):
                fh.write(chunk)
        tmp.replace(dest)
        return dest


# ------------------------------------------------------------- ticker -> CIK

def to_db_symbol(ticker: str) -> str:
    """SEC/Tiingo class-share format (BRK-B) -> database format (BRK.B)"""
    return ticker.upper().replace('-', '.')


def current_ticker_map(client: SecClient) -> pd.DataFrame:
    """Currently listed tickers -> CIK: [symbol, cik, name]"""
    data = client.json(TICKERS_URL)
    df = pd.DataFrame(data.values()).rename(columns={'cik_str': 'cik', 'title': 'name'})
    df['symbol'] = df['ticker'].map(to_db_symbol)
    return df[['symbol', 'cik', 'name']].drop_duplicates('symbol')


_SUFFIXES = r'\b(inc|incorporated|corp|corporation|co|company|ltd|limited|plc|llc|lp|holdings?|group|the|sa|nv|ag)\b'


_ABBREVIATIONS = {
    r'\bintl\b': 'international', r"\bint'l\b": 'international', r'\bsvcs\b': 'services',
    r'\bmfg\b': 'manufacturing', r'\bnatl\b': 'national', r'\bfin\b': 'financial',
    r'\bbancorporation\b': 'bancorp', r'\bcos\b': 'companies', r'\bsys\b': 'systems',
}


def normalize_name(name: str) -> str:
    """
    Comparable company name: lowercase, without share-class / par-value suffixes
    ("- Class A", "Com Par 0.001"), state codes ("/DE/", "(Delaware)"), common
    abbreviations expanded ("Intl" -> "international"), punctuation, legal
    suffixes or spaces ("Exxon Mobil" == "ExxonMobil")
    """
    if not isinstance(name, str):
        return ''
    name = name.lower()
    name = re.sub(r'\s+-\s+.*$', ' ', name)                       # "Rover Group Inc - Class A"
    name = re.sub(r'\b(class|cl|series)\s+[a-z0-9]\b.*$', ' ', name)
    name = re.sub(r'\bcom(mon)?\b.*\bpar\b.*$', ' ', name)        # "Com Par 0.001"
    name = re.sub(r'\((delaware|de|nevada|nv|new|the)\)', ' ', name)
    name = re.sub(r'/[a-z]{2,3}/?', ' ', name)
    for pattern, full in _ABBREVIATIONS.items():
        name = re.sub(pattern, full, name)
    name = re.sub(r'[^a-z0-9 ]', ' ', name.replace('&', ' '))
    name = re.sub(r'\band\b', ' ', name)                          # "Rohm & Haas" == "Rohm Haas"
    name = re.sub(_SUFFIXES, ' ', name)
    return re.sub(r'\s+', '', name)


def load_cik_lookup(client: SecClient, refresh: bool = False) -> pd.DataFrame:
    """Every EDGAR entity name (current and former) -> CIK: [name_key, cik]"""
    path = CACHE_DIR / 'cik-lookup-data.txt'
    if refresh or not path.exists():
        logger.info("Downloading SEC CIK lookup file...")
        client.download(CIK_LOOKUP_URL, path)
    rows = []
    with open(path, encoding='latin-1') as fh:
        for line in fh:
            parts = line.rstrip('\n').rsplit(':', 2)
            if len(parts) == 3 and parts[1].isdigit():
                rows.append((normalize_name(parts[0]), int(parts[1])))
    return pd.DataFrame(rows, columns=['name_key', 'cik']).drop_duplicates()


def match_cik_by_name(name: str, lookup: pd.DataFrame, prefix_fallback: bool = True) -> List[int]:
    """
    Candidate CIKs for a company name: exact normalised match, else (if
    prefix_fallback) names where one starts with the other (>= 6 characters).
    Callers must verify candidates (e.g. filings while the stock was listed).
    """
    key = normalize_name(name)
    if not key:
        return []
    exact = lookup.loc[lookup['name_key'] == key, 'cik'].unique().tolist()
    if exact or not prefix_fallback or len(key) < 6:
        return sorted(exact)
    keys = lookup['name_key']
    hits = lookup.loc[keys.str.startswith(key) | ((keys.str.len() >= 6) & keys.map(key.startswith)), 'cik']
    return sorted(hits.unique().tolist())[:25]


def last_periodic_report(submissions: dict) -> Optional[pd.Timestamp]:
    recent = submissions.get('filings', {}).get('recent', {})
    dates = [pd.Timestamp(d) for f, d in zip(recent.get('form', []), recent.get('filingDate', []))
             if f in ('10-K', '10-Q')]
    return max(dates) if dates else None


def find_predecessors(sec: 'SecClient', cik: int, first_report, needed_from,
                      lookup: pd.DataFrame) -> List[int]:
    """
    Earlier SEC filers for the same business, e.g. after a holding-company
    reorganisation that created a new CIK (ExxonMobil 2025).

    Only searched when `cik`'s first report (`first_report`, the earliest filing
    date in its company facts) is more than a year after `needed_from`. A
    candidate must share a normalised current or former name with `cik`, have
    filed 10-K/10-Q reports after `needed_from`, have STOPPED filing by the
    time `cik` started (so sister companies that file alongside it are rejected),
    and have the same SIC industry code (rejects unrelated companies that happen
    to share a name, e.g. NBTY's parent "Alphabet Holding Company").
    Renames with different names (Google -> Alphabet) need data/cik_overrides.csv.
    """
    first_report = pd.Timestamp(first_report)
    if first_report <= pd.Timestamp(needed_from) + pd.Timedelta(days=365):
        return []
    sub = sec.submissions(cik) or {}
    names = [sub.get('name', '')] + [n.get('name', '') for n in sub.get('formerNames', [])]
    keys = {normalize_name(n) for n in names if n}
    candidates = set(lookup.loc[lookup['name_key'].isin(keys), 'cik']) - {int(cik)}
    found = []
    for candidate in sorted(candidates):
        csub = sec.submissions(candidate) or {}
        last = last_periodic_report(csub)
        same_industry = not sub.get('sic') or not csub.get('sic') or csub.get('sic') == sub.get('sic')
        if (same_industry and last is not None and last <= first_report + pd.Timedelta(days=180)
                and filed_periodic_reports_between(csub, needed_from, first_report) > 0):
            found.append(int(candidate))
    return found


def load_cik_overrides(path: Path = None) -> Dict[str, List[int]]:
    """Manual symbol -> extra CIKs (renamed predecessors name matching cannot find)"""
    path = path or PROJECT_ROOT / 'data' / 'cik_overrides.csv'
    if not path.exists():
        return {}
    df = pd.read_csv(path, comment='#')
    return {sym: sorted(set(group['cik'].astype(int))) for sym, group in df.groupby('symbol')}


def filed_periodic_reports_between(submissions: dict, start, end) -> int:
    """Number of 10-K/10-Q filings between two dates (verifies a name match)"""
    recent = submissions.get('filings', {}).get('recent', {})
    forms, dates = recent.get('form', []), recent.get('filingDate', [])
    start, end = pd.Timestamp(start), pd.Timestamp(end) + pd.Timedelta(days=120)
    return sum(1 for f, d in zip(forms, dates)
               if f in ('10-K', '10-Q', '10-K/A', '10-Q/A') and start <= pd.Timestamp(d) <= end)


# ------------------------------------------------------------------- parsing

def _facts_frame(facts: dict, taxonomy: str, unit: str, tags: List[str]) -> pd.DataFrame:
    """All reported values for the tags, one row per (start, end, filed), best tag first"""
    frames = []
    group = facts.get('facts', {}).get(taxonomy, {})
    for priority, tag in enumerate(tags):
        values = group.get(tag, {}).get('units', {}).get(unit)
        if values:
            df = pd.DataFrame(values)
            df['priority'] = priority
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    if 'start' not in df:
        df['start'] = None
    df['end'] = pd.to_datetime(df['end'])
    df['start'] = pd.to_datetime(df['start'])
    df['filed'] = pd.to_datetime(df['filed'])
    df = df.dropna(subset=['val'])
    df = df.sort_values('priority').drop_duplicates(['start', 'end', 'filed'], keep='first')
    df['days'] = (df['end'] - df['start']).dt.days + 1
    return df


def _latest_known(df: pd.DataFrame, asof) -> pd.DataFrame:
    """For each (start, end), the most recently filed version on or before `asof`"""
    known = df[df['filed'] <= asof]
    return known.sort_values('filed').drop_duplicates(['start', 'end'], keep='last')


def _quarters(df: pd.DataFrame, derive_q4: bool = True) -> pd.DataFrame:
    """Quarterly versions [period_end, available_date, value]: direct 3-month facts + derived Q4"""
    if df.empty:
        return pd.DataFrame(columns=['period_end', 'available_date', 'value', 'derived'])
    q = df[df['days'].between(*QUARTER_DAYS)]
    rows = [pd.DataFrame({'period_end': q['end'], 'available_date': q['filed'],
                          'value': q['val'].astype(float), 'derived': False})]

    years = df[df['days'].between(*YEAR_DAYS)] if derive_q4 else df.iloc[0:0]
    years = years.sort_values('filed').drop_duplicates(['start', 'end'], keep='first')  # original 10-K only
    derived = []
    for fy in years.itertuples():
        known = _latest_known(df, fy.filed)
        nine = known[(known['start'] == fy.start) & known['days'].between(*NINE_MONTH_DAYS)
                     & (known['end'] < fy.end)]
        if len(nine):
            value = fy.val - nine.iloc[-1]['val']
        else:
            parts = known[known['days'].between(*QUARTER_DAYS) & (known['start'] >= fy.start)
                          & (known['end'] < fy.end - pd.Timedelta(days=60))]
            if len(parts) != 3:
                continue
            value = fy.val - parts['val'].sum()
        derived.append({'period_end': fy.end, 'available_date': fy.filed, 'value': float(value), 'derived': True})
    if derived:
        rows.append(pd.DataFrame(derived))

    out = pd.concat(rows, ignore_index=True)
    # a direct quarterly value beats a derived one filed the same day
    out = out.sort_values(['period_end', 'available_date', 'derived']).drop_duplicates(
        ['period_end', 'available_date'], keep='first')
    return out


def _dedupe_versions(rows: pd.DataFrame) -> pd.DataFrame:
    """Keep the first filing of each value; later filings only if the number changed"""
    rows = rows.sort_values(['field', 'period_end', 'available_date'])
    prev = rows.groupby(['field', 'period_end'])['value'].shift()
    changed = prev.isna() | ((rows['value'] - prev).abs() > 1e-9 * rows['value'].abs().clip(lower=1))
    return rows[changed]


def parse_company_facts(facts: dict, symbol: str) -> pd.DataFrame:
    """
    Point-in-time quarterly fundamentals for one company.

    Returns:
        DataFrame [symbol, field, period_end, available_date, value]
    """
    out = []
    for field, (unit, tags) in DURATION_FIELDS.items():
        q = _quarters(_facts_frame(facts, 'us-gaap', unit, tags), derive_q4=field not in NON_ADDITIVE)
        if not q.empty:
            out.append(q.assign(field=field))
    for field, (taxonomy, unit, tags) in INSTANT_FIELDS.items():
        df = _facts_frame(facts, taxonomy, unit, tags)
        if not df.empty:
            out.append(pd.DataFrame({'period_end': df['end'], 'available_date': df['filed'],
                                     'value': df['val'].astype(float), 'field': field}))
    if not out:
        return pd.DataFrame(columns=['symbol', 'field', 'period_end', 'available_date', 'value'])
    rows = _dedupe_versions(pd.concat(out, ignore_index=True))
    rows.insert(0, 'symbol', symbol)
    return rows[['symbol', 'field', 'period_end', 'available_date', 'value']].reset_index(drop=True)


def iter_companyfacts_zip(path: Path, ciks: Iterable[int]):
    """Yield (cik, facts) from the bulk companyfacts.zip for the requested CIKs"""
    wanted = {f"CIK{int(c):010d}.json": int(c) for c in ciks}
    with zipfile.ZipFile(path) as zf:
        for name in zf.namelist():
            if name in wanted:
                with zf.open(name) as fh:
                    yield wanted[name], json.load(fh)


DAILY_INDEX_URL = 'https://www.sec.gov/Archives/edgar/daily-index/{year}/QTR{quarter}/master.{date:%Y%m%d}.idx'
PERIODIC_FORMS = {'10-K', '10-Q', '10-K/A', '10-Q/A', '10-KT', '10-QT'}


def periodic_filers_on(client: SecClient, date) -> set:
    """
    CIKs that filed a 10-K/10-Q (or amendment) on `date`, from the SEC daily
    master index. Weekends/holidays have no index and return an empty set.
    """
    date = pd.Timestamp(date)
    url = DAILY_INDEX_URL.format(year=date.year, quarter=date.quarter, date=date)
    try:
        response = client.get(url)
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code in (403, 404):
            return set()
        raise
    if response is None:
        return set()
    ciks = set()
    for line in response.text.splitlines():
        parts = line.split('|')
        if len(parts) == 5 and parts[0].isdigit() and parts[2] in PERIODIC_FORMS:
            ciks.add(int(parts[0]))
    return ciks
