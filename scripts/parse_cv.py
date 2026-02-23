"""
parse_cv.py - Parse a PDF CV and propose additions to the website data files.

Usage:
    python3 scripts/parse_cv.py /path/to/Tucker_CV.pdf

Extracts publications and media appearances from the CV, compares against
existing YAML data, and proposes new entries.
"""

from __future__ import annotations

import sys
import os
import re
import yaml
import pdfplumber
from rich.console import Console
from rich.table import Table
from rich.prompt import Confirm

sys.path.insert(0, os.path.dirname(__file__))
from config import PUBLICATIONS_YAML, SITE_CONTENT_YAML, CV_PDF

console = Console()


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", title.lower()).strip()


# ---------------------------------------------------------------------------
# PDF extraction
# ---------------------------------------------------------------------------

def extract_text(pdf_path: str) -> str:
    text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    return text


# ---------------------------------------------------------------------------
# Section parsing
# ---------------------------------------------------------------------------

# Common LaTeX CV section headers (case-insensitive)
SECTION_HEADERS = [
    "Books",
    "Book Chapters",
    "Journal Articles",
    "Refereed Journal Articles",
    "Working Papers",
    "Under Review",
    "Other Publications",
    "Reports",
    "Media Coverage",
    "Media Appearances",
    "Press Coverage",
    "Multimedia",
    "Teaching",
    "Education",
    "Awards",
    "Honors",
    "Employment",
    "Professional Activities",
]

