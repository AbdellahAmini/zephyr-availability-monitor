import hashlib
import re
from datetime import datetime
from html import unescape
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup

from app.models import SnapshotRecord

MOROCCO_TZ = ZoneInfo("Africa/Casablanca")


ELEMENTOR_HIDDEN_ALL = {
    "elementor-hidden-desktop",
    "elementor-hidden-tablet",
    "elementor-hidden-mobile",
}


def raw_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()


def compact_message(text: str, limit: int = 700) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def regex_first(pattern: str, text: str, default: str | None = None) -> str | None:
    match = re.search(pattern, text or "", flags=re.I)
    if not match:
        return default
    if match.groups():
        return match.group(1).strip()
    return match.group(0).strip()


def tag_classes(tag) -> set[str]:
    try:
        classes = tag.get("class") or []
        return {str(value) for value in classes}
    except Exception:
        return set()


def has_all_elementor_hidden_classes(tag) -> bool:
    return ELEMENTOR_HIDDEN_ALL.issubset(tag_classes(tag))


def is_generally_hidden(tag) -> bool:
    try:
        if tag.has_attr("hidden"):
            return True

        aria_hidden = str(tag.get("aria-hidden", "")).lower().strip()
        if aria_hidden == "true":
            return True

        style = str(tag.get("style", "")).lower().replace(" ", "")
        if "display:none" in style or "visibility:hidden" in style:
            return True

        classes = tag_classes(tag)
        if "hidden" in classes or "d-none" in classes:
            return True

        return False
    except Exception:
        return False


def safe_decompose(tag) -> None:
    try:
        tag.decompose()
    except Exception:
        try:
            tag.extract()
        except Exception:
            pass


def build_visible_soup(html: str) -> BeautifulSoup:
    soup = BeautifulSoup(html or "", "html.parser")

    for tag in list(soup(["script", "style", "noscript", "template", "svg"])):
        safe_decompose(tag)

    # Reverse order is important: remove children before parents.
    # Elementor pages have deeply nested hidden blocks; document-order deletion can
    # corrupt later tags from the same precomputed list.
    all_tags = list(soup.find_all(True))
    for tag in reversed(all_tags):
        if has_all_elementor_hidden_classes(tag) or is_generally_hidden(tag):
            safe_decompose(tag)

    return soup


def visible_text_from_html(html: str) -> str:
    soup = build_visible_soup(html)
    text = soup.get_text(" ", strip=True)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def classify_page_state(url: str, text: str, status_code: int | None) -> str:
    lowered = (text or "").lower()
    lowered_url = (url or "").lower()

    if status_code == 429:
        return "RATE_LIMITED"

    if status_code in {401, 403}:
        return "RATE_LIMITED"

    if any(marker in lowered for marker in [
        "captcha",
        "access denied",
        "forbidden",
        "too many requests",
        "rate limit",
        "trop de requêtes",
    ]):
        return "RATE_LIMITED"

    if any(marker in lowered for marker in [
        "paiement",
        "payment",
        "carte bancaire",
        "numéro de carte",
        "finaliser la réservation",
        "confirmer la réservation",
    ]):
        return "PAYMENT_OR_FINAL_CONFIRMATION"

    if any(marker in lowered for marker in [
        "adhérent invalide",
        "adherent invalide",
        "numéro invalide",
        "numero invalide",
        "carte invalide",
    ]):
        return "ADHERENT_INVALID"

    # This now checks only visible text because hidden Elementor blocks were removed.
    if any(marker in lowered for marker in [
        "maintenance",
        "en cours de maintenance",
        "réessayer plus tard",
        "reessayer plus tard",
    ]):
        return "MAINTENANCE"

    if any(marker in lowered for marker in [
        "saturation des réservations",
        "saturation des reservations",
        "grande affluence",
    ]):
        return "SATURATION_OR_AFFLUENCE"

    queue_markers = [
        "file d'attente",
        "file d’attente",
        "connexion en cours",
        "veuillez patienter",
        "temps estimé",
        "temps estime",
        "en attente",
        "ne pas actualiser",
        "gardez cette page ouverte",
    ]

    if any(marker in lowered for marker in queue_markers):
        if "/s/n" in lowered_url or "non-adhérent" in lowered or "non-adherent" in lowered:
            return "QUEUE_NON_ADHERENT"
        return "QUEUE_ADHERENT"

    form_markers = [
        "date d'arrivée",
        "date d’arrivee",
        "date d arrivee",
        "date de départ",
        "date de depart",
        "disponibilité",
        "disponibilite",
        "rechercher",
        "réserver",
        "reserver",
        "adhérent",
        "adherent",
    ]

    if "booking.zephyr.ma" in lowered_url and any(marker in lowered for marker in form_markers):
        return "BOOKING_FORM_OPEN"

    no_availability_markers = [
        "aucune disponibilité",
        "aucune disponibilite",
        "aucun logement",
        "complet",
        "pas de disponibilité",
        "pas de disponibilite",
    ]

    if any(marker in lowered for marker in no_availability_markers):
        return "NO_AVAILABILITY"

    available_markers = [
        "mad",
        "dh",
        "chambre",
        "appartement",
        "suite",
        "sélectionner",
        "selectionner",
        "choisir",
    ]

    if any(marker in lowered for marker in available_markers) and any(marker in lowered for marker in ["prix", "tarif", "disponible"]):
        return "AVAILABLE"

    if status_code and 500 <= status_code <= 599:
        return "NETWORK_ERROR"

    return "PUBLIC_PAGE_OK"


