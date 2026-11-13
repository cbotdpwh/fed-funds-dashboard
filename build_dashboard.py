#!/usr/bin/env python3
"""
Builds the FED Funds 2026 dashboard (docs/index.html) from the Google Sheet.

How it works (in plain words):
  1. Downloads the "Regular-FY2026" tab of the Google Sheet as a CSV file.
  2. Reads every request row (one row = one FED-SAA reference number).
  3. Sorts each request into a request type, an OKB tag and a status.
  4. Puts the cleaned numbers inside template.html and saves docs/index.html.

Only Python's standard library is used, so nothing needs to be installed.

Settings come from environment variables (GitHub stores them for you):
  SHEET_ID      required  the long ID in the Google Sheet link (kept as a GitHub secret)
  REGISTER_GID  optional  tab ID of "Regular-FY2026"   (default 1074405312)
  SOF_GID       optional  tab ID of "Status of Funding" (default 1227294781)

For testing on your own computer you can skip the download:
  python build_dashboard.py --csv register.csv [--sof-csv status.csv]
"""

import argparse
import csv
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "template.html"
OUT_DIR = HERE / "docs"

DEFAULT_REGISTER_GID = "1074405312"
DEFAULT_SOF_GID = "1227294781"

REF_PATTERN = re.compile(r"FED-SAA[\w]*-\d+", re.IGNORECASE)
OKB_PATTERN = re.compile(r"oplan\s+kontra\s+baha|\bokb\b", re.IGNORECASE)
IN_GITHUB = os.environ.get("GITHUB_ACTIONS") == "true"


class BuildError(Exception):
    """A problem we can explain in plain words."""

    def __init__(self, title, message):
        super().__init__(message)
        self.title = title
        self.message = message


def report_error(title: str, message: str):
    """Print the reason so it appears in GitHub's red 'Annotations' box, not only in the log."""
    if IN_GITHUB:
        safe = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print(f"::error title={title}::{safe}")
    print(f"\nERROR - {title}\n{message}\n", file=sys.stderr)


def clean_sheet_id(raw: str) -> str:
    """Accepts the bare ID or a whole Google Sheets link pasted by mistake."""
    raw = (raw or "").strip().strip("\"'").strip()
    match = re.search(r"/d/([A-Za-z0-9_-]{20,})", raw)
    sheet_id = match.group(1) if match else raw
    if sheet_id and not re.fullmatch(r"[A-Za-z0-9_-]{20,}", sheet_id):
        raise BuildError(
            "The SHEET_ID secret looks wrong",
            "It should be only the long code between /d/ and /edit in the Google Sheet link "
            "(letters, numbers, - and _, no spaces). Update it under Settings > Secrets and "
            "variables > Actions > Repository secrets > SHEET_ID (pencil icon).",
        )
    return sheet_id