HEADER_PATTERN = re.compile(
    r"^(" + "|".join(re.escape(h) for h in SECTION_HEADERS) + r")\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def split_into_sections(text: str) -> dict:
    """Split CV text into named sections."""
    sections = {}
    matches = list(HEADER_PATTERN.finditer(text))
    for i, match in enumerate(matches):
        header = match.group(1).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections[header.lower()] = text[start:end].strip()
    return sections


# ---------------------------------------------------------------------------
# Publication parsing
# ---------------------------------------------------------------------------

def parse_publication_line(line: str) -> dict | None:
    """
    Try to parse a single publication line from a CV.
    Typical LaTeX CV format:
      Tucker, Joshua A. and Co-Author. (YEAR). "Title." *Journal*, Vol(Issue), pp. X-Y.
    Returns a partial dict or None if unparseable.
    """
    line = line.strip()
    if len(line) < 20:
        return None

    # Extract year
    year_m = re.search(r"\b(19|20)\d{2}\b", line)
    year = int(year_m.group()) if year_m else 0

    # Extract title (in quotes or italics — look for quoted text)
    title_m = re.search(r'["\u201c\u201d]([^"\u201c\u201d]+)["\u201c\u201d]', line)
    if not title_m:
        # Fallback: title might be the whole line minus authors/year
        return None
    title = title_m.group(1).strip().rstrip(".")

    # Authors: everything before the year (rough)
    pre_year = line[:year_m.start()].strip().rstrip(".(") if year_m else ""
    authors = pre_year if pre_year else "Tucker, Joshua A."

    # Venue: text after the title quote, up to end of line
    after_title = line[title_m.end():].strip().lstrip('."').strip()
    venue_m = re.match(r"[*_]?([^,.*_]+)[*_]?", after_title)
    venue = venue_m.group(1).strip() if venue_m else after_title[:60]

    return {
        "title": title,
        "authors": authors,
        "year": year,
        "venue": venue,
        "volume_issue_pages": "",
        "doi": "",
        "type": "journal_article",
        "abstract": "",
        "tags": [],
        "awards": [],
        "links": {
            "published": "",
            "preprint": "",
            "appendix": "",
            "replication": "",
        },
        "_source": "cv",
    }


def make_slug(title: str, year: int) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return f"tucker-{year}-{slug[:50]}"


def parse_publications_section(text: str, existing_titles: set, pub_type: str = "journal_article") -> list:
    proposals = []
    for line in text.splitlines():
        line = line.strip()
        if not line or len(line) < 20:
            continue
        result = parse_publication_line(line)
        if result and normalize_title(result["title"]) not in existing_titles:
            result["type"] = pub_type
            result["id"] = make_slug(result["title"], result["year"])
            proposals.append(result)
    return proposals


# ---------------------------------------------------------------------------
# Media parsing
# ---------------------------------------------------------------------------

def parse_media_line(line: str) -> dict | None:
    """
    Try to parse a media mention line. Typical format:
      "Outlet Name, 'Article Title', Month Day, Year."
    """
    line = line.strip()
    if len(line) < 15:
        return None

    # Date at end
    date_m = re.search(r"(\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4})", line)
    date_str = ""
    if date_m:
        from datetime import datetime
        try:
            date_str = datetime.strptime(date_m.group(1), "%B %d, %Y").strftime("%Y-%m-%d")
        except ValueError:
            pass

    # Title in quotes
    title_m = re.search(r'["\u201c\u2018]([^"\u201c\u2019\u201d]+)["\u201d\u2019]', line)
    title = title_m.group(1).strip() if title_m else line[:80]

    # Outlet: typically the first token(s) before a comma
    outlet_m = re.match(r"^([^,\"]+),", line)
    outlet = outlet_m.group(1).strip() if outlet_m else "Unknown"

    return {
        "outlet": outlet,
        "title": title,
        "date": date_str,
        "url": "",
        "_source": "cv",
    }


def parse_media_section(text: str, existing_titles: set) -> list:
    proposals = []
    for line in text.splitlines():
        result = parse_media_line(line)
        if result and result["title"] and normalize_title(result["title"]) not in existing_titles:
            proposals.append(result)
    return proposals


# ---------------------------------------------------------------------------
# Load existing data
# ---------------------------------------------------------------------------

def load_existing_pub_titles() -> set:
    with open(PUBLICATIONS_YAML, "r") as f:
        pubs = yaml.safe_load(f)
    return {normalize_title(p["title"]) for p in pubs if p.get("title")}


def load_existing_media_titles() -> set:
    with open(SITE_CONTENT_YAML, "r") as f:
        data = yaml.safe_load(f)
    titles = set()
    media = data.get("media", {})
    for section in ("press", "multimedia"):
        for item in media.get(section, []):
            if item.get("title"):
                titles.add(normalize_title(item["title"]))
    return titles


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_cv(pdf_path: str, interactive: bool = True) -> dict:
    """
    Parse a CV PDF and return proposed additions.

    Returns:
        {"publications": [...], "media": [...]}
    """
    if not os.path.exists(pdf_path):
        console.print(f"[red]CV file not found: {pdf_path}[/red]")
        return {"publications": [], "media": []}

    console.print(f"[bold cyan]Parsing CV: {pdf_path}[/bold cyan]")
    text = extract_text(pdf_path)
    sections = split_into_sections(text)

    console.print(f"[dim]Detected sections: {', '.join(sections.keys())}[/dim]")

    existing_pubs = load_existing_pub_titles()
    existing_media = load_existing_media_titles()

    pub_proposals = []
    media_proposals = []

    # Publications
    section_type_map = {
        "books": "book",
        "book chapters": "book_chapter",
        "journal articles": "journal_article",
        "refereed journal articles": "journal_article",
        "working papers": "working_paper",
        "under review": "under_review",
        "other publications": "other",
        "reports": "other",
    }
    for section_name, pub_type in section_type_map.items():
        if section_name in sections:
            proposals = parse_publications_section(sections[section_name], existing_pubs, pub_type)
            pub_proposals.extend(proposals)
            if proposals:
                console.print(f"[yellow]  {len(proposals)} new entry(ies) in '{section_name}'[/yellow]")

    # Media
    for section_name in ("media coverage", "media appearances", "press coverage", "multimedia"):
        if section_name in sections:
            proposals = parse_media_section(sections[section_name], existing_media)
            media_proposals.extend(proposals)
            if proposals:
                console.print(f"[yellow]  {len(proposals)} new media entry(ies) in '{section_name}'[/yellow]")

    total = len(pub_proposals) + len(media_proposals)
    if total == 0:
        console.print("[green]CV is fully in sync with the website — no new entries found.[/green]")
    else:
        console.print(f"\n[bold yellow]{total} new item(s) proposed from CV:[/bold yellow]")

    if pub_proposals and interactive:
        table = Table(title="New Publications from CV")
        table.add_column("#", width=4)
        table.add_column("Year", width=6)
        table.add_column("Type", width=16)
        table.add_column("Title")
        table.add_column("Venue")
        for i, p in enumerate(pub_proposals, 1):
            table.add_row(str(i), str(p["year"]), p["type"], p["title"], p["venue"])
        console.print(table)

    if media_proposals and interactive:
        table = Table(title="New Media Mentions from CV")
        table.add_column("#", width=4)
        table.add_column("Date", width=12)
        table.add_column("Outlet")
        table.add_column("Title")
        for i, m in enumerate(media_proposals, 1):
            table.add_row(str(i), m["date"], m["outlet"], m["title"])
        console.print(table)

    return {"publications": pub_proposals, "media": media_proposals}


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else CV_PDF
    parse_cv(path)
