from html.parser import HTMLParser
from datetime import datetime, timezone
from typing import Optional, List

from ..commons.data import DATE_FORMATS

class MLStripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: List[str] = []

    def handle_data(self, d: str) -> None:
        self.parts.append(d)

    def get_data(self) -> str:
        return "".join(self.parts).strip()

def strip_html(raw: str) -> str:
    stripper = MLStripper()
    stripper.feed(raw or "")
    return stripper.get_data()

def parse_date(date_str: str) -> Optional[datetime]:
    if not date_str:
        return None
    for date_format in DATE_FORMATS:
        try:
            dt = datetime.strptime(date_str.strip(), date_format)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None