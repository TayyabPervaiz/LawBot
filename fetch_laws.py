#!/usr/bin/env python3
"""
fetch_laws.py - semi-automatic law PDF fetcher and checker for pakistan-law-bot.

Put this file in the project root (next to the data folder), for example:
    C:\\Users\\tayya\\pakistan-law-bot\\fetch_laws.py

What it does for each law listed in data/laws_manifest.json:
  1. Downloads the PDF from the direct URL you pasted into the manifest
     (skipped if the PDF is already there, or if you gave no URL).
  2. Checks the file really is a PDF and records its size, SHA-256 and the date.
  3. Checks whether the PDF has selectable text (scanned PDFs are flagged).
  4. Extracts a DRAFT text file into data/raw_draft/<category>/.
  5. Records everything in data/source_log.json (a provenance record per law).

What it deliberately does NOT do:
  - It never writes into data/raw/. You review the draft against the PDF first
    (section count, 20 random sections, provisos and schedules), then copy it
    into data/raw/ yourself.
  - It follows each site's robots.txt. If a site disallows automated access, the
    script skips it and tells you to download by hand. There is no override.
  - It does not search the portals. Find the direct PDF link in your browser and
    paste it into the manifest. "--list-links PAGE_URL" can help you find it.
  - It never invents law text. The draft contains only what is in the PDF.

Usage:
    pip install requests pdfplumber pypdf
    python fetch_laws.py --init                 # create folders + manifest template
    python fetch_laws.py                        # download (if URL given) + check + extract
    python fetch_laws.py --only ppc_1860        # just one law
    python fetch_laws.py --process-only         # no network: check PDFs you placed by hand
    python fetch_laws.py --list-links URL       # list PDF links found on a portal page
    python fetch_laws.py --bulk URL --into NAME # download all PDFs linked from one page
                                                #   (into data/source_pdfs/_bulk/NAME/, max 25)
    python fetch_laws.py --force                # re-download even if the PDF exists
    python fetch_laws.py --strip-page-numbers   # drop lone page numbers at page edges
    python fetch_laws.py --insecure             # skip SSL verification (see warning below)
"""

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from urllib import robotparser
from urllib.parse import unquote, urljoin, urlparse

BOT_TOKEN = "pakistan-law-bot"
HEADERS = {
    "User-Agent": f"{BOT_TOKEN}/1.0 (personal research project; respects robots.txt)",
    "Accept": "application/pdf,text/html;q=0.8,*/*;q=0.5",
}

MIN_CHARS_PER_TEXT_PAGE = 50     # a page with fewer characters counts as "no text"
SCANNED_RATIO_WARN = 0.80        # warn if fewer than 80% of pages have text
POLITE_DELAY_SECONDS = 2

TEMPLATE = {
    "_help": (
        "Paste the DIRECT PDF link into 'url' (or leave null and place the PDF by hand "
        "at data/source_pdfs/<category>/<filename>.pdf). 'portal' and 'notes' are for you."
    ),
    "laws": [
        {"id": "tenancy_punjab_2009", "category": "tenancy_punjab",
         "filename": "punjab_rented_premises_act_2009",
         "portal": "Punjab Law Portal", "url": None, "notes": ""},
        {"id": "tenancy_punjab_rules_2010", "category": "tenancy_punjab",
         "filename": "punjab_rented_premises_rules_2010",
         "portal": "Punjab Law Portal", "url": None, "notes": "optional"},
        {"id": "peca_2016", "category": "cybercrime",
         "filename": "peca_2016",
         "portal": "Pakistan Code", "url": None,
         "notes": "check that amendments are included"},
        {"id": "mflo_1961", "category": "family",
         "filename": "muslim_family_laws_ordinance_1961",
         "portal": "Pakistan Code", "url": None, "notes": ""},
        {"id": "family_courts_1964", "category": "family",
         "filename": "family_courts_act_1964",
         "portal": "Pakistan Code", "url": None, "notes": ""},
        {"id": "dmma_1939", "category": "family",
         "filename": "dissolution_of_muslim_marriages_act_1939",
         "portal": "Pakistan Code", "url": None, "notes": ""},
        {"id": "ppc_1860", "category": "criminal",
         "filename": "pakistan_penal_code_1860",
         "portal": "Pakistan Code", "url": None, "notes": "record amended-up-to date"},
        {"id": "crpc_1898", "category": "criminal",
         "filename": "code_of_criminal_procedure_1898",
         "portal": "Pakistan Code", "url": None,
         "notes": "check for Punjab amendments"},
        {"id": "consumer_punjab_2005", "category": "consumer",
         "filename": "punjab_consumer_protection_act_2005",
         "portal": "Punjab Law Portal", "url": None, "notes": ""},
    ],
}


