#!/usr/bin/env python3
"""MVP v1.1 invoice extraction / извличане на фактури към review Excel.

Reads standardized filenames and, for PDF invoices, attempts real text extraction
to improve supplier/date/invoice number/amount detection.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

try:
    import fitz  # type: ignore
except Exception:
    fitz = None

try:
    from pypdf import PdfReader  # type: ignore
except Exception:
    PdfReader = None

# Local module — best-effort SQLite-backed pattern store.
try:
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    import pattern_store  # type: ignore
except Exception:
    pattern_store = None  # type: ignore


FILENAME_PATTERN = re.compile(
    r"^(?P<client>.+)_(?P<date>\d{4}-\d{2}-\d{2}|UNKNOWNDATE)_(?P<dtype>Invoice|Receipt|Bank|Other)_(?P<counterparty>[^_]+)_(?P<amount>[^_]+?)(?:_(?P<dup>\d+))?$",
    re.IGNORECASE,
)

SUPPORTED_INVOICE_EXTENSIONS = {
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
    ".tif",
    ".tiff",
    ".bmp",
    ".webp",
}

IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".tif",
    ".tiff",
    ".bmp",
    ".webp",
}


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def write_log(log_file: Path, line: str) -> None:
    with log_file.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def ensure_log_header(log_file: Path) -> None:
    if not log_file.exists() or log_file.stat().st_size == 0:
        with log_file.open("a", encoding="utf-8") as fh:
            fh.write("# Accounting AI Run Log / Дневник на изпълнение\n")
            fh.write("# Format / Формат: YYYY-MM-DD HH:MM [Action details / Детайли]\n")


def parse_amount(value: str) -> float | None:
    if value.lower() == "unknown":
        return None
    normalized = value.replace(",", ".")
    try:
        return float(normalized)
    except ValueError:
        return None


def normalize_dtype(dtype: str) -> str:
    lower = dtype.lower()
    if lower == "invoice":
        return "Invoice"
    if lower == "receipt":
        return "Receipt"
    if lower == "bank":
        return "Bank"
    return "Other"


def _normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


# ---------------------------------------------------------------------------
# Multi-locale date extraction
# ---------------------------------------------------------------------------

# Map Eastern Arabic (٠-٩) and Persian (۰-۹) digits to ASCII so subsequent
# numeric regexes work uniformly. Other scripts (Devanagari, Bengali, etc.)
# could be added the same way.
_DIGIT_TRANSLATION = {
    **{ord("٠") + i: ord("0") + i for i in range(10)},
    **{ord("۰") + i: ord("0") + i for i in range(10)},
}


def _normalize_digits(text: str) -> str:
    if not text:
        return text
    return text.translate(_DIGIT_TRANSLATION)


# Month-name → 1..12 covering EN, BG, RU, DE, FR, ES, IT (full + short).
# Lowercased, accents preserved as-is (regex matches case-insensitively).
MONTHS: dict[str, int] = {}


def _add_months(*pairs):
    for tokens, num in pairs:
        for tok in tokens:
            MONTHS[tok.lower()] = num


_add_months(
    # English
    (("january", "jan"), 1), (("february", "feb"), 2), (("march", "mar"), 3),
    (("april", "apr"), 4), (("may",), 5), (("june", "jun"), 6),
    (("july", "jul"), 7), (("august", "aug"), 8), (("september", "sep", "sept"), 9),
    (("october", "oct"), 10), (("november", "nov"), 11), (("december", "dec"), 12),
    # Bulgarian
    (("януари", "ян"), 1), (("февруари", "фев"), 2), (("март", "мар"), 3),
    (("април", "апр"), 4), (("май",), 5), (("юни",), 6),
    (("юли",), 7), (("август", "авг"), 8), (("септември", "сеп"), 9),
    (("октомври", "окт"), 10), (("ноември", "ное", "ноем"), 11), (("декември", "дек"), 12),
    # Russian (genitive forms)
    (("января", "янв"), 1), (("февраля",), 2), (("марта",), 3),
    (("апреля",), 4), (("мая",), 5), (("июня",), 6),
    (("июля",), 7), (("августа",), 8), (("сентября", "сент"), 9),
    (("октября",), 10), (("ноября",), 11), (("декабря",), 12),
    # German
    (("januar", "jän"), 1), (("februar",), 2), (("märz", "marz"), 3),
    (("mai",), 5), (("juni",), 6), (("juli",), 7),
    (("oktober",), 10), (("dezember",), 12),
    # French
    (("janvier", "janv"), 1), (("février", "fevrier", "févr", "fevr"), 2), (("mars",), 3),
    (("avril", "avr"), 4), (("juin",), 6), (("juillet", "juil"), 7),
    (("août", "aout"), 8), (("septembre", "sept"), 9),
    (("octobre",), 10), (("novembre", "nov"), 11), (("décembre", "decembre", "déc"), 12),
    # Spanish
    (("enero", "ene"), 1), (("febrero",), 2), (("marzo",), 3),
    (("abril", "abr"), 4), (("mayo",), 5), (("junio",), 6),
    (("julio",), 7), (("agosto", "ago"), 8), (("septiembre", "setiembre"), 9),
    (("octubre",), 10), (("noviembre",), 11), (("diciembre",), 12),
    # Italian
    (("gennaio",), 1), (("febbraio",), 2), (("marzo",), 3),
    (("aprile",), 4), (("maggio",), 5), (("giugno",), 6),
    (("luglio",), 7), (("agosto",), 8), (("settembre",), 9),
    (("ottobre",), 10), (("novembre",), 11), (("dicembre",), 12),
)


def _safe_iso(year: int, month: int, day: int) -> str:
    """Validate (y, m, d) and return ISO string. Year guard: 2000..today+1."""
    current_year = datetime.now().year
    if year < 2000 or year > current_year + 1:
        return ""
    try:
        return datetime(year, month, day).strftime("%Y-%m-%d")
    except (ValueError, OverflowError):
        return ""


def _two_digit_year_to_full(yy: int) -> int:
    current_year = datetime.now().year
    candidate = 2000 + yy
    if candidate <= current_year + 1:
        return candidate
    return 1900 + yy


# Pattern fragments. We compile once and reuse.
_NUM_DATE_RE = re.compile(
    r"(?<!\d)(\d{1,4})[./\-](\d{1,2})[./\-](\d{1,4})(?!\d)"
)
_MONTH_NAME_TOKEN = "|".join(sorted(MONTHS.keys(), key=len, reverse=True))
_MONTH_DMY_RE = re.compile(
    rf"(?<!\w)(\d{{1,2}})(?:st|nd|rd|th)?\s*[\-\.\s,]*\s*({_MONTH_NAME_TOKEN})\s*[\-\.\s,]*\s*(\d{{2,4}})(?!\w)",
    re.IGNORECASE | re.UNICODE,
)
_MONTH_MDY_RE = re.compile(
    rf"(?<!\w)({_MONTH_NAME_TOKEN})\s*[\.\s]*\s*(\d{{1,2}})(?:st|nd|rd|th)?\s*[,.\s]*\s*(\d{{2,4}})(?!\w)",
    re.IGNORECASE | re.UNICODE,
)
_CJK_CN_RE = re.compile(r"(\d{2,4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
_CJK_KR_RE = re.compile(r"(\d{2,4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일")


def _iter_date_matches(text: str):
    """Yield (offset, iso_date, raw_match, kind) for every parseable date.

    Numeric ambiguity policy: DD/MM (EU) by default; only flip to MM/DD when
    the first number is > 12 (unambiguous US-style). A ``YYYY-MM-DD`` form
    is detected by the year being 4 digits in the leading slot.
    """
    if not text:
        return

    # CJK first (unambiguous, won't be matched by numeric patterns).
    for m in _CJK_CN_RE.finditer(text):
        y, mo, d = (int(x) for x in m.groups())
        if y < 100:
            y = _two_digit_year_to_full(y)
        iso = _safe_iso(y, mo, d)
        if iso:
            yield (m.start(), iso, m.group(0), "cjk")
    for m in _CJK_KR_RE.finditer(text):
        y, mo, d = (int(x) for x in m.groups())
        if y < 100:
            y = _two_digit_year_to_full(y)
        iso = _safe_iso(y, mo, d)
        if iso:
            yield (m.start(), iso, m.group(0), "cjk")

    # Month-name DMY ("2 March 2026", "27th Feb. 2026", "15 март 2026 г.").
    for m in _MONTH_DMY_RE.finditer(text):
        d_str, mon_tok, y_str = m.groups()
        mo = MONTHS.get(mon_tok.lower())
        if not mo:
            continue
        y = int(y_str)
        if y < 100:
            y = _two_digit_year_to_full(y)
        iso = _safe_iso(y, mo, int(d_str))
        if iso:
            yield (m.start(), iso, m.group(0), "month_name")

    # Month-name MDY ("March 2, 2026", "MARCH 25, 2026", "Mar 9, 2026").
    for m in _MONTH_MDY_RE.finditer(text):
        mon_tok, d_str, y_str = m.groups()
        mo = MONTHS.get(mon_tok.lower())
        if not mo:
            continue
        y = int(y_str)
        if y < 100:
            y = _two_digit_year_to_full(y)
        iso = _safe_iso(y, mo, int(d_str))
        if iso:
            yield (m.start(), iso, m.group(0), "month_name")

    # Numeric forms.
    for m in _NUM_DATE_RE.finditer(text):
        a, b, c = m.groups()
        a_i, b_i, c_i = int(a), int(b), int(c)

        # YYYY-MM-DD (4-digit leading year)
        if len(a) == 4:
            iso = _safe_iso(a_i, b_i, c_i)
            if iso:
                yield (m.start(), iso, m.group(0), "numeric_iso")
                continue
        # 4-digit trailing year
        if len(c) == 4:
            # Default DD/MM/YYYY (EU). Flip to MM/DD only when the SECOND
            # number is > 12 — the only case where it cannot be a month.
            if b_i > 12 and a_i <= 12:
                iso = _safe_iso(c_i, a_i, b_i)  # MDY
                kind = "numeric_mdy"
            else:
                iso = _safe_iso(c_i, b_i, a_i)  # DMY
                kind = "numeric_dmy"
            if iso:
                yield (m.start(), iso, m.group(0), kind)
                continue
        # 2-digit trailing year
        if len(c) == 2 and len(a) <= 2:
            yy = _two_digit_year_to_full(c_i)
            if b_i > 12 and a_i <= 12:
                iso = _safe_iso(yy, a_i, b_i)
                kind = "numeric_mdy"
            else:
                iso = _safe_iso(yy, b_i, a_i)
                kind = "numeric_dmy"
            if iso:
                yield (m.start(), iso, m.group(0), kind)


# Issue-date label patterns (multi-locale). Higher score for these.
_ISSUE_LABELS = [
    # Bulgarian
    "дата на издаване", "дата на фактурата", "дата на издаването",
    "дата на дан\\.?\\s*събитие", "дата на данъчно събитие",
    "дата на изд",
    # English
    "invoice date", "issue date", "date of issue", "billing date",
    # German
    "rechnungsdatum", "rechnungs-?datum",
    # French
    "date de la facture", "date de facturation", "date d'émission",
    # Spanish
    "fecha de emisión", "fecha factura", "fecha de la factura", "fecha de emision",
    # Italian
    "data emissione", "data fattura",
    # Russian
    "дата выставления", "дата счёта", "дата счета",
    # Chinese / Japanese / Korean
    "开票日期", "发票日期", "請求日", "発行日", "발행일",
]
_ISSUE_LABEL_RE = re.compile(
    r"(?i)\b(?:" + "|".join(_ISSUE_LABELS) + r")\b\s*[:\-]?\s*",
)
_GENERIC_DATE_LABEL_RE = re.compile(
    r"(?i)\b(?:дата|date|datum|fecha|data|日期|날짜)\b\s*[:\-]?\s*",
)
_INVOICE_NUM_LABEL_RE = re.compile(
    r"(?i)(?:№|no\.?|nr\.?|number|номер|фактура|invoice|rechnung|factura|发票号|fattura)",
)
_DUE_LABEL_RE = re.compile(
    r"(?i)\b(?:падеж|срок\s+за\s+плащане|дата\s+на\s+падеж|due\s*date|payment\s*due|fälligkeit|faelligkeit|vencimiento|scadenza|date\s+limite|到期日|만기일)\b",
)
_PERIOD_LABEL_RE = re.compile(
    r"(?i)\b(?:период|за\s+период|периода|дата\s+на\s+доставка|delivery\s*date|billing\s*period|period|leistungsdatum|leistungszeitraum|periodo|période)\b",
)


def _choose_invoice_date(text: str) -> str:
    """Pick the best invoice-issue date from arbitrary text.

    Returns "" when nothing matches plausibly; caller should then flag the
    row for manual review.
    """
    if not text:
        return ""
    norm = _normalize_digits(text)
    candidates = list(_iter_date_matches(norm))
    if not candidates:
        return ""

    text_len = max(len(norm), 1)
    # Pre-collect label offsets for proximity scoring.
    issue_label_spans = [m.start() for m in _ISSUE_LABEL_RE.finditer(norm)]
    generic_label_spans = [m.start() for m in _GENERIC_DATE_LABEL_RE.finditer(norm)]
    inv_num_spans = [m.start() for m in _INVOICE_NUM_LABEL_RE.finditer(norm)]
    due_spans = [m.start() for m in _DUE_LABEL_RE.finditer(norm)]
    period_spans = [m.start() for m in _PERIOD_LABEL_RE.finditer(norm)]

    def _near(offset: int, spans: list[int], window: int) -> bool:
        # A label is "near" if it appears within `window` chars BEFORE the date.
        for s in spans:
            if 0 <= offset - s <= window:
                return True
        return False

    best = None
    best_score = float("-inf")
    for offset, iso, raw, kind in candidates:
        score = 0
        if _near(offset, issue_label_spans, 60):
            score += 100
        if _near(offset, generic_label_spans, 30):
            score += 60
        if _near(offset, inv_num_spans, 80):
            score += 40
        if offset < text_len * 0.25:
            score += 20
        elif offset > text_len * 0.85:
            score -= 20
        if _near(offset, due_spans, 40):
            score -= 80
        if _near(offset, period_spans, 50):
            score -= 40
        # Tie-break: earlier offset slightly preferred.
        score -= offset / max(text_len, 1) * 5
        if score > best_score:
            best_score = score
            best = iso

    # When no positive label cue was found anywhere in the document,
    # fall back to the earliest plausible numeric/month-name match —
    # better than blank for simple receipts with no labels.
    if best_score < 0 and not issue_label_spans and not generic_label_spans:
        candidates.sort(key=lambda c: c[0])
        return candidates[0][1]
    return best or ""


# Keep _to_iso_date as a small back-compat helper used by tests.
def _to_iso_date(date_value: str) -> str:
    date_value = date_value.strip()
    for fmt in ("%d.%m.%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(date_value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


# ---------------------------------------------------------------------------
# Money helpers
# ---------------------------------------------------------------------------

def _parse_money(value: str) -> float | None:
    cleaned = value.replace(" ", "").replace("\u00a0", "")
    cleaned = cleaned.replace(",", ".")
    cleaned = re.sub(r"[^0-9.]", "", cleaned)
    if cleaned.count(".") > 1:
        # Keep last decimal separator and strip older ones (e.g. 1.234.56)
        left, right = cleaned.rsplit(".", 1)
        cleaned = left.replace(".", "") + "." + right
    try:
        return float(cleaned)
    except ValueError:
        return None


# Currency sniff: which currency token (if any) is dominant in the text.
_CURRENCY_TOKENS = [
    ("BGN", re.compile(r"\bBGN\b|лв\.?", re.IGNORECASE)),
    ("EUR", re.compile(r"\bEUR\b|€|евро", re.IGNORECASE)),
    ("USD", re.compile(r"\bUSD\b|US\$|\$|US\s?\$", re.IGNORECASE)),
    ("GBP", re.compile(r"\bGBP\b|£")),
    ("CNY", re.compile(r"\bCNY\b|\bRMB\b|元|人民币")),
    ("KRW", re.compile(r"\bKRW\b|₩")),
    ("JPY", re.compile(r"\bJPY\b|¥|円")),
]


def _sniff_currency(text: str, default: str = "BGN") -> str:
    counts: dict[str, int] = {}
    for code, rx in _CURRENCY_TOKENS:
        counts[code] = len(rx.findall(text))
    best = max(counts.items(), key=lambda kv: kv[1])
    return best[0] if best[1] > 0 else default


# Multi-locale gross / VAT / net label patterns.
# Each entry: (label_regex, capture_group_for_amount)
_GROSS_LABELS = [
    # Bulgarian
    "общо\\s+за\\s+плащане", "сума\\s+за\\s+плащане", "крайна\\s+сума",
    "сума\\s+за\\s+плащане", "общо",
    # English
    "total\\s+due", "grand\\s+total", "amount\\s+due", "total\\s+amount",
    "total",
    # German
    "gesamtbetrag", "gesamtsumme", "rechnungsbetrag", "endbetrag",
    "zu\\s+zahlen",
    # French
    "total\\s+ttc", "montant\\s+total", "à\\s+payer", "total\\s+à\\s+régler",
    # Spanish
    "importe\\s+total", "total\\s+a\\s+pagar", "total",
    # Italian
    "totale\\s+fattura", "totale", "importo\\s+totale",
    # Russian
    "итого\\s+к\\s+оплате", "итого", "всего",
    # CJK
    "合\\s*计", "总\\s*计", "총\\s*합계", "合計",
]
_VAT_LABELS = [
    "ддс", "vat", "mwst", "iva", "tva", "ндс", "增值税", "부가세", "ust",
]
_NET_LABELS = [
    "нетна(?:\\s+стойност)?", "данъчна\\s+основа",
    "net\\s+amount", "subtotal", "net",
    "netto", "nettobetrag",
    "base\\s+imponible",
    "imponibile",
    "小\\s*计", "소\\s*계",
]

_AMOUNT_AFTER_LABEL_RE = (
    r"\s*[:\-]?\s*"
    r"(?:[A-ZА-Я$€£¥₩元]{0,4}\s*)?"
    r"([0-9][0-9 \u00a0,.\u2009]*[0-9])"
    r"\s*(?:%|\.|лв\.?|BGN|EUR|€|USD|US\$|\$|GBP|£|RMB|元|CNY|KRW|₩|JPY|¥)?"
)


def _label_matches(text: str, labels: list[str]):
    pattern = re.compile(
        r"(?i)\b(?:" + "|".join(labels) + r")\b" + _AMOUNT_AFTER_LABEL_RE,
        re.IGNORECASE | re.UNICODE,
    )
    for m in pattern.finditer(text):
        amt = _parse_money(m.group(1))
        if amt is not None and amt > 0:
            yield (m.start(), amt, m.group(0))


def _choose_gross_amount(text: str) -> tuple[float | None, float | None, float | None]:
    """Return (gross, vat, net) — any may be None. Sanity-check net+vat≈gross.

    The "best" gross is picked by these rules, in order:
    - the LARGEST amount appearing right after a gross-total label
      (intentional: invoices commonly repeat the total in BGN and EUR — we
      keep the larger because BGN > EUR for the same row in BG invoices,
      but the reverse holds for non-BG invoices; further refinement uses
      currency hints downstream),
    - else the largest amount near a VAT label + net label (compute total),
    - else None.
    """
    gross_candidates = list(_label_matches(text, _GROSS_LABELS))
    vat_candidates = list(_label_matches(text, _VAT_LABELS))
    net_candidates = list(_label_matches(text, _NET_LABELS))

    gross = max((c[1] for c in gross_candidates), default=None)
    vat = max((c[1] for c in vat_candidates), default=None)
    net = max((c[1] for c in net_candidates), default=None)

    if gross is None and net is not None and vat is not None:
        gross = round(net + vat, 2)

    return gross, vat, net


def extract_pdf_text(file_path: Path) -> tuple[str, str]:
    """Return (text, backend_used). backend_used is empty if extraction fails."""
    if fitz is not None:
        try:
            chunks: list[str] = []
            with fitz.open(file_path) as doc:
                for page in doc:
                    chunks.append(page.get_text("text"))
            text = "\n".join(chunks)
            if text.strip():
                return text, "PyMuPDF"
        except Exception:
            pass

    if PdfReader is not None:
        try:
            reader = PdfReader(str(file_path))
            chunks = [page.extract_text() or "" for page in reader.pages]
            text = "\n".join(chunks)
            if text.strip():
                return text, "pypdf"
        except Exception:
            pass

    try:
        proc = subprocess.run(
            ["pdftotext", "-layout", str(file_path), "-"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout, "pdftotext"
    except FileNotFoundError:
        pass

    return "", ""


def parse_invoice_fields_from_text(text: str) -> dict[str, object]:
    """Extract invoice number/date/supplier/gross amount from BG/EN invoice text."""
    data: dict[str, object] = {
        "Supplier/Customer": "",
        "Invoice Number": "",
        "Invoice Date": "",
        "Gross Amount": None,
        "VAT Amount": None,
        "Net Amount": None,
        "Currency": "",
    }

    if not text:
        return data

    text = _normalize_digits(text)
    normalized_text = _normalize_space(text)

    supplier_patterns = [
        # "Doctor: NAME" or "Supplier: NAME" with colon/dash (strict)
        r"(?:Доставчик|Supplier)\s*[:\-]\s*([^\n\r|]{3,120})",
        r"(?:Издател|Продавач)\s*[:\-]\s*([^\n\r|]{3,120})",
        # Loose: BG invoices often have "Клиент X     Доставчик Y" with spaces only
        r"Доставчик\s+([^\n\r|]{3,120})",
        # All-caps name followed by company suffix
        r"^(?:[A-ZА-Я][A-ZА-Я0-9\-\s\.,]{3,120})(?:\s+(?:ООД|ЕООД|АД|ЕТ|Ltd\.?|LLC))",
    ]
    # Header/label words that indicate the regex captured a layout artifact
    # rather than a real supplier name.
    bad_supplier_words = {
        "billed", "payment", "status", "account", "balance", "total", "due",
        "subtotal", "vat", "invoice", "bill", "paid", "credit", "debit",
        "amount", "tax", "сума", "плащане", "обща", "междинна",
        # Column-header words from BG two-column layouts
        "име", "получател", "клиент", "адрес", "ид.№", "мол", "еик/егн",
    }
    for pattern in supplier_patterns:
        m = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
        if m:
            supplier = _normalize_space(m.group(1) if m.lastindex else m.group(0))
            # Trim at the next field label that often follows the supplier
            # name on the same line (BG/EN invoices, two-column layouts).
            supplier = re.split(
                r"\s+(?:Град|Адрес|ЕИК|ЕГН|Ид\.?\s*№|МОЛ|IBAN|Банка|BIC|VAT|TIN|Tel\.?|Phone|Email)\b",
                supplier,
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0]
            supplier = supplier.strip(" .,-")
            if len(supplier) < 3 or len(supplier) > 80:
                continue
            tokens = {t.lower().strip(".,") for t in supplier.split()}
            if tokens & bad_supplier_words:
                continue
            data["Supplier/Customer"] = supplier
            break

    # Words that may appear between "Фактура"/"Ф-ра" and the actual number
    # (e.g. "Оригинал", "Копие", "Original", "Copy") — skip them when matching.
    inv_skip_words = {
        "оригинал", "копие", "дубликат",
        "original", "copy", "duplicate",
        "no", "n", "номер", "number",
    }
    inv_no_patterns = [
        # "№ 0000000058 / 10.03.2026" — invoice-number-and-date header
        # (e.g. e-Docs.bg layout). Capture only the number part.
        r"№\s*([0-9][\w/\-]{2,39})\s*[/\-]\s*\d{1,4}[./\-]\d{1,2}[./\-]\d{1,4}",
        # Look ahead up to ~40 chars after the trigger and capture the first
        # token that contains at least one digit. This skips qualifiers like
        # "Оригинал"/"Копие" that appear before the real number.
        r"(?:Фактура|Ф-ра|Invoice)[^\n\r]{0,40}?(?<![\w/-])([A-Za-zА-Яа-я0-9][A-Za-zА-Яа-я0-9\-/]{2,39})(?![\w/-])",
        r"(?:Номер|№)\s*[:\-]?\s*(?<![\w/-])([A-Za-zА-Яа-я0-9][A-Za-zА-Яа-я0-9\-/]{2,39})(?![\w/-])",
    ]
    for pattern in inv_no_patterns:
        for m in re.finditer(pattern, normalized_text, flags=re.IGNORECASE):
            candidate = m.group(1).strip()
            if candidate.lower() in inv_skip_words:
                continue
            if not re.search(r"\d", candidate):
                continue
            data["Invoice Number"] = candidate
            break
        if data["Invoice Number"]:
            break

    # Multi-locale date — uses the offset-aware scorer over RAW text (not
    # the single-line normalised form) so top/bottom/proximity heuristics
    # work as intended.
    chosen_date = _choose_invoice_date(text)
    if chosen_date:
        data["Invoice Date"] = chosen_date

    # Multi-locale gross / VAT / net.
    gross, vat, net = _choose_gross_amount(text)
    if gross is not None and gross > 0:
        data["Gross Amount"] = round(gross, 2)
    if vat is not None and vat > 0:
        data["VAT Amount"] = round(vat, 2)
    if net is not None and net > 0:
        data["Net Amount"] = round(net, 2)

    data["Currency"] = _sniff_currency(text, default="")

    return data


XLSX_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
XLSX_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
XLSX_CONTENT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
XLSX_RELS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def _col_letter(col_idx: int) -> str:
    """Convert 0-based column index to Excel column letter (A, B, ..., Z, AA, ...)."""
    result = ""
    idx = col_idx
    while True:
        result = chr(65 + idx % 26) + result
        idx = idx // 26 - 1
        if idx < 0:
            break
    return result


def read_xlsx_headers(template_path: Path) -> list[str]:
    """Read first-row headers from an xlsx template using only stdlib."""
    ns = {"ns": XLSX_NS}
    with zipfile.ZipFile(template_path, "r") as zf:
        # Try shared strings first
        strings: list[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            tree = ET.parse(zf.open("xl/sharedStrings.xml"))
            for si in tree.findall(".//ns:si", ns):
                t_el = si.find("ns:t", ns)
                strings.append(t_el.text if t_el is not None and t_el.text else "")

        tree = ET.parse(zf.open("xl/worksheets/sheet1.xml"))
        row1 = tree.find(".//ns:sheetData/ns:row", ns)
        if row1 is None:
            raise ValueError("Template has no rows / Шаблонът няма редове")

        headers: list[str] = []
        for c in row1:
            t_attr = c.get("t", "")
            # Inline string
            if t_attr == "inlineStr":
                is_el = c.find("ns:is/ns:t", ns)
                headers.append(is_el.text if is_el is not None and is_el.text else "")
            # Shared string
            elif t_attr == "s":
                v_el = c.find("ns:v", ns)
                if v_el is not None and v_el.text:
                    headers.append(strings[int(v_el.text)])
                else:
                    headers.append("")
            # Plain value
            else:
                v_el = c.find("ns:v", ns)
                headers.append(v_el.text if v_el is not None and v_el.text else "")
    return headers


def write_xlsx(output_path: Path, headers: list[str], rows: list[list[object]]) -> None:
    """Write a minimal xlsx file with headers and data rows using only stdlib."""
    # Collect all unique strings
    all_strings: list[str] = []
    string_index: dict[str, int] = {}
    for h in headers:
        if h not in string_index:
            string_index[h] = len(all_strings)
            all_strings.append(h)
    for row in rows:
        for val in row:
            if isinstance(val, str) and val not in string_index:
                string_index[val] = len(all_strings)
                all_strings.append(val)

    # Build sharedStrings.xml
    ss_root = ET.Element("sst", xmlns=XLSX_NS, count=str(len(all_strings)), uniqueCount=str(len(all_strings)))
    for s in all_strings:
        si = ET.SubElement(ss_root, "si")
        t = ET.SubElement(si, "t")
        t.text = s

    # Build sheet1.xml
    ws_root = ET.Element("worksheet", xmlns=XLSX_NS)
    sd = ET.SubElement(ws_root, "sheetData")

    # Header row
    r1 = ET.SubElement(sd, "row", r="1")
    for ci, h in enumerate(headers):
        c = ET.SubElement(r1, "c", r=f"{_col_letter(ci)}1", t="s")
        v = ET.SubElement(c, "v")
        v.text = str(string_index[h])

    # Data rows
    for ri, row in enumerate(rows, start=2):
        r_el = ET.SubElement(sd, "row", r=str(ri))
        for ci, val in enumerate(row):
            ref = f"{_col_letter(ci)}{ri}"
            if isinstance(val, (int, float)):
                c = ET.SubElement(r_el, "c", r=ref)
                v = ET.SubElement(c, "v")
                v.text = str(val)
            else:
                s = str(val) if val is not None else ""
                if s not in string_index:
                    string_index[s] = len(all_strings)
                    all_strings.append(s)
                    si = ET.SubElement(ss_root, "si")
                    t = ET.SubElement(si, "t")
                    t.text = s
                    ss_root.set("count", str(len(all_strings)))
                    ss_root.set("uniqueCount", str(len(all_strings)))
                c = ET.SubElement(r_el, "c", r=ref, t="s")
                v = ET.SubElement(c, "v")
                v.text = str(string_index[s])

    # Build minimal xlsx ZIP
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Types xmlns="{XLSX_CONTENT_NS}">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
        '</Types>'
    )

    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{XLSX_RELS_NS}">'
        f'<Relationship Id="rId1" Type="{XLSX_REL_NS}/officeDocument" Target="xl/workbook.xml"/>'
        '</Relationships>'
    )

    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<workbook xmlns="{XLSX_NS}" xmlns:r="{XLSX_REL_NS}">'
        '<sheets><sheet name="Extracted" sheetId="1" r:id="rId1"/></sheets>'
        '</workbook>'
    )

    wb_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{XLSX_RELS_NS}">'
        f'<Relationship Id="rId1" Type="{XLSX_REL_NS}/worksheet" Target="worksheets/sheet1.xml"/>'
        f'<Relationship Id="rId2" Type="{XLSX_REL_NS}/sharedStrings" Target="sharedStrings.xml"/>'
        '</Relationships>'
    )

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("xl/workbook.xml", workbook)
        zf.writestr("xl/_rels/workbook.xml.rels", wb_rels)
        zf.writestr(
            "xl/worksheets/sheet1.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            + ET.tostring(ws_root, encoding="unicode"),
        )
        zf.writestr(
            "xl/sharedStrings.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            + ET.tostring(ss_root, encoding="unicode"),
        )


def resolve_column_map(headers: list[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    normalized_headers = {h.strip().lower(): idx for idx, h in enumerate(headers)}

    aliases = {
        "Client": ["client"],
        "File Name": ["file name"],
        "Document Type": ["document type", "document type (invoice/receipt)"],
        "Supplier/Customer": ["supplier/customer"],
        "Invoice Number": ["invoice number"],
        "Invoice Date": ["invoice date"],
        "Net Amount": ["net amount"],
        "VAT Amount": ["vat amount"],
        "Gross Amount": ["gross amount"],
        "Currency": ["currency"],
        "Confidence Score": ["confidence score"],
        "Mandatory Review": ["mandatory review", "mandatory check", "manual review required"],
        "Notes": ["notes"],
    }

    for key, names in aliases.items():
        found = None
        for name in names:
            if name in normalized_headers:
                found = normalized_headers[name]
                break
        if found is not None:
            result[key] = found

    required = [
        "Client",
        "File Name",
        "Document Type",
        "Supplier/Customer",
        "Invoice Number",
        "Invoice Date",
        "Net Amount",
        "VAT Amount",
        "Gross Amount",
        "Currency",
        "Confidence Score",
        "Notes",
    ]
    missing = [k for k in required if k not in result]
    if missing:
        raise ValueError("Template is missing required column(s) / Шаблонът няма задължителни колони: " + ", ".join(missing))

    return result


def build_row_values(file_path: Path, client_default: str) -> dict[str, object]:
    file_name = file_path.name
    stem = Path(file_name).stem
    match = FILENAME_PATTERN.match(stem)

    if not match:
        return {
            "Client": client_default,
            "File Name": file_name,
            "Document Type": "Other",
            "Supplier/Customer": "Unknown",
            "Invoice Number": "",
            "Invoice Date": "",
            "Net Amount": "",
            "VAT Amount": "",
            "Gross Amount": "",
            "Currency": "EUR",
            "Confidence Score": 0.30,
            "Notes": (
                "Filename-only extraction / Извличане само по името на файла. "
                "Filename pattern mismatch / Несъответствие с шаблона на име; "
                "manual review required / нужна е ръчна проверка."
            ),
        }

    client = match.group("client")
    date_str = match.group("date")
    dtype = normalize_dtype(match.group("dtype"))
    counterparty = match.group("counterparty")
    amount = parse_amount(match.group("amount"))

    invoice_date = "" if date_str == "UNKNOWNDATE" else date_str
    invoice_number = ""
    mandatory_review = "No"
    extracted_vat: object = ""
    extracted_net: object = ""
    extracted_currency = ""
    matched_class_id: int | None = None
    matched_class_score = 0
    source_note_prefix = "Filename-only extraction / Извличане само по името на файла."
    notes: list[str] = []
    if dtype == "Receipt":
        notes.append("Receipt may not have invoice number / Касовият бон може да няма номер на фактура.")
    if dtype not in {"Invoice", "Receipt"}:
        notes.append("Document type is not invoice/receipt / Типът не е фактура/касов бон.")

    if counterparty.lower() == "unknown":
        notes.append("Missing supplier/customer in filename / Липсва доставчик/клиент в името.")

    if amount is None:
        notes.append("Missing or invalid amount in filename / Липсваща или невалидна сума в името.")

    confidence = 0.80
    if invoice_date == "":
        confidence -= 0.20
        notes.append("Missing date in filename / Липсваща дата в името.")
    if counterparty.lower() == "unknown":
        confidence -= 0.20
    if amount is None:
        confidence -= 0.20
    if dtype not in {"Invoice", "Receipt"}:
        confidence = min(confidence, 0.40)

    gross_amount = amount if amount is not None else ""

    ext = file_path.suffix.lower()

    if dtype in {"Invoice", "Receipt"} and ext in IMAGE_EXTENSIONS:
        mandatory_review = "Yes"
        source_note_prefix = "Image-based extraction / Извличане от изображение."
        notes.append(
            "MANDATORY CHECK (image source): verify supplier, date, number, VAT, and total / "
            "ЗАДЪЛЖИТЕЛНА ПРОВЕРКА (изображение): проверете доставчик, дата, номер, ДДС и обща сума."
        )
        confidence = min(confidence, 0.55)

    if dtype in {"Invoice", "Receipt"} and ext == ".pdf":
        pdf_text, backend = extract_pdf_text(file_path)
        if pdf_text:
            extracted = parse_invoice_fields_from_text(pdf_text)

            # Best-effort: ask the SQLite pattern store for a class-specific
            # extraction, then merge — class patterns win where they fire,
            # generic regexes fill the rest.
            class_overrides: dict[str, str] = {}
            client_record: dict | None = None
            try:
                if pattern_store is not None:
                    rules_dir = file_path.parents[3] / "Rules"
                    db_path = rules_dir / "patterns.sqlite"
                    if not db_path.exists():
                        try:
                            pattern_store.bootstrap(rules_dir)
                        except Exception:
                            pass
                    if db_path.exists():
                        client_record = pattern_store.get_client(db_path, client or client_default)
                        matched_class_id, matched_class_score = pattern_store.match_class(db_path, pdf_text)
                        if matched_class_id is not None:
                            class_overrides = pattern_store.apply_class_patterns(
                                db_path, matched_class_id, pdf_text
                            )
            except Exception as exc:  # pragma: no cover — best-effort
                notes.append(f"pattern_store unavailable: {exc}")

            # Apply class-specific overrides where they exist; otherwise
            # fall back to the generic extractor's results.
            cls_date = (class_overrides.get("date") or "").strip()
            cls_iso = _to_iso_date(cls_date) if cls_date else ""
            if cls_iso:
                extracted["Invoice Date"] = cls_iso
            cls_number = (class_overrides.get("number") or "").strip()
            if cls_number:
                extracted["Invoice Number"] = cls_number
            cls_supplier = (class_overrides.get("supplier") or "").strip()
            if cls_supplier:
                extracted["Supplier/Customer"] = cls_supplier

            found_supplier = str(extracted.get("Supplier/Customer") or "").strip()
            found_inv_no = str(extracted.get("Invoice Number") or "").strip()
            found_date = str(extracted.get("Invoice Date") or "").strip()
            found_amount = extracted.get("Gross Amount")
            extracted_vat = extracted.get("VAT Amount") or ""
            extracted_net = extracted.get("Net Amount") or ""
            extracted_currency = str(extracted.get("Currency") or "").strip()

            if found_supplier:
                # Prefer filename counterparty when it's meaningful;
                # only override with PDF text when filename has no useful name.
                if not counterparty or counterparty.lower() in {"unknown", ""}:
                    counterparty = found_supplier
            if found_inv_no:
                invoice_number = found_inv_no
            if found_date:
                invoice_date = found_date
            if isinstance(found_amount, float):
                # Sanity check: if filename had a parseable amount, the PDF amount
                # should not be drastically smaller (likely a stray "1" or qty).
                # Reject PDF amount when it's <10% of filename amount.
                if isinstance(gross_amount, float) and gross_amount > 0 and \
                        found_amount < gross_amount * 0.1:
                    notes.append(
                        f"PDF amount {found_amount} ignored (filename {gross_amount} preferred) / "
                        f"PDF сума {found_amount} пренебрегната."
                    )
                else:
                    gross_amount = found_amount

            # Buyer verification + counterparty memory (best-effort).
            try:
                if pattern_store is not None and client_record is not None:
                    db_path = file_path.parents[3] / "Rules" / "patterns.sqlite"
                    verdict = pattern_store.verify_buyer(
                        db_path, client or client_default, pdf_text
                    )
                    if verdict.get("mismatch_with") and not verdict.get("match"):
                        mandatory_review = "Yes"
                        notes.append(
                            "Buyer block matches another client folder ("
                            + ",".join(verdict["mismatch_with"])
                            + ") — possible misrouting / Възможно грешно насочване."
                        )
                    cp = pattern_store.match_counterparty(
                        db_path, client_record["id"], supplier_name=found_supplier
                    )
                    if cp and cp.get("suggested_account"):
                        notes.append(
                            f"Suggested account: {cp['suggested_account']} (seen {cp['seen_count']}x)"
                        )
                    elif found_supplier:
                        pattern_store.upsert_counterparty(
                            db_path, client_record["id"], found_supplier
                        )
            except Exception as exc:  # pragma: no cover — best-effort
                notes.append(f"buyer-check skipped: {exc}")

            if matched_class_id is not None:
                notes.append(f"Class match #{matched_class_id} score={matched_class_score}")

            notes.append(
                f"PDF text parsed ({backend}) / Обработен PDF текст ({backend})."
            )
            source_note_prefix = "Filename + PDF text extraction / Извличане по име на файл + PDF текст."
            confidence = min(0.98, confidence + 0.10)

            # High-confidence learning hook (best-effort).
            try:
                if (
                    pattern_store is not None
                    and confidence >= pattern_store.LEARN_THRESHOLD
                    and matched_class_id is None
                ):
                    db_path = file_path.parents[3] / "Rules" / "patterns.sqlite"
                    pattern_store.learn_from(
                        db_path,
                        file_name=file_name,
                        text=pdf_text,
                        fields=extracted,
                        confidence=confidence,
                        matched_class_id=matched_class_id,
                    )
            except Exception:
                pass
        else:
            notes.append(
                "PDF text extraction unavailable/empty / Липсва извличане на текст от PDF или текстът е празен."
            )

    # Final ambiguity check: flag for review if date is still unknown after
    # both filename and PDF parsing — Delta Pro accounting date would default
    # to today, which is almost always wrong.
    if not invoice_date:
        mandatory_review = "Yes"
        if "Date ambiguous" not in " ".join(notes):
            notes.append(
                "Date ambiguous / unresolved — manual review required / "
                "Двусмислена/неустановена дата — нужна е ръчна проверка."
            )

    # Same for the gross amount: if neither filename nor PDF text yielded a
    # usable positive number, the entry is incomplete and must be reviewed.
    if not isinstance(gross_amount, (int, float)) or gross_amount <= 0:
        mandatory_review = "Yes"
        notes.append(
            "Amount ambiguous / unresolved — manual review required / "
            "Двусмислена/неустановена сума — нужна е ръчна проверка."
        )

    return {
        "Client": client or client_default,
        "File Name": file_name,
        "Document Type": dtype,
        "Supplier/Customer": counterparty,
        "Invoice Number": invoice_number,
        "Invoice Date": invoice_date,
        "Net Amount": extracted_net,
        "VAT Amount": extracted_vat,
        "Gross Amount": gross_amount,
        "Currency": extracted_currency or "EUR",
        "Confidence Score": max(0.0, round(confidence, 2)),
        "Mandatory Review": mandatory_review,
        "Notes": source_note_prefix + " " + " ".join(notes).strip(),
    }


def run(base_dir: Path, client_name: str) -> int:
    client_dir = base_dir / "Clients" / client_name
    processed_dir = client_dir / "01_Processed"
    review_dir = client_dir / "02_Review"
    templates_dir = base_dir / "Templates"
    template_file = templates_dir / "extracted_invoices.xlsx"
    output_file = review_dir / "extracted_invoices.xlsx"
    log_file = base_dir / "Logs" / "run_log.txt"

    required_paths = [processed_dir, review_dir, template_file, log_file.parent]
    missing = [p for p in required_paths if not p.exists()]
    if missing:
        raise FileNotFoundError("Missing required path(s) / Липсват задължителни пътища: " + ", ".join(str(m) for m in missing))

    ensure_log_header(log_file)

    if output_file.exists():
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = output_file.with_name(f"extracted_invoices_BACKUP_{ts}.xlsx")
        shutil.copy2(output_file, backup)
        write_log(log_file, f"{now_str()} Backup / Резервно копие: {output_file.name} -> {backup.name}")

    headers = read_xlsx_headers(template_file)
    col_map = resolve_column_map([str(h) for h in headers])
    if "Mandatory Review" not in col_map:
        write_log(
            log_file,
            (
                f"{now_str()} Warning / Предупреждение: Template missing 'Mandatory Review' column; "
                "processing continues without that field / Шаблонът няма колона 'Mandatory Review'; "
                "обработката продължава без това поле."
            ),
        )

    files = [p for p in processed_dir.iterdir() if p.is_file()]
    files.sort(key=lambda p: p.name.lower())

    extracted_count = 0
    all_rows: list[list[object]] = []
    for file_path in files:
        try:
            row_data = build_row_values(file_path, client_name)
            if row_data["Document Type"] not in {"Invoice", "Receipt"}:
                continue
            if file_path.suffix.lower() not in SUPPORTED_INVOICE_EXTENSIONS:
                write_log(
                    log_file,
                    f"{now_str()} Skipped unsupported extraction format / Пропуснат неподдържан формат за извличане: {file_path.name}",
                )
                continue

            row: list[object] = ["" for _ in headers]
            for key, value in row_data.items():
                if key not in col_map:
                    continue
                idx = col_map[key]
                row[idx] = value

            all_rows.append(row)
            extracted_count += 1

            write_log(log_file, f"{now_str()} Extracted invoice row / Извлечен ред от {file_path.name} -> {output_file.name}")
        except Exception as exc:
            write_log(
                log_file,
                f"{now_str()} ERROR extracting / ГРЕШКА при извличане на {file_path.name}: {exc}",
            )

    try:
        write_xlsx(output_file, headers, all_rows)
    except PermissionError as exc:
        raise PermissionError(
            f"Cannot save {output_file} / Не може да се запише файлът. "
            "It may be open in Excel / Файлът може да е отворен в Excel."
        ) from exc
    write_log(log_file, f"{now_str()} Invoice extraction completed / Извличането приключи: {extracted_count} row(s)/реда за {client_name}")
    return extracted_count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Accounting-AI MVP invoice extraction runner / Стартиране на извличането на фактури")
    parser.add_argument(
        "--base-dir",
        default=".",
        help="Path to Accounting-AI root folder / Път до основната папка (по подразбиране: текущата)",
    )
    parser.add_argument(
        "--client",
        default="Client_A",
        help="Client folder name under Clients/ / Име на клиентска папка в Clients/ (по подразбиране: Client_A)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    base_dir = Path(args.base_dir).resolve()

    if args.client.strip() == "":
        raise ValueError("--client cannot be empty / --client не може да е празно")

    count = run(base_dir=base_dir, client_name=args.client)
    print(f"Extracted / Извлечени: {count} invoice/receipt row(s) за {args.client}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