# ----------------------------------------------------------------------------
# Download
# ----------------------------------------------------------------------------
def download_csv(sheet_id: str, gid: str, tab_name: str) -> str:
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"
    last_error = None
    for attempt in range(1, 4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "fed-funds-dashboard"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read().decode("utf-8-sig")
            if body.lstrip().lower().startswith("<!doctype html") or "<html" in body[:500].lower():
                raise BuildError(
                    "Google did not share the sheet",
                    "Google answered with a sign-in page instead of the data. In the Google Sheet, "
                    "click Share > General access > 'Anyone with the link' (Viewer is enough), then run again.",
                )
            return body
        except BuildError:
            raise
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code == 404:
                raise BuildError(
                    "Sheet or tab not found",
                    f"Google could not find the {tab_name} tab. Most likely the SHEET_ID secret has a typo "
                    "(it must be only the code between /d/ and /edit). If the tab was deleted and re-created, "
                    "its tab ID changed: open the tab, copy the number after #gid= in the address bar, and "
                    "save it as a repository variable (Settings > Secrets and variables > Actions > Variables).",
                ) from exc
            if exc.code in (401, 403):
                raise BuildError(
                    "Google did not share the sheet",
                    "Google refused access (error %d). In the Google Sheet, click Share > General access > "
                    "'Anyone with the link' (Viewer is enough), then run again." % exc.code,
                ) from exc
            print(f"  download attempt {attempt} failed: {exc}", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001 - retry any network hiccup
            last_error = exc
            print(f"  download attempt {attempt} failed: {exc}", file=sys.stderr)
        time.sleep(5 * attempt)
    raise BuildError(
        "Could not reach Google Sheets",
        f"Downloading the {tab_name} tab failed 3 times ({last_error}). This is usually temporary: "
        "wait a few minutes, then Actions > Update dashboard > Run workflow.",
    )


# ----------------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------------
def parse_amount(text: str):
    """'₱1,043,617.00' -> 1043617.0 ; blank -> None"""
    if text is None:
        return None
    cleaned = re.sub(r"[^\d.\-]", "", str(text))
    if cleaned in ("", ".", "-"):
        return None
    try:
        return round(float(cleaned), 2)
    except ValueError:
        return None


def parse_date(text: str):
    """'02/10/2026' (MM/DD/YYYY) -> '2026-02-10' ; anything else -> None"""
    text = (text or "").strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def norm_header(text: str) -> str:
    return re.sub(r"[^a-z() ]", "", (text or "").lower()).strip()


def clean_spaces(text: str) -> str:
    """Turns line breaks and long runs of spaces into ', ' so equipment lists read cleanly."""
    parts = re.split(r"\s*\n\s*|\s{2,}", (text or "").strip())
    joined = ", ".join(p.strip().strip(",") for p in parts if p.strip().strip(","))
    return re.sub(r"\s*,\s*,?\s*", ", ", joined).strip(", ")


def region_label(text: str) -> str:
    return re.sub(r"\s*-\s*", "-", (text or "").strip())


# ----------------------------------------------------------------------------
# Business rules (edit here if your definitions change)
# ----------------------------------------------------------------------------
def classify_request(fund_type: str) -> str:
    """One request type per row. Order matters: the first match wins."""
    f = (fund_type or "").lower()
    if "preventive" in f:
        return "Preventive maintenance"
    if "corrective" in f:
        return "Corrective maintenance"
    if "dry dock" in f:
        return "Dry docking and repair"
    if "accessor" in f:
        return "Accessories"
    # Operating funds = running the equipment with DPWH's own crew
    if any(word in f for word in ("operational", "labor", "osh", "bunkhouse", "office supplies")):
        return "Dredging by administration"
    if "mobilization" in f:
        return "Mobilization"
    return "Other"


def classify_status(status: str) -> str:
    s = (status or "").strip().lower()
    if not s:
        return "none"
    if "approved" in s:
        return "approved"
    if "released from boe" in s:
        return "boe"
    if "released from fed" in s:
        return "fed"
    if "signature" in s:
        return "signature"
    if "return" in s:
        return "returned"
    return "other"


# ----------------------------------------------------------------------------
# Parse the register tab
# ----------------------------------------------------------------------------
def parse_register(csv_text: str) -> dict:
    rows = list(csv.reader(io.StringIO(csv_text)))

    meta = {"fund": "", "legal_basis": "", "ppa_code": "", "total_budget": None,
            "sheet_total": None, "sheet_remaining": None}

    header_idx = None
    for i, row in enumerate(rows):
        first = (row[0] if row else "").strip().lower()
        if header_idx is None:
            if first.startswith("fed release date"):
                header_idx = i
                break
            if first.startswith("legal basis") and len(row) > 1:
                meta["legal_basis"] = row[1].strip()
            elif first.startswith("p. p. a. code") and len(row) > 1:
                meta["ppa_code"] = row[1].strip()
            elif first.startswith("total allotment") and len(row) > 1:
                meta["total_budget"] = parse_amount(row[1])
            elif i == 0 and len(row) > 1:
                meta["fund"] = row[1].strip()

    if header_idx is None:
        raise BuildError(
            "Sheet layout not recognised",
            "Could not find the header row that starts with 'FED Release Date:' in the Regular-FY2026 tab. "
            "Check that the first cell of the header row still says 'FED Release Date:'. If you renamed or "
            "re-created the tab, its tab ID may have changed (see the setup guide, Troubleshooting).",
        )

    headers = [norm_header(h) for h in rows[header_idx]]

    def col(*names):
        for name in names:
            if name in headers:
                return headers.index(name)
        return None

    c = {
        "date": col("fed release date"),
        "region": col("dpwh region"),
        "office": col("implementing office"),
        "dpwh_no": col("dpwh no"),
        "equipment": col("equipment type"),
        "fund": col("fund type"),
        "amount": col("allotment"),
        "ref": col("file link"),
        "remarks": col("remarks"),
        "status": col("status"),
    }
    missing = [k for k, v in c.items() if v is None]
    if missing:
        names = {"date": "FED Release Date:", "region": "DPWH Region:", "office": "Implementing Office:",
                 "dpwh_no": "DPWH No.:", "equipment": "Equipment Type:", "fund": "Fund Type:",
                 "amount": "Allotment:", "ref": "File Link:", "remarks": "Remarks:", "status": "Status"}
        raise BuildError(
            "A column was renamed",
            "These column headings were not found in the Regular-FY2026 tab: "
            + ", ".join(names[m] for m in missing)
            + ". Put the heading back exactly as written (the column order does not matter).",
        )

    def cell(row, key):
        idx = c[key]
        return row[idx] if idx < len(row) else ""

    records, seen = [], set()
    for row in rows[header_idx + 1:]:
        joined = " ".join(row).upper()
        if "TOTAL ALLOTMENT" in joined:
            # Read the sheet's own totals so we can double-check our maths.
            for j, val in enumerate(row):
                if "TOTAL ALLOTMENT" in val.upper():
                    meta["sheet_total"] = next((parse_amount(v) for v in row[j + 1:] if parse_amount(v) is not None), None)
            continue
        if "REMAINING BALANCE" in joined:
            for j, val in enumerate(row):
                if "REMAINING BALANCE" in val.upper():
                    meta["sheet_remaining"] = next((parse_amount(v) for v in row[j + 1:] if parse_amount(v) is not None), None)
            break  # everything below this line is notes, not requests

        ref_match = REF_PATTERN.search(cell(row, "ref"))
        if not ref_match:
            continue
        ref = ref_match.group(0)
        if ref.upper() in seen:
            continue
        seen.add(ref.upper())

        fund_type = cell(row, "fund").strip()
        remarks = cell(row, "remarks")
        status_raw = cell(row, "status").strip()
        records.append({
            "ref": ref,
            "no": int(re.search(r"(\d+)$", ref).group(1)),
            "date": parse_date(cell(row, "date")),
            "region": region_label(cell(row, "region")),
            "office": clean_spaces(cell(row, "office")),
            "dpwh_no": clean_spaces(cell(row, "dpwh_no")),
            "equipment": clean_spaces(cell(row, "equipment")),
            "fund_type": fund_type,
            "type": classify_request(fund_type),
            "okb": bool(OKB_PATTERN.search(remarks or "")),
            "status": classify_status(status_raw),
            "status_raw": status_raw if classify_status(status_raw) == "other" else "",
            "amount": parse_amount(cell(row, "amount")),
            # NOTE: the Remarks text itself is deliberately NOT published.
        })

    return {"meta": meta, "records": records}


def parse_status_of_funding(csv_text: str) -> dict:
    out = {"admin_overhead": None, "sof_as_of": None}
    for row in csv.reader(io.StringIO(csv_text)):
        for j, val in enumerate(row):
            up = val.upper()
            if "ALLOTMENT (I)" in up and out["admin_overhead"] is None:
                out["admin_overhead"] = next((parse_amount(v) for v in row[j + 1:] if parse_amount(v) is not None), None)
            if up.strip().endswith("AS OF") and out["sof_as_of"] is None:
                out["sof_as_of"] = next((parse_date(v) for v in row[j + 1:] if parse_date(v)), None)
    return out


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", help="use a local CSV of the Regular-FY2026 tab instead of downloading")
    ap.add_argument("--sof-csv", help="use a local CSV of the Status of Funding tab")
    ap.add_argument("--out", default=str(OUT_DIR / "index.html"))
    args = ap.parse_args()

    sheet_id = clean_sheet_id(os.environ.get("SHEET_ID", ""))
    register_gid = re.sub(r"\D", "", os.environ.get("REGISTER_GID", "")) or DEFAULT_REGISTER_GID
    sof_gid = re.sub(r"\D", "", os.environ.get("SOF_GID", "")) or DEFAULT_SOF_GID

    if not TEMPLATE.exists():
        raise BuildError(
            "template.html is missing",
            "template.html must sit at the top level of the repository, next to build_dashboard.py. "
            "Upload it again with Add file > Upload files.",
        )

    if args.csv:
        register_csv = Path(args.csv).read_text(encoding="utf-8-sig")
    else:
        if not sheet_id:
            raise BuildError(
                "The SHEET_ID secret is missing",
                "GitHub could not find a repository secret named SHEET_ID. Go to Settings > Secrets and "
                "variables > Actions, open the 'Secrets' tab (not 'Variables'), click 'New repository secret', "
                "Name: SHEET_ID, Secret: the code between /d/ and /edit in the sheet link. Then run again.",
            )
        print("Downloading Regular-FY2026 tab ...")
        register_csv = download_csv(sheet_id, register_gid, "Regular-FY2026")

    parsed = parse_register(register_csv)
    records, meta = parsed["records"], parsed["meta"]
    if not records:
        raise BuildError(
            "No requests found",
            "The Regular-FY2026 tab was read, but no rows had a reference number like FED-SAAreg2026-001 "
            "in the 'File Link:' column. The dashboard was left unchanged.",
        )

    sof = {"admin_overhead": None, "sof_as_of": None}
    try:
        if args.sof_csv:
            sof = parse_status_of_funding(Path(args.sof_csv).read_text(encoding="utf-8-sig"))
        elif sheet_id:
            print("Downloading Status of Funding tab ...")
            sof = parse_status_of_funding(download_csv(sheet_id, sof_gid, "Status of Funding"))
    except BuildError as exc:  # this tab is optional; never fail the build because of it
        print(f"  (skipped Status of Funding: {exc.message})", file=sys.stderr)
        if IN_GITHUB:
            print(f"::warning title=Status of Funding tab skipped::{exc.message}")

    computed_total = round(sum(r["amount"] or 0 for r in records), 2)
    meta.update(sof)
    meta["computed_total"] = computed_total
    meta["generated_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    meta["request_count"] = len(records)

    payload = {"meta": meta, "records": records}
    data_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    data_json = data_json.replace("<", "\\u003c")  # safe inside <script>

    html = TEMPLATE.read_text(encoding="utf-8")
    if "__FED_DATA__" not in html:
        raise BuildError(
            "template.html is damaged",
            "template.html no longer contains the __FED_DATA__ placeholder. Upload the original template.html again.",
        )
    html = html.replace("__FED_DATA__", data_json)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    (out_path.parent / ".nojekyll").write_text("", encoding="utf-8")

    # A short report that shows up in the GitHub Actions log
    print(f"Requests read:        {len(records)}")
    print(f"Computed sub-allotted: PHP {computed_total:,.2f}")
    if meta.get("sheet_total") is not None:
        diff = round(computed_total - meta["sheet_total"], 2)
        print(f"Sheet TOTAL ALLOTMENT: PHP {meta['sheet_total']:,.2f}  (difference {diff:,.2f})")
    if meta.get("total_budget") is not None:
        print(f"Remaining balance:     PHP {meta['total_budget'] - computed_total:,.2f}")
    print(f"Saved {out_path}")


if __name__ == "__main__":
    try:
        main()
    except BuildError as err:
        report_error(err.title, err.message)
        sys.exit(1)
    except Exception as err:  # noqa: BLE001 - anything unexpected still gets a readable message
        report_error("Unexpected error", f"{type(err).__name__}: {err}. The dashboard was left unchanged.")
        raise
