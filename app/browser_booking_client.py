import json
import re
import os
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.async_api import Page, async_playwright

from app.config import City
from app.models import SnapshotRecord

MOROCCO_TZ = ZoneInfo("Africa/Casablanca")


def compact(text: str, limit: int = 900) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def normalize_adherent_code(adherent_number: str) -> str:
    digits = re.sub(r"\D+", "", adherent_number or "")
    return digits[:10]


def has_queue_text(text: str) -> bool:
    lowered = (text or "").lower()
    return any(
        marker in lowered
        for marker in [
            "file d'attente",
            "file d’attente",
            "connexion en cours",
            "veuillez patienter",
            "en attente",
            "ne pas actualiser",
            "gardez cette page ouverte",
            "temps estimé",
            "temps estime",
            "vérif.",
            "verif.",
        ]
    )


def has_no_availability_text(text: str) -> bool:
    lowered = (text or "").lower()

    return any(
        marker in lowered
        for marker in [
            "aucune disponibilité",
            "aucune disponibilite",
            "pas de disponibilité",
            "pas de disponibilite",
            "pas de résultat trouvé",
            "pas de resultat trouvé",
            "pas de resultat trouve",
            "nous n'avons pas de disponibilités",
            "nous n'avons pas de disponibilites",
            "nous n’avons pas de disponibilités",
            "nous n’avons pas de disponibilites",
            "disponiblilités",
            "disponiblilites",
            "les dates que vous avez sélectionnées",
            "les dates que vous avez selectionnees",
            "veuillez réessayer pour d'autres dates",
            "veuillez reessayer pour d'autres dates",
            "veuillez réessayer pour d’autres dates",
            "veuillez reessayer pour d’autres dates",
            "réessayer pour d'autres dates",
            "reessayer pour d'autres dates",
            "aucun logement",
            "aucune chambre",
            "aucun hébergement",
            "aucun hebergement",
            "aucune offre",
            "aucun résultat",
            "aucun resultat",
            "complet",
            "indisponible",
        ]
    )

async def visible_text(page: Page) -> str:
    try:
        return await page.locator("body").inner_text(timeout=10_000)
    except Exception:
        return ""


async def dom_diagnostics(page: Page) -> dict:
    return await page.evaluate(
        """
        () => {
            function findDateEl() {
                return document.getElementById('form.date')
                    || Array.from(document.querySelectorAll('input')).find((el) => el.getAttribute('wire:model') === 'data.date')
                    || document.querySelector('input.flatpickr-input');
            }

            function findCodeEl() {
                return document.getElementById('form.code')
                    || Array.from(document.querySelectorAll('input')).find((el) => el.getAttribute('wire:model') === 'data.code')
                    || Array.from(document.querySelectorAll('input')).find((el) => (el.getAttribute('placeholder') || '').toLowerCase().includes('code'));
            }

            const dateEl = findDateEl();
            const codeEl = findCodeEl();

            const allInputs = Array.from(document.querySelectorAll('input')).map((el) => ({
                id: el.id || null,
                type: el.type || null,
                name: el.name || null,
                placeholder: el.getAttribute('placeholder'),
                wireModel: el.getAttribute('wire:model'),
                value: el.value,
                readonly: el.hasAttribute('readonly'),
                visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length),
            }));

            return {
                hasDate: !!dateEl,
                hasCode: !!codeEl,
                date: dateEl ? {
                    id: dateEl.id || null,
                    wireModel: dateEl.getAttribute('wire:model'),
                    value: dateEl.value,
                    readonly: dateEl.hasAttribute('readonly'),
                    visible: !!(dateEl.offsetWidth || dateEl.offsetHeight || dateEl.getClientRects().length),
                    hasFlatpickr: !!dateEl._flatpickr,
                } : null,
                code: codeEl ? {
                    id: codeEl.id || null,
                    wireModel: codeEl.getAttribute('wire:model'),
                    placeholder: codeEl.getAttribute('placeholder'),
                    value: codeEl.value,
                    visible: !!(codeEl.offsetWidth || codeEl.offsetHeight || codeEl.getClientRects().length),
                } : null,
                inputs: allInputs,
                submitButtons: Array.from(document.querySelectorAll('button[type="submit"]')).map((el) => ({
                    text: el.innerText,
                    visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length),
                })),
            };
        }
        """
    )


async def exact_booking_form_is_visible(page: Page) -> bool:
    try:
        diag = await dom_diagnostics(page)
        return bool(diag.get("hasDate") and diag.get("hasCode"))
    except Exception:
        return False


async def detect_page_state(
    page: Page,
    *,
    options_found: bool = False,
    after_search: bool = False,
) -> str:
    text = await visible_text(page)
    lowered = text.lower()
    url = page.url.lower()

    if any(x in lowered for x in ["captcha", "access denied", "forbidden", "too many requests", "rate limit"]):
        return "RATE_LIMITED"

    if any(x in lowered for x in ["paiement", "payment", "carte bancaire", "finaliser la réservation", "confirmer la réservation"]):
        return "PAYMENT_OR_FINAL_CONFIRMATION"

    if any(x in lowered for x in ["code adhérent incorrect", "merci de saisir un code adhérent correct"]):
        return "ADHERENT_INVALID"

    if any(x in lowered for x in ["erreur de date", "merci de verifier la date", "merci de vérifier la date"]):
        return "DATE_ERROR"

    if any(x in lowered for x in ["limite dépassée", "durée de séjour autorisée", "durée de sejour autorisee"]):
        return "LIMIT_ERROR"

    # After a search, result messages must win over queue/loading words.
    if has_no_availability_text(text):
        return "NO_AVAILABILITY"

    if options_found:
        return "AVAILABLE"

    # Only treat queue text as queue before a search is submitted.
    # Search result pages may contain "Veuillez patienter" or "Recherche en cours",
    # which is not the same as the initial queue page.
    if not after_search and has_queue_text(text):
        return "QUEUE_NON_ADHERENT" if "/s/n" in url else "QUEUE_ADHERENT"

    if after_search and has_search_loading_text(text):
        return "SEARCH_IN_PROGRESS"

    if after_search:
        return "SEARCH_SUBMITTED_NO_OPTIONS"

    if await exact_booking_form_is_visible(page):
        return "BOOKING_FORM_OPEN"

    return "UNKNOWN"

