"""
add_from_url.py - Add a media mention or commentary piece by URL.

Fetches the page, extracts title/date/outlet/excerpt, and writes the entry
to the appropriate data file. For publications, use add_publication.py instead.

Usage:
    python3 scripts/add_from_url.py <URL>   # pre-fill from URL
    python3 scripts/add_from_url.py          # enter everything manually
"""

from __future__ import annotations

import sys
import os
import re
import subprocess
from datetime import datetime

import requests
import yaml
from bs4 import BeautifulSoup
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm

sys.path.insert(0, os.path.dirname(__file__))
from config import SITE_CONTENT_YAML, COMMENTARY_DIR, REPO_ROOT

console = Console()
HEADERS = {
    "User-Agent": "Mozilla/5.0 (academic website updater; contact: joshua.tucker@nyu.edu)"
}


# ---------------------------------------------------------------------------
# Metadata extraction
# ---------------------------------------------------------------------------

def _parse_iso_or_common(date_raw: str) -> str:
    """Try to parse an ISO or human-readable date string → 'YYYY-MM-DD'."""
    if not date_raw:
        return ""
    # ISO-style: 2026-02-18T12:21:04+0000 or 2026-02-18
    iso_m = re.match(r"(\d{4}-\d{2}-\d{2})", date_raw)
    if iso_m:
        return iso_m.group(1)
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%d %B %Y"):
        try:
            return datetime.strptime(date_raw.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


def _extract_date(soup: BeautifulSoup, url: str) -> str:
    """
    Try multiple signals to extract a publication date, in priority order:
    1. article:published_time meta property (used by many news sites)
    2. og:article:published_time
    3. Common date-named meta tags (parsely-pub-date, sailthru.date, etc.)
    4. JSON-LD structured data (datePublished / uploadDate)
    5. <time> HTML element (datetime attribute or text)
    6. Date pattern in the URL itself (e.g. /2026/02/18/)
    """
    import json

    def meta_content(*props):
        for prop in props:
            tag = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
            if tag and tag.get("content"):
                return tag["content"].strip()
        return ""

    # 1 & 2: article:published_time (with or without "og:" prefix)
    raw = meta_content("article:published_time", "og:article:published_time",
                       "article:modified_time", "parsely-pub-date",
                       "sailthru.date", "DC.date", "pubdate", "published_time")
    date_str = _parse_iso_or_common(raw)
    if date_str:
        return date_str

    # 3: JSON-LD structured data
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            if not isinstance(data, dict):
                continue
            raw = (data.get("datePublished") or data.get("dateCreated")
                   or data.get("uploadDate") or "")
            date_str = _parse_iso_or_common(raw)
            if date_str:
                return date_str
        except (json.JSONDecodeError, AttributeError):
            continue

    # 4: <time> element
    time_el = soup.find("time")
    if time_el:
        raw = time_el.get("datetime") or time_el.get_text(strip=True)
        date_str = _parse_iso_or_common(raw)
        if date_str:
            return date_str

    # 5: Date pattern in URL — e.g. /2026/02/18/ or /2026-02-18/
    url_m = re.search(r"/(20\d{2})[/-](\d{2})[/-](\d{2})[/-]", url)
    if url_m:
        return f"{url_m.group(1)}-{url_m.group(2)}-{url_m.group(3)}"

    return ""


def fetch_metadata(url: str) -> dict:
    """Fetch a URL and extract Open Graph / meta tags / JSON-LD / page title."""
    console.print(f"[cyan]Fetching: {url}[/cyan]")
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        console.print(f"[red]Failed to fetch URL: {e}[/red]")
        return {}

    soup = BeautifulSoup(resp.text, "html.parser")

    def meta(prop=None, name=None):
        """Find a meta tag by property or name attribute."""
        tag = None
        if prop:
            tag = soup.find("meta", property=prop)
        if not tag and name:
            tag = soup.find("meta", attrs={"name": name})
        return tag["content"].strip() if tag and tag.get("content") else ""

    title = meta("og:title") or (soup.title.string.strip() if soup.title else "")
    description = meta("og:description", name="description")
    site_name = meta("og:site_name")

    # --- Date extraction (try multiple sources in priority order) ---
    date_str = _extract_date(soup, url)

    # Outlet / publisher name
    outlet = site_name
    if not outlet:
        # Try domain name as fallback
        m = re.search(r"https?://(?:www\.)?([^/]+)", url)
        if m:
            outlet = m.group(1).split(".")[0].capitalize()

    return {
        "title": title,
        "description": description,
        "outlet": outlet,
        "date": date_str,
        "url": url,
    }


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------

def slug_from_title(date: str, title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:50]
    return f"{date}-{slug}"


def append_commentary(meta: dict) -> str:
    """Write a new commentary markdown file and return its path."""
    date = meta["date"] or datetime.today().strftime("%Y-%m-%d")
    filename = slug_from_title(date, meta["title"]) + ".md"
    filepath = os.path.join(COMMENTARY_DIR, filename)

    front_matter = {
        "title": meta["title"],
        "date": date,
        "outlet": meta["outlet"],
        "link": meta["url"],
        "excerpt": meta["description"],
    }
    content = "---\n" + yaml.dump(front_matter, allow_unicode=True, default_flow_style=False) + "---\n"

    with open(filepath, "w") as f:
        f.write(content)
    console.print(f"[green]Created: {filepath}[/green]")
    return filepath


def append_media_press(meta: dict) -> None:
    """Append a press entry to site_content.yml."""
    with open(SITE_CONTENT_YAML, "r") as f:
        data = yaml.safe_load(f)

    entry = {
        "outlet": meta["outlet"],
        "title": meta["title"],
        "date": meta["date"],
        "url": meta["url"],
    }
    data.setdefault("media", {}).setdefault("press", []).insert(0, entry)

    with open(SITE_CONTENT_YAML, "w") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    console.print(f"[green]Added media mention to site_content.yml[/green]")


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def git_commit_and_push(message: str) -> bool:
    try:
        subprocess.run(["git", "-C", REPO_ROOT, "add", "."], check=True)
        subprocess.run(["git", "-C", REPO_ROOT, "commit", "-m", message], check=True)
        subprocess.run(["git", "-C", REPO_ROOT, "push"], check=True)
        console.print("[bold green]Pushed to GitHub successfully.[/bold green]")
        return True
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Git error: {e}[/red]")
        return False


# ---------------------------------------------------------------------------
# Interactive field editor
# ---------------------------------------------------------------------------

def confirm_and_edit(meta: dict) -> dict | None:
    """Show the extracted metadata and let user edit fields before saving."""
    if meta.get("title"):
        # Pre-filled from URL — show panel and let user confirm or edit
        console.print(Panel(
            f"[bold]Title:[/bold]   {meta['title']}\n"
            f"[bold]Date:[/bold]    {meta['date']}\n"
            f"[bold]Outlet:[/bold]  {meta['outlet']}\n"
            f"[bold]URL:[/bold]     {meta['url']}\n"
            f"[bold]Excerpt:[/bold] {(meta['description'] or '')[:120]}",
            title="Extracted Metadata",
            border_style="cyan",
        ))
        if Confirm.ask("Does this look right? (you can edit individual fields)"):
            return meta
    else:
        console.print("[dim]No URL provided — entering all fields manually.[/dim]")

    # Prompt for all fields (either editing pre-filled data or fresh manual entry)
    meta["title"]       = Prompt.ask("Title", default=meta.get("title", ""))
    meta["date"]        = Prompt.ask("Date (YYYY-MM-DD)", default=meta.get("date", ""))
    meta["outlet"]      = Prompt.ask("Outlet / publisher", default=meta.get("outlet", ""))
    meta["url"]         = Prompt.ask("URL", default=meta.get("url", ""))
    meta["description"] = Prompt.ask("Excerpt / description", default=meta.get("description", ""))

    if not meta["title"]:
        console.print("[red]Title is required.[/red]")
        return None

    return meta


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    prefill: dict = {}

    if len(sys.argv) >= 2:
        prefill = fetch_metadata(sys.argv[1])
        if not prefill:
            console.print("[yellow]Could not fetch URL — continuing with manual entry.[/yellow]")
            prefill = {"url": sys.argv[1]}
    else:
        console.print("[dim]No URL provided — entering all fields manually.[/dim]")

    meta = confirm_and_edit(prefill)
    if meta is None:
        console.print("[yellow]Cancelled.[/yellow]")
        return

    # Classify content type
    console.print("\n[bold]What type of content is this?[/bold]")
    console.print("  1) Commentary (op-ed, blog post, policy piece)")
    console.print("  2) Media mention (interview, press quote, news article about you)")
    console.print("[dim]  For publications, use: python3 scripts/add_publication.py <URL>[/dim]")
    choice = Prompt.ask("Enter 1 or 2", choices=["1", "2"])

    if choice == "1":
        append_commentary(meta)
        commit_msg = f"Add commentary: {meta['title'][:60]}"
    else:
        append_media_press(meta)
        commit_msg = f"Add media mention: {meta['title'][:60]}"

    if Confirm.ask(f"\nCommit and push to GitHub? ('{commit_msg}')"):
        git_commit_and_push(commit_msg)
    else:
        console.print("[yellow]Changes saved locally. Remember to push when ready.[/yellow]")


if __name__ == "__main__":
    main()
