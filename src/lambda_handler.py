import json
import logging
import os
from datetime import date

import boto3

session = boto3.Session()

# ---------------------------------------------------------------------------
# Configuration — read from environment variables
# ---------------------------------------------------------------------------

KNOWLEDGE_BASE_ID = os.environ.get("KNOWLEDGE_BASE_ID", "FPTYDJRUZK")
REGION            = os.environ.get("REGION", "us-east-1")
EMAIL_SENDER      = os.environ.get("EMAIL_SENDER", "S4062761@student.rmit.edu.au")
EMAIL_RECIPIENTS  = os.environ.get("EMAIL_RECIPIENTS", "").split(",")

MODEL_ID = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"

MACRO_QUERY = (
    "What are the latest Australian macroeconomic conditions including "
    "inflation, consumer price index, employment, unemployment rate, "
    "and labour force trends relevant to the private health insurance sector?"
)

PHI_QUERY = (
    "What are the latest private health insurance industry developments including "
    "APRA statistics, competitor activity, premium approvals, regulatory changes, "
    "ombudsman reports, and PHI membership or claims trends in Australia?"
)

MEDIBANK_QUERY = (
    "What are the latest Medibank Private announcements including ASX releases, "
    "media releases, financial results, product launches, partnerships, "
    "leadership changes, and company news?"
)

SENTIMENT_QUERY = (
    "What is the latest public sentiment around private health insurance "
    "in Australia including consumer complaints, social media discussions, "
    "news coverage, ratings, and public opinion trends relevant to Medibank?"
)

OFFERS_QUERY = (
    "What are the current private health insurance promotional offers "
    "in Australia including free weeks, waived waiting periods, gift cards, "
    "cashback deals, and loyalty rewards from insurers like Medibank, ahm, "
    "Bupa, nib, HCF, and HBF?"
)

NUM_RESULTS = 10

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Step 1: Retrieve context from Knowledge Base
# ---------------------------------------------------------------------------

def retrieve_context(query: str, kb_id: str, num_results: int) -> str:
    client = session.client("bedrock-agent-runtime", region_name=REGION)

    log.info("Querying Knowledge Base %s — '%s'", kb_id, query[:60])

    response = client.retrieve(
        knowledgeBaseId=kb_id,
        retrievalQuery={"text": query},
        retrievalConfiguration={
            "vectorSearchConfiguration": {"numberOfResults": num_results}
        },
    )

    results = response.get("retrievalResults", [])
    log.info("Retrieved %d chunks from Knowledge Base", len(results))

    if not results:
        log.warning("No results for query: %s", query[:60])
        return "[No data available for this tier this week]"

    context_parts = []
    for i, r in enumerate(results, start=1):
        text = r.get("content", {}).get("text", "").strip()
        if text:
            context_parts.append(f"[Source {i}]\n{text}")

    return "\n\n".join(context_parts)


# ---------------------------------------------------------------------------
# Step 2: Generate briefing via Claude Sonnet
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a market intelligence analyst producing a weekly briefing \
for Medibank Private's strategy team. Format this like an executive dashboard \
— scannable in under 2 minutes. Every word must earn its place.

Writing principles:
- Dashboard first: use markdown tables for data-driven sections. \
  No sentences where a table row will do.
- Signal over narrative: lead with numbers and facts. Context only \
  where absolutely necessary.
- Balanced tone: factual, never alarmist. Avoid "erode", "deteriorate", \
  "threaten", "crisis", "alarming", "failing".
- Source-attributed: every data point needs a source and date.

Tone: a trusted colleague who respects the reader's time. \
Never refer to yourself or the data retrieval process."""


