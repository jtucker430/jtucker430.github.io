"""
scan_csmap.py - Scan csmapnyu.org for new Tucker content.

Scrapes the Joshua Tucker profile page on CSMAP, which aggregates all associated
publications, media appearances, and commentary. Compares against existing
_data/publications.yml, _data/site_content.yml, and _commentary/ files.

Returns proposals of three types: "publications", "commentary", "media"

Usage (standalone):
    python3 scripts/scan_csmap.py
"""

import sys
import os
import re
import warnings
import yaml
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from rich.console import Console
from rich.table import Table

warnings.filterwarnings("ignore")  # suppress LibreSSL urllib3 warning

sys.path.insert(0, os.path.dirname(__file__))
from config import (
    CSMAP_BASE_URL,
    PUBLICATIONS_YAML,
    SITE_CONTENT_YAML,
    COMMENTARY_DIR,
)

console = Console()
TUCKER_PROFILE_URL = f"{CSMAP_BASE_URL}/people/joshua-a-tucker"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (academic website updater; contact: joshua.tucker@nyu.edu)"
}

# typeLabel text → internal type
TYPE_MAP = {
    "journal article": "publications",
    "working paper": "publications",
    "report": "publications",
    "book": "publications",
    "book chapter": "publications",
    "policy": "commentary",
    "commentary": "commentary",
    "news": "commentary",
    "in the media": "media",
    "media": "media",
}


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", title.lower()).strip()


def parse_date(date_str: str) -> str:
    """'February 19, 2026' → '2026-02-19'"""
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return date_str.strip()


# ---------------------------------------------------------------------------
# Load existing content for deduplication
# ---------------------------------------------------------------------------

def load_existing_publication_titles() -> set:
    with open(PUBLICATIONS_YAML, "r") as f:
        pubs = yaml.safe_load(f)
    return {normalize_title(p["title"]) for p in pubs if p.get("title")}


def load_existing_commentary_titles() -> set:
    titles = set()
    for fname in os.listdir(COMMENTARY_DIR):
        if not fname.endswith(".md"):
            continue
        with open(os.path.join(COMMENTARY_DIR, fname), "r") as f:
            content = f.read()
        match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
        if match:
            try:
                fm = yaml.safe_load(match.group(1))
                if fm and fm.get("title"):
                    titles.add(normalize_title(fm["title"]))
            except yaml.YAMLError:
                pass
    return titles


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
# Scraping
# ---------------------------------------------------------------------------

def get_soup(url: str) -> BeautifulSoup:
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def get_total_pages(soup: BeautifulSoup) -> int:
    """Extract total page count from ul.pagination."""
    pag = soup.select_one("ul.pagination")
    if not pag:
        return 1
    nums = []
    for li in pag.find_all("li"):
        try:
            nums.append(int(li.get_text(strip=True)))
        except ValueError:
            pass
    return max(nums) if nums else 1


def scrape_one_page(url: str) -> list:
    """Parse one profile page and return raw item dicts."""
    soup = get_soup(url)
    items = []

    for li in soup.select("li.entryBlock"):
        # Type
        type_label_el = li.select_one("div.typeLabel")
        type_label = type_label_el.get_text(strip=True) if type_label_el else ""
        content_type = TYPE_MAP.get(type_label.lower(), "commentary")

        # Title + internal link
        h3_a = li.select_one("header h3 a")
        if not h3_a:
            continue
        title = h3_a.get_text(strip=True)
        href = h3_a.get("href", "")
        link = href if href.startswith("http") else CSMAP_BASE_URL + href

        # Date
        date_el = li.select_one("p.entryBlock-sub")
        date_str = parse_date(date_el.get_text(strip=True)) if date_el else ""

        # Excerpt
        excerpt_el = li.select_one("div.entryBlock-excerpt")
        excerpt = excerpt_el.get_text(strip=True) if excerpt_el else ""

        # Venue (for research items, it comes after the excerpt — not always present)
        # We'll leave it blank and let it be filled in when the user reviews
        venue = ""

        items.append({
            "title": title,
            "link": link,
            "date": date_str,
            "type": content_type,
            "venue": venue,
            "excerpt": excerpt,
            "raw_type": type_label,
        })

    return items


