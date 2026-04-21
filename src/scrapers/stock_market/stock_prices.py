import json
import logging
from datetime import datetime, timezone
from ...commons.tiers import TIER
import os

import yfinance as yf
import pandas as pd

from ...utils.helpers import build_payload

RAW_ROOT = './raw'
ANALYTICS_ROOT = './analytics'
TICKERS = [
    {'ticker': 'MPL.AX', 'source': 'asx_mpl'},
    {'ticker': 'NHF.AX', 'source': 'asx_nib'}
]

def format_content_kv(csv_text: str) -> str:
    lines = csv_text.splitlines()
    if len(lines) < 2:
        return csv_text
    headers = [h.strip() for h in lines[0].split(',')]
    values = [v.strip() for v in lines[1].split(',')]
    pairs = [f"{k}={v}" for k, v in zip(headers, values)]
    return ",".join(pairs)

def format_metrics_content(metrics: dict) -> str:
    parts = []
    fr = metrics.get('financial_ratios', {})
    fr_items = ", ".join(f"{k}={v!s}" for k, v in fr.items())
    parts.append(f"financial_ratios : {fr_items}")

    inc = metrics.get('income_statement', {})
    inc_items = ", ".join(f"{k}={v!s}" for k, v in inc.items())
    parts.append(f"income_statement : {inc_items}")

    div = metrics.get('dividend_data', {})
    # dividend_history as compact list
    dh = div.get('dividend_history', [])
    dh_str = "; ".join(f"{d['date']}={d['amount']}" for d in dh)
    other_div = ", ".join(f"{k}={v!s}" for k, v in div.items() if k != 'dividend_history')
    div_line = ", ".join(filter(None, [other_div, f"dividend_history=[{dh_str}]" if dh_str else ""]))
    parts.append(f"dividend_data : {div_line or 'None'}")

    growth = metrics.get('growth_metrics', {})
    growth_items = ", ".join(f"{k}={v!s}" for k, v in growth.items())
    parts.append(f"growth_metrics : {growth_items or 'None'}")

    analyst = metrics.get('analyst_data', {})
    analyst_items = ", ".join(f"{k}={v!s}" for k, v in analyst.items())
    parts.append(f"analyst_data : {analyst_items or 'None'}")

    return "\\n".join(parts)


def parse_source_dataset(source_field: str) -> tuple:
    parts = source_field.split('_',1)
    return (parts[0], parts[1]) if len(parts)==2 else (parts[0], '')

def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)