def build_user_prompt(context: str, report_date: str) -> str:
    return f"""Using the market intelligence data below, produce this week's \
Medibank Market Intelligence Briefing.

CRITICAL FORMATTING RULES:
- Sections 1, 2, and 3 MUST use markdown tables. No prose in these sections.
- Sections 4, 5, and 6 use concise bullet points or short prose.
- Use the direction arrows: Improving = ↑, Stable = →, Softening = ↓

Structure your response exactly as follows:

---

## MEDIBANK MARKET INTELLIGENCE BRIEFING
### Week of {report_date}

---

### THIS WEEK AT A GLANCE
2 sentences maximum. The single most important signal this week, plus one supporting observation.

---

### 1. MACROECONOMIC SNAPSHOT

| Indicator | Value | Direction | Source |
|-----------|-------|-----------|--------|
| Annual CPI | X.X% | ↑/→/↓ | ABS, [date] |
| Trimmed mean inflation | X.X% | ↑/→/↓ | ABS, [date] |
| [etc.] | | | |

**Keep an eye on:** [one line only]

### 2. PHI INDUSTRY SIGNALS

| Signal | Key Fact | Direction | Source |
|--------|----------|-----------|--------|
| Coverage rate | XX.X% hold hospital cover | ↑/→/↓ | APRA, [date] |
| Premium increases | [fact] | ↑/→/↓ | [source], [date] |
| [etc.] | | | |

**Keep an eye on:** [one line only]

### 3. MEDIBANK IN THE NEWS

| Announcement | Detail | Source |
|-------------|--------|--------|
| H1 FY26 results | [key numbers] | Medibank ASX, [date] |
| Premium increase | [detail] | Medibank ASX, [date] |
| [etc.] | | |

**Keep an eye on:** [one line only]

### 4. PUBLIC SENTIMENT
3-5 items most relevant to Medibank. One line each:
- **[Topic]:** [what is being said] | [↑/→/↓] | (Source: [name], [date])

**Keep an eye on:** [one line only]

### 5. COMPETITIVE OFFERS SNAPSHOT

| Insurer | Offer | Expiry |
|---------|-------|--------|
| ahm | [offer details] | [date] |
| Bupa | [offer details] | [date] |
| HBF | [offer details] | [date] |
| Medibank | [offer details] | [date] |
| nib | [offer details] | - |
| HCF | [offer details] | ongoing |

(Source: Finder, [date])

**Keep an eye on:** [one line on expiring offers]

### 6. ON OUR RADAR
2-3 items only. For each:
- **[Topic]:** [what to watch + why it matters, two sentences max]

---

Important instructions:
- Base every claim strictly on the retrieved data. Do not invent statistics.
- If data is insufficient for a section or sub-topic, omit it entirely.
- Every data point must include a source and date.
- Keep the total briefing under 900 words.
- Use plain Australian English.
- Do NOT use "Implication for Medibank" anywhere.
- Do NOT use "Key Risks" anywhere.
- Do NOT use alarmist language.
- Sections 1, 2, 3, and 5 MUST be markdown tables. This is non-negotiable.

RETRIEVED MARKET INTELLIGENCE DATA:
{context}"""


def generate_briefing(context: str, report_date: str) -> str:
    client = session.client("bedrock-runtime", region_name=REGION)
    user_prompt = build_user_prompt(context, report_date)

    log.info("Sending context (%d chars) to %s", len(context), MODEL_ID)

    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 4096,
        "system": SYSTEM_PROMPT,
        "messages": [
            {"role": "user", "content": user_prompt}
        ],
    })

    response = client.invoke_model(
        modelId=MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=body,
    )

    result = json.loads(response["body"].read())
    email_text = result["content"][0]["text"]

    log.info(
        "Briefing generated — %d chars, %d input tokens, %d output tokens",
        len(email_text),
        result["usage"]["input_tokens"],
        result["usage"]["output_tokens"],
    )

    return email_text


# ---------------------------------------------------------------------------
# Step 3: Convert briefing to HTML (with table support)
# ---------------------------------------------------------------------------

def briefing_to_html(briefing: str, report_date: str) -> str:
    lines = briefing.splitlines()
    html_parts = []
    in_list = False
    in_table = False
    table_header_done = False

    def close_list():
        nonlocal in_list
        if in_list:
            html_parts.append("</ul>")
            in_list = False

    def close_table():
        nonlocal in_table, table_header_done
        if in_table:
            html_parts.append("</tbody></table></div>")
            in_table = False
            table_header_done = False

    def render_inline(text: str) -> str:
        import re
        text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
        text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
        return text

    def is_table_row(line: str) -> bool:
        return line.strip().startswith("|") and line.strip().endswith("|")

    def is_separator_row(line: str) -> bool:
        stripped = line.strip()
        return stripped.startswith("|") and all(
            c in "|- :" for c in stripped
        )

    def parse_table_cells(line: str) -> list:
        cells = line.strip().strip("|").split("|")
        return [render_inline(c.strip()) for c in cells]

    for line in lines:
        stripped = line.strip()

        if stripped.lower().startswith("subject:"):
            continue

        if is_table_row(stripped):
            close_list()
            if is_separator_row(stripped):
                continue
            cells = parse_table_cells(stripped)
            if not in_table:
                in_table = True
                table_header_done = True
                html_parts.append(
                    '<div style="overflow-x:auto; margin:12px 0;">'
                    '<table style="width:100%; border-collapse:collapse; '
                    'font-size:13px; line-height:1.6;">'
                )
                html_parts.append("<thead><tr>")
                for cell in cells:
                    html_parts.append(
                        f'<th style="text-align:left; padding:8px 12px; '
                        f'background:#003087; color:#ffffff; '
                        f'border:1px solid #dde3ed; font-weight:600;">{cell}</th>'
                    )
                html_parts.append("</tr></thead><tbody>")
            else:
                html_parts.append("<tr>")
                for cell in cells:
                    html_parts.append(
                        f'<td style="padding:8px 12px; border:1px solid #dde3ed; '
                        f'vertical-align:top;">{cell}</td>'
                    )
                html_parts.append("</tr>")
            continue

        close_table()

        if stripped.startswith("## ") and not stripped.startswith("### "):
            close_list()
            heading = render_inline(stripped[3:].strip())
            html_parts.append(
                f'<h2 style="color:#003087; border-bottom:2px solid #003087; '
                f'padding-bottom:6px; margin-top:32px;">{heading}</h2>'
            )
        elif stripped.startswith("### "):
            close_list()
            heading = render_inline(stripped[4:].strip())
            html_parts.append(
                f'<h3 style="color:#003087; margin-top:24px; margin-bottom:4px;">{heading}</h3>'
            )
        elif stripped.startswith("- "):
            if not in_list:
                html_parts.append('<ul style="line-height:1.8; padding-left:20px;">')
                in_list = True
            item = render_inline(stripped[2:].strip())
            html_parts.append(f"<li>{item}</li>")
        elif stripped == "":
            close_list()
            html_parts.append("<br>")
        elif stripped == "---":
            close_list()
            html_parts.append('<hr style="border:none; border-top:1px solid #dde3ed; margin:20px 0;">')
        else:
            close_list()
            html_parts.append(f'<p style="line-height:1.8; margin:8px 0;">{render_inline(stripped)}</p>')

    close_list()
    close_table()

    body = "\n".join(html_parts)

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"></head>
<body style="font-family: Arial, sans-serif; font-size:14px; color:#222;
             max-width:720px; margin:auto; padding:32px;">

  <div style="background:#003087; padding:20px 28px; border-radius:6px 6px 0 0;">
    <h1 style="color:#ffffff; margin:0; font-size:20px;">
      Medibank Market Intelligence Briefing
    </h1>
    <p style="color:#cce0ff; margin:6px 0 0; font-size:13px;">{report_date}</p>
  </div>

  <div style="border:1px solid #dde3ed; border-top:none; padding:24px 28px;
              border-radius:0 0 6px 6px;">
    {body}
  </div>

  <p style="font-size:11px; color:#999; margin-top:20px; text-align:center;">
    Generated by Medibank Intelligence Pipeline &mdash; P000268DS &mdash; RMIT University
  </p>

