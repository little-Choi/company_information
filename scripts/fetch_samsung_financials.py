"""Fetch Samsung Electronics financial statements from OpenDART.

Usage:
    # Option 1: put your key in OPEN_DART_API_KEY below, then run:
    python scripts/fetch_samsung_financials.py --year 2025

    # Option 2: use an environment variable instead:
    $env:OPEN_DART_API_KEY = "your_40_char_key"  # PowerShell
    python scripts/fetch_samsung_financials.py --year 2025
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen


API_URL = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
SAMSUNG_ELECTRONICS_CORP_CODE = "00126380"

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


def fetch_financial_statement(
    api_key: str,
    year: int,
    report_code: str = "11011",
    fs_div: str = "CFS",
    corp_code: str = SAMSUNG_ELECTRONICS_CORP_CODE,
    timeout: int = 30,
) -> list[dict[str, Any]]:
    params = {
        "crtfc_key": api_key,
        "corp_code": corp_code,
        "bsns_year": str(year),
        "reprt_code": report_code,
        "fs_div": fs_div,
    }
    url = f"{API_URL}?{urlencode(params)}"

    try:
        with urlopen(url, timeout=timeout) as response:
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
        raise OpenDartError(f"OpenDART error {status}: {message}")

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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch Samsung Electronics financial statements from OpenDART."
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="OpenDART API key. Overrides the environment variable and code setting.",
    )
    parser.add_argument(
        "--year",
        type=int,
        default=date.today().year - 1,
        help="Business year to request. Defaults to last calendar year.",
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
        help="Directory for output files.",
    )
    parser.add_argument(
        "--format",
        choices=("json", "csv", "both"),
        default="both",
        help="Output format.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    api_key = resolve_api_key(args.api_key)
    if not api_key:
        raise SystemExit(
            "Paste your key into OPEN_DART_API_KEY, set the OPEN_DART_API_KEY "
            "environment variable, or pass --api-key."
        )

    rows = fetch_financial_statement(
        api_key=api_key,
        year=args.year,
        report_code=args.report_code,
        fs_div=args.fs_div,
    )
    rows = filter_statement(rows, args.statement)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    base_name = (
        f"samsung_electronics_{args.year}_{REPORT_CODES[args.report_code]}_{args.fs_div}"
    )
    if args.statement:
        base_name += f"_{args.statement}"

    written: list[Path] = []
    if args.format in ("json", "both"):
        path = args.out_dir / f"{base_name}.json"
        write_json(path, rows)
        written.append(path)
    if args.format in ("csv", "both"):
        path = args.out_dir / f"{base_name}.csv"
        write_csv(path, rows)
        written.append(path)

    print(f"Fetched {len(rows)} rows.")
    for path in written:
        print(f"Wrote {path}")


if __name__ == "__main__":
    main()
