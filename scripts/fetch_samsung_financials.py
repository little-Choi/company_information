"""Fetch OpenDART financial statements.

Usage:
    # Samsung Electronics only, all years.
    python scripts/fetch_samsung_financials.py

    # Every listed company except Samsung Electronics, all years.
    python scripts/fetch_samsung_financials.py --all-companies --format json

    # Resume a large all-company run in batches.
    python scripts/fetch_samsung_financials.py --all-companies --offset 0 --limit 100 --format json

    # Fetch only the latest two business years, which is what index.html displays.
    python scripts/fetch_samsung_financials.py --all-companies --recent-years 2 --format json

    # Optionally use an environment variable instead of OPEN_DART_API_KEY below:
    $env:OPEN_DART_API_KEY = "your_40_char_key"  # PowerShell
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
import time
import zipfile
from datetime import date
from pathlib import Path
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen
from xml.etree import ElementTree


FINANCIAL_STATEMENT_API_URL = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
CORP_CODE_API_URL = "https://opendart.fss.or.kr/api/corpCode.xml"
SAMSUNG_ELECTRONICS_CORP_CODE = "00126380"
SAMSUNG_ELECTRONICS_STOCK_CODE = "005930"
DEFAULT_START_YEAR = 2015
MANIFEST_FILE_NAME = "company_financials_manifest.json"

# You can paste your OpenDART API key here for local use.
# Do not commit a real API key to a shared or public repository.
OPEN_DART_API_KEY = ""

REPORT_CODES = {
    "11013": "q1",
    "11012": "half",
    "11014": "q3",
    "11011": "annual",
}

DART_FIELDS = [
    "rcept_no",
    "reprt_code",
    "bsns_year",
    "corp_code",
    "corp_name",
    "stock_code",
    "sj_div",
    "sj_nm",
    "account_id",
    "account_nm",
    "account_detail",
    "thstrm_nm",
    "thstrm_amount",
    "thstrm_add_amount",
    "frmtrm_nm",
    "frmtrm_amount",
    "frmtrm_q_nm",
    "frmtrm_q_amount",
    "frmtrm_add_amount",
    "bfefrmtrm_nm",
    "bfefrmtrm_amount",
    "ord",
    "currency",
]


class OpenDartError(RuntimeError):
    """Raised when OpenDART returns an error response."""

    def __init__(self, message: str, status: Optional[str] = None) -> None:
        super().__init__(message)
        self.status = status


def read_windows_environment_variable(name: str) -> Optional[str]:
    if sys.platform != "win32":
        return None

    try:
        import winreg
    except ImportError:
        return None

    registry_locations = (
        (winreg.HKEY_CURRENT_USER, r"Environment"),
        (
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
        ),
    )
    for root, path in registry_locations:
        try:
            with winreg.OpenKey(root, path) as key:
                value, _ = winreg.QueryValueEx(key, name)
        except FileNotFoundError:
            continue
        if isinstance(value, str) and value:
            return value
    return None


def resolve_api_key(cli_api_key: Optional[str]) -> str:
    return (
        cli_api_key
        or os.getenv("OPEN_DART_API_KEY")
        or read_windows_environment_variable("OPEN_DART_API_KEY")
        or OPEN_DART_API_KEY
    )


def fetch_json_payload(url: str, params: dict[str, str], timeout: int) -> dict[str, Any]:
    request_url = f"{url}?{urlencode(params)}"
    try:
        with urlopen(request_url, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise OpenDartError(f"HTTP error from OpenDART: {exc.code}") from exc
    except URLError as exc:
        raise OpenDartError(f"Network error while calling OpenDART: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise OpenDartError("OpenDART returned invalid JSON.") from exc

    status = payload.get("status")
    if status != "000":
        message = payload.get("message", "unknown error")
        raise OpenDartError(f"OpenDART error {status}: {message}", status=status)
    return payload


def fetch_corporations(api_key: str, timeout: int) -> list[dict[str, str]]:
    params = {"crtfc_key": api_key}
    url = f"{CORP_CODE_API_URL}?{urlencode(params)}"

    try:
        with urlopen(url, timeout=timeout) as response:
            content = response.read()
    except HTTPError as exc:
        raise OpenDartError(f"HTTP error from OpenDART: {exc.code}") from exc
    except URLError as exc:
        raise OpenDartError(f"Network error while calling OpenDART: {exc.reason}") from exc

    if content.lstrip().startswith(b"{"):
        try:
            payload = json.loads(content.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise OpenDartError("OpenDART returned invalid corporation payload.") from exc
        status = payload.get("status")
        message = payload.get("message", "unknown error")
        raise OpenDartError(f"OpenDART error {status}: {message}", status=status)

    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            xml_name = next(name for name in archive.namelist() if name.lower().endswith(".xml"))
            xml_bytes = archive.read(xml_name)
    except (zipfile.BadZipFile, StopIteration, KeyError) as exc:
        raise OpenDartError("OpenDART returned an invalid corporation zip file.") from exc

    root = ElementTree.fromstring(xml_bytes)
    corporations: list[dict[str, str]] = []
    for item in root.findall("list"):
        corp = {
            "corp_code": (item.findtext("corp_code") or "").strip(),
            "corp_name": (item.findtext("corp_name") or "").strip(),
            "stock_code": (item.findtext("stock_code") or "").strip(),
            "modify_date": (item.findtext("modify_date") or "").strip(),
        }
        if corp["corp_code"] and corp["corp_name"]:
            corporations.append(corp)
    return corporations


def fetch_financial_statement(
    api_key: str,
    corp_code: str,
    year: int,
    report_code: str,
    fs_div: str,
    timeout: int,
) -> list[dict[str, Any]]:
    payload = fetch_json_payload(
        FINANCIAL_STATEMENT_API_URL,
        {
            "crtfc_key": api_key,
            "corp_code": corp_code,
            "bsns_year": str(year),
            "reprt_code": report_code,
            "fs_div": fs_div,
        },
        timeout,
    )

    rows = payload.get("list", [])
    if not isinstance(rows, list):
        raise OpenDartError("OpenDART response did not include a list of rows.")
    return rows


def filter_statement(rows: list[dict[str, Any]], statement: Optional[str]) -> list[dict[str, Any]]:
    if statement is None:
        return rows
    return [row for row in rows if row.get("sj_div") == statement]


def write_json(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as file:
        json.dump(rows, file, ensure_ascii=False, indent=2)
        file.write("\n")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    extra_fields = sorted({key for row in rows for key in row} - set(DART_FIELDS))
    fieldnames = DART_FIELDS + extra_fields

    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def resolve_years(recent_years: Optional[int]) -> list[int]:
    end_year = date.today().year - 1
    if recent_years is not None:
        start_year = end_year - recent_years + 1
        return list(range(start_year, end_year + 1))
    return list(range(DEFAULT_START_YEAR, end_year + 1))


def samsung_corporation() -> dict[str, str]:
    return {
        "corp_code": SAMSUNG_ELECTRONICS_CORP_CODE,
        "corp_name": "삼성전자",
        "stock_code": SAMSUNG_ELECTRONICS_STOCK_CODE,
        "modify_date": "",
    }


def corporation_sort_key(corp: dict[str, str]) -> tuple[str, str, str]:
    stock_code = corp.get("stock_code") or "999999"
    return stock_code, corp.get("corp_name", ""), corp.get("corp_code", "")


def select_corporations(api_key: str, args: argparse.Namespace) -> list[dict[str, str]]:
    if args.all_companies:
        corporations = fetch_corporations(api_key, args.timeout)
        if not args.include_unlisted:
            corporations = [corp for corp in corporations if corp.get("stock_code")]
        if not args.include_samsung:
            corporations = [
                corp
                for corp in corporations
                if corp.get("corp_code") != SAMSUNG_ELECTRONICS_CORP_CODE
            ]
        corporations = sorted(corporations, key=corporation_sort_key)
    else:
        corporations = [samsung_corporation()]

    if args.corp_code:
        requested = set(args.corp_code)
        corporations = [corp for corp in corporations if corp.get("corp_code") in requested]

    if args.offset:
        corporations = corporations[args.offset :]
    if args.limit is not None:
        corporations = corporations[: args.limit]
    return corporations


def output_directory(args: argparse.Namespace) -> Path:
    if args.all_companies and args.company_out_dir is None:
        return args.out_dir / "companies"
    return args.company_out_dir or args.out_dir


def company_file_stem(corp: dict[str, str], args: argparse.Namespace) -> str:
    if corp.get("corp_code") == SAMSUNG_ELECTRONICS_CORP_CODE and not args.all_companies:
        company_part = "samsung_electronics"
    else:
        stock_code = corp.get("stock_code") or "unlisted"
        company_part = f"company_{corp['corp_code']}_{stock_code}"

    year_part = "all_years" if args.recent_years is None else f"{args.years[0]}_{args.years[-1]}"
    base_name = f"{company_part}_{year_part}_{REPORT_CODES[args.report_code]}_{args.fs_div}"
    if args.statement:
        base_name += f"_{args.statement}"
    return base_name


def browser_path(path: Path) -> str:
    resolved_path = path.resolve()
    try:
        relative = resolved_path.relative_to(Path.cwd().resolve())
    except ValueError:
        relative = path
    return relative.as_posix()


def primary_output_path(corp: dict[str, str], args: argparse.Namespace) -> Path:
    extension = "csv" if args.format == "csv" else "json"
    return output_directory(args) / f"{company_file_stem(corp, args)}.{extension}"


def manifest_entry(corp: dict[str, str], args: argparse.Namespace) -> dict[str, Any]:
    stock_code = corp.get("stock_code", "")
    stock_part = f" · {stock_code}" if stock_code else ""
    report = REPORT_CODES[args.report_code]
    fs = args.fs_div
    year_value = "all_years" if args.recent_years is None else f"{args.years[0]}-{args.years[-1]}"
    year_label = "전체 연도" if args.recent_years is None else year_value
    return {
        "company": corp.get("corp_name", corp.get("corp_code", "")),
        "corpCode": corp.get("corp_code", ""),
        "stockCode": stock_code,
        "year": year_value,
        "allYears": args.recent_years is None,
        "report": report,
        "fs": fs,
        "label": f"{corp.get('corp_name', '-')}{stock_part} · {year_label} · {report} · {fs}",
        "file": browser_path(primary_output_path(corp, args)),
    }


def load_manifest(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("sources"), list):
        return [item for item in payload["sources"] if isinstance(item, dict)]
    return []


def write_manifest(path: Path, entries: list[dict[str, Any]]) -> None:
    existing = load_manifest(path)
    by_file = {entry.get("file"): entry for entry in existing if entry.get("file")}
    for entry in entries:
        by_file[entry["file"]] = entry

    sources = sorted(
        by_file.values(),
        key=lambda item: (
            str(item.get("company", "")),
            str(item.get("stockCode", "")),
            str(item.get("file", "")),
        ),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump({"sources": sources}, file, ensure_ascii=False, indent=2)
        file.write("\n")


def enrich_rows(rows: list[dict[str, Any]], corp: dict[str, str]) -> list[dict[str, Any]]:
    enriched = []
    for row in rows:
        enriched.append(
            {
                **row,
                "corp_code": row.get("corp_code") or corp["corp_code"],
                "corp_name": row.get("corp_name") or corp["corp_name"],
                "stock_code": row.get("stock_code") or corp.get("stock_code", ""),
            }
        )
    return enriched


def fetch_company_rows(
    api_key: str,
    corp: dict[str, str],
    args: argparse.Namespace,
) -> tuple[list[dict[str, Any]], list[int]]:
    rows: list[dict[str, Any]] = []
    skipped_years: list[int] = []
    for year in args.years:
        try:
            year_rows = fetch_financial_statement(
                api_key=api_key,
                corp_code=corp["corp_code"],
                year=year,
                report_code=args.report_code,
                fs_div=args.fs_div,
                timeout=args.timeout,
            )
        except OpenDartError as exc:
            if exc.status == "013":
                skipped_years.append(year)
                continue
            raise

        year_rows = filter_statement(year_rows, args.statement)
        if not year_rows:
            skipped_years.append(year)
            continue
        rows.extend(enrich_rows(year_rows, corp))

        if args.sleep:
            time.sleep(args.sleep)

    return rows, skipped_years


def write_company_outputs(
    corp: dict[str, str],
    rows: list[dict[str, Any]],
    args: argparse.Namespace,
) -> list[Path]:
    directory = output_directory(args)
    directory.mkdir(parents=True, exist_ok=True)
    base_name = company_file_stem(corp, args)

    written: list[Path] = []
    if args.format in ("json", "both"):
        path = directory / f"{base_name}.json"
        write_json(path, rows)
        written.append(path)
    if args.format in ("csv", "both"):
        path = directory / f"{base_name}.csv"
        write_csv(path, rows)
        written.append(path)
    return written


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch all available OpenDART financial statement years."
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="OpenDART API key. Overrides the environment variable and code setting.",
    )
    parser.add_argument(
        "--all-companies",
        action="store_true",
        help="Fetch every listed company except Samsung Electronics by default.",
    )
    parser.add_argument(
        "--include-samsung",
        action="store_true",
        help="Include Samsung Electronics when --all-companies is used.",
    )
    parser.add_argument(
        "--include-unlisted",
        action="store_true",
        help="Include companies without stock codes. This can be very large.",
    )
    parser.add_argument(
        "--corp-code",
        action="append",
        help="Restrict fetching to a corporation code. Can be passed multiple times.",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Skip this many selected companies. Useful for batching large runs.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Fetch at most this many selected companies. Useful for batching large runs.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Refetch and overwrite files that already exist.",
    )
    parser.add_argument(
        "--recent-years",
        type=int,
        default=None,
        help="Fetch only the latest N business years instead of every year since 2015.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print selected companies without fetching financial statements.",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.0,
        help="Seconds to wait after each successful year request.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="HTTP timeout in seconds.",
    )
    parser.add_argument(
        "--report-code",
        choices=sorted(REPORT_CODES),
        default="11011",
        help="11013=q1, 11012=half, 11014=q3, 11011=annual.",
    )
    parser.add_argument(
        "--fs-div",
        choices=("CFS", "OFS"),
        default="CFS",
        help="CFS=consolidated, OFS=separate financial statements.",
    )
    parser.add_argument(
        "--statement",
        choices=("BS", "IS", "CIS", "CF", "SCE"),
        help="Optional statement filter: BS, IS, CIS, CF, or SCE.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("dart_output"),
        help="Root directory for output files and manifest.",
    )
    parser.add_argument(
        "--company-out-dir",
        type=Path,
        default=None,
        help="Directory for per-company output files. Defaults to dart_output/companies for --all-companies.",
    )
    parser.add_argument(
        "--format",
        choices=("json", "csv", "both"),
        default="both",
        help="Output format.",
    )
    args = parser.parse_args()
    if args.offset < 0:
        parser.error("--offset must be zero or greater.")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be one or greater.")
    if args.recent_years is not None and args.recent_years < 1:
        parser.error("--recent-years must be one or greater.")
    args.years = resolve_years(args.recent_years)
    return args


def main() -> None:
    args = parse_args()
    api_key = resolve_api_key(args.api_key)
    if not api_key:
        raise SystemExit(
            "Paste your key into OPEN_DART_API_KEY, set the OPEN_DART_API_KEY "
            "environment variable, or pass --api-key."
        )

    corporations = select_corporations(api_key, args)
    if not corporations:
        raise SystemExit("No companies matched the requested selection.")

    if args.dry_run:
        print(f"Selected {len(corporations)} companies.")
        preview = corporations[:20]
        for corp in preview:
            stock_code = corp.get("stock_code") or "-"
            print(f"{corp['corp_code']} {stock_code} {corp['corp_name']}")
        if len(corporations) > len(preview):
            print(f"... {len(corporations) - len(preview)} more")
        return

    manifest_entries: list[dict[str, Any]] = []
    manifest_path = args.out_dir / MANIFEST_FILE_NAME
    fetched_companies = 0
    skipped_companies = 0
    total_rows = 0
    year_label = f"{args.years[0]}-{args.years[-1]}"

    for index, corp in enumerate(corporations, start=1):
        primary_path = primary_output_path(corp, args)
        company_label = f"{corp['corp_name']} ({corp['corp_code']})"

        if primary_path.exists() and not args.overwrite:
            print(f"[{index}/{len(corporations)}] Skipping existing {company_label}: {primary_path}")
            entry = manifest_entry(corp, args)
            manifest_entries.append(entry)
            write_manifest(manifest_path, [entry])
            skipped_companies += 1
            continue

        print(f"[{index}/{len(corporations)}] Fetching {company_label} for {year_label}...")
        rows, skipped_years = fetch_company_rows(api_key, corp, args)
        if not rows:
            skipped_companies += 1
            print(f"  No rows fetched. Skipped years: {', '.join(map(str, skipped_years))}")
            continue

        written = write_company_outputs(corp, rows, args)
        entry = manifest_entry(corp, args)
        manifest_entries.append(entry)
        write_manifest(manifest_path, [entry])
        fetched_companies += 1
        total_rows += len(rows)

        skipped = f"; skipped years: {', '.join(map(str, skipped_years))}" if skipped_years else ""
        print(f"  Fetched {len(rows)} rows{skipped}")
        for path in written:
            print(f"  Wrote {path}")

    if manifest_entries:
        write_manifest(manifest_path, manifest_entries)
        print(f"Wrote manifest {manifest_path}")

    print(
        "Done. "
        f"Fetched {fetched_companies} companies, skipped {skipped_companies}, "
        f"total rows {total_rows}."
    )


if __name__ == "__main__":
    main()
