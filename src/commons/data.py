AMA_SOURCE_URL = "https://www.ama.com.au/articles/ama-private-health-insurance-report-card-2025"
ARTICLES_SEARCH_URL = "https://www.choice.com.au/?s=Medibank&tab=articles"
AWARDS_URL = "https://www.canstar.com.au/star-ratings-awards/"
ASX_MEDIBANK_RELEASES_URL = "https://www.medibank.com.au/livebetter/newsroom/classification/asx-releases"
ASX_NIB_ANNOUNCEMENTS_URL = 'https://www.nib.com.au/shareholders/announcements'
MEDIBANK_SPECIFIC_MEDIA_RELEASES_URL = 'https://www.medibank.com.au/livebetter/newsroom/classification/media-releases'
YFINANCE_URL = "https://au.finance.yahoo.com/quote/ASX.AX/"

MEDIBANK_NEWSROOM_TAG = "/livebetter/newsroom/post/"
MEDIBANK_BASE_URL = "https://www.medibank.com.au"
INSURANCE_PROVIDERS = "medibank"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

INSURANCE_AWARD_URLS = [
    # General insurance awards
    "https://www.canstar.com.au/star-ratings-awards/insurer-of-the-year-award/",
    "https://www.canstar.com.au/travel-insurance/star-ratings-awards/",
    "https://www.canstar.com.au/pet-insurance/star-ratings-awards/",
    # Personal insurance awards
    "https://www.canstar.com.au/star-ratings-awards/health-insurance/",
    "https://www.canstar.com.au/star-ratings-awards/overseas-student-working-visa-health/",
    "https://www.canstar.com.au/star-ratings-awards/direct-life-insurance/",
    "https://www.canstar.com.au/star-ratings-awards/direct-income-protection/",
    # Customer satisfaction awards
    "https://www.canstar.com.au/star-ratings-awards/most-satisfied-customers-health-insurer-award/",
    "https://www.canstar.com.au/star-ratings-awards/most-satisfied-customers-travel-insurance-award/",
    "https://www.canstar.com.au/star-ratings-awards/most-satisfied-customers-pet-insurance-awards/"
]

NIB_ASX_SKIP_TITLES = [
    "View our Reconciliation Action Plan",
    "Terms & Conditions",
    "Privacy Policy",
    "Code of Conduct",
]

MONTH_MAP = {
    "Jan":"January",
    "Feb":"February",
    "Mar":"March",
    "Apr":"April",
    "May":"May",
    "Jun":"June",
    "Jul":"July",
    "Aug":"August",
    "Sep":"September",
    "Oct":"October",
    "Nov":"November",
    "Dec":"December"
}

BOILERPLATE = {
    "MEDIBANK" : [
        
        "These details are for journalist enquiries only.",
        "If you are a customer please call",
        "Copyright © 2026 Medibank Private Limited.",
        "All rights reserved.",
        "ABN 47 080 890 259.",
        "Read more"
    ],
    "NIB" : [
        "Copyright © 2026 nib health funds limited",
        "ABN 83 000 124 381",
        "Terms & Conditions",
        "Privacy Policy",
        "Code of Conduct",
        "All of the documents below are in PDF format",
        "Reconciliation Action Plan"
    ]
}

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

# Keywords for filtering articles
NEWS_KEYWORDS = {
    "phi": [
        "medibank", "bupa", "nib", "hcf", "hbf",
        "private health insurance", "health fund", 
        "health cover", "health insurer"
    ],
    "health_tech": [
        "health technology", "digital health", "health ai",
        "medical ai", "health innovation", "medtech",
        "telehealth", "health data", "wearable health",
        "health automation", "clinical ai", "precision medicine"
    ]
}

DATE_FORMATS = [
    "%a, %d %b %Y %H:%M:%S %Z",
    "%a, %d %b %Y %H:%M:%S %z",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%SZ",
]

TICKERS = [
    {'ticker': 'MPL.AX', 'source': 'asx_mpl'},
    {'ticker': 'NHF.AX', 'source': 'asx_nib'}
]
