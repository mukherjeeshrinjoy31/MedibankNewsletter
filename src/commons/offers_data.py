from enum import Enum
import re

class SOURCE(Enum):
    AHM = 'ahm'
    BUPA = 'bupa'
    FINDER = 'finder'
    HBF = 'hbf'
    HCF = 'hcf'
    MEDIBANK = 'medibank'
    NIB = 'nib'

BRANDS = {
    "medibank": "Medibank",
    "ahm":      "ahm",
    "bupa":     "Bupa",
    "nib":      "nib",
    "hcf":      "HCF",
    "hbf":      "HBF",
}    

HOSPITAL_EXTRAS = "hospital + extras"
HOSPITAL_ONLY = "hospital only"
EXTRAS_ONLY = "extras only"
FINDER_URL = "https://www.finder.com.au/health-insurance"

AHM_OFFER_URL = "https://ahm.com.au/offer"
AHM_ROOT_URL = 'https://ahm.com.au/health-insurance'

HBF_ROOT_URL  = 'https://www.hbf.com.au'
HBF_TERMS_URL = 'https://www.hbf.com.au/terms-and-conditions/new-member-promotion'
HBF_SCRAPE_PAGES = [
    {"url": "https://www.hbf.com.au",                                 "cover_hint": HOSPITAL_EXTRAS},
    {"url": "https://www.hbf.com.au/health-insurance/hospital-cover", "cover_hint": HOSPITAL_ONLY},
    {"url": "https://www.hbf.com.au/health-insurance/extras-cover",   "cover_hint": EXTRAS_ONLY},
]

BUPA_OFFER_URL = "https://www.bupa.com.au/offers"
HCF_OFFER_URL = "https://www.hcf.com.au/health-insurance"
NIB_OFFER_URL = "https://www.nib.com.au/health-insurance/offers"

MEDIBANK_ROOT_URL  = 'https://www.medibank.com.au'
MEDIBANK_OFFER_URL = 'https://www.medibank.com.au'
MEDIBANK_SCRAPE_PAGES = [
    {"url": "https://www.medibank.com.au"},
    {"url": "https://www.medibank.com.au/health-insurance/hospital-cover/"},
    {"url": "https://www.medibank.com.au/health-insurance/extras-cover/", "cover_hint": EXTRAS_ONLY},
]

OFFER_EXCEL_FILE      = 'comp_offer.xlsx'

COVER_TYPES = ["hospital + extras", "hospital only", EXTRAS_ONLY]
COVER_CATEGORY = ["basic", "bronze", "silver", "gold"]

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

BUPA_OFFER_PAGES = [
    {"name": "Bupa Offers",            "url": "https://www.bupa.com.au/offers"},
    {"name": "Bupa Hospital & Extras", "url": "https://www.bupa.com.au/health-insurance/hospital-and-extras-cover"},
    {"name": "Bupa Hospital Only",     "url": "https://www.bupa.com.au/health-insurance/hospital-cover"},
    {"name": "Bupa Extras Only",       "url": "https://www.bupa.com.au/health-insurance/extras-cover"},
]

HCF_OFFER_PAGES = [
    {"name": "HCF Homepage",            "url": "https://www.hcf.com.au/"},
    {"name": "HCF Find Health Insurance","url": "https://www.hcf.com.au/health-insurance/find-health-insurance"},
    {"name": "HCF Hospital & Extras",   "url": "https://www.hcf.com.au/health-insurance/find-health-insurance/hospital-and-extras"},
    {"name": "HCF Hospital Only",       "url": "https://www.hcf.com.au/health-insurance/find-health-insurance/hospital"},
    {"name": "HCF Extras Only",         "url": "https://www.hcf.com.au/health-insurance/find-health-insurance/extras"},
]

NIB_OFFER_PAGES = [
    {"name": "NIB Offers",              "url": "https://www.nib.com.au/health-insurance/offers"},
    {"name": "NIB Homepage",            "url": "https://www.nib.com.au/"},
    {"name": "NIB Health Insurance",    "url": "https://www.nib.com.au/health-insurance"},
    {"name": "NIB Hospital",            "url": "https://www.nib.com.au/health-insurance/hospital"},
    {"name": "NIB Extras",              "url": "https://www.nib.com.au/health-insurance/extras"},
]

OFFER_KEYWORDS = [
    "weeks free", "week free", "waiting period", "waiver", "promo",
    "offer", "bonus", "discount", "join by", "ends", "new members",
    "everyday rewards", "10weeksfree", "everyday120", "gift card",
    "mastercard", "e-gift", "cashback", "loyalty",
    "12wfreeww", "extras8wf", "skip the", "month wait",
]

TC_KEYWORDS = [
    "new members only", "fulfilled", "ineligible", "residency",
    "exclusions apply", "direct debit", "maintained", "t&cs apply",
    "eligibility", "terms and conditions", "annual payers", "excluding",
    "eligible members", "eligible customers", "waiting periods",
    "australian resident", "not have been", "cooling off",
    "new australian resident", "available to new", "value of offer",
    "level of cover", "kickstarter",
]

WEEKS_PAT    = re.compile(r'(?:up to\s+)?(\d+(?:\+\d+)?)\s*weeks?\s*free', re.I)
WAITING_PAT  = re.compile(r'(\d+)\s*(?:and|&)\s*(\d+)\s*month.*?(?:wait|waiv)', re.I)
WAITING_PAT2 = re.compile(r'(\d+)\s*month.*?(?:wait|waiv)', re.I)
ENDDATE_PAT2 = re.compile(r'(\d{1,2}\s+[A-Za-z]{3,}\s+\d{4})', re.I)