class NotAPdf(Exception):
    pass


class RobotsBlocked(Exception):
    pass


# --------------------------------------------------------------------------- helpers

def say(msg=""):
    print(msg, flush=True)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path: Path, default):
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def need(module_name: str, pip_name: str = None):
    say(f"Missing Python package '{module_name}'. Install it with:")
    say(f"    pip install {pip_name or module_name}")
    sys.exit(2)


# --------------------------------------------------------------------------- robots.txt

_ROBOTS_CACHE = {}


def robots_allows(url: str, insecure: bool = False):
    """Return (allowed, reason). This script follows the site's robots.txt."""
    try:
        import requests
    except ImportError:
        need("requests")
    parts = urlparse(url)
    host = f"{parts.scheme}://{parts.netloc}"
    if host not in _ROBOTS_CACHE:
        parser, verdict = None, None
        try:
            r = requests.get(host + "/robots.txt", headers=HEADERS,
                             timeout=(10, 30), verify=not insecure)
            if r.status_code == 200:
                parser = robotparser.RobotFileParser()
                parser.parse(r.text.splitlines())
            elif r.status_code in (401, 403):
                verdict = (False, f"robots.txt returned HTTP {r.status_code}: "
                                  "the site does not allow automated access")
            elif 400 <= r.status_code < 500:
                verdict = (True, "no robots.txt")
            else:
                verdict = (False, f"could not read robots.txt (HTTP {r.status_code}); try again later")
        except Exception as e:
            verdict = (False, f"could not read robots.txt ({str(e)[:80]}); try again later")
        _ROBOTS_CACHE[host] = (parser, verdict)
    parser, verdict = _ROBOTS_CACHE[host]
    if verdict:
        return verdict
    if parser.can_fetch(BOT_TOKEN, url):
        return True, "allowed by robots.txt"
    return False, "the site's robots.txt does not allow automated access to this address"


# --------------------------------------------------------------------------- download

def download(url: str, dest: Path, insecure: bool = False, retries: int = 3):
    try:
        import requests
    except ImportError:
        need("requests")

    ok, why = robots_allows(url, insecure)
    if not ok:
        raise RobotsBlocked(why)

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    last_err = None

    for attempt in range(1, retries + 1):
        try:
            with requests.get(url, headers=HEADERS, stream=True, timeout=(15, 120),
                              verify=not insecure, allow_redirects=True) as r:
                r.raise_for_status()
                ctype = r.headers.get("Content-Type", "unknown")
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(65536):
                        if chunk:
                            f.write(chunk)
            with open(tmp, "rb") as f:
                head = f.read(1024)
            if b"%PDF" not in head:
                tmp.unlink(missing_ok=True)
                raise NotAPdf(
                    f"the server returned '{ctype}', not a PDF. This URL is probably a web "
                    f"page, not a direct PDF link. Try: python fetch_laws.py --list-links <page url>"
                )
            tmp.replace(dest)
            return
        except NotAPdf:
            raise
        except requests.exceptions.SSLError as e:
            tmp.unlink(missing_ok=True)
            raise RuntimeError(
                "SSL certificate problem. Government sites sometimes have bad certificates. "
                "Only if you trust the site, re-run with --insecure. Details: " + str(e)[:200]
            )
        except Exception as e:  # network errors, HTTP errors, timeouts
            last_err = e
            tmp.unlink(missing_ok=True)
            if attempt < retries:
                time.sleep(2 * attempt)
    raise RuntimeError(f"download failed after {retries} tries: {last_err}")


# --------------------------------------------------------------------------- PDF checks

def extract_pages(pdf_path: Path):
    """Return (list of page texts, engine name). Prefers pdfplumber, falls back to pypdf."""
    try:
        import pdfplumber
        pages = []
        with pdfplumber.open(str(pdf_path)) as pdf:
            for p in pdf.pages:
                pages.append(p.extract_text() or "")
        return pages, "pdfplumber"
    except ImportError:
        pass
    try:
        from pypdf import PdfReader
    except ImportError:
        need("pdfplumber", "pdfplumber pypdf")
    reader = PdfReader(str(pdf_path))
    return [(p.extract_text() or "") for p in reader.pages], "pypdf"