async def wait_until_queue_or_form(page: Page, wait_seconds: int) -> str:
    state = await detect_page_state(page)

    waited = 0
    while state == "QUEUE_ADHERENT" and waited < wait_seconds:
        await page.wait_for_timeout(5_000)
        waited += 5
        state = await detect_page_state(page)

    return state

def has_search_loading_text(text: str) -> bool:
    lowered = (text or "").lower()
    return any(
        marker in lowered
        for marker in [
            "vérification",
            "verification",
            "chargement",
            "loading",
            "veuillez patienter",
        ]
    )


def has_available_text(text: str) -> bool:
    lowered = (text or "").lower()

    lodging_marker = any(
        marker in lowered
        for marker in [
            "appartement",
            "chambre",
            "suite",
            "studio",
            "bungalow",
        ]
    )

    price_marker = any(
        marker in lowered
        for marker in [
            "mad",
            "dh",
            "dhs",
            "dirham",
            "tarif",
            "prix",
        ]
    )

    action_marker = any(
        marker in lowered
        for marker in [
            "sélectionner",
            "selectionner",
            "choisir",
            "réserver",
            "reserver",
            "continuer",
        ]
    )

    return lodging_marker and (price_marker or action_marker)


async def wait_for_search_result(page: Page, max_seconds: int = 90) -> dict:
    result = {
        "finished": False,
        "seconds_waited": 0,
        "reason": None,
        "last_button_text": None,
        "last_text_sample": None,
        "cards_seen": 0,
        "reserve_buttons_seen": 0,
        "no_availability_seen": False,
        "loading_seen": False,
    }

    def strip_accents(value: str) -> str:
        import unicodedata
        return "".join(
            ch
            for ch in unicodedata.normalize("NFKD", value)
            if not unicodedata.combining(ch)
        )

    for second in range(max_seconds):
        text = await visible_text(page)
        lowered = text.lower()
        normalized = strip_accents(lowered)

        result["seconds_waited"] = second + 1
        result["last_text_sample"] = compact(text, 700)

        loading_now = (
            has_search_loading_text(text)
            or "recherche en cours" in normalized
            or "veuillez patienter" in normalized
        )
        no_availability_now = has_no_availability_text(text)

        result["loading_seen"] = result["loading_seen"] or loading_now
        result["no_availability_seen"] = result["no_availability_seen"] or no_availability_now

        try:
            result["cards_seen"] = await page.locator("form.ant-form .grid.relative").count()
        except Exception:
            result["cards_seen"] = 0

        reserve_buttons_seen = 0

        try:
            buttons = page.locator("form.ant-form button")
            button_count = await buttons.count()

            for button_index in range(button_count):
                raw_button_text = await buttons.nth(button_index).inner_text(timeout=1000)
                button_text = strip_accents(compact(raw_button_text, 100).lower())

                if "reserver" in button_text:
                    reserve_buttons_seen += 1
        except Exception:
            reserve_buttons_seen = 0

        result["reserve_buttons_seen"] = reserve_buttons_seen

        try:
            button_text = await page.locator("button[type='submit'], button.ant-btn-primary").first().inner_text(timeout=1000)
        except Exception:
            button_text = ""

        result["last_button_text"] = button_text

        # Room cards must win.
        if result["cards_seen"] > 0:
            result["finished"] = True
            result["reason"] = "result_cards_visible"
            return result

        # Never trust no-availability while loading text is still visible.
        if no_availability_now and not loading_now and second >= 8:
            result["finished"] = True
            result["reason"] = "no_availability_message_after_loading"
            return result

        if any(marker in normalized for marker in [
            "code adherent incorrect",
            "merci de saisir un code adherent correct",
            "erreur de date",
            "merci de verifier la date",
            "limite depassee",
            "duree de sejour autorisee",
        ]):
            result["finished"] = True
            result["reason"] = "error_modal"
            return result

        if second >= 20 and not loading_now:
            result["finished"] = True
            result["reason"] = "loading_finished_no_explicit_result"
            return result

        await page.wait_for_timeout(1000)

    result["reason"] = "timeout"
    return result


def compact(text: str, limit: int = 900) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def normalize_adherent_code(adherent_number: str) -> str:
    digits = re.sub(r"\D+", "", adherent_number or "")
    return digits[:10]


def has_queue_text(text: str) -> bool:
    lowered = (text or "").lower()
    return any(
        marker in lowered
        for marker in [
            "file d'attente",
            "file d’attente",
            "connexion en cours",
            "veuillez patienter",
            "en attente",
            "ne pas actualiser",
            "gardez cette page ouverte",
            "temps estimé",
            "temps estime",
            "vérif.",
            "verif.",
        ]
    )


def has_no_availability_text(text: str) -> bool:
    lowered = (text or "").lower()

    return any(
        marker in lowered
        for marker in [
            "aucune disponibilité",
            "aucune disponibilite",
            "pas de disponibilité",
            "pas de disponibilite",
            "pas de résultat trouvé",
            "pas de resultat trouvé",
            "pas de resultat trouve",
            "nous n'avons pas de disponibilités",
            "nous n'avons pas de disponibilites",
            "nous n’avons pas de disponibilités",
            "nous n’avons pas de disponibilites",
            "disponiblilités",
            "disponiblilites",
            "les dates que vous avez sélectionnées",
            "les dates que vous avez selectionnees",
            "veuillez réessayer pour d'autres dates",
            "veuillez reessayer pour d'autres dates",
            "veuillez réessayer pour d’autres dates",
            "veuillez reessayer pour d’autres dates",
            "réessayer pour d'autres dates",
            "reessayer pour d'autres dates",
            "aucun logement",
            "aucune chambre",
            "aucun hébergement",
            "aucun hebergement",
            "aucune offre",
            "aucun résultat",
            "aucun resultat",
            "complet",
            "indisponible",
        ]
    )

async def visible_text(page: Page) -> str:
    try:
        return await page.locator("body").inner_text(timeout=10_000)
    except Exception:
        return ""