def write_json_file(root, tier, source, dataset, date_str, filename_suffix, payload):
    ensure_dir(os.path.join(root, tier))
    filename = f"{source}{dataset}{date_str}{filename_suffix}"
    path = os.path.join(root, tier, filename)
    if os.path.exists(path):
        logging.info(f"Skipped (exists): {path}")
        return path
    with open(path,'w',encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    logging.info(f"Wrote: {path}")
    return path

def scrape(ticker: str) -> str:
    """
    Returns plain-text CSV string for latest trading day:
    header: ticker,date,open,high,low,close,volume,source_timestamp
    """
    tk = yf.Ticker(ticker)
    hist = tk.history(period='5d')
    if hist.empty:
        raise RuntimeError(f"No data for {ticker}")
    last = hist.iloc[-1]
    date = last.name.strftime('%Y-%m-%d')
    open_p = last.get('Open', '')
    high_p = last.get('High', '')
    low_p = last.get('Low', '')
    close_p = last.get('Close', '')
    volume = int(last.get('Volume', 0)) if not pd.isna(last.get('Volume')) else ''
    api_timestamp = datetime.now(timezone.utc).isoformat()
    header = 'ticker,date,open,high,low,close,volume,source_timestamp'
    line = f"{ticker},{date},{open_p},{high_p},{low_p},{close_p},{volume},{api_timestamp}"
    return header + "\n" + line

def get_financial_metrics(ticker: str) -> dict:
    tk = yf.Ticker(ticker)
    info = tk.info

    # Income Statement
    net_income = None
    dividend_history = []
    
    try:
        if hasattr(tk, 'financials') and not tk.financials.empty and 'Net Income' in tk.financials.index:
            net_income = float(tk.financials.loc['Net Income'].iloc[0])
    except Exception as e:
        logging.warning(f"Income Statement Error for {ticker}: {e}")

    # Dividend History
    try:
        if hasattr(tk, 'dividends') and not tk.dividends.empty:
            divs = tk.dividends.tail(5)
            for date, amount in divs.items():
                dividend_history.append({
                    'date': date.strftime('%Y-%m-%d'),
                    'amount': float(amount)
                })
    except Exception as e:
        logging.warning(f"Dividend History Error for {ticker}: {e}")

    # Historical Growth
    growth_metrics = {}
    try:
        hist_1m = tk.history(period='1mo')
        if len(hist_1m) >= 2:
            growth_1m = ((hist_1m['Close'].iloc[-1] - hist_1m['Close'].iloc[0]) / hist_1m['Close'].iloc[0]) * 100
            growth_metrics['1_month_growth_pct'] = round(growth_1m, 2)

        hist_6m = tk.history(period='6mo')
        if len(hist_6m) >= 2:
            growth_6m = ((hist_6m['Close'].iloc[-1] - hist_6m['Close'].iloc[0]) / hist_6m['Close'].iloc[0]) * 100
            growth_metrics['6_month_growth_pct'] = round(growth_6m, 2)

        hist_1y = tk.history(period='1y')
        if len(hist_1y) >= 2:
            growth_1y = ((hist_1y['Close'].iloc[-1] - hist_1y['Close'].iloc[0]) / hist_1y['Close'].iloc[0]) * 100
            growth_metrics['1_year_growth_pct'] = round(growth_1y, 2)
            growth_metrics['52_week_high'] = round(float(hist_1y['High'].max()), 2)
            growth_metrics['52_week_low'] = round(float(hist_1y['Low'].min()), 2)
    except Exception as e:
        logging.warning(f"Historical Growth Error for {ticker}: {e}")

    financial_metrics = {
        'financial_ratios': {
            'pe_ratio': info.get('trailingPE'),
            'peg_ratio': info.get('pegRatio'),
            'roe': info.get('returnOnEquity'),
            'roa': info.get('returnOnAssets'),
            'debt_to_equity': info.get('debtToEquity'),
            'eps': info.get('trailingEps')
        },
        'income_statement': {
            'net_income': net_income
        },
        'dividend_data': {
            'dividend_yield': info.get('dividendYield'),
            'dividend_history': dividend_history
        },
        'growth_metrics': growth_metrics,
        'analyst_data': {
            'target_mean_price': info.get('targetMeanPrice'),
            'target_high_price': info.get('targetHighPrice'),
            'target_low_price': info.get('targetLowPrice'),
            'recommendation': info.get('recommendationKey'),
            'number_of_analyst_opinions': info.get('numberOfAnalystOpinions')
        }
    }
    return financial_metrics




# Fetch data for all tickers
date_str = datetime.utcnow().strftime('%Y-%m-%d')
results = []
for item in TICKERS:
    ticker = item.get('ticker')
    source_field = item.get('source')
    source, dataset = parse_source_dataset(source_field)
    url = f"yfinance:{ticker}"

    try:
        content = scrape(ticker)
    except Exception as e:
        logging.error(f"ERROR scraping {ticker}: {e}")
        continue

    if not content or not content.strip():
        logging.error(f"Empty content for {ticker}; skipping.")
        continue

    # build and write spec-compliant raw file (six fields)
    spec_payload = build_payload(
        content=format_content_kv(content),
        source=source,
        dataset=dataset,
        scrapped_at=datetime.now(timezone.utc).isoformat(),
        tier=TIER.COMPETITOR,
        url=url
    )
    raw_path = write_json_file(RAW_ROOT, TIER.COMPETITOR, source, dataset, date_str, '.json', spec_payload)

    # build and write financial metrics separately under analytics
    analytics_path = None
    try:
        metrics = get_financial_metrics(ticker)
        metrics_payload = {
            'source': source,
            'tier': TIER.COMPETITOR,
            'dataset': dataset,
            'scraped_at': spec_payload['scraped_at'],
            'url': url,
            'content': format_metrics_content(metrics)
        }
        analytics_path = write_json_file(ANALYTICS_ROOT, TIER, source, dataset, date_str, '_metrics.json', metrics_payload)
    except Exception as e:
        logging.warning(f"Failed to collect/write metrics for {ticker}: {e}")

    results.append({
        'ticker': ticker,
        'raw': raw_path,
        'metrics': analytics_path
    })

# Final summary printed locally
logging.info("Run complete. Files:")
for r in results:
    logging.info(json.dumps(r))