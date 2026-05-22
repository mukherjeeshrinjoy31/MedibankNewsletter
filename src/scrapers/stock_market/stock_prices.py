import json
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

import pandas as pd
import yfinance as yf

from ...commons.data import TICKERS, YFINANCE_URL
from ...commons.dataset import DATASET
from ...commons.tiers import TIER
from ...utils.helpers import build_payload, fetch_run_date, save_local, upload_to_s3

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Stock Price
# ---------------------------------------------------------------------------

def scrape_stock_price(ticker: str) -> str:
    """Fetch latest stock price data for a ticker and return as CSV string."""
    tk = yf.Ticker(ticker)
    hist = tk.history(period='5d')

    if hist.empty:
        raise ValueError(f"No data for {ticker}")

    last = hist.iloc[-1]
    date = last.name.strftime('%Y-%m-%d')

    header = 'ticker,date,open,high,low,close,volume,source_timestamp'
    line = (
        f"{ticker},{date},"
        f"{last.get('Open', '')},"
        f"{last.get('High', '')},"
        f"{last.get('Low', '')},"
        f"{last.get('Close', '')},"
        f"{int(last.get('Volume', 0)) if not pd.isna(last.get('Volume')) else ''},"
        f"{datetime.now(timezone.utc).isoformat()}"
    )
    return header + "\n" + line


# ---------------------------------------------------------------------------
# Financial Metrics
# ---------------------------------------------------------------------------

def get_dividend_history(tk: yf.Ticker) -> List[Dict]:
    """Extract last 5 dividend payments for a ticker."""
    try:
        if hasattr(tk, 'dividends') and not tk.dividends.empty:
            divs = tk.dividends.tail(5)
            return [
                {
                    'date': date.strftime('%Y-%m-%d'),
                    'amount': round(float(amount), 4)
                }
                for date, amount in divs.items()
            ]
        return []
    except Exception as e:
        logger.warning("Dividend history extraction error: %s", e)
        return []


def calculate_growth_metrics(tk: yf.Ticker) -> Dict[str, float]:
    """Calculate 1-month, 6-month and 1-year price growth metrics."""
    growth_metrics = {}
    try:
        hist_1m = tk.history(period='1mo')
        if len(hist_1m) >= 2:
            growth_metrics['1_month_growth_pct'] = round(
                ((hist_1m['Close'].iloc[-1] - hist_1m['Close'].iloc[0]) / hist_1m['Close'].iloc[0]) * 100, 2
            )

        hist_6m = tk.history(period='6mo')
        if len(hist_6m) >= 2:
            growth_metrics['6_month_growth_pct'] = round(
                ((hist_6m['Close'].iloc[-1] - hist_6m['Close'].iloc[0]) / hist_6m['Close'].iloc[0]) * 100, 2
            )

        hist_1y = tk.history(period='1y')
        if len(hist_1y) >= 2:
            growth_metrics['1_year_growth_pct'] = round(
                ((hist_1y['Close'].iloc[-1] - hist_1y['Close'].iloc[0]) / hist_1y['Close'].iloc[0]) * 100, 2
            )
            growth_metrics['52_week_high'] = round(float(hist_1y['High'].max()), 2)
            growth_metrics['52_week_low'] = round(float(hist_1y['Low'].min()), 2)

    except Exception as e:
        logger.warning("Growth metrics calculation error: %s", e)

    return growth_metrics


def get_financial_metrics(ticker: str) -> Dict[str, Any]:
    """Fetch comprehensive financial metrics for a ticker."""
    tk = yf.Ticker(ticker)
    info = tk.info

    return {
        'ticker': ticker,
        'financial_ratios': {
            'pe_ratio': info.get('trailingPE'),
            'peg_ratio': info.get('pegRatio'),
            'roe': info.get('returnOnEquity'),
            'roa': info.get('returnOnAssets'),
            'debt_to_equity': info.get('debtToEquity'),
            'eps': info.get('trailingEps')
        },
        'dividend_data': {
            'dividend_yield': info.get('dividendYield'),
            'dividend_history': get_dividend_history(tk)
        },
        'growth_metrics': calculate_growth_metrics(tk),
        'analyst_data': {
            'target_mean_price': info.get('targetMeanPrice'),
            'target_high_price': info.get('targetHighPrice'),
            'target_low_price': info.get('targetLowPrice'),
            'recommendation': info.get('recommendationKey'),
            'number_of_analyst_opinions': info.get('numberOfAnalystOpinions')
        }
    }


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def run(local: Optional[str] = None) -> bool:
    """Scrape stock prices and financial metrics for all tickers."""
    logger.info("Starting stock prices scraper")

    stock_prices_list = []
    financial_metrics_list = []

    for ticker_info in TICKERS:
        ticker = ticker_info['ticker']
        try:
            stock_prices_list.append({
                'ticker': ticker,
                'data': scrape_stock_price(ticker)
            })
            financial_metrics_list.append({
                'ticker': ticker,
                'data': get_financial_metrics(ticker)
            })
        except Exception as e:
            logger.error("Error processing ticker %s: %s", ticker, e)
            continue

    if not stock_prices_list and not financial_metrics_list:
        logger.warning("No stock data extracted — skipping.")
        return False

    stock_price_payload = build_payload(
        json.dumps(stock_prices_list),
        "yfinance_stock_price",
        DATASET.STOCK_PRICE.value,
        fetch_run_date(),
        TIER.COMPETITOR.value,
        YFINANCE_URL
    )

    fin_metrics_payload = build_payload(
        json.dumps(financial_metrics_list),
        "yfinance_financial_metrics",
        DATASET.FIN_METRICS.value,
        fetch_run_date(),
        TIER.COMPETITOR.value,
        YFINANCE_URL
    )

    if local:
        save_local(stock_price_payload)
        save_local(fin_metrics_payload)
    else:
        upload_to_s3(stock_price_payload)
        upload_to_s3(fin_metrics_payload)

    return True


if __name__ == "__main__":
    run(local="data")