async def dom_diagnostics(page: Page) -> dict:
    return await page.evaluate(
        """
        () => {
            function findDateEl() {
                return document.getElementById('form.date')
                    || Array.from(document.querySelectorAll('input')).find((el) => el.getAttribute('wire:model') === 'data.date')
                    || document.querySelector('input.flatpickr-input');
            }

            function findCodeEl() {
                return document.getElementById('form.code')
                    || Array.from(document.querySelectorAll('input')).find((el) => el.getAttribute('wire:model') === 'data.code')
                    || Array.from(document.querySelectorAll('input')).find((el) => (el.getAttribute('placeholder') || '').toLowerCase().includes('code'));
            }

            const dateEl = findDateEl();
            const codeEl = findCodeEl();

            const allInputs = Array.from(document.querySelectorAll('input')).map((el) => ({
                id: el.id || null,
                type: el.type || null,
                name: el.name || null,
                placeholder: el.getAttribute('placeholder'),
                wireModel: el.getAttribute('wire:model'),
                value: el.value,
                readonly: el.hasAttribute('readonly'),
                visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length),
            }));

            return {
                hasDate: !!dateEl,
                hasCode: !!codeEl,
                date: dateEl ? {
                    id: dateEl.id || null,
                    wireModel: dateEl.getAttribute('wire:model'),
                    value: dateEl.value,
                    readonly: dateEl.hasAttribute('readonly'),
                    visible: !!(dateEl.offsetWidth || dateEl.offsetHeight || dateEl.getClientRects().length),
                    hasFlatpickr: !!dateEl._flatpickr,
                } : null,
                code: codeEl ? {
                    id: codeEl.id || null,
                    wireModel: codeEl.getAttribute('wire:model'),
                    placeholder: codeEl.getAttribute('placeholder'),
                    value: codeEl.value,
                    visible: !!(codeEl.offsetWidth || codeEl.offsetHeight || codeEl.getClientRects().length),
                } : null,
                inputs: allInputs,
                submitButtons: Array.from(document.querySelectorAll('button[type="submit"]')).map((el) => ({
                    text: el.innerText,
                    visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length),
                })),
            };
        }
        """
    )


async def exact_booking_form_is_visible(page: Page) -> bool:
    try:
        diag = await dom_diagnostics(page)
        return bool(diag.get("hasDate") and diag.get("hasCode"))
    except Exception:
        return False


async def detect_page_state(
    page: Page,
    *,
    options_found: bool = False,
    after_search: bool = False,
) -> str:
    text = await visible_text(page)
    lowered = text.lower()
    url = page.url.lower()

    if any(x in lowered for x in ["captcha", "access denied", "forbidden", "too many requests", "rate limit"]):
        return "RATE_LIMITED"

    if any(x in lowered for x in ["paiement", "payment", "carte bancaire", "finaliser la réservation", "confirmer la réservation"]):
        return "PAYMENT_OR_FINAL_CONFIRMATION"

    if any(x in lowered for x in ["code adhérent incorrect", "merci de saisir un code adhérent correct"]):
        return "ADHERENT_INVALID"

    if any(x in lowered for x in ["erreur de date", "merci de verifier la date", "merci de vérifier la date"]):
        return "DATE_ERROR"

    if any(x in lowered for x in ["limite dépassée", "durée de séjour autorisée", "durée de sejour autorisee"]):
        return "LIMIT_ERROR"

    # After a search, result messages must win over queue/loading words.
    if has_no_availability_text(text):
        return "NO_AVAILABILITY"

    if options_found:
        return "AVAILABLE"

    # Only treat queue text as queue before a search is submitted.
    # Search result pages may contain "Veuillez patienter" or "Recherche en cours",
    # which is not the same as the initial queue page.
    if not after_search and has_queue_text(text):
        return "QUEUE_NON_ADHERENT" if "/s/n" in url else "QUEUE_ADHERENT"

    if after_search and has_search_loading_text(text):
        return "SEARCH_IN_PROGRESS"

    if after_search:
        return "SEARCH_SUBMITTED_NO_OPTIONS"

    if await exact_booking_form_is_visible(page):
        return "BOOKING_FORM_OPEN"

    return "UNKNOWN"

async def wait_until_queue_or_form(page: Page, wait_seconds: int) -> str:
    state = await detect_page_state(page)

    waited = 0
    while state == "QUEUE_ADHERENT" and waited < wait_seconds:
        await page.wait_for_timeout(5_000)
        waited += 5
        state = await detect_page_state(page)

    return state

def has_search_loading_text(text: str) -> bool:
    lowered = (text or "").lower()
    return any(
        marker in lowered
        for marker in [
            "vérification",
            "verification",
            "chargement",
            "loading",
            "veuillez patienter",
        ]
    )


def has_available_text(text: str) -> bool:
    lowered = (text or "").lower()

    lodging_marker = any(
        marker in lowered
        for marker in [
            "appartement",
            "chambre",
            "suite",
            "studio",
            "bungalow",
        ]
    )

    price_marker = any(
        marker in lowered
        for marker in [
            "mad",
            "dh",
            "dhs",
            "dirham",
            "tarif",
            "prix",
        ]
    )

    action_marker = any(
        marker in lowered
        for marker in [
            "sélectionner",
            "selectionner",
            "choisir",
            "réserver",
            "reserver",
            "continuer",
        ]
    )

    return lodging_marker and (price_marker or action_marker)


