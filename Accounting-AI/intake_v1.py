#!/usr/bin/env python3
"""MVP v1.0 intake flow / входящ поток: classify, rename, move, and log files.

Scope intentionally limited to:
- scanning one client 00_Incoming folder
- simple classification by extension and filename keywords
- deterministic safe renaming
- moving files to 01_Processed or 02_Review
- logging every action to Logs/run_log.txt
"""

from __future__ import annotations

import argparse
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


KNOWN_DOC_TYPES = {"invoice", "receipt", "bank", "other"}
ALLOWED_EXTENSIONS = {
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
    ".tif",
    ".tiff",
    ".bmp",
    ".webp",
    ".csv",
    ".xlsx",
    ".xls",
}


@dataclass
class IntakeResult:
    source: Path
    destination: Path
    doc_type: str
    reason: str


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def sanitize_token(value: str) -> str:
    value = value.strip()
    value = re.sub(r"\s+", "-", value, flags=re.UNICODE)
    value = re.sub(r"[^\w.-]", "", value, flags=re.UNICODE)
    value = value.strip("-_.")
    return value or "Unknown"


def detect_doc_type(file_name: str, ext: str) -> tuple[str, str]:
    lower = file_name.lower()

    bank_keywords = [
        "bank", "statement", "extract", "izvlechenie",
        "banka", "bankovo", "konto", "iban", "transak",
    ]
    invoice_keywords = [
        "invoice", "inv", "factura", "faktura", "fakt",
        "bill", "danachna",
    ]
    receipt_keywords = [
        "receipt", "kasov", "bon", "slip", "sticker",
        "касов", "бон",
    ]

    if ext in {".csv", ".xlsx", ".xls"}:
        return "bank", "extension"

    if any(k in lower for k in bank_keywords):
        return "bank", "name"

    if any(k in lower for k in invoice_keywords):
        return "invoice", "name"

    if any(k in lower for k in receipt_keywords):
        return "receipt", "name"

    if ext in {".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}:
        return "other", "unrecognized-document"

    return "other", "unsupported-extension"


def detect_date(file_stem: str) -> str:
    patterns = [
        (r"(?<!\d)(20\d{2})[-_.](\d{2})[-_.](\d{2})(?!\d)", "ymd_sep"),
        (r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)", "ymd_compact"),
        (r"(?<!\d)(\d{2})[.-](\d{2})[.-](20\d{2})(?!\d)", "dmy_sep"),
    ]

    for pattern, pattern_type in patterns:
        match = re.search(pattern, file_stem)
        if not match:
            continue
        try:
            if pattern_type in {"ymd_sep", "ymd_compact"}:
                y, m, d = match.groups()
            else:
                d, m, y = match.groups()
            dt = datetime(int(y), int(m), int(d))
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue

    return "UNKNOWNDATE"


def detect_amount(file_stem: str) -> str:
    # Accept common formats like 124.50 or 124,50 from filename text.
    amount_match = re.search(r"(?<!\d)(\d{1,7}(?:[.,]\d{2}))(?!\d)", file_stem)
    if not amount_match:
        return "Unknown"
    return amount_match.group(1).replace(",", ".")


def detect_counterparty(file_stem: str) -> str:
    # Heuristic: choose the first alphabetic token with len >= 3.
    generic_words = {
        "invoice",
        "receipt",
        "bank",
        "statement",
        "extract",
        "factura",
        "faktura",
        "img",
        "scan",
        "document",
        "other",
        # Bulgarian document-type words that are not counterparty names
        "касов",
        "бон",
        "bankovo",
        "banka",
        "izvlechenie",
        "danachna",
    }
    for token in re.split(r"[_\-.\s]+", file_stem):
        token_lower = token.lower()
        if token_lower in generic_words:
            continue
        if re.fullmatch(r"[^\W\d_]{3,}", token, flags=re.UNICODE):
            return token
    return "Unknown"


def build_target_name(client: str, date_str: str, doc_type: str, counterparty: str, amount: str, ext: str) -> str:
    parts = [
        sanitize_token(client),
        sanitize_token(date_str),
        sanitize_token(doc_type.capitalize()),
        sanitize_token(counterparty),
        sanitize_token(amount),
    ]
    return "_".join(parts) + ext.lower()


def unique_destination_path(folder: Path, file_name: str) -> Path:
    candidate = folder / file_name
    if not candidate.exists():
        return candidate

    stem = candidate.stem
    suffix = candidate.suffix
    index = 2
    while True:
        next_candidate = folder / f"{stem}_{index}{suffix}"
        if not next_candidate.exists():
            return next_candidate
        index += 1


def process_file(file_path: Path, client_name: str, processed_dir: Path,
                 review_dir: Path, unsupported_dir: Path) -> IntakeResult:
    ext = file_path.suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        doc_type = "other"
        reason = "unsupported-extension"
    else:
        doc_type, reason = detect_doc_type(file_path.name, ext)

    date_str = detect_date(file_path.stem)
    amount = detect_amount(file_path.stem)
    counterparty = detect_counterparty(file_path.stem)
    target_name = build_target_name(client_name, date_str, doc_type, counterparty, amount, ext)

    if doc_type in {"invoice", "receipt", "bank"}:
        destination_folder = processed_dir
    elif reason == "unsupported-extension":
        destination_folder = unsupported_dir
    else:
        destination_folder = review_dir
    destination = unique_destination_path(destination_folder, target_name)
    return IntakeResult(source=file_path, destination=destination, doc_type=doc_type, reason=reason)


def write_log(log_file: Path, line: str) -> None:
    with log_file.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def ensure_log_header(log_file: Path) -> None:
    if not log_file.exists() or log_file.stat().st_size == 0:
        with log_file.open("a", encoding="utf-8") as fh:
            fh.write("# Accounting AI Run Log / Дневник на изпълнение\n")
            fh.write("# Format / Формат: YYYY-MM-DD HH:MM [Action details / Детайли]\n")


def run(base_dir: Path, client_name: str, dry_run: bool = False) -> int:
    client_dir = base_dir / "Clients" / client_name
    incoming_dir = client_dir / "00_Incoming"
    processed_dir = client_dir / "01_Processed"
    review_dir = client_dir / "02_Review"
    unsupported_dir = client_dir / "04_Unsupported"
    log_file = base_dir / "Logs" / "run_log.txt"

    required_dirs = [incoming_dir, processed_dir, review_dir, log_file.parent]
    missing = [p for p in required_dirs if not p.exists()]
    if missing:
        raise FileNotFoundError("Missing required path(s) / Липсват задължителни пътища: " + ", ".join(str(m) for m in missing))

    unsupported_dir.mkdir(parents=True, exist_ok=True)
    ensure_log_header(log_file)

    files = [p for p in incoming_dir.iterdir() if p.is_file()]
    files.sort(key=lambda p: p.name.lower())

    if not files:
        write_log(log_file, f"{now_str()} No files found / Няма файлове в {incoming_dir}")
        return 0

    for source in files:
        result = process_file(source, client_name, processed_dir, review_dir, unsupported_dir)

        write_log(
            log_file,
            (
                f"{now_str()} Classified {source.name} as {result.doc_type} "
                f"/ Класифициран {source.name} като {result.doc_type} "
                f"(reason/причина={result.reason})"
            ),
        )
        write_log(
            log_file,
            (
                f"{now_str()} Renamed / Преименуван {source.name} -> {result.destination.name}"
            ),
        )

        if dry_run:
            write_log(log_file, f"{now_str()} Dry-run: move skipped / Тестов режим: преместването е пропуснато за {source.name}")
            continue

        shutil.move(str(source), str(result.destination))
        if result.doc_type in {"invoice", "receipt", "bank"}:
            target_bucket = "01_Processed"
        elif result.reason == "unsupported-extension":
            target_bucket = "04_Unsupported"
        else:
            target_bucket = "02_Review"

        write_log(log_file, f"{now_str()} Moved / Преместен в {target_bucket}")

    return len(files)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Accounting-AI MVP intake runner / Стартиране на входящия модул")
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
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log actions without moving files / Записва действията без преместване на файлове",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    base_dir = Path(args.base_dir).resolve()

    if args.client.strip() == "":
        raise ValueError("--client cannot be empty / --client не може да е празно")

    processed_count = run(base_dir=base_dir, client_name=args.client, dry_run=args.dry_run)
    print(f"Processed / Обработени: {processed_count} file(s) за {args.client}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
