"""
Stock Market Scrapers
---------------------
Scrapers for stock market data relevant to Medibank and its
competitors in the private health insurance industry.

Scrapers:
    stock_prices - Yahoo Finance stock prices and financial metrics
                   for Medibank and competitor tickers
"""

from .stock_prices import run as run_stock_prices

__all__ = [
    "run_stock_prices",
]