async def fill_form_dom(page: Page, adherent_number: str, checkin: date, checkout: date) -> dict:
    code = normalize_adherent_code(adherent_number)
    start = checkin.isoformat()
    end = checkout.isoformat()

    return await page.evaluate(
        """
        async ({ code, start, end }) => {
            function findDateEl() {
                return document.getElementById('form.date')
                    || Array.from(document.querySelectorAll('input')).find((el) => el.getAttribute('wire:model') === 'data.date')
                    || document.querySelector('input.flatpickr-input');
            }

            function findCodeEl() {
                return document.getElementById('form.code')
                    || Array.from(document.querySelectorAll('input')).find((el) => el.getAttribute('wire:model') === 'data.code')
                    || Array.from(document.querySelectorAll('input')).find((el) => (el.getAttribute('placeholder') || '').toLowerCase().includes('code'));
            }

            function fire(el) {
                el.dispatchEvent(new InputEvent('input', {
                    bubbles: true,
                    inputType: 'insertText',
                    data: el.value,
                }));

                el.dispatchEvent(new Event('change', { bubbles: true }));
                el.dispatchEvent(new Event('blur', { bubbles: true }));
            }

            function findLivewireComponent(el) {
                if (!window.Livewire) return null;

                let root = el.closest('[wire\\\\:id]');

                if (!root) {
                    root = Array.from(document.querySelectorAll('*')).find((node) => node.hasAttribute('wire:id'));
                }

                if (!root) return null;

                const id = root.getAttribute('wire:id');

                if (!id) return null;

                try {
                    return window.Livewire.find(id);
                } catch (_) {
                    return null;
                }
            }

            const dateEl = findDateEl();
            const codeEl = findCodeEl();

            const result = {
                ok: false,
                codeOk: false,
                dateOk: false,
                livewireSetCode: false,
                livewireSetDate: false,
                codeBefore: null,
                codeAfter: null,
                dateBefore: null,
                dateAfter: null,
                dateMethod: null,
                hasDate: !!dateEl,
                hasCode: !!codeEl,
                error: null,
            };

            if (!dateEl || !codeEl) {
                result.error = 'date or code input not found';
                return result;
            }

            result.codeBefore = codeEl.value;
            result.dateBefore = dateEl.value;

            codeEl.scrollIntoView({ block: 'center' });
            codeEl.focus();
            codeEl.value = '';
            fire(codeEl);

            codeEl.value = code;
            fire(codeEl);

            result.codeAfter = codeEl.value;
            result.codeOk = codeEl.value === code;

            dateEl.scrollIntoView({ block: 'center' });
            dateEl.click();

            const fp =
                dateEl._flatpickr ||
                dateEl.parentElement?._flatpickr ||
                dateEl.closest('.fi-fo-date-time-picker')?._flatpickr ||
                null;

            if (fp && typeof fp.setDate === 'function') {
                fp.clear();
                fp.setDate([start, end], true, 'Y-m-d');
                result.dateMethod = 'flatpickr.setDate';
            } else {
                dateEl.removeAttribute('readonly');
                dateEl.value = `${start} au ${end}`;
                result.dateMethod = 'direct-value';
            }

            fire(dateEl);

            result.dateAfter = dateEl.value;
            result.dateOk = !!dateEl.value && dateEl.value.includes(start) && dateEl.value.includes(end);

            const component = findLivewireComponent(codeEl) || findLivewireComponent(dateEl);

            if (component && typeof component.set === 'function') {
                try {
                    await component.set('data.code', code);
                    result.livewireSetCode = true;
                } catch (_) {}

                try {
                    await component.set('data.date', dateEl.value);
                    result.livewireSetDate = true;
                } catch (_) {}
            }

            result.ok = result.codeOk && result.dateOk;

            return result;
        }
        """,
        {"code": code, "start": start, "end": end},
    )


async def click_search_dom(page: Page) -> dict:
    return await page.evaluate(
        """
        () => {
            function findDateEl() {
                return document.getElementById('form.date')
                    || Array.from(document.querySelectorAll('input')).find((el) => el.getAttribute('wire:model') === 'data.date')
                    || document.querySelector('input.flatpickr-input');
            }

            function findCodeEl() {
                return document.getElementById('form.code')
                    || Array.from(document.querySelectorAll('input')).find((el) => el.getAttribute('wire:model') === 'data.code')
                    || Array.from(document.querySelectorAll('input')).find((el) => (el.getAttribute('placeholder') || '').toLowerCase().includes('code'));
            }

            const dateEl = findDateEl();
            const codeEl = findCodeEl();

            const form =
                dateEl?.closest('form') ||
                codeEl?.closest('form') ||
                Array.from(document.querySelectorAll('form')).find((el) => el.getAttribute('wire:submit') === 'submit') ||
                document.querySelector('form');

            if (!form) {
                return {
                    ok: false,
                    error: 'form not found',
                };
            }

            const button =
                form.querySelector('button[type="submit"]') ||
                Array.from(document.querySelectorAll('button')).find((el) => /recherche|vérification|verification/i.test(el.innerText || ''));

            if (!button) {
                return {
                    ok: false,
                    error: 'submit button not found',
                };
            }

            button.scrollIntoView({ block: 'center' });
            button.click();

            return {
                ok: true,
                buttonText: button.innerText,
            };
        }
        """
    )


async def submit_one_date_range(
    page: Page,
    *,
    adherent_number: str,
    checkin: date,
    checkout: date,
) -> dict:
    actions = {
        "checkin": checkin.isoformat(),
        "checkout": checkout.isoformat(),
        "dom_before": {},
        "fill": {},
        "search": {},
        "dom_after": {},
    }

    actions["dom_before"] = await dom_diagnostics(page)

    actions["fill"] = await fill_form_dom(
        page=page,
        adherent_number=adherent_number,
        checkin=checkin,
        checkout=checkout,
    )

    await page.wait_for_timeout(700)

    actions["dom_after"] = await dom_diagnostics(page)

    if actions["fill"].get("ok"):
        actions["search"] = await click_search_dom(page)

    return actions

def get_max_price_per_night_mad() -> float:
    raw = os.getenv("MAX_PRICE_PER_NIGHT_MAD", "350").strip()

    try:
        return float(raw.replace(",", "."))
    except Exception:
        return 350.0


