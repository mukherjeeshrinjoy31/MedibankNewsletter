# ============================
# Global Constants (Sorted)
# ============================

ABC_NEWS_URL                            = "https://www.abc.net.au/"
ACCC_BASE_URL                           = "https://www.accc.gov.au"
ACCC_PHI_URL                            = "https://www.accc.gov.au/about-us/publications/serial-publications/private-health-insurance-reports"
AMA_SOURCE_URL                          = "https://www.ama.com.au/"
AMA_REPORT_URL                          = "https://www.ama.com.au/advocacy-policy?f%5B0%5D=type%3A51" # AMA report card page
APRA_ANNUAL_STATISTICS_URL              = "https://www.apra.gov.au/operations-of-private-health-insurers-annual-report"
APRA_QUARTERLY_STATISTICS_URL           = "https://www.apra.gov.au/quarterly-private-health-insurance-statistics"
APRA_BASE_URL                           = "https://www.apra.gov.au"
ARTICLES_SEARCH_URL                     = "https://www.choice.com.au/?s=Medibank&tab=articles"
ASX_MEDIBANK_RELEASES_URL               = "https://www.medibank.com.au/livebetter/newsroom/classification/asx-releases"
ASX_NIB_ANNOUNCEMENTS_URL               = "https://www.nib.com.au/shareholders/announcements"
GUARDIAN_NEWS_URL                       = "https://www.theguardian.com/au"
HBF_URL                                 = "https://www.hbf.com.au"
HCF_URL                                 = 'https://www.hcf.com.au'
HEALTH_DEPT_MINISTERS_URL               = "https://www.health.gov.au/ministers"
HEALTH_DEPT_CLINICAL_URL                = "https://www.health.gov.au/resources/collections/private-health-insurance-clinical-category-and-procedure-type"
HEALTH_DEPT_BASE_URL                    = "https://www.health.gov.au"
LEGISLATION_PHI_URL                     = "https://www.legislation.gov.au/Latest/F2018C00750"
LEGISLATION_RSS_URL                     = "https://news.google.com/rss/search?q=private+health+insurance+legislation+amendment+Australia&hl=en-AU&gl=AU&ceid=AU:en"
MBS_BASE_URL                            = "http://www.mbsonline.gov.au"
MBS_DOWNLOAD_URL                        = "http://www.mbsonline.gov.au/internet/mbsonline/publishing.nsf/Content/downloads"
MEDIBANK_BASE_URL                       = "https://www.medibank.com.au"
MEDIBANK_SPECIFIC_MEDIA_RELEASES_URL    = "https://www.medibank.com.au/livebetter/newsroom/classification/media-releases"
OMBUDSMAN_PHI_URL                       = "https://www.ombudsman.gov.au/industry-and-agency-oversight/industry-updates/private-health-insurance-updates"
OMBUDSMAN_RSS_URL                       = "https://news.google.com/rss/search?q=private+health+insurance+ombudsman+Australia&hl=en-AU&gl=AU&ceid=AU:en"
OZBARGAIN_URL                           = "https://www.ozbargain.com.au"
PRIVATE_HEALTH_URL                      = "https://data.gov.au/data/dataset/private-health-insurance"
PRIVATE_HEALTH_FALLBACK_ZIP_URL         = "https://data.gov.au/data/dataset/8ab10b1f-6eac-423c-abc5-bbffc31b216c/resource/ca9c9e9f-a114-4e9a-a29f-6b3f641b8e6f/download/privatehealth-01-mar-2026.zip"
RSS_FEED_URL                            = "https://www.ozbargain.com.au/deals/medibank.com.au/feed"
YFINANCE_URL                            = "https://au.finance.yahoo.com/quote/ASX.AX/"
SBS_NEWS_URL                            = "https://www.sbs.com.au/news"


NEWSROOM_COMPETITOR_SOURCE_URLS = [
    {
        "name": "Bupa",
        "url": "https://media.bupa.com.au/",
        "rss": False,
        "article_url_keywords": ["media.bupa.com.au/"]
    },
    {
        "name": "NIB",
        "url": "https://www.nib.com.au/media/company",
        "rss": False,
        "article_url_keywords": ["/media/"]
    },
    {
        "name": "HCF",
        "url": "https://www.hcf.com.au/about-us/media-centre/media-releases",
        "rss": False,
        "article_url_keywords": ["media-releases/20", "newsroom/post"]
    },
    {
        "name": "HBF",
        "url": "https://www.hbf.com.au/about-hbf/newsroom",
        "rss": False,
        "article_url_keywords": ["/newsroom/about-hbf/newsroom/"]
    },
]

NEWSROOM_SKIP_URL_KEYWORDS = [
    "contact", "login", "quote", "find-a-provider", "careers",
    "tel:", "#nav", "bupa.com.au/#", "bupaplus", "dental.bupa",
    "bupamvs", "format=rss", "compare", "switch", "corporate"
]

MACRO_URLS = [
    (
        "https://www.abs.gov.au/statistics/economy/price-indexes-and-inflation"
        "/consumer-price-index-australia/latest-release",
        "abs_cpi",
        "cpi",
    ),
    (
        "https://www.abs.gov.au/statistics/labour/employment-and-unemployment"
        "/labour-force-australia/latest-release",
        "abs_labour_force",
        "labour_force",
    ),
    (
        "https://www.abs.gov.au/statistics/labour/employment-and-unemployment"
        "/labour-force-australia-detailed/latest-release",
        "abs_labour_force_detailed",
        "labour_force_detailed",
    ),
]

MACRO_NOISE_TAGS = {"script", "style", "noscript", "nav", "footer", "header", "form", "button"}

