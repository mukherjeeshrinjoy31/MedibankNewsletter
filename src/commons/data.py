# ============================
# Global Constants (Sorted)
# ============================

ABC_NEWS_URL                            = "https://www.abc.net.au/"
AMA_SOURCE_URL                          = "https://www.ama.com.au/"
AMA_REPORT_URL                          = "https://www.ama.com.au/advocacy-policy?f%5B0%5D=type%3A51" # AMA report card page
ARTICLES_SEARCH_URL                     = "https://www.choice.com.au/?s=Medibank&tab=articles"
ASX_MEDIBANK_RELEASES_URL               = "https://www.medibank.com.au/livebetter/newsroom/classification/asx-releases"
ASX_NIB_ANNOUNCEMENTS_URL               = "https://www.nib.com.au/shareholders/announcements"
GUARDIAN_NEWS_URL                       = "https://www.theguardian.com/au"
HBF_URL                                 = "https://www.hbf.com.au"
HCF_URL                                 = 'https://www.hcf.com.au'
MEDIBANK_BASE_URL                       = "https://www.medibank.com.au"
MEDIBANK_SPECIFIC_MEDIA_RELEASES_URL    = "https://www.medibank.com.au/livebetter/newsroom/classification/media-releases"
OZBARGAIN_URL                           = "https://www.ozbargain.com.au"
RSS_FEED_URL                            = "https://www.ozbargain.com.au/deals/medibank.com.au/feed"
YFINANCE_URL                            = "https://au.finance.yahoo.com/quote/ASX.AX/"
SBS_NEWS_URL                            = "https://www.sbs.com.au/news"

NEWS_URLS = {
    "ABC" : [
        "https://www.abc.net.au/news/health",
        "https://www.abc.net.au/news/",
        "https://www.abc.net.au/news/australia/",
        "https://www.abc.net.au/news/search/?query=health+australia",
        "https://www.abc.net.au/news/search/?query=private+health+insurance"
    ],
    "SBS" : [
        "https://www.sbs.com.au/news/collection/health-and-wellbeing",
        "https://www.sbs.com.au/news/tag/subject/health",
        "https://www.sbs.com.au/news/collection/just-in-articles",
        "https://www.sbs.com.au/news/tag/section/life",
        "https://www.sbs.com.au/search?query=private+health+insurance&sort=date&filter=news"
    ],
    "GUARDIAN" : [
        "https://www.theguardian.com/australia-news/health",
        "https://www.theguardian.com/australia-news",
        "https://www.theguardian.com/au/lifeandstyle",
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
# News Sources (Sorted)
# ============================

NEWS_SOURCES = {
    "abc": {
        "url": "https://www.abc.net.au/",
        "feeds": [
            "https://www.abc.net.au/news/feed/5470430/rss.xml", # abc top stories
            "https://www.abc.net.au/news/feed/45910/rss.xml", # abc top stories
            "https://www.abc.net.au/news/feed/7112600/rss.xml", # abc health
            "https://www.abc.net.au/news/feed/9167776/rss.xml" # abc health
        ],
    },
    "sbs": {
        "url": "https://www.sbs.com.au/news",
        "feeds": [
            "https://www.sbs.com.au/news/feed", # sbs top stories,
            "https://www.sbs.com.au/feed/news/podcast-rss/headlines-on-health" # sbs health podcast
        ],
    },
    "theguardian": {
        "url": "https://www.theguardian.com/au",
        "feeds": [
            "https://www.theguardian.com/au/rss" # the guardian top stories
        ],
    }
}

# ============================
# News Keywords (Sorted)
# ============================

NEWS_KEYWORDS = {
    "phi": [
        "medibank", "bupa", "nib", "hcf", "hbf",
        "private health insurance", "health fund",
        "health cover", "health insurer", "private health"
    ],
    "health_tech": [
        "health technology", "digital health", "health ai",
        "medical ai", "health innovation", "medtech",
        "telehealth", "health data", "wearable health",
        "health automation", "clinical ai", "precision medicine",
    ],
}

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