def price_filter_treat_price_as_total_stay() -> bool:
    raw = os.getenv("PRICE_FILTER_PRICE_IS_TOTAL_STAY", "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def parse_mad_amount(price_text: str) -> float | None:
    if not price_text:
        return None

    text = price_text.lower()
    text = text.replace("mad", "")
    text = text.replace("dhs", "")
    text = text.replace("dh", "")
    text = text.replace("dirhams", "")
    text = text.replace("dirham", "")
    text = re.sub(r"[^\d,.\s]", "", text).strip()
    text = text.replace(" ", "")

    if not text:
        return None

    # Examples:
    # 1 050 MAD -> 1050
    # 1.050,00 MAD -> 1050.00
    # 1,050.00 MAD -> 1050.00
    # 350,00 MAD -> 350.00
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        parts = text.split(",")
        if len(parts[-1]) == 2:
            text = text.replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "." in text:
        parts = text.split(".")
        if len(parts[-1]) != 2:
            text = text.replace(".", "")

    try:
        return float(text)
    except Exception:
        return None


def price_per_night_mad(price_text: str, nights: int | None) -> float | None:
    amount = parse_mad_amount(price_text)

    if amount is None:
        return None

    if price_filter_treat_price_as_total_stay() and nights and nights > 0:
        return amount / nights

    return amount


def option_passes_price_filter(price_text: str, nights: int | None) -> tuple[bool, float | None, float | None]:
    total_amount = parse_mad_amount(price_text)
    nightly_amount = price_per_night_mad(price_text, nights)
    max_nightly = get_max_price_per_night_mad()

    if nightly_amount is None:
        return False, total_amount, nightly_amount

    return nightly_amount <= max_nightly, total_amount, nightly_amount

def extract_visible_options(
    text: str,
    city: City,
    source_url: str,
    checkin: date | None,
    checkout: date | None,
    nights: int | None,
) -> list[dict]:
    if has_queue_text(text) or has_no_availability_text(text):
        return []

    options = []

    lodging_terms = r"(appartement|chambre|suite|studio|bungalow)"
    price_terms = r"(\d[\d\s.,]{1,10}\s*(?:MAD|DH|DHS|dirhams?))"

    patterns = [
        rf"(?P<label>.{{0,180}}?{lodging_terms}.{{0,180}}?)(?P<price>{price_terms})",
        rf"(?P<price>{price_terms})(?P<label>.{{0,220}}?{lodging_terms}.{{0,220}})",
    ]

    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.I):
            gd = match.groupdict()
            price = compact(gd.get("price", ""), 80)
            label = compact(gd.get("label", "Possible option"), 260)

            if not price or not re.search(lodging_terms, label, flags=re.I):
                continue

            passes_price_filter, total_amount, nightly_amount = option_passes_price_filter(price, nights)

            # Telegram should only receive available stays at or below the max nightly price.
            # If the price cannot be parsed, skip it to avoid unwanted alerts.
            if not passes_price_filter:
                continue

            options.append(
                {
                    "city_key": city.key,
                    "city_name": city.name,
                    "checkin": checkin.isoformat() if checkin else None,
                    "checkout": checkout.isoformat() if checkout else None,
                    "nights": nights,
                    "room_type": label,
                    "price": price,
                    "price_amount_mad": total_amount,
                    "price_per_night_mad": nightly_amount,
                    "max_price_per_night_mad": get_max_price_per_night_mad(),
                    "booking_url": source_url,
                    "confidence": "medium",
                    "note": "Available option passed the max nightly price filter.",
                }
            )

    return options[:20]