PAGE_NO_RE = re.compile(r"^\s*(?:page\s+)?\d{1,4}(?:\s*(?:of|/)\s*\d{1,4})?\s*$", re.IGNORECASE)
SECTION_LIKE_RE = re.compile(r"^\s*(?:Section\s+)?(\d{1,3}[A-Z]{0,2})\.\s+\S")


def strip_page_numbers(pages):
    """Remove lone page numbers, but ONLY within the first/last 2 lines of each page."""
    removed = 0
    cleaned = []
    for text in pages:
        lines = text.splitlines()
        keep = []
        for i, line in enumerate(lines):
            at_edge = i < 2 or i >= len(lines) - 2
            if at_edge and PAGE_NO_RE.match(line):
                removed += 1
                continue
            keep.append(line)
        cleaned.append("\n".join(keep))
    return cleaned, removed


def section_preview(text: str):
    nums = []
    for line in text.splitlines():
        m = SECTION_LIKE_RE.match(line)
        if m:
            nums.append(m.group(1))
    return {
        "section_like_lines": len(nums),
        "first": nums[0] if nums else None,
        "last": nums[-1] if nums else None,
    }


def process_pdf(pdf_path: Path, draft_path: Path, strip_numbers: bool):
    pages, engine = extract_pages(pdf_path)
    removed = 0
    if strip_numbers:
        pages, removed = strip_page_numbers(pages)

    n_pages = len(pages)
    with_text = sum(1 for t in pages if len(t.strip()) >= MIN_CHARS_PER_TEXT_PAGE)
    ratio = (with_text / n_pages) if n_pages else 0.0
    full_text = "\n".join(pages)

    draft_path.parent.mkdir(parents=True, exist_ok=True)
    with open(draft_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(full_text)

    return {
        "pages": n_pages,
        "pages_with_text": with_text,
        "text_ratio": round(ratio, 3),
        "characters": len(full_text),
        "engine": engine,
        "page_numbers_removed": removed,
        "likely_scanned": ratio < SCANNED_RATIO_WARN,
        "section_preview": section_preview(full_text),
    }


# --------------------------------------------------------------------------- link lister

class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)


def find_pdf_links(page_url: str, insecure: bool):
    """Return (links, error_message). Follows robots.txt."""
    try:
        import requests
    except ImportError:
        need("requests")
    ok, why = robots_allows(page_url, insecure)
    if not ok:
        return [], f"Skipped: {why}. Open the page in your browser and download by hand."
    try:
        r = requests.get(page_url, headers=HEADERS, timeout=(15, 60), verify=not insecure)
        r.raise_for_status()
    except requests.exceptions.SSLError:
        return [], "SSL certificate problem. If you trust the site, re-run with --insecure."
    except requests.exceptions.RequestException as e:
        return [], (f"Could not open the page: {str(e)[:200]}\n"
                    "Open it in your browser instead and copy the PDF link address by hand.")
    parser = LinkParser()
    parser.feed(r.text)
    found = []
    for href in parser.links:
        full = urljoin(page_url, href)
        low = full.lower()
        if (".pdf" in low or "pdffiles" in low or "download" in low) and full not in found:
            found.append(full)
    return found, None


NO_LINKS_HELP = (
    "No PDF-looking links found. The page may load its links with JavaScript.\n"
    "Open the page in your browser, right-click the PDF/Download button,\n"
    "choose 'Copy link address', and paste that into the manifest."
)


def list_links(page_url: str, insecure: bool):
    links, err = find_pdf_links(page_url, insecure)
    if err:
        say(err)
        return
    if not links:
        say(NO_LINKS_HELP)
    for link in links:
        say(link)


