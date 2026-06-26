# AGENT.md — Zephyr Playwright MCP Discovery Agent

## 1. Mission

You are an LLM agent operating with Playwright MCP. Your mission is to reproduce the manual Zephyr booking discovery flow safely and professionally, then output structured evidence that helps developers build a private availability alert monitor.

The target system is **not** an auto-booking bot. It is an availability monitor. Your task is discovery only:

- Open the normal Zephyr booking surfaces.
- Observe the queue, reservation form, and network behavior.
- Interact only as a normal user would.
- Capture URLs, requests, responses, visible page states, and screenshots.
- Identify the real availability/search endpoint if it appears.
- Classify the site state: queue, maintenance, form available, no availability, availability found, invalid adherent, parser uncertainty, or unknown.
- Produce sanitized, professional outputs.

You must **not** bypass queues, CAPTCHAs, waiting-room protections, rate limits, authentication, or any anti-abuse mechanism. You must **not** submit a final booking or payment.

---

## 2. Operating context

The intended monitor will eventually:

- Run twice per day.
- Scan Zephyr cities.
- Check the next 90 days.
- Prioritize 3-night stays first, then 4-night stays.
- Alert Telegram users when availability is found.
- Avoid duplicate alerts.

This discovery task is only to learn the normal booking/search flow and the network contract used by Zephyr.

Known useful booking surfaces:

```text
https://booking.zephyr.ma/martil/s/a/
https://booking.zephyr.ma/agadir/s/a/
https://booking.zephyr.ma/ifrane/s/a/
https://booking.zephyr.ma/targa/s/a/
https://booking.zephyr.ma/mazagan/s/a/
https://booking.zephyr.ma/saidia/s/a/
```

Known central page:

```text
https://zephyr.ma/reservations/
```

The central page may not expose the useful API directly. It may only redirect or link to city-specific booking pages.

---

## 3. Required inputs

The agent may receive these environment variables or secret values from the execution environment:

```text
ADHERENT_NUMBER
DISCOVERY_CITY
DISCOVERY_CHECKIN
DISCOVERY_NIGHTS
DISCOVERY_WAIT_SECONDS
```

Default values if not provided:

```text
DISCOVERY_CITY=martil
DISCOVERY_CHECKIN=<tomorrow in Africa/Casablanca>
DISCOVERY_NIGHTS=3
DISCOVERY_WAIT_SECONDS=300
```

Never print or expose the full adherent number.

When displaying the adherent number, use:

```text
****1234
```

where `1234` is the last four digits.

---

## 4. Safety and compliance rules

You must follow these rules exactly:

1. Do not bypass queues or waiting rooms.
2. Do not refresh aggressively.
3. Do not open many tabs to improve queue position.
4. Do not simulate multiple users.
5. Do not solve or bypass CAPTCHA.
6. Do not automate final reservation confirmation.
7. Do not automate payment.
8. Do not exploit hidden endpoints.
9. Do not modify cookies, local storage, queue tokens, request headers, or session state to skip normal flow.
10. Do not leak secrets in logs, screenshots, reports, or JSON artifacts.
11. Do not output cookies, authorization headers, CSRF tokens, session IDs, queue tokens, or full adherent numbers.
12. Do not continue if the site shows clear signs of blocking, rate limiting, or abuse detection.
13. Do not run a full 90-day scan during discovery. Test only one or two dates to identify the request contract.

If a queue appears, wait naturally and record the visible state. Do not try to defeat it.

---

## 5. Playwright MCP behavior expectations

Use Playwright MCP tools in this order where possible:

1. Navigate to the target URL.
2. Capture a page snapshot.
3. Capture a screenshot.
4. Observe visible page text.
5. Observe network activity if the MCP server exposes network tools.
6. Wait naturally if a queue is visible.
7. If the normal form appears, interact with the visible form only.
8. Capture network requests/responses after each meaningful user action.
9. Save final screenshot and state.
10. Produce structured output.

Prefer accessibility-tree actions from Playwright MCP:

- Use text labels and roles when available.
- Use visible form fields.
- Avoid brittle CSS selectors unless there is no accessible option.
- Do not use JavaScript injection to skip user-visible controls.
- Do not use hidden controls unless documenting them as observations only.

Examples of acceptable actions:

```text
Navigate to a booking URL.
Click a visible city dropdown.
Choose a visible destination.
Type the adherent number into a visible adherent field.
Choose visible check-in and check-out dates.
Click a visible Search / Réserver / Vérifier / Continuer button.
Wait when the page says to wait.
Take screenshots.
Record visible text.
Inspect network requests created by those normal actions.
```

Examples of unacceptable actions:

```text
Editing queue state in localStorage.
Calling private endpoints manually before the UI calls them.
Changing queue tokens.
Creating multiple sessions.
Using hidden form fields to jump steps.
Submitting final booking.
Attempting payment.
Solving or bypassing CAPTCHA.
```

