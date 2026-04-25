from datetime import datetime, timezone
from typing import Optional, Dict, Any


import pandas as pd
import json
import yfinance as yf

from ...commons.dataset import DATASET
from ...commons.tiers import TIER
from ...utils.helpers import build_payload, upload_to_s3, save_local
from ...commons.data import TICKERS, YFINANCE_URL

def scrape_stock_price(ticker: str) -> str:
    """
    Scrape latest stock price data for a given ticker
    Returns plain-text CSV string
    """
    try:
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
    
    except Exception as e:
        print(f"Error scraping stock price for {ticker}: {e}")
        raise

def get_financial_metrics(ticker: str) -> Dict[str, Any]:
    """
    Fetch comprehensive financial metrics for a given ticker
    """
    try:
        tk = yf.Ticker(ticker)
        info = tk.info

        # Financial Ratios
        financial_ratios = {
            'pe_ratio': info.get('trailingPE'),
            'peg_ratio': info.get('pegRatio'),
            'roe': info.get('returnOnEquity'),
            'roa': info.get('returnOnAssets'),
            'debt_to_equity': info.get('debtToEquity'),
            'eps': info.get('trailingEps')
        }

        # Dividend Data
        dividend_data = {
            'dividend_yield': info.get('dividendYield'),
            'dividend_history': get_dividend_history(tk)
        }

        # Growth Metrics
        growth_metrics = calculate_growth_metrics(tk)

        # Analyst Data
        analyst_data = {
            'target_mean_price': info.get('targetMeanPrice'),
            'target_high_price': info.get('targetHighPrice'),
            'target_low_price': info.get('targetLowPrice'),
            'recommendation': info.get('recommendationKey'),
            'number_of_analyst_opinions': info.get('numberOfAnalystOpinions')
        }

        return {
            'ticker': ticker,
            'financial_ratios': financial_ratios,
            'dividend_data': dividend_data,
            'growth_metrics': growth_metrics,
            'analyst_data': analyst_data
        }
    
    except Exception as e:
        print(f"Error fetching financial metrics for {ticker}: {e}")
        raise

def get_dividend_history(tk: yf.Ticker) -> list:
    """
    Extract dividend history
    """
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
        print(f"Dividend history extraction error: {e}")
        return []

def calculate_growth_metrics(tk: yf.Ticker) -> Dict[str, float]:
    """
    Calculate historical growth metrics
    """
    growth_metrics = {}
    try:
        # 1 Month Growth
        hist_1m = tk.history(period='1mo')
        if len(hist_1m) >= 2:
            growth_1m = ((hist_1m['Close'].iloc[-1] - hist_1m['Close'].iloc[0]) / hist_1m['Close'].iloc[0]) * 100
            growth_metrics['1_month_growth_pct'] = round(growth_1m, 2)

        # 6 Months Growth
        hist_6m = tk.history(period='6mo')
        if len(hist_6m) >= 2:
            growth_6m = ((hist_6m['Close'].iloc[-1] - hist_6m['Close'].iloc[0]) / hist_6m['Close'].iloc[0]) * 100
            growth_metrics['6_month_growth_pct'] = round(growth_6m, 2)

        # 1 Year Growth and 52-week stats
        hist_1y = tk.history(period='1y')
        if len(hist_1y) >= 2:
            growth_1y = ((hist_1y['Close'].iloc[-1] - hist_1y['Close'].iloc[0]) / hist_1y['Close'].iloc[0]) * 100
            growth_metrics['1_year_growth_pct'] = round(growth_1y, 2)
            growth_metrics['52_week_high'] = round(float(hist_1y['High'].max()), 2)
            growth_metrics['52_week_low'] = round(float(hist_1y['Low'].min()), 2)

        return growth_metrics
    except Exception as e:
        print(f"Growth metrics calculation error: {e}")
        return {}

def run(local: Optional[str] = None) -> bool:
    """
    Main execution method for scraping stock data
    """
    
    # Initialize stock price and financial metrics lists
    stock_prices_list = []
    financial_metrics_list = []

    # Process each ticker
    for ticker_info in TICKERS:
        ticker = ticker_info['ticker']
        try:
            # Scrape stock price
            stock_price_content = scrape_stock_price(ticker)
            
            # Get financial metrics
            financial_metrics = get_financial_metrics(ticker)

            # Add to respective lists
            stock_prices_list.append({
                'ticker': ticker,
                'data': stock_price_content
            })

            financial_metrics_list.append({
                'ticker': ticker,
                'data': financial_metrics
            })

        except Exception as e:
            logging.error(f"Error processing ticker {ticker}: {e}")
            continue

    # Create payloads with collected data
    stock_price_payload = build_payload(
        json.dumps(stock_prices_list),
        "yfinance_stock_price",
        DATASET.STOCK_PRICE.value,
        datetime.now(timezone.utc).isoformat(),
        TIER.COMPETITOR.value,
        YFINANCE_URL
    )

    fin_metrics_payload = build_payload(
        json.dumps(financial_metrics_list),
        "yfinance_financial_metrics",
        DATASET.FIN_METRICS.value,
        datetime.now(timezone.utc).isoformat(),
        TIER.COMPETITOR.value,
        YFINANCE_URL
    )

    # Determine save method based on local flag
    if local:
        save_local(stock_price_payload)
        save_local(fin_metrics_payload)
    else:
        upload_to_s3(stock_price_payload)
        upload_to_s3(fin_metrics_payload)
    
    return True