def bulk_download(root: Path, page_url: str, into: str, insecure: bool, max_files: int):
    """Download every PDF linked from one page into data/source_pdfs/_bulk/<into>/."""
    links, err = find_pdf_links(page_url, insecure)
    if err:
        say(err)
        return 1
    if not links:
        say(NO_LINKS_HELP)
        return 1

    if len(links) > max_files:
        say(f"Found {len(links)} links; downloading the first {max_files} "
            f"(change with --max).")
        links = links[:max_files]

    out_dir = root / "data" / "source_pdfs" / "_bulk" / into
    out_dir.mkdir(parents=True, exist_ok=True)

    used, plan = set(), []
    for url in links:
        name = re.sub(r"[^A-Za-z0-9._-]+", "_", unquote(Path(urlparse(url).path).name) or "download")
        if not name.lower().endswith(".pdf"):
            name += ".pdf"
        base, n = name[:-4], 1
        while name in used:
            n += 1
            name = f"{base}_{n}.pdf"
        used.add(name)
        plan.append((url, out_dir / name))

    done = skipped = failed = 0
    for i, (url, dest) in enumerate(plan, 1):
        if dest.exists():
            say(f"[{i}/{len(plan)}] already have {dest.name}")
            skipped += 1
            continue
        if done + failed > 0:
            time.sleep(POLITE_DELAY_SECONDS)
        try:
            download(url, dest, insecure=insecure)
            say(f"[{i}/{len(plan)}] saved {dest.name}")
            done += 1
        except RobotsBlocked as e:
            say(f"[{i}/{len(plan)}] SKIPPED {url}: {e}")
            failed += 1
        except (NotAPdf, RuntimeError) as e:
            say(f"[{i}/{len(plan)}] FAILED {url}: {str(e)[:160]}")
            failed += 1

    say(f"\nDownloaded {done}, already present {skipped}, failed/skipped {failed}.")
    say(f"Files are in: {out_dir}")
    say("These are NOT in the manifest and have not been checked. Pick the laws you")
    say("need, move/rename them to data/source_pdfs/<category>/<filename>.pdf as in the")
    say("manifest, then run: python fetch_laws.py --process-only")
    return 0 if done or skipped else 1


# --------------------------------------------------------------------------- main flow

def init_project(root: Path, force: bool):
    data = root / "data"
    manifest = data / "laws_manifest.json"
    for cat in sorted({e["category"] for e in TEMPLATE["laws"]}):
        (data / "source_pdfs" / cat).mkdir(parents=True, exist_ok=True)
        (data / "raw" / cat).mkdir(parents=True, exist_ok=True)
    (data / "raw_draft").mkdir(parents=True, exist_ok=True)
    (data / "processed").mkdir(parents=True, exist_ok=True)
    if manifest.exists() and not force:
        say(f"Manifest already exists, left unchanged: {manifest}")
    else:
        save_json(manifest, TEMPLATE)
        say(f"Created manifest template: {manifest}")
    say("Folders created under data/. Next: paste direct PDF links into the manifest.")