</body>
</html>"""


# ---------------------------------------------------------------------------
# Step 4: Send via SES
# ---------------------------------------------------------------------------

def send_email(subject: str, html_body: str) -> str:
    ses = session.client("ses", region_name=REGION)

    log.info("Sending email via SES — from %s to %s", EMAIL_SENDER, EMAIL_RECIPIENTS)

    response = ses.send_email(
        Source=EMAIL_SENDER,
        Destination={"ToAddresses": EMAIL_RECIPIENTS},
        Message={
            "Subject": {"Data": subject, "Charset": "UTF-8"},
            "Body": {"Html": {"Data": html_body, "Charset": "UTF-8"}},
        },
    )

    message_id = response["MessageId"]
    log.info("Email sent — SES MessageId: %s", message_id)
    return message_id


# ---------------------------------------------------------------------------
# Core pipeline logic
# ---------------------------------------------------------------------------

def run() -> str:
    report_date = date.today().strftime("%-d %B %Y")

    macro_context     = retrieve_context(MACRO_QUERY,     KNOWLEDGE_BASE_ID, NUM_RESULTS)
    phi_context       = retrieve_context(PHI_QUERY,       KNOWLEDGE_BASE_ID, NUM_RESULTS)
    medibank_context  = retrieve_context(MEDIBANK_QUERY,  KNOWLEDGE_BASE_ID, NUM_RESULTS)
    sentiment_context = retrieve_context(SENTIMENT_QUERY, KNOWLEDGE_BASE_ID, NUM_RESULTS)
    offers_context    = retrieve_context(OFFERS_QUERY,    KNOWLEDGE_BASE_ID, NUM_RESULTS)

    context = (
        "=== MACROECONOMIC DATA ===\n\n"         + macro_context +
        "\n\n=== PHI INDUSTRY DATA ===\n\n"      + phi_context +
        "\n\n=== MEDIBANK-SPECIFIC NEWS ===\n\n" + medibank_context +
        "\n\n=== PUBLIC SENTIMENT DATA ===\n\n"  + sentiment_context +
        "\n\n=== COMPETITIVE OFFERS DATA ===\n\n" + offers_context
    )

    briefing  = generate_briefing(context, report_date)
    html_body = briefing_to_html(briefing, report_date)
    subject   = f"Medibank Weekly Market Intelligence Briefing — {report_date}"
    send_email(subject, html_body)

    return briefing


# ---------------------------------------------------------------------------
# Lambda entry point
# ---------------------------------------------------------------------------

def lambda_handler(event, context):
    log.info("Lambda invoked — starting weekly briefing pipeline")

    try:
        briefing = run()
        log.info("Pipeline completed successfully")
        return {
            "statusCode": 200,
            "body": json.dumps({
                "status": "success",
                "message": "Weekly briefing generated and sent",
                "preview": briefing[:200]
            })
        }

    except Exception as e:
        log.error("Pipeline failed: %s", str(e), exc_info=True)
        return {
            "statusCode": 500,
            "body": json.dumps({
                "status": "error",
                "message": str(e)
            })
        }