NEWS_URLS = {
    "ABC" : [
        "https://www.abc.net.au/news/health",
        "https://www.abc.net.au/news/topic/health-insurance",
    ],
    "SBS" : [
        "https://www.sbs.com.au/news/collection/health-and-wellbeing",
        "https://www.sbs.com.au/news/tag/subject/health",
        "https://www.sbs.com.au/news/tag/subject/health-care-costs"
    ],
    "GUARDIAN" : [
        "https://www.theguardian.com/australia-news/health",
        "https://www.theguardian.com/money/healthinsurance",
    ]
}


NEWS_BOILERPLATE_PATTERNS = {
    "ABC" : [     
        r"^topic:?$",
        r"^this site is protected by recaptcha",
        r"^follow @abc",
        r"^\(.+:.+\)$",
        r"^analysis by ",
        r"^live$",
        r"^[a-z ]+:$",
    ],
    "SBS" : [
        r"^sign up now",
        r"^sbs on the money",
        r"^sbs news in easy english",
        r"^your daily ten minute",
        r"^get the latest with our",
        r"^live stream",
        r"^follow the latest",
        r"^from breaking headlines",
        r"^[a-z ]+:$",
        r"^\(.+:.+\)$",
    ],
    "GUARDIAN" : [
        r"^sign in",
        r"^subscribe",
        r"^support the guardian",
        r"^print this page",
        r"^reuse this content",
        r"^\(.+:.+\)$",
        r"^[a-z ]+:$",
        r"^topics$",
        r"^more on this story",
    ]
}

EXCLUDED_SECTIONS = {
    "live",       # live blogs
    "video",      # video pages
    "audio",      # podcasts
    "picture",    # picture galleries
    "morning-mail-newsletter",
    "afternoon-update-newsletter",
}

MEDIBANK_NEWSROOM_TAG = "/livebetter/newsroom/post/"
INSURANCE_PROVIDERS = "medibank"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# ============================
# Insurance Award URLs (Sorted)
# ============================

INSURANCE_AWARD_URLS = [
    "https://www.canstar.com.au/pet-insurance/star-ratings-awards/",
    "https://www.canstar.com.au/star-ratings-awards/direct-income-protection/",
    "https://www.canstar.com.au/star-ratings-awards/direct-life-insurance/",
    "https://www.canstar.com.au/star-ratings-awards/health-insurance/",
    "https://www.canstar.com.au/star-ratings-awards/insurer-of-the-year-award/",
    "https://www.canstar.com.au/star-ratings-awards/most-satisfied-customers-health-insurer-award/",
    "https://www.canstar.com.au/star-ratings-awards/most-satisfied-customers-pet-insurance-awards/",
    "https://www.canstar.com.au/star-ratings-awards/most-satisfied-customers-travel-insurance-award/",
    "https://www.canstar.com.au/star-ratings-awards/overseas-student-working-visa-health/",
    "https://www.canstar.com.au/travel-insurance/star-ratings-awards/",
]

# ============================
# Skip Titles (Sorted)
# ============================

NIB_ASX_SKIP_TITLES = [
    "Code of Conduct",
    "Privacy Policy",
    "Reconciliation Action Plan",
    "Terms & Conditions",
    "View our Reconciliation Action Plan",
]

# ============================
# Month Map (Sorted)
# ============================

MONTH_MAP = {
    "Apr": "April",
    "Aug": "August",
    "Dec": "December",
    "Feb": "February",
    "Jan": "January",
    "Jul": "July",
    "Jun": "June",
    "Mar": "March",
    "May": "May",
    "Nov": "November",
    "Oct": "October",
    "Sep": "September",
}

# ============================
# Boilerplate (Sorted)
# ============================

BOILERPLATE = {
    "MEDIBANK": [
        "ABN 47 080 890 259.",
        "All rights reserved.",
        "Copyright © 2026 Medibank Private Limited.",
        "If you are a customer please call",
        "Read more",
        "These details are for journalist enquiries only.",
    ],
    "NIB": [
        "ABN 83 000 124 381",
        "All of the documents below are in PDF format",
        "Code of Conduct",
        "Copyright © 2026 nib health funds limited",
        "Privacy Policy",
        "Reconciliation Action Plan",
        "Terms & Conditions",
    ],
    "HBF": [
        "T&Cs apply",
        "T&Cs.",
        "Opens in a new window",
        "Resume quote",
        "Find the right cover in minutes",
        "Health Insurance Switch to HBF Get a recommendation New to health insurance",
    ],
    "HCF": [
        "Get a quote",
        "Compare cover",
        "Get a quick quote",
        "Chat to us",
        "Login",
    ]
}

# ============================
# News Keywords (Sorted)
# ============================

NEWS_KEYWORDS = [
        "medibank", "bupa", "nib", "hcf", "hbf",
        "private health insurance", "health fund",
        "health cover", "health insurer", "private health"
    ]

# Keywords that need whole-word matching (short words that appear as substrings)
WHOLE_WORD_KEYWORDS = {"nib", "hcf", "hbf", "bupa"}

# ============================
# Offer Keywords (Sorted)
# ============================

OFFER_KEYWORDS = [
    "%", 
    "bonus",
    "discount",
    "free",
    "gift",
    "offer ends",
    "save",
    "weeks",
]

# ============================
# Date Formats (Sorted)
# ============================

DATE_FORMATS = [
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S%z",
    "%a, %d %b %Y %H:%M:%S %Z",
    "%a, %d %b %Y %H:%M:%S %z",
]


# ============================
# Tickers (Sorted)
# ============================

TICKERS = [
    {"ticker": "MPL.AX", "source": "asx_mpl"},
    {"ticker": "NHF.AX", "source": "asx_nib"},
]
