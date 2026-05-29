from enum import Enum

class SOURCE(Enum):
    AHM = 'ahm'
    MEDIBANK = 'medibank'

EXTRAS_ONLY = "extras only"

AHM_OFFER_URL = "https://ahm.com.au/offer"
AHM_ROOT_URL = 'https://ahm.com.au/health-insurance'

MEDIBANK_ROOT_URL  = 'https://www.medibank.com.au'
MEDIBANK_OFFER_URL = 'https://www.medibank.com.au'
MEDIBANK_SCRAPE_PAGES = [
    {"url": "https://www.medibank.com.au"},
    {"url": "https://www.medibank.com.au/health-insurance/hospital-cover/"},
    {"url": "https://www.medibank.com.au/health-insurance/extras-cover/", "cover_hint": EXTRAS_ONLY},
]

OFFER_EXCEL_FILE      = 'comp_offer.xlsx'

COVER_TYPES = ["hospital + extras", "hospital only", EXTRAS_ONLY]

AHM_SCRAPE_PAGES = [
    {"url": "https://ahm.com.au/offer"},
    {"url": "https://ahm.com.au/health-insurance"},
    {"url": "https://ahm.com.au/health-insurance/hospital-cover"},
    {"url": "https://ahm.com.au/health-insurance/extras-cover", "cover_hint": "extras only"},
]

# Excel column mapping (scraper field -> Excel header)
EXCEL_COL_MAP = {
    "weeks_free":       "Offer : Weeks Free",
    "waiting_waive":    "Offer : Waiting period waive",
    "other":            "Offer : Other",
    "end_date":         "Offer : End date",
    "terms_conditions": ("Offer : T&C", "Offer : T&C's", "Offer : T&Cs", "Offer : T&Cs apply"),
}

TERM_HEADINGS = [
    "Hospital and Extras offer:",
    "12 weeks free terms:",
    "2&6 month waits waived on extras terms:",
    "Live Better rewards points terms:",
    "Live Better rewards terms:",
    "Extras only offer:",
    "Weeks free terms:",
    "Live Better points terms:",
]

TERMS_STOP_MARKERS = [
    "Health members save 15%",
    "Ready for your next adventure?",
    "2 months free pet insurance",
    "Get 2 months free on Medibank Life Insurance",
    "Request a call back",
    "COVID-19 Health Assist",
    "Insurance Health insurance",
]