async def save_debug_artifacts(page: Page, output_dir: Path, name: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        await page.screenshot(path=output_dir / f"{name}.png", full_page=True)
    except Exception:
        pass

    try:
        html = await page.content()
        (output_dir / f"{name}.html").write_text(html, encoding="utf-8")
    except Exception:
        pass

    try:
        text = await visible_text(page)
        (output_dir / f"{name}.txt").write_text(text, encoding="utf-8")
    except Exception:
        pass



async def post_search_panel_is_visible(page: Page) -> bool:
    try:
        return await page.evaluate(
            """
            () => {
                const panel = document.querySelector('.ant-picker-range');
                const button = Array.from(document.querySelectorAll('button')).find((el) =>
                    /vérifier la disponibilité|verifier la disponibilite|disponibilité|disponibilite/i.test(el.innerText || '')
                );

                return !!panel && !!button;
            }
            """
        )
    except Exception:
        return False


async def fill_post_search_panel_date_range(
    page: Page,
    *,
    checkin: date,
    checkout: date,
) -> dict:
    start = checkin.isoformat()
    end = checkout.isoformat()

    result = {
        "ok": False,
        "method": None,
        "checkin": start,
        "checkout": end,
        "clear_clicked": False,
        "start_before": None,
        "end_before": None,
        "start_after": None,
        "end_after": None,
        "error": None,
    }

    try:
        panel = page.locator(".ant-picker-range").nth(0)
        await panel.scroll_into_view_if_needed(timeout=5000)
        await panel.hover(timeout=5000)

        start_input = panel.locator("input").nth(0)
        end_input = panel.locator("input").nth(1)

        result["start_before"] = await start_input.input_value(timeout=3000)
        result["end_before"] = await end_input.input_value(timeout=3000)

        try:
            clear_button = panel.locator(".ant-picker-clear").nth(0)
            if await clear_button.count() > 0:
                await clear_button.click(timeout=3000, force=True)
                result["clear_clicked"] = True
                await page.wait_for_timeout(500)
        except Exception:
            pass

        # Normal user-like typing into Ant Design range inputs.
        await start_input.click(timeout=5000)
        await page.keyboard.press("Control+A")
        await page.keyboard.type(start, delay=30)
        await page.keyboard.press("Tab")
        await page.wait_for_timeout(300)

        await end_input.click(timeout=5000)
        await page.keyboard.press("Control+A")
        await page.keyboard.type(end, delay=30)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(700)

        result["start_after"] = await start_input.input_value(timeout=3000)
        result["end_after"] = await end_input.input_value(timeout=3000)
        result["method"] = "ant-picker-keyboard-fill"
        result["ok"] = result["start_after"] == start and result["end_after"] == end

        if result["ok"]:
            return result

        # JS fallback for controlled Ant inputs.
        js_result = await page.evaluate(
            """
            ({ start, end }) => {
                const panel = document.querySelector('.ant-picker-range');

                if (!panel) {
                    return { ok: false, error: 'panel not found' };
                }

                const inputs = panel.querySelectorAll('input');

                if (inputs.length < 2) {
                    return { ok: false, error: 'range inputs not found' };
                }

                const nativeSetter = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype,
                    'value'
                ).set;

                function setInput(el, value) {
                    el.focus();
                    nativeSetter.call(el, value);

                    el.dispatchEvent(new InputEvent('input', {
                        bubbles: true,
                        inputType: 'insertText',
                        data: value,
                    }));

                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    el.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, key: 'Enter', code: 'Enter' }));
                    el.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true, key: 'Enter', code: 'Enter' }));
                    el.dispatchEvent(new Event('blur', { bubbles: true }));
                }

                setInput(inputs[0], start);
                setInput(inputs[1], end);

                return {
                    ok: inputs[0].value === start && inputs[1].value === end,
                    startValue: inputs[0].value,
                    endValue: inputs[1].value,
                };
            }
            """,
            {"start": start, "end": end},
        )

        result["method"] = "ant-picker-js-fallback"
        result["start_after"] = js_result.get("startValue") if js_result else result["start_after"]
        result["end_after"] = js_result.get("endValue") if js_result else result["end_after"]
        result["ok"] = bool(js_result and js_result.get("ok"))

        return result

    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result


async def click_post_search_verify_button(page: Page) -> dict:
    result = {
        "ok": False,
        "button_text": None,
        "error": None,
    }

    try:
        buttons = page.locator("button")
        count = await buttons.count()

        for index in range(count):
            button = buttons.nth(index)

            try:
                text = await button.inner_text(timeout=1000)
            except Exception:
                continue

            lowered = text.lower()

            if (
                "vérifier la disponibilité" in lowered
                or "verifier la disponibilite" in lowered
                or "vérifier" in lowered
                or "disponibilité" in lowered
            ):
                if await button.is_visible(timeout=1000):
                    result["button_text"] = text
                    await button.click(timeout=8000)
                    result["ok"] = True
                    return result

        result["error"] = "verify button not found"
        return result

    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result

async def submit_post_search_panel_date_range(
    page: Page,
    *,
    checkin: date,
    checkout: date,
) -> dict:
    actions = {
        "mode": "post_search_panel",
        "checkin": checkin.isoformat(),
        "checkout": checkout.isoformat(),
        "panel_visible": False,
        "date": {},
        "search": {},
    }

    actions["panel_visible"] = await post_search_panel_is_visible(page)

    if not actions["panel_visible"]:
        return actions

    actions["date"] = await fill_post_search_panel_date_range(
        page,
        checkin=checkin,
        checkout=checkout,
    )

    await page.wait_for_timeout(700)

    if actions["date"].get("ok"):
        actions["search"] = await click_post_search_verify_button(page)

    return actions


def zephyr_max_price_per_night_mad() -> float:
    raw = os.getenv("MAX_PRICE_PER_NIGHT_MAD", "350").strip()

    try:
        return float(raw.replace(",", "."))
    except Exception:
        return 350.0


def zephyr_price_is_total_stay() -> bool:
    raw = os.getenv("PRICE_FILTER_PRICE_IS_TOTAL_STAY", "false").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def zephyr_parse_mad_amount(price_text: str) -> float | None:
    if not price_text:
        return None

    text = price_text.lower()
    text = text.replace("mad", "")
    text = text.replace("dhs", "")
    text = text.replace("dh", "")
    text = text.replace("dirhams", "")
    text = text.replace("dirham", "")
    text = re.sub(r"[^\d,.\s]", "", text).strip()
    text = text.replace(" ", "")

    if not text:
        return None

    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        parts = text.split(",")
        if len(parts[-1]) == 2:
            text = text.replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "." in text:
        parts = text.split(".")
        if len(parts[-1]) != 2:
            text = text.replace(".", "")

    try:
        return float(text)
    except Exception:
        return None


def slugify_booking_title(value: str | None) -> str:
    text = compact(value or "option", 200).lower()
    text = (
        text.replace("é", "e")
        .replace("è", "e")
        .replace("ê", "e")
        .replace("à", "a")
        .replace("â", "a")
        .replace("î", "i")
        .replace("ï", "i")
        .replace("ô", "o")
        .replace("ù", "u")
        .replace("û", "u")
        .replace("ç", "c")
    )
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "option"


def parse_booking_number(value: str | None) -> float | None:
    if not value:
        return None

    match = re.search(r"\d+(?:[,.]\d+)?", value.replace(" ", ""))

    if not match:
        return None

    try:
        return float(match.group(0).replace(",", "."))
    except Exception:
        return None


def max_price_per_night_mad() -> float:
    raw = os.getenv("MAX_PRICE_PER_NIGHT_MAD", "350").strip()

    try:
        return float(raw.replace(",", "."))
    except Exception:
        return 350.0


def price_is_total_stay() -> bool:
    raw = os.getenv("PRICE_FILTER_PRICE_IS_TOTAL_STAY", "false").strip().lower()
    return raw in {"1", "true", "yes", "on"}


async def extract_filtered_available_options_from_result_page(
    page: Page,
    *,
    city: City,
    source_url: str,
    checkin: date | None,
    checkout: date | None,
    nights: int | None,
) -> tuple[list[dict], int]:
    """
    Extract available room cards from Zephyr result pages.

    Cards have no stable booking IDs, so each card is identified by:
    - DOM position
    - title
    - generated slug

    Availability rule:
    - has Réserver button
    - does not contain Non disponible / Pas de disponibilité
    - remaining inventory > 0
    - price per night <= MAX_PRICE_PER_NIGHT_MAD
    """

    options: list[dict] = []
    available_cards_seen = 0
    max_price = max_price_per_night_mad()

    cards = page.locator("form.ant-form .grid.relative")
    count = await cards.count()

    for index in range(count):
        card = cards.nth(index)

        try:
            full_text = compact(await card.inner_text(timeout=2000), 3000)
        except Exception:
            continue

        if not re.search(r"MAD\s*\d+", full_text, flags=re.I):
            continue

        try:
            has_image = await card.locator("img[alt]").count() > 0
        except Exception:
            has_image = False

        if not has_image:
            continue

        title = ""

        try:
            title = await card.evaluate(
                """
                (el) => {
                    const imgAlt = el.querySelector("img[alt]")?.getAttribute("alt") || "";
                    const titleSpan = el.querySelector("a span")?.innerText || "";
                    const boldTitle = Array.from(el.querySelectorAll(".font-bold"))
                        .map((node) => node.innerText || "")
                        .find((value) =>
                            /Appartement|Chambre|Suite|Studio|Bungalow/i.test(value)
                        ) || "";

                    return (titleSpan || imgAlt || boldTitle || "").trim();
                }
                """
            )
            title = compact(title, 120)
        except Exception:
            title = ""

        if not title:
            title = "Option disponible"

        marked_unavailable = bool(
            re.search(
                r"Non disponible|Pas de disponibilité|Pas de disponibilite",
                full_text,
                flags=re.I,
            )
        )

        has_reserve_button = False

        try:
            buttons = card.locator("button")
            button_count = await buttons.count()

            for button_index in range(button_count):
                button_text = compact(await buttons.nth(button_index).inner_text(timeout=1000), 100)

                if re.search(r"Réserver|Reserver", button_text, flags=re.I):
                    has_reserve_button = True
                    break
        except Exception:
            has_reserve_button = False

        remaining = 0
        remaining_match = re.search(
            r"(\d+)\s*h[ée]bergement\(s\)\s+restant\(s\)",
            full_text,
            flags=re.I,
        )

        if remaining_match:
            remaining = int(remaining_match.group(1))

        available = has_reserve_button and not marked_unavailable and remaining > 0

        if not available:
            continue

        available_cards_seen += 1

        price_match = re.search(r"MAD\s*([\d\s.,]+)", full_text, flags=re.I)
        price_amount = parse_booking_number(price_match.group(1) if price_match else None)

        if price_amount is None:
            continue

        is_per_night = bool(re.search(r"Par nuit", full_text, flags=re.I))

        if is_per_night:
            nightly_amount = price_amount
            price_unit = "per_night"
        elif price_is_total_stay() and nights and nights > 0:
            nightly_amount = price_amount / nights
            price_unit = "total_stay"
        else:
            nightly_amount = price_amount
            price_unit = "unknown_assumed_per_night"

        if nightly_amount > max_price:
            continue

        capacity_max = None
        capacity_match = re.search(r"Capacité maximale\s+(\d+)\s+personne", full_text, flags=re.I)

        if capacity_match:
            capacity_max = int(capacity_match.group(1))

        capacity_text = None
        capacity_text_match = re.search(
            r"Capacité maximale\s+\d+\s+personne(?:s)?",
            full_text,
            flags=re.I,
        )

        if capacity_text_match:
            capacity_text = capacity_text_match.group(0)

        cancellation = "Non remboursable" if re.search(r"Non remboursable", full_text, flags=re.I) else None
        taxes = "Taxes de séjour non incluses" if re.search(r"Taxes de séjour non incluses", full_text, flags=re.I) else None

        image = None

        try:
            image = await card.locator("img").first().get_attribute("src", timeout=1000)
        except Exception:
            image = None

        description_parts = []

        if capacity_text:
            description_parts.append(capacity_text)

        if cancellation:
            description_parts.append(cancellation)

        description_parts.append(f"{remaining} hébergement(s) restant(s)")

        if taxes:
            description_parts.append(taxes)

        generated_id = f"{index + 1}-{slugify_booking_title(title)}"

        options.append(
            {
                "city_key": city.key,
                "city_name": city.name,
                "checkin": checkin.isoformat() if checkin else None,
                "checkout": checkout.isoformat() if checkout else None,
                "nights": nights,

                "label": title,
                "room_type": title,
                "description": " • ".join(description_parts),

                "generated_id": generated_id,
                "card_index": index + 1,

                "price": f"MAD {price_amount:.2f}",
                "price_amount_mad": price_amount,
                "price_per_night_mad": nightly_amount,
                "max_price_per_night_mad": max_price,
                "price_unit": price_unit,

                "remaining": remaining,
                "capacity_max": capacity_max,
                "cancellation": cancellation,
                "taxes": taxes,
                "image": image,

                "booking_url": source_url,
                "confidence": "high",
                "note": "Available booking card detected by Réserver button, remaining inventory, and price filter.",
            }
        )

    return options, available_cards_seen

class BrowserBookingClient:
    def __init__(
        self,
        *,
        headless: bool = True,
        wait_seconds: int = 60,
        hold_browser_open_seconds: int = 0,
    ):
        self.headless = headless
        self.wait_seconds = wait_seconds
        self.hold_browser_open_seconds = hold_browser_open_seconds

    async def scan_city_ranges(
        self,
        *,
        scan_id: str,
        scan_started_at: datetime,
        city: City,
        adherent_number: str,
        date_ranges: list[dict],
    ) -> list[SnapshotRecord]:
        debug_dir = Path("debug") / "browser_booking" / city.key
        snapshots: list[SnapshotRecord] = []

        total_ranges = len(date_ranges)
        progress_marks_reported: set[int] = set()

        print(f"[{city.name}] Starting availability scan: {total_ranges} date ranges", flush=True)

        def report_city_progress(done: int) -> None:
            if total_ranges <= 0:
                return

            percent = int((done / total_ranges) * 100)

            for mark in (20, 40, 60, 80, 100):
                if percent >= mark and mark not in progress_marks_reported:
                    progress_marks_reported.add(mark)
                    print(
                        f"[{city.name}] {mark}% complete ({done}/{total_ranges} ranges checked)",
                        flush=True,
                    )

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self.headless)
            context = await browser.new_context(
                viewport={"width": 1440, "height": 1100},
                locale="fr-FR",
                timezone_id="Africa/Casablanca",
            )

            page = await context.new_page()

            try:
                await page.goto(city.booking_adherent_url, wait_until="domcontentloaded", timeout=60_000)
                await page.wait_for_timeout(3000)

                await save_debug_artifacts(page, debug_dir, "01_initial_loaded")

                state = await wait_until_queue_or_form(page, self.wait_seconds)

                await save_debug_artifacts(page, debug_dir, "02_after_initial_queue_wait")

                if state == "QUEUE_ADHERENT":
                    text = await visible_text(page)

                    snapshots.append(
                        SnapshotRecord(
                            scan_id=scan_id,
                            scan_started_at=scan_started_at,
                            source_url=city.booking_adherent_url,
                            final_url=page.url,
                            city_key=city.key,
                            city_name=city.name,
                            user_type="adherent",
                            page_type="booking_direct_browser",
                            state="QUEUE_ADHERENT",
                            http_status_if_available=None,
                            visible_message=compact(text, 1800),
                            checkin=None,
                            checkout=None,
                            nights=None,
                            booking_url=city.booking_adherent_url,
                            raw_hash=str(abs(hash(text))),
                            booking_options=[],
                            availability_options=[],
                        )
                    )

                    return snapshots

                for index, item in enumerate(date_ranges, start=1):
                    checkin = item["checkin"]
                    checkout = item["checkout"]
                    nights = item["nights"]

                    actions = {
                        "date_attempt_index": index,
                        "checkin": checkin.isoformat(),
                        "checkout": checkout.isoformat(),
                        "used_fallback_fresh_page": False,
                    }

                    try:
                        if index == 1:
                            # First search uses the original Flatpickr + adherent form.
                            actions["mode"] = "initial_form"

                            actions.update(
                                await submit_one_date_range(
                                    page,
                                    adherent_number=adherent_number,
                                    checkin=checkin,
                                    checkout=checkout,
                                )
                            )
                        else:
                            # Next searches use the post-search Ant Design range panel.
                            panel_actions = await submit_post_search_panel_date_range(
                                page,
                                checkin=checkin,
                                checkout=checkout,
                            )

                            actions.update(panel_actions)

                            # Safety fallback: if the post-search panel is missing, reload clean page.
                            if not panel_actions.get("panel_visible") or not panel_actions.get("date", {}).get("ok"):
                                actions["used_fallback_fresh_page"] = True

                                await page.goto(city.booking_adherent_url, wait_until="domcontentloaded", timeout=60_000)
                                await page.wait_for_timeout(3000)

                                state = await wait_until_queue_or_form(page, self.wait_seconds)

                                if state == "QUEUE_ADHERENT":
                                    text = await visible_text(page)

                                    snapshots.append(
                                        SnapshotRecord(
                                            scan_id=scan_id,
                                            scan_started_at=scan_started_at,
                                            source_url=city.booking_adherent_url,
                                            final_url=page.url,
                                            city_key=city.key,
                                            city_name=city.name,
                                            user_type="adherent",
                                            page_type="booking_direct_browser",
                                            state="QUEUE_ADHERENT",
                                            http_status_if_available=None,
                                            visible_message=compact(text, 1800),
                                            checkin=checkin,
                                            checkout=checkout,
                                            nights=nights,
                                            booking_url=city.booking_adherent_url,
                                            raw_hash=str(abs(hash(text))),
                                            booking_options=[],
                                            availability_options=[],
                                        )
                                    )

                                    break

                                fallback_actions = await submit_one_date_range(
                                    page,
                                    adherent_number=adherent_number,
                                    checkin=checkin,
                                    checkout=checkout,
                                )

                                actions["fallback_initial_form"] = fallback_actions

                        after_search = bool(actions.get("search", {}).get("ok"))

                        if not after_search and actions.get("fallback_initial_form"):
                            after_search = bool(actions["fallback_initial_form"].get("search", {}).get("ok"))

                        await save_debug_artifacts(page, debug_dir, f"03_after_submit_{index:03d}")

                        if after_search:
                            actions["result_wait"] = await wait_for_search_result(page, max_seconds=90)

                        await save_debug_artifacts(page, debug_dir, f"04_after_result_{index:03d}")

                        text = await visible_text(page)

                        try:
                            options, available_cards_seen = await extract_filtered_available_options_from_result_page(
                                page,
                                city=city,
                                source_url=page.url,
                                checkin=checkin,
                                checkout=checkout,
                                nights=nights,
                            )
                        except Exception as extractor_exc:
                            options = []
                            available_cards_seen = 0
                            actions["availability_extractor_error"] = f"{type(extractor_exc).__name__}: {extractor_exc}"

                        actions["available_cards_seen"] = available_cards_seen
                        actions["price_filtered_options_count"] = len(options)
                        actions["max_price_per_night_mad"] = max_price_per_night_mad()

                        state = await detect_page_state(
                            page,
                            options_found=bool(options),
                            after_search=after_search,
                        )

                        if options:
                            state = "AVAILABLE"
                        elif after_search and actions.get("available_cards_seen", 0) > 0:
                            state = "AVAILABLE_PRICE_FILTERED_OUT"
                        elif after_search and has_no_availability_text(text):
                            state = "NO_AVAILABILITY"

                        visible_message = compact(
                            f"{text} | form_actions={json.dumps(actions, ensure_ascii=False)}",
                            4000,
                        )

                        snapshots.append(
                            SnapshotRecord(
                                scan_id=scan_id,
                                scan_started_at=scan_started_at,
                                source_url=city.booking_adherent_url,
                                final_url=page.url,
                                city_key=city.key,
                                city_name=city.name,
                                user_type="adherent",
                                page_type="booking_direct_browser",
                                state=state,
                                http_status_if_available=None,
                                visible_message=visible_message,
                                checkin=checkin,
                                checkout=checkout,
                                nights=nights,
                                booking_url=city.booking_adherent_url,
                                raw_hash=str(abs(hash(text))),
                                booking_options=[],
                                availability_options=options,
                            )
                        )

                        await page.wait_for_timeout(3000)
                        report_city_progress(index)

                    except Exception as exc:
                        message = f"Date range scan failed: {type(exc).__name__}: {exc}"

                        snapshots.append(
                            SnapshotRecord(
                                scan_id=scan_id,
                                scan_started_at=scan_started_at,
                                source_url=city.booking_adherent_url,
                                final_url=page.url if page else city.booking_adherent_url,
                                city_key=city.key,
                                city_name=city.name,
                                user_type="adherent",
                                page_type="booking_direct_browser",
                                state="NETWORK_ERROR",
                                http_status_if_available=None,
                                visible_message=compact(
                                    f"{message} | form_actions={json.dumps(actions, ensure_ascii=False)}",
                                    4000,
                                ),
                                checkin=checkin,
                                checkout=checkout,
                                nights=nights,
                                booking_url=city.booking_adherent_url,
                                raw_hash=str(abs(hash(message))),
                                booking_options=[],
                                availability_options=[],
                            )
                        )

                        await page.wait_for_timeout(3000)
                        report_city_progress(index)
                        continue

                if self.hold_browser_open_seconds > 0 and not self.headless:
                    print(f"Holding browser open for {self.hold_browser_open_seconds}s for {city.name}...")
                    await page.wait_for_timeout(self.hold_browser_open_seconds * 1000)

                return snapshots

            finally:
                await context.close()
                await browser.close()
    async def scan_city(
        self,
        *,
        scan_id: str,
        scan_started_at: datetime,
        city: City,
        adherent_number: str,
        checkin: date,
        checkout: date,
        nights: int,
    ) -> SnapshotRecord:
        snapshots = await self.scan_city_ranges(
            scan_id=scan_id,
            scan_started_at=scan_started_at,
            city=city,
            adherent_number=adherent_number,
            date_ranges=[
                {
                    "checkin": checkin,
                    "checkout": checkout,
                    "nights": nights,
                }
            ],
        )

        return snapshots[0]