def fetch_all_profile_items() -> list:
    """Fetch all paginated content from Tucker's CSMAP profile."""
    console.print(f"[bold cyan]Fetching CSMAP profile: {TUCKER_PROFILE_URL}[/bold cyan]")
    soup = get_soup(TUCKER_PROFILE_URL)
    total_pages = get_total_pages(soup)
    console.print(f"[dim]Detected {total_pages} page(s) of profile content.[/dim]")

    all_items = scrape_one_page(TUCKER_PROFILE_URL)

    for page in range(2, total_pages + 1):
        page_url = f"{TUCKER_PROFILE_URL}?page={page}"
        console.print(f"[dim]  Fetching page {page}/{total_pages}...[/dim]")
        all_items.extend(scrape_one_page(page_url))

    # Deduplicate by normalized title
    seen = set()
    unique = []
    for item in all_items:
        key = normalize_title(item["title"])
        if key not in seen:
            seen.add(key)
            unique.append(item)

    console.print(f"[green]Found {len(unique)} unique items on CSMAP profile.[/green]")
    return unique


# ---------------------------------------------------------------------------
# Build proposals
# ---------------------------------------------------------------------------

def make_pub_slug(title: str, year: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:50]
    return f"tucker-{year}-{slug}"


def build_publication_proposal(item: dict) -> dict:
    year_str = item["date"][:4] if item["date"] else "0"
    return {
        "id": make_pub_slug(item["title"], year_str),
        "title": item["title"],
        "authors": "Tucker, Joshua A.",
        "year": int(year_str) if year_str.isdigit() else 0,
        "venue": item["venue"],
        "volume_issue_pages": "",
        "doi": "",
        "type": "journal_article",
        "abstract": item["excerpt"],
        "tags": [],
        "awards": [],
        "links": {
            "published": item["link"],
            "preprint": "",
            "appendix": "",
            "replication": "",
        },
        "_source": "csmap",
    }


def build_commentary_proposal(item: dict) -> dict:
    return {
        "title": item["title"],
        "date": item["date"] or "2000-01-01",
        "outlet": item["venue"] or "CSMAP",
        "link": item["link"],
        "excerpt": item["excerpt"],
        "_source": "csmap",
    }


def build_media_proposal(item: dict) -> dict:
    return {
        "outlet": item["venue"] or "Unknown",
        "title": item["title"],
        "date": item["date"] or "",
        "url": item["link"],
        "_source": "csmap",
    }


# ---------------------------------------------------------------------------
# Main scan function
# ---------------------------------------------------------------------------

def scan(verbose: bool = True) -> dict:
    """
    Scan CSMAP for new Tucker content.

    Returns:
        {
          "publications": [...],
          "commentary": [...],
          "media": [...],
        }
    """
    existing_pubs = load_existing_publication_titles()
    existing_commentary = load_existing_commentary_titles()
    existing_media = load_existing_media_titles()

    all_items = fetch_all_profile_items()

    pub_proposals = []
    commentary_proposals = []
    media_proposals = []

    for item in all_items:
        t = normalize_title(item["title"])
        if item["type"] == "publications":
            if t not in existing_pubs:
                pub_proposals.append(build_publication_proposal(item))
        elif item["type"] == "commentary":
            if t not in existing_commentary:
                commentary_proposals.append(build_commentary_proposal(item))
        elif item["type"] == "media":
            if t not in existing_media:
                media_proposals.append(build_media_proposal(item))

    if verbose:
        total = len(pub_proposals) + len(commentary_proposals) + len(media_proposals)
        if total == 0:
            console.print("[green]No new CSMAP content found.[/green]")
        else:
            console.print(f"[bold yellow]{total} potential new item(s) found on CSMAP:[/bold yellow]")
            if pub_proposals:
                t = Table(title="New Publications")
                t.add_column("Year", width=6)
                t.add_column("Title")
                t.add_column("Venue")
                for p in pub_proposals:
                    t.add_row(str(p["year"]), p["title"], p["venue"])
                console.print(t)
            if commentary_proposals:
                t = Table(title="New Commentary")
                t.add_column("Date", width=12)
                t.add_column("Title")
                t.add_column("Outlet")
                for c in commentary_proposals:
                    t.add_row(c["date"], c["title"], c["outlet"])
                console.print(t)
            if media_proposals:
                t = Table(title="New Media Mentions")
                t.add_column("Date", width=12)
                t.add_column("Title")
                t.add_column("Outlet")
                for m in media_proposals:
                    t.add_row(m["date"], m["title"], m["outlet"])
                console.print(t)

    return {
        "publications": pub_proposals,
        "commentary": commentary_proposals,
        "media": media_proposals,
    }


if __name__ == "__main__":
    scan()