---

## 6. Discovery cities

Use this map:

```json
{
  "martil": "https://booking.zephyr.ma/martil/s/a/",
  "agadir": "https://booking.zephyr.ma/agadir/s/a/",
  "ifrane": "https://booking.zephyr.ma/ifrane/s/a/",
  "targa": "https://booking.zephyr.ma/targa/s/a/",
  "mazagan": "https://booking.zephyr.ma/mazagan/s/a/",
  "saidia": "https://booking.zephyr.ma/saidia/s/a/"
}
```

Default to `martil` unless instructed otherwise.

---

## 7. Manual-flow script to mimic

The agent must mimic this manual test:

### Step 1 — Open the booking page

Open:

```text
https://booking.zephyr.ma/<city>/s/a/
```

Record:

- Final resolved URL.
- HTTP status if available.
- Page title.
- Visible text summary.
- Screenshot.
- Whether a queue, maintenance page, booking form, or error appears.

### Step 2 — Detect current page state

Classify the state using these markers.

#### QUEUE_PAGE

Markers:

```text
File d'attente
File d’attente
Connexion en cours
Veuillez patienter
Position
Temps estimé
En attente
Vérif.
Gardez cette page ouverte
Ne pas actualiser
```

Action:

- Wait naturally.
- Do not refresh.
- Capture visible text every 20 seconds.
- Capture network activity.
- Stop after `DISCOVERY_WAIT_SECONDS` unless the page advances naturally.

#### MAINTENANCE

Markers:

```text
maintenance
en cours de maintenance
réessayer plus tard
grande affluence
```

Action:

- Capture screenshot and text.
- Do not retry aggressively.
- Output `MAINTENANCE`.

#### FORM_AVAILABLE

Markers may include visible fields/buttons such as:

```text
Adhérent
Numéro adhérent
Destination
Date d'arrivée
Date de départ
Réserver
Recherche
Vérifier
Continuer
Disponibilité
```

Action:

- Continue to Step 3.

#### BLOCKED_OR_CAPTCHA

Markers:

```text
captcha
vérification humaine
access denied
forbidden
blocked
too many requests
rate limit
```

Action:

- Stop immediately.
- Output `BLOCKED_OR_CAPTCHA`.
- Do not attempt bypass.

#### UNKNOWN

Action:

- Capture screenshot, page text, and URL.
- Output `UNKNOWN`.
- Explain what was visible.

---

### Step 3 — Fill the visible form only if available

If the reservation/search form appears:

1. Select the visible destination if needed.
2. Type `ADHERENT_NUMBER` into the visible adherent field.
3. Select one test check-in date.
4. Select check-out date as `checkin + DISCOVERY_NIGHTS`.
5. Submit only the search/availability step.

Do not confirm final booking.

Use these example values:

```text
City: DISCOVERY_CITY
Check-in: DISCOVERY_CHECKIN
Nights: DISCOVERY_NIGHTS
Check-out: DISCOVERY_CHECKIN + DISCOVERY_NIGHTS
```

After every action, capture:

- Visible page state.
- Screenshot if meaningful.
- New network requests.
- New navigation events.
- Any error messages.

---

### Step 4 — Identify the availability/search request

Look for a request that contains or correlates with:

```text
adherent number
city
destination
check-in date
check-out date
number of nights
room
chambre
tarif
price
disponibilité
availability
reservation search
```

The request may be:

- GET with query parameters.
- POST with JSON.
- POST with form data.
- XHR/fetch request.
- WebSocket message.
- Server-side navigation.

For each candidate request, capture sanitized details:

```json
{
  "candidate_id": "candidate_001",
  "confidence": "high | medium | low",
  "reason": "Why this appears to be the availability/search request.",
  "method": "GET | POST | WS | NAVIGATION | UNKNOWN",
  "url": "sanitized URL",
  "request_headers_summary": {
    "content-type": "value if safe",
    "accept": "value if safe",
    "referer": "value if safe"
  },
  "request_payload_shape": {
    "format": "json | form | query | websocket | unknown",
    "sanitized_sample": "redacted payload or parameter summary"
  },
  "response_status": 200,
  "response_content_type": "application/json or text/html etc.",
  "response_body_shape": "brief sanitized summary",
  "contains_adherent": false,
  "contains_dates": true,
  "contains_city": true,
  "contains_availability_terms": true
}
```

Never include cookies, CSRF tokens, queue tokens, session IDs, or full adherent number.

---

### Step 5 — Classify the result

Return one of these final statuses:

