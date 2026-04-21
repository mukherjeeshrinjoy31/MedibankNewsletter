from datetime import datetime

def build_payload(content: str, source: str, dataset: str, scrapped_at: datetime, tier: str, url: str) -> dict:
    return {
        'source': source,
        'tier': tier,
        'dataset': dataset,
        'scraped_at': scrapped_at,
        'url': url,
        'content': content
    }