"""
add_publication.py - Add a new publication to the website.

Optionally fetches a URL (journal page, arXiv, SSRN, OSF, etc.) to pre-fill
metadata, then prompts for all publication-specific fields: authors, type,
venue, year, tags, links, abstract, and DOI. Writes the entry to
_data/publications.yml and optionally pushes to GitHub.

Usage:
    python3 scripts/add_publication.py <URL>   # pre-fill from URL
    python3 scripts/add_publication.py          # enter everything manually
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime

import requests
import warnings
import yaml
from bs4 import BeautifulSoup
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

warnings.filterwarnings("ignore")

sys.path.insert(0, os.path.dirname(__file__))
from config import PUBLICATIONS_YAML, REPO_ROOT

console = Console()
HEADERS = {
    "User-Agent": "Mozilla/5.0 (academic website updater; contact: joshua.tucker@nyu.edu)"
}

# All known topic tags used on the site
KNOWN_TAGS = [
    "Data Science Methodology",
    "Elections & Voting",
    "Elite & Mass Political Behavior",
    "Foreign Influence Campaigns",
    "Media Consumption",
    "Online Information Environment",
    "Partisanship",
    "Political Polarization",
    "Politics of Authoritarianism",
    "Post-Communist Politics",
    "Protest",
    "Public Opinion",
]

PUB_TYPES = [
    "journal_article",
    "working_paper",
    "under_review",
    "book_chapter",
    "book",
    "other",
]


# ---------------------------------------------------------------------------
# URL metadata extraction
# ---------------------------------------------------------------------------

def _parse_iso_or_common(date_raw: str) -> str:
    if not date_raw:
        return ""
    iso_m = re.match(r"(\d{4}-\d{2}-\d{2})", date_raw)
    if iso_m:
        return iso_m.group(1)
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%d %B %Y"):
        try:
            return datetime.strptime(date_raw.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


def _extract_year(soup: BeautifulSoup, url: str) -> str:
    """Extract a 4-digit year from metadata or URL."""
    # JSON-LD
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            if not isinstance(data, dict):
                continue
            for key in ("datePublished", "dateCreated", "copyrightYear"):
                val = data.get(key, "")
                if val:
                    m = re.search(r"(20\d{2})", str(val))
                    if m:
                        return m.group(1)
        except (json.JSONDecodeError, AttributeError):
            continue
    # Meta tags
    for prop in ("article:published_time", "citation_publication_date", "DC.date"):
        tag = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
        if tag and tag.get("content"):
            m = re.search(r"(20\d{2})", tag["content"])
            if m:
                return m.group(1)
    # URL — standard date pattern /2025/02/
    m = re.search(r"/(20\d{2})[/\-]", url)
    if m:
        return m.group(1)
    # arXiv-style: abs/2201.xxxxx → year 2022
    m = re.search(r"/abs/(20\d{2})\d{2}\.", url)
    if m:
        return m.group(1)
    return ""


def _extract_abstract(soup: BeautifulSoup) -> str:
    """Try to find an abstract on the page."""
    # citation_abstract meta (used by many journals and preprint servers)
    for name in ("citation_abstract", "DC.description", "description"):
        tag = soup.find("meta", attrs={"name": name})
        if tag and tag.get("content") and len(tag["content"]) > 80:
            return tag["content"].strip()
    # OG description
    tag = soup.find("meta", property="og:description")
    if tag and tag.get("content") and len(tag["content"]) > 80:
        return tag["content"].strip()
    # Look for a div/section with 'abstract' in its id or class
    for el in soup.find_all(id=re.compile(r"abstract", re.I)):
        text = el.get_text(strip=True)
        if len(text) > 80:
            return text[:2000]
    for el in soup.find_all(class_=re.compile(r"abstract", re.I)):
        text = el.get_text(strip=True)
        if len(text) > 80:
            return text[:2000]
    return ""


def _extract_authors(soup: BeautifulSoup) -> str:
    """Try to find author list on the page (citation_author meta tags)."""
    authors = []
    for tag in soup.find_all("meta", attrs={"name": "citation_author"}):
        if tag.get("content"):
            authors.append(tag["content"].strip())
    if authors:
        return ", ".join(authors)
    # Try og:article:author or similar
    tag = soup.find("meta", attrs={"name": "author"})
    if tag and tag.get("content"):
        return tag["content"].strip()
    return ""


def _extract_venue(soup: BeautifulSoup) -> str:
    """Try to find journal/venue name."""
    for name in ("citation_journal_title", "citation_conference_title",
                 "citation_publisher", "DC.publisher"):
        tag = soup.find("meta", attrs={"name": name})
        if tag and tag.get("content"):
            return tag["content"].strip()
    # og:site_name as fallback
    tag = soup.find("meta", property="og:site_name")
    if tag and tag.get("content"):
        return tag["content"].strip()
    return ""


def _extract_doi(soup: BeautifulSoup, url: str) -> str:
    """Try to find a DOI."""
    for name in ("citation_doi", "DC.identifier", "prism.doi"):
        tag = soup.find("meta", attrs={"name": name})
        if tag and tag.get("content"):
            doi = tag["content"].strip().lstrip("https://doi.org/").lstrip("doi:")
            return doi
    # DOI in URL
    m = re.search(r"10\.\d{4,}/\S+", url)
    if m:
        return m.group(0).rstrip(".")
    return ""


def fetch_publication_metadata(url: str) -> dict:
    """Fetch a publication URL and extract as much metadata as possible."""
    console.print(f"[cyan]Fetching: {url}[/cyan]")
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        console.print(f"[red]Failed to fetch URL: {e}[/red]")
        return {}

    soup = BeautifulSoup(resp.text, "html.parser")

    # Title
    title_tag = (soup.find("meta", attrs={"name": "citation_title"})
                 or soup.find("meta", property="og:title"))
    title = (title_tag["content"].strip() if title_tag and title_tag.get("content")
             else (soup.title.string.strip() if soup.title else ""))

    return {
        "title": title,
        "authors": _extract_authors(soup),
        "year": _extract_year(soup, url),
        "venue": _extract_venue(soup),
        "abstract": _extract_abstract(soup),
        "doi": _extract_doi(soup, url),
        "url": url,
    }


# ---------------------------------------------------------------------------
# Interactive prompts
# ---------------------------------------------------------------------------

def prompt_tags() -> list:
    """Show numbered tag list and let user pick any combination."""
    console.print("\n[bold]Select topic tags[/bold] (comma-separated numbers, or press Enter to skip):")
    for i, tag in enumerate(KNOWN_TAGS, 1):
        console.print(f"  {i:2d}) {tag}")
    console.print("   0) Add a new tag not in the list")

    raw = Prompt.ask("Tags", default="")
    if not raw.strip():
        return []

    chosen = []
    for part in raw.split(","):
        part = part.strip()
        if part == "0":
            new_tag = Prompt.ask("New tag name")
            if new_tag.strip():
                chosen.append(new_tag.strip())
        elif part.isdigit() and 1 <= int(part) <= len(KNOWN_TAGS):
            chosen.append(KNOWN_TAGS[int(part) - 1])
    return chosen


def prompt_links(prefill_url: str = "") -> dict:
    """Ask for each link field."""
    console.print("\n[bold]Links[/bold] (press Enter to leave blank):")
    published = Prompt.ask("Published URL (journal page)", default=prefill_url if prefill_url else "")
    preprint  = Prompt.ask("Preprint URL (arXiv, SSRN, OSF, etc.)", default="")
    appendix  = Prompt.ask("Appendix URL", default="")
    replication = Prompt.ask("Replication data URL", default="")
    return {
        "published": published,
        "preprint": preprint,
        "appendix": appendix,
        "replication": replication,
    }


def prompt_all_fields(prefill: dict) -> dict | None:
    """Walk through all publication fields interactively."""

    console.print(Panel(
        f"[bold]Title:[/bold]   {prefill.get('title', '')}\n"
        f"[bold]Authors:[/bold] {prefill.get('authors', '')}\n"
        f"[bold]Year:[/bold]    {prefill.get('year', '')}\n"
        f"[bold]Venue:[/bold]   {prefill.get('venue', '')}\n"
        f"[bold]DOI:[/bold]     {prefill.get('doi', '')}\n"
        f"[bold]Abstract:[/bold] {(prefill.get('abstract') or '')[:120]}{'...' if len(prefill.get('abstract','')) > 120 else ''}",
        title="Pre-filled from URL" if prefill.get("url") else "New Publication",
        border_style="cyan",
    ))

    # Core fields
    title   = Prompt.ask("Title", default=prefill.get("title", ""))
    authors = Prompt.ask(
        "Authors (e.g. Tucker, Joshua A. and Smith, Jane)",
        default=prefill.get("authors", "Tucker, Joshua A."),
    )
    year_raw = Prompt.ask("Year", default=prefill.get("year", ""))
    try:
        year = int(year_raw)
    except ValueError:
        year = 0

    venue = Prompt.ask("Venue (journal, publisher, or archive)", default=prefill.get("venue", ""))
    vol_issue_pages = Prompt.ask("Volume / Issue / Pages (e.g. Vol. 12, No. 3, pp. 45–67)", default="")
    doi   = Prompt.ask("DOI (just the identifier, not the full URL)", default=prefill.get("doi", ""))

    # Type
    console.print("\n[bold]Publication type:[/bold]")
    for i, t in enumerate(PUB_TYPES, 1):
        console.print(f"  {i}) {t}")
    type_choice = Prompt.ask("Enter number", choices=[str(i) for i in range(1, len(PUB_TYPES) + 1)], default="1")
    pub_type = PUB_TYPES[int(type_choice) - 1]

    # Abstract
    abstract_default = prefill.get("abstract", "")
    if abstract_default:
        keep = Confirm.ask(f"Use pre-filled abstract ({len(abstract_default)} chars)?")
        abstract = abstract_default if keep else Prompt.ask("Abstract")
    else:
        abstract = Prompt.ask("Abstract (paste or leave blank)", default="")

    # Tags
    tags = prompt_tags()

    # Links
    links = prompt_links(prefill_url=prefill.get("url", ""))

    if not title:
        console.print("[red]Title is required.[/red]")
        return None

    # Build ID
    year_for_id = str(year) if year else "0"
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:50]
    pub_id = f"tucker-{year_for_id}-{slug}"

    return {
        "id": pub_id,
        "title": title,
        "authors": authors,
        "year": year,
        "venue": venue,
        "volume_issue_pages": vol_issue_pages,
        "doi": doi,
        "type": pub_type,
        "abstract": abstract,
        "tags": tags,
        "awards": [],
        "links": links,
    }


# ---------------------------------------------------------------------------
# Write + git
# ---------------------------------------------------------------------------

def append_publication(entry: dict) -> None:
    with open(PUBLICATIONS_YAML, "r") as f:
        existing = yaml.safe_load(f) or []
    existing.insert(0, entry)
    with open(PUBLICATIONS_YAML, "w") as f:
        yaml.dump(existing, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    console.print(f"[green]Added to publications.yml[/green]")


def git_commit_and_push(title: str) -> bool:
    msg = f"Add publication: {title[:70]}"
    try:
        subprocess.run(["git", "-C", REPO_ROOT, "add", "."], check=True)
        subprocess.run(["git", "-C", REPO_ROOT, "commit", "-m", msg], check=True)
        subprocess.run(["git", "-C", REPO_ROOT, "push"], check=True)
        console.print("[bold green]Pushed to GitHub successfully.[/bold green]")
        return True
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Git error: {e}[/red]")
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    prefill: dict = {}

    if len(sys.argv) >= 2:
        prefill = fetch_publication_metadata(sys.argv[1])
        if not prefill:
            console.print("[yellow]Could not fetch URL — continuing with manual entry.[/yellow]")
            prefill = {}
    else:
        console.print("[dim]No URL provided — entering all fields manually.[/dim]")

    entry = prompt_all_fields(prefill)
    if entry is None:
        console.print("[yellow]Cancelled.[/yellow]")
        return

    # Preview the final entry
    console.print(Panel(
        f"[bold]ID:[/bold]      {entry['id']}\n"
        f"[bold]Title:[/bold]   {entry['title']}\n"
        f"[bold]Authors:[/bold] {entry['authors']}\n"
        f"[bold]Year:[/bold]    {entry['year']}\n"
        f"[bold]Venue:[/bold]   {entry['venue']}\n"
        f"[bold]Type:[/bold]    {entry['type']}\n"
        f"[bold]Tags:[/bold]    {', '.join(entry['tags']) or '(none)'}\n"
        f"[bold]Published:[/bold] {entry['links']['published'] or '(none)'}\n"
        f"[bold]Preprint:[/bold]  {entry['links']['preprint'] or '(none)'}",
        title="Entry Preview",
        border_style="green",
    ))

    if not Confirm.ask("Save this entry?"):
        console.print("[yellow]Cancelled.[/yellow]")
        return

    append_publication(entry)

    if Confirm.ask("Commit and push to GitHub?"):
        git_commit_and_push(entry["title"])
    else:
        console.print("[yellow]Saved locally. Push manually when ready:[/yellow]")
        console.print("  git -C ~/Sites/tucker-academic-site add . && git commit -m 'Add publication' && git push")


if __name__ == "__main__":
    main()
