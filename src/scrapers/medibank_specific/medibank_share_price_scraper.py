import json
import logging
import yfinance as yf
from datetime import datetime, timezone

# ── Config ──────────────────────────────────────────────────────
SOURCE  = 'medibank'
TIER    = 'medibank_specific'
DATASET = 'share_price'
URL     = 'https://finance.yahoo.com/quote/MPL.AX'
BUCKET  = 'p000268ds-medibank-intelligence'

TICKER  = 'MPL.AX'   # Medibank on ASX

# ── Logging ──────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("medibank_share_price.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


# ── Step 1: Fetch price and volume data ─────────────────────────
def scrape() -> str:
    try:
        log.info(f"Fetching data for {TICKER}")
        ticker = yf.Ticker(TICKER)

        # Get last 30 days of history
        hist = ticker.history(period="30d")

        if hist.empty:
            log.error("No historical data returned")
            return None

        # ── Latest day ───────────────────────────────────────────
        latest        = hist.iloc[-1]
        latest_close  = round(latest["Close"], 2)
        latest_volume = int(latest["Volume"])

        # ── Price changes ────────────────────────────────────────
        prev_close    = round(hist.iloc[-2]["Close"], 2)
        day_change    = round(latest_close - prev_close, 2)
        day_change_pct = round((day_change / prev_close) * 100, 2)

        week_close    = round(hist.iloc[-6]["Close"], 2) if len(hist) >= 6 else None
        week_change_pct = round(((latest_close - week_close) / week_close) * 100, 2) if week_close else None

        month_close   = round(hist.iloc[0]["Close"], 2)
        month_change_pct = round(((latest_close - month_close) / month_close) * 100, 2)

        # ── 52 week high/low ─────────────────────────────────────
        yearly = ticker.history(period="52wk")
        high_52w = round(yearly["High"].max(), 2)
        low_52w  = round(yearly["Low"].min(), 2)

        # ── Volume vs 30 day average ─────────────────────────────
        avg_volume_30d = int(hist["Volume"].mean())
        volume_spike   = latest_volume > (avg_volume_30d * 1.5)

        # ── Build plain text content ─────────────────────────────
        content = f"""
Medibank Private (ASX: MPL) Share Price & Volume Report
Run Date: {datetime.now(timezone.utc).isoformat()}

PRICE MOVEMENT
Current Price:        ${latest_close} AUD
Daily Change:         ${day_change} ({day_change_pct}%)
7-Day Change:         {week_change_pct}%
30-Day Change:        {month_change_pct}%
52-Week High:         ${high_52w}
52-Week Low:          ${low_52w}

TRADING VOLUME
Latest Volume:        {latest_volume:,} shares
30-Day Avg Volume:    {avg_volume_30d:,} shares
Volume Spike:         {'YES - unusual activity detected' if volume_spike else 'No - within normal range'}
        """.strip()

        log.info("Data fetched successfully")
        return content

    except Exception as e:
        log.error(f"Failed to fetch share price data: {e}")
        return None


# ── Step 2: Build payload ────────────────────────────────────────
def build_payload(content: str) -> dict:
    return {
        'source':     SOURCE,
        'tier':       TIER,
        'dataset':    DATASET,
        'scraped_at': datetime.now(timezone.utc).isoformat(),
        'url':        URL,
        'content':    content,
    }


# ── Step 3: Save locally ─────────────────────────────────────────
def save_locally(payload: dict) -> None:
    date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    filename = f"{SOURCE}_{DATASET}_{date}.json"
    try:
        with open(filename, "w") as f:
            json.dump(payload, f, indent=2)
        log.info(f"Saved: {filename}")
    except Exception as e:
        log.error(f"Failed to save file: {e}")


# ── Step 4: Upload to S3 (uncomment when ready) ──────────────────
# def upload_to_s3(payload: dict) -> None:
#     import boto3
#     s3   = boto3.client('s3', region_name='ap-southeast-2')
#     date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
#     key  = f"raw/{payload['tier']}/{payload['source']}_{payload['dataset']}_{date}.json"
#     s3.put_object(Bucket=BUCKET, Key=key,
#                   Body=json.dumps(payload, ensure_ascii=False),
#                   ContentType='application/json')
#     log.info(f'Uploaded: s3://{BUCKET}/{key}')


# ── Main ─────────────────────────────────────────────────────────
if __name__ == '__main__':
    log.info("=" * 50)
    log.info(f"Starting scrape: {SOURCE} / {DATASET}")
    log.info("=" * 50)

    content = scrape()

    if not content:
        log.warning("No data returned — file will not be saved")
    else:
        payload = build_payload(content)
        save_locally(payload)
        # swap to upload_to_s3(payload) when ready for S3

    log.info("Scrape complete")