def run(args):
    root = Path(args.root).resolve()
    data = root / "data"
    manifest_path = data / "laws_manifest.json"
    log_path = data / "source_log.json"

    if not manifest_path.exists():
        say(f"No manifest at {manifest_path}. Run:  python fetch_laws.py --init")
        return 2

    manifest = load_json(manifest_path, {"laws": []})
    source_log = load_json(log_path, {})
    laws = manifest.get("laws", [])
    if args.only:
        laws = [e for e in laws if e["id"] == args.only]
        if not laws:
            say(f"No law with id '{args.only}' in the manifest.")
            return 2

    if args.insecure:
        say("WARNING: --insecure skips SSL certificate checks. Use only for sites you trust.")

    summary = []
    first_download = True

    for entry in laws:
        lid = entry["id"]
        cat = entry["category"]
        name = entry["filename"]
        pdf_path = data / "source_pdfs" / cat / f"{name}.pdf"
        draft_path = data / "raw_draft" / cat / f"{name}.txt"
        url = entry.get("url")

        say(f"\n=== {lid} ===")
        status, note = "OK", ""
        record = source_log.get(lid, {})

        # 1. download
        if args.process_only:
            pass
        elif pdf_path.exists() and not args.force:
            say(f"PDF already present, not downloading: {pdf_path}")
        elif url:
            if not first_download:
                time.sleep(POLITE_DELAY_SECONDS)
            first_download = False
            say(f"Downloading: {url}")
            try:
                download(url, pdf_path, insecure=args.insecure)
                record["source_url"] = url
                record["downloaded_on"] = date.today().isoformat()
            except RobotsBlocked as e:
                say(f"SKIPPED: {e}.")
                say("Download this one by hand in your browser and save it at:")
                say(f"    {pdf_path}")
                summary.append((lid, "BLOCKED", "robots.txt: download by hand"))
                continue
            except (NotAPdf, RuntimeError) as e:
                say(f"FAILED: {e}")
                summary.append((lid, "FAIL", "download failed"))
                continue
        else:
            say("No URL in the manifest. Place the PDF by hand at:")
            say(f"    {pdf_path}")

        if not pdf_path.exists():
            summary.append((lid, "MISSING", "no PDF yet"))
            continue

        # 2. verify + 3. text check + 4. draft extraction
        try:
            with open(pdf_path, "rb") as f:
                if b"%PDF" not in f.read(1024):
                    say("FAILED: the file is not a valid PDF.")
                    summary.append((lid, "FAIL", "not a PDF"))
                    continue
            info = process_pdf(pdf_path, draft_path, args.strip_page_numbers)
        except SystemExit:
            raise
        except Exception as e:
            say(f"FAILED while reading the PDF: {e}")
            summary.append((lid, "FAIL", "unreadable PDF"))
            continue

        if "downloaded_on" not in record:
            record["downloaded_on"] = date.today().isoformat() + " (file placed by hand or earlier)"
        record.update({
            "pdf_path": str(pdf_path.relative_to(root)),
            "draft_path": str(draft_path.relative_to(root)),
            "size_bytes": pdf_path.stat().st_size,
            "sha256": sha256_of(pdf_path),
            "checked_on": date.today().isoformat(),
            **info,
        })
        # fields for the owner, never overwritten by this script
        record.setdefault("amended_up_to", None)
        record.setdefault("expected_section_count", None)
        record.setdefault("verified_by_owner", False)
        source_log[lid] = record

        sp = info["section_preview"]
        say(f"Pages: {info['pages']}  with text: {info['pages_with_text']}  "
            f"(engine: {info['engine']})")
        say(f"Draft text: {draft_path}  ({info['characters']} characters)")
        say(f"Rough section-like lines: {sp['section_like_lines']}  "
            f"first: {sp['first']}  last: {sp['last']}   (rough guide only)")
        if info["page_numbers_removed"]:
            say(f"Page-number lines removed: {info['page_numbers_removed']}")

        if info["likely_scanned"]:
            status = "WARN"
            note = "likely scanned/low text: needs OCR or another source"
            say("WARNING: many pages have no selectable text. This PDF is probably a scan.")
            say("The draft will be incomplete or empty. Do not use it without OCR and heavy checking.")
        elif sp["section_like_lines"] == 0:
            status = "WARN"
            note = "no section-like lines found: check the draft by eye"
            say("WARNING: no section-style lines were detected. Check the draft by eye.")
        summary.append((lid, status, note))

    save_json(log_path, source_log)

    say("\n================ SUMMARY ================")
    for lid, status, note in summary:
        say(f"{status:8} {lid:28} {note}")
    say(f"\nProvenance log: {log_path}")
    say("Next for each law marked OK or WARN:")
    say("  1. Open the draft in data/raw_draft/ next to the PDF.")
    say("  2. Compare the section count with the official table of contents.")
    say("  3. Spot-check 20 random sections word for word.")
    say("  4. Fill in 'amended_up_to' and 'expected_section_count' in data/source_log.json.")
    say("  5. Only then copy the verified text into data/raw/<category>/.")
    return 1 if any(s == "FAIL" for _, s, _ in summary) else 0


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="Fetch and check law PDFs for pakistan-law-bot.")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent),
                    help="project root (default: folder containing this script)")
    ap.add_argument("--init", action="store_true", help="create folders and manifest template")
    ap.add_argument("--only", help="process just this law id")
    ap.add_argument("--process-only", action="store_true",
                    help="no downloading; check PDFs already in data/source_pdfs/")
    ap.add_argument("--force", action="store_true", help="re-download even if the PDF exists")
    ap.add_argument("--list-links", metavar="PAGE_URL",
                    help="print PDF-looking links found on a portal page")
    ap.add_argument("--bulk", metavar="PAGE_URL",
                    help="download every PDF linked from one page into data/source_pdfs/_bulk/")
    ap.add_argument("--into", default="bulk",
                    help="sub-folder name under _bulk for --bulk (default: bulk)")
    ap.add_argument("--max", type=int, default=25, dest="max_files",
                    help="safety cap for --bulk (default 25)")
    ap.add_argument("--strip-page-numbers", action="store_true",
                    help="remove lone page numbers at the top/bottom edge of pages")
    ap.add_argument("--insecure", action="store_true", help="skip SSL certificate verification")
    args = ap.parse_args()

    if args.list_links:
        list_links(args.list_links, args.insecure)
        return 0
    if args.bulk:
        return bulk_download(Path(args.root).resolve(), args.bulk, args.into,
                             args.insecure, args.max_files)
    if args.init:
        init_project(Path(args.root).resolve(), args.force)
        return 0
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