def infer_booking_user_type(href: str, label: str) -> str:
    lowered = f"{href} {label}".lower()

    if "/s/a" in lowered or "adhérent" in lowered or "adherent" in lowered:
        return "adherent"

    if "/s/n" in lowered or "public" in lowered or "non-adhérent" in lowered or "non-adherent" in lowered:
        return "public"

    return "unknown"


def extract_booking_options(html: str, base_url: str, city_key: str, city_name: str) -> list[dict]:
    soup = build_visible_soup(html)
    options: list[dict] = []
    seen: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        href = urljoin(base_url, anchor.get("href", "").strip())
        parsed = urlparse(href)

        if parsed.netloc.lower() != "booking.zephyr.ma":
            continue

        label = anchor.get_text(" ", strip=True)
        user_type = infer_booking_user_type(href, label)

        key = f"{href}|{user_type}"
        if key in seen:
            continue
        seen.add(key)

        options.append(
            {
                "city_key": city_key,
                "city_name": city_name,
                "user_type": user_type,
                "label": label or user_type,
                "url": href,
                "status": "visible_booking_link",
            }
        )

    return options


def extract_availability_options(html: str, base_url: str, city_key: str, city_name: str, state: str) -> list[dict]:
    if state not in {"AVAILABLE", "BOOKING_FORM_OPEN"}:
        return []

    soup = build_visible_soup(html)
    text = soup.get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text)

    options: list[dict] = []

    price_patterns = [
        r"(?P<label>.{0,80}?(?:chambre|appartement|suite).{0,80}?)(?P<price>\d[\d\s.,]*\s*(?:MAD|DH|DHS|dirhams?))",
        r"(?P<price>\d[\d\s.,]*\s*(?:MAD|DH|DHS|dirhams?))(?P<label>.{0,100})",
    ]

    for pattern in price_patterns:
        for match in re.finditer(pattern, text, flags=re.I):
            label = compact_message(match.groupdict().get("label") or "Possible option", 160)
            price = compact_message(match.groupdict().get("price") or "", 80)

            if not price:
                continue

            options.append(
                {
                    "city_key": city_key,
                    "city_name": city_name,
                    "label": label,
                    "price": price,
                    "source_url": base_url,
                    "confidence": "low",
                    "note": "Extracted from visible page text. Confirm manually before booking.",
                }
            )

    return options[:20]


class ZephyrClient:
    def __init__(self, timeout_seconds: float = 30):
        self.timeout_seconds = timeout_seconds

    async def fetch_snapshot(
        self,
        *,
        scan_id: str,
        scan_started_at: datetime,
        source_url: str,
        city_key: str,
        city_name: str,
        page_type: str,
        user_type: str | None = None,
        booking_url: str | None = None,
    ) -> SnapshotRecord:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.6",
        }

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds,
                follow_redirects=True,
                headers=headers,
            ) as client:
                response = await client.get(source_url)

            body = response.text or ""
            final_url = str(response.url)

            try:
                visible_text = visible_text_from_html(body)
            except Exception as parse_exc:
                visible_text = f"Parser failed after successful HTTP fetch: {type(parse_exc).__name__}: {parse_exc}"
                return SnapshotRecord(
                    scan_id=scan_id,
                    scan_started_at=scan_started_at,
                    source_url=source_url,
                    final_url=final_url,
                    city_key=city_key,
                    city_name=city_name,
                    user_type=user_type,
                    page_type=page_type,
                    state="PARSER_ERROR",
                    http_status_if_available=response.status_code,
                    visible_message=compact_message(visible_text),
                    booking_url=booking_url or source_url,
                    raw_hash=raw_hash(body),
                    booking_options=[],
                    availability_options=[],
                )

            state = classify_page_state(final_url, visible_text, response.status_code)

            queue_position = regex_first(r"Position\s*([-–—]|\d+)", visible_text)
            queue_estimated_time = regex_first(r"Temps estim[ée]\s*([-–—:]|\d{1,2}:\d{2})", visible_text)
            interval_raw = regex_first(r"V[ée]rif\.\s*(\d+)\s*s", visible_text)
            interval = int(interval_raw) if interval_raw and interval_raw.isdigit() else None

            try:
                booking_options = extract_booking_options(
                    html=body,
                    base_url=final_url,
                    city_key=city_key,
                    city_name=city_name,
                )
            except Exception:
                booking_options = []

            try:
                availability_options = extract_availability_options(
                    html=body,
                    base_url=final_url,
                    city_key=city_key,
                    city_name=city_name,
                    state=state,
                )
            except Exception:
                availability_options = []

            return SnapshotRecord(
                scan_id=scan_id,
                scan_started_at=scan_started_at,
                source_url=source_url,
                final_url=final_url,
                city_key=city_key,
                city_name=city_name,
                user_type=user_type,
                page_type=page_type,
                state=state,
                http_status_if_available=response.status_code,
                visible_message=compact_message(visible_text),
                queue_position=queue_position,
                queue_estimated_time=queue_estimated_time,
                verification_interval_seconds=interval,
                booking_url=booking_url or source_url,
                raw_hash=raw_hash(body),
                booking_options=booking_options,
                availability_options=availability_options,
            )

        except Exception as exc:
            text = f"Request failed before parsing: {type(exc).__name__}: {exc}"
            return SnapshotRecord(
                scan_id=scan_id,
                scan_started_at=scan_started_at,
                source_url=source_url,
                final_url=source_url,
                city_key=city_key,
                city_name=city_name,
                user_type=user_type,
                page_type=page_type,
                state="NETWORK_ERROR",
                http_status_if_available=None,
                visible_message=compact_message(text),
                booking_url=booking_url or source_url,
                raw_hash=raw_hash(text),
                booking_options=[],
                availability_options=[],
            )
