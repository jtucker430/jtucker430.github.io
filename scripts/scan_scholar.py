"""
scan_scholar.py - Scan Google Scholar for new publications by Joshua A. Tucker.

Compares Scholar results against the existing _data/publications.yml and
returns a list of proposed new entries.

Usage (standalone):
    python3 scripts/scan_scholar.py
"""

import sys
import re
import yaml
from scholarly import scholarly
from rich.console import Console
from rich.table import Table

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from config import SCHOLAR_AUTHOR_ID, PUBLICATIONS_YAML

console = Console()


def normalize_title(title: str) -> str:
    """Lowercase, strip punctuation and whitespace for fuzzy comparison."""
    return re.sub(r"[^a-z0-9 ]", "", title.lower()).strip()


def load_existing_titles() -> set:
    """Load normalized titles from publications.yml."""
    with open(PUBLICATIONS_YAML, "r") as f:
        pubs = yaml.safe_load(f)
    return {normalize_title(p["title"]) for p in pubs if p.get("title")}


def fetch_scholar_publications() -> list:
    """Fetch all publications for the author from Google Scholar."""
    console.print("[bold cyan]Connecting to Google Scholar...[/bold cyan]")
    author = scholarly.search_author_id(SCHOLAR_AUTHOR_ID)
    author = scholarly.fill(author, sections=["publications"])
    pubs = author.get("publications", [])
    console.print(f"[green]Found {len(pubs)} publications on Scholar.[/green]")
    return pubs


def make_slug(title: str, year: int) -> str:
    """Generate a YAML id slug from title and year."""
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return f"tucker-{year}-{slug[:50]}"


def build_proposal(pub: dict) -> dict:
    """Convert a scholarly publication dict into a proposal for publications.yml."""
    bib = pub.get("bib", {})
    title = bib.get("title", "Unknown Title")
    year = bib.get("pub_year", "")
    try:
        year_int = int(year)
    except (ValueError, TypeError):
        year_int = 0
    authors = bib.get("author", "Tucker, Joshua A.")
    venue = bib.get("venue", bib.get("journal", bib.get("publisher", "")))
    volume = bib.get("volume", "")
    number = bib.get("number", "")
    pages = bib.get("pages", "")
    vol_issue_pages = ""
    if volume or number or pages:
        parts = []
        if volume:
            parts.append(f"Vol. {volume}")
        if number:
            parts.append(f"No. {number}")
        if pages:
            parts.append(f"pp. {pages}")
        vol_issue_pages = ", ".join(parts)

    scholar_url = f"https://scholar.google.com/scholar?q={title.replace(' ', '+')}"
    pub_url = pub.get("pub_url", scholar_url)

    return {
        "id": make_slug(title, year_int),
        "title": title,
        "authors": authors,
        "year": year_int,
        "venue": venue,
        "volume_issue_pages": vol_issue_pages,
        "doi": "",
        "type": "journal_article",
        "abstract": bib.get("abstract", ""),
        "tags": [],
        "awards": [],
        "links": {
            "published": pub_url if pub_url != scholar_url else "",
            "preprint": "",
            "appendix": "",
            "replication": "",
        },
        "_scholar_url": scholar_url,  # for display only, not written to YAML
    }


def scan(verbose: bool = True) -> list:
    """
    Main scan function. Returns a list of proposal dicts for new publications.
    Each proposal is a dict ready to be appended to publications.yml (minus _scholar_url).
    """
    existing = load_existing_titles()
    console.print(f"[dim]Loaded {len(existing)} existing publications from YAML.[/dim]")

    scholar_pubs = fetch_scholar_publications()

    proposals = []
    for pub in scholar_pubs:
        title = pub.get("bib", {}).get("title", "")
        if not title:
            continue
        if normalize_title(title) not in existing:
            proposals.append(build_proposal(pub))

    if verbose:
        if proposals:
            table = Table(title=f"[bold yellow]{len(proposals)} potential new publication(s) found on Scholar[/bold yellow]")
            table.add_column("#", style="dim", width=4)
            table.add_column("Year", width=6)
            table.add_column("Title", no_wrap=False)
            table.add_column("Venue", no_wrap=False)
            for i, p in enumerate(proposals, 1):
                table.add_row(str(i), str(p["year"]), p["title"], p["venue"])
            console.print(table)
        else:
            console.print("[green]No new publications found on Scholar.[/green]")

    return proposals


if __name__ == "__main__":
    scan()