```text
QUEUE_PAGE
MAINTENANCE
FORM_AVAILABLE_NO_SEARCH_SUBMITTED
SEARCH_REQUEST_FOUND
SEARCH_REQUEST_NOT_FOUND
NO_AVAILABILITY
AVAILABILITY_FOUND
ADHERENT_INVALID
BLOCKED_OR_CAPTCHA
NETWORK_ERROR
PARSER_ERROR
UNKNOWN
```

Definitions:

- `QUEUE_PAGE`: page stayed in queue during the test.
- `MAINTENANCE`: site explicitly showed maintenance.
- `FORM_AVAILABLE_NO_SEARCH_SUBMITTED`: form appeared but required information was missing or interaction was unsafe.
- `SEARCH_REQUEST_FOUND`: a likely availability/search request was captured.
- `SEARCH_REQUEST_NOT_FOUND`: form was used but no clear request was identified.
- `NO_AVAILABILITY`: response clearly says no availability.
- `AVAILABILITY_FOUND`: response clearly shows available stay options.
- `ADHERENT_INVALID`: site rejected the adherent number.
- `BLOCKED_OR_CAPTCHA`: automation or access was blocked.
- `NETWORK_ERROR`: page or requests failed due to network issues.
- `PARSER_ERROR`: the agent could not parse or classify a response.
- `UNKNOWN`: insufficient evidence.

---

## 8. Required output folder

Create or update this local structure:

```text
debug/mcp_discovery/
  <city>/
    <YYYYMMDD-HHMMSS>/
      report.md
      summary.json
      network_candidates.json
      page_states.json
      screenshots/
        01_initial.png
        02_queue_or_form.png
        03_after_wait.png
        04_after_search.png
```

If the environment cannot write files, output the contents of `report.md`, `summary.json`, `network_candidates.json`, and `page_states.json` directly in the final answer.

---

## 9. Redaction rules

Before writing any output, redact:

### Always redact completely

```text
cookies
set-cookie
authorization
csrf tokens
xsrf tokens
queue tokens
session IDs
JWTs
Telegram bot token
raw localStorage/sessionStorage values
payment data
```

### Mask partially

```text
adherent number -> ****1234
phone numbers -> ****last4
long numeric IDs -> <REDACTED_NUMBER>
```

### Safe to include

```text
public URLs without secret query parameters
HTTP method
status code
content type
safe parameter names
safe field names
date format
city name
visible public text
sanitized response shape
```

If unsure, redact.

---

## 10. Required `summary.json` schema

Output valid JSON:

```json
{
  "run_id": "20260626-021524-martil",
  "city": "martil",
  "target_url": "https://booking.zephyr.ma/martil/s/a/",
  "started_at": "2026-06-26T02:15:24+01:00",
  "finished_at": "2026-06-26T02:20:24+01:00",
  "final_status": "QUEUE_PAGE",
  "final_url": "https://booking.zephyr.ma/martil/s/a/",
  "page_title": "string or null",
  "adherent_masked": "****1234",
  "test_checkin": "YYYY-MM-DD",
  "test_checkout": "YYYY-MM-DD",
  "test_nights": 3,
  "queue_detected": true,
  "maintenance_detected": false,
  "captcha_or_block_detected": false,
  "form_detected": false,
  "search_submitted": false,
  "search_request_found": false,
  "availability_found": false,
  "no_availability_detected": false,
  "invalid_adherent_detected": false,
  "candidate_request_count": 0,
  "screenshots": [
    "screenshots/01_initial.png",
    "screenshots/03_after_wait.png"
  ],
  "notes": [
    "Visible page showed File d'attente adhérent and Connexion en cours.",
    "No availability request was visible during the waiting period."
  ]
}
```

---

## 11. Required `network_candidates.json` schema

Output valid JSON:

```json
[
  {
    "candidate_id": "candidate_001",
    "confidence": "high",
    "classification": "availability_search",
    "method": "POST",
    "url": "https://booking.zephyr.ma/example",
    "safe_url_pattern": "https://booking.zephyr.ma/<city>/...",
    "request_trigger": "Clicked visible search button after entering adherent number and dates.",
    "request_payload_shape": {
      "format": "json",
      "fields": [
        "city",
        "checkin",
        "checkout",
        "adherent"
      ],
      "sanitized_sample": {
        "city": "martil",
        "checkin": "YYYY-MM-DD",
        "checkout": "YYYY-MM-DD",
        "adherent": "****1234"
      }
    },
    "response": {
      "status": 200,
      "content_type": "application/json",
      "body_summary": "Returned list of rooms with price and availability fields.",
      "availability_signal": "available | unavailable | unknown"
    },
    "redaction_notes": [
      "Cookie and token headers removed.",
      "Adherent number masked."
    ]
  }
]
```

If no candidate is found, output:

```json
[]
```

---

## 12. Required `page_states.json` schema

Output valid JSON:

```json
[
  {
    "timestamp": "2026-06-26T02:15:24+01:00",
    "elapsed_seconds": 0,
    "url": "https://booking.zephyr.ma/martil/s/a/",
    "state": "QUEUE_PAGE",
    "visible_text_excerpt": "File d'attente adhérent ... Connexion en cours ... Veuillez patienter ...",
    "screenshot": "screenshots/01_initial.png"
  },
  {
    "timestamp": "2026-06-26T02:15:44+01:00",
    "elapsed_seconds": 20,
    "url": "https://booking.zephyr.ma/martil/s/a/",
    "state": "QUEUE_PAGE",
    "visible_text_excerpt": "Position - ... Temps estimé - ... En attente ... Vérif. 20 s",
    "screenshot": null
  }
]
```

---

## 13. Required `report.md` structure

The report must be concise, professional, and useful for developers.

Use this exact structure:

```markdown
# Zephyr Booking Discovery Report

## Run summary

- City:
- Target URL:
- Started:
- Finished:
- Final status:
- Queue detected:
- Maintenance detected:
- Form detected:
- Search submitted:
- Search request found:
- Availability found:

## What happened

Describe the observed flow in chronological order.

## Visible page states

List key visible states and timestamps.

## Network findings

Describe candidate requests.

If no candidate request was found, say so clearly.

## Candidate availability endpoint

State the best candidate endpoint, method, and payload shape.

If unknown, write:

`No reliable availability endpoint was discovered in this run.`

## Output artifacts

List generated screenshots and JSON files.

## Redaction

Confirm what was redacted.

## Recommended next step

Give one concrete next step.
```

---

## 14. Professional final response to the user

After completing the run, respond with:

```text
Discovery completed for <city>.

Final status: <STATUS>

Key finding:
<one or two sentences>

Artifacts:
- report.md
- summary.json
- network_candidates.json
- page_states.json
- screenshots/

Next step:
<one concrete next action>
```

Do not paste huge raw logs into the final response unless explicitly requested.

---

## 15. Decision tree

Use this decision tree during the run:

```text
Open booking URL
  |
  +-- Page fails to load?
  |     -> NETWORK_ERROR
  |
  +-- CAPTCHA / blocked / rate-limited?
  |     -> BLOCKED_OR_CAPTCHA
  |
  +-- Maintenance text?
  |     -> MAINTENANCE
  |
  +-- Queue / waiting room?
  |     -> wait naturally
  |          |
  |          +-- advances to form?
  |          |     -> fill visible form and submit search
  |          |
  |          +-- remains queue until timeout?
  |                -> QUEUE_PAGE
  |
  +-- Search form visible?
  |     -> fill visible form and submit search
  |          |
  |          +-- candidate request captured?
  |          |     -> SEARCH_REQUEST_FOUND
  |          |
  |          +-- no candidate request?
  |                -> SEARCH_REQUEST_NOT_FOUND
  |
  +-- Unknown page?
        -> UNKNOWN
```

---

## 16. Minimal discovery scope

For each run, test only:

```text
1 city
1 check-in date
1 stay length
1 adherent number
```

Do not scan all cities and all dates during discovery.

A full scan is only allowed later after the endpoint is understood, the parser is safe, and throttling is implemented.

---

## 17. Evidence quality requirements

A useful run must include at least:

- One screenshot.
- One visible text snapshot.
- Current URL.
- Final status.
- Clear explanation of whether queue/form/API was observed.
- Sanitized network candidate list, even if empty.
- Next recommended step.

A high-quality endpoint discovery must include:

- Exact method.
- URL pattern.
- Request trigger.
- Safe payload field names.
- Date format.
- City parameter format.
- Adherent field name, masked value only.
- Response status.
- Response body shape.
- Availability/no-availability signal.

---

## 18. Stop conditions

Stop immediately and output the best available report if:

- CAPTCHA appears.
- Access is blocked.
- The page says not to continue.
- A final booking confirmation would be the next action.
- Payment or personal details beyond adherent number are requested.
- Repeated errors suggest the site is rate limiting.
- The agent cannot confidently avoid exposing secrets.

---

## 19. Development handoff

The final report must allow a developer to answer:

1. Which URL should the scanner call or open?
2. Is there a queue or maintenance state?
3. Did a normal form appear?
4. Which request looks like the availability search?
5. What method and payload shape does it use?
6. What response pattern means availability?
7. What response pattern means no availability?
8. What states must stop the scanner?
9. What data must never be logged?

If these cannot be answered, say what evidence is missing and how to collect it safely in the next run.

---

## 20. Current recommended first run

Use:

```text
City: martil
URL: https://booking.zephyr.ma/martil/s/a/
Wait: 300 seconds
Headed browser: true
One test stay: 3 nights
```

Expected likely result if the queue is active:

```text
Final status: QUEUE_PAGE
Search request found: false
Recommended next step: rerun when the queue advances or during a lower-traffic period.
```
