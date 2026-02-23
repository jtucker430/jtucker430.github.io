"""
check_updates.py - Master update scanner.

Runs both scan_scholar.py and scan_csmap.py, presents all proposals to the
user for review, writes approved items to the data files, then commits and
pushes to GitHub.

Usage:
    python3 scripts/check_updates.py [--scholar-only] [--csmap-only] [--dry-run]
"""

import sys
import os
import re
import subprocess
from datetime import datetime, date

import yaml
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Prompt, Confirm

sys.path.insert(0, os.path.dirname(__file__))
from config import PUBLICATIONS_YAML, SITE_CONTENT_YAML, COMMENTARY_DIR, REPO_ROOT

console = Console()

# Path to the "snoozed / ignored" list so the user doesn't see the same item twice
IGNORE_FILE = os.path.join(REPO_ROOT, "scripts", ".scan_ignore.yml")


# ---------------------------------------------------------------------------
# Ignore list helpers
# ---------------------------------------------------------------------------

def load_ignore_list() -> set:
    if not os.path.exists(IGNORE_FILE):
        return set()
    with open(IGNORE_FILE, "r") as f:
        data = yaml.safe_load(f) or []
    return set(data)


def save_ignore_list(ignore_set: set) -> None:
    with open(IGNORE_FILE, "w") as f:
        yaml.dump(sorted(ignore_set), f, allow_unicode=True)


def normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", title.lower()).strip()


# ---------------------------------------------------------------------------
# Write helpers (shared with add_from_url.py)
# ---------------------------------------------------------------------------

def append_publication(entry: dict) -> None:
    """Append a publication dict to publications.yml."""
    # Strip internal-only keys
    clean = {k: v for k, v in entry.items() if not k.startswith("_")}
    with open(PUBLICATIONS_YAML, "r") as f:
        existing = yaml.safe_load(f) or []
    existing.insert(0, clean)
    with open(PUBLICATIONS_YAML, "w") as f:
        yaml.dump(existing, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def append_commentary(entry: dict) -> str:
    """Write a new _commentary markdown file. Returns the file path."""
    d = entry.get("date") or datetime.today().strftime("%Y-%m-%d")
    slug = re.sub(r"[^a-z0-9]+", "-", entry["title"].lower()).strip("-")[:50]
    filename = f"{d}-{slug}.md"
    filepath = os.path.join(COMMENTARY_DIR, filename)

    front_matter = {
        "title": entry["title"],
        "date": d,
        "outlet": entry.get("outlet", ""),
        "link": entry.get("link", ""),
        "excerpt": entry.get("excerpt", ""),
    }
    content = "---\n" + yaml.dump(front_matter, allow_unicode=True, default_flow_style=False) + "---\n"
    with open(filepath, "w") as f:
        f.write(content)
    return filepath


def append_media_press(entry: dict) -> None:
    """Prepend a press entry to site_content.yml media.press."""
    clean = {k: v for k, v in entry.items() if not k.startswith("_")}
    with open(SITE_CONTENT_YAML, "r") as f:
        data = yaml.safe_load(f)
    data.setdefault("media", {}).setdefault("press", []).insert(0, clean)
    with open(SITE_CONTENT_YAML, "w") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


# ---------------------------------------------------------------------------
# Review loop
# ---------------------------------------------------------------------------

CONTENT_TYPE_LABELS = {
    "publications": ("publication", "publications.yml"),
    "commentary": ("commentary", "_commentary/"),
    "media": ("media mention", "site_content.yml → media.press"),
}


def review_proposals(proposals_by_type: dict, dry_run: bool = False) -> tuple[list, list]:
    """
    Interactively review all proposals.

    Returns:
        (approved_list, ignored_keys)
    Each item in approved_list is (content_type, entry_dict).
    """
    ignore_list = load_ignore_list()
    approved = []
    new_ignores = []

    total = sum(len(v) for v in proposals_by_type.values())
    if total == 0:
        console.print("[bold green]Everything is up to date! No new content found.[/bold green]")
        return [], []

    console.print(f"\n[bold yellow]Found {total} proposed new item(s) to review.[/bold yellow]")
    console.print("[dim]For each item: [y] add it, [n] skip this time, [s] skip always (snooze)[/dim]\n")

    for content_type, proposals in proposals_by_type.items():
        if not proposals:
            continue
        label, target = CONTENT_TYPE_LABELS[content_type]

        for i, entry in enumerate(proposals, 1):
            key = normalize_title(entry.get("title", ""))
            if key in ignore_list:
                continue

            console.print(Panel(
                f"[bold]Title:[/bold]   {entry.get('title', '')}\n"
                f"[bold]Type:[/bold]    {label} → {target}\n"
                f"[bold]Date:[/bold]    {entry.get('date', entry.get('year', ''))}\n"
                f"[bold]Outlet/Venue:[/bold] {entry.get('venue', entry.get('outlet', ''))}\n"
                f"[bold]URL:[/bold]     {entry.get('link', entry.get('links', {}).get('published', '') if isinstance(entry.get('links'), dict) else '')}",
                title=f"Item {i} of {len(proposals)} ({content_type})",
                border_style="yellow",
            ))

            action = Prompt.ask("Action", choices=["y", "n", "s"], default="n")

            if action == "y":
                approved.append((content_type, entry))
                console.print("[green]  ✓ Approved[/green]")
            elif action == "s":
                new_ignores.append(key)
                console.print("[dim]  Snoozed (won't appear again)[/dim]")
            else:
                console.print("[dim]  Skipped[/dim]")

    # Persist new ignores
    if new_ignores:
        updated = ignore_list | set(new_ignores)
        save_ignore_list(updated)

    return approved, new_ignores


# ---------------------------------------------------------------------------
# Apply approved items
# ---------------------------------------------------------------------------

def apply_approved(approved: list, dry_run: bool = False) -> list:
    """Write approved entries to data files. Returns list of changed file paths."""
    changed_files = []

    for content_type, entry in approved:
        if dry_run:
            console.print(f"[dim][DRY RUN] Would add {content_type}: {entry.get('title', '')}[/dim]")
            continue

        if content_type == "publications":
            append_publication(entry)
            changed_files.append(PUBLICATIONS_YAML)
            console.print(f"[green]Added publication: {entry.get('title', '')[:60]}[/green]")
        elif content_type == "commentary":
            path = append_commentary(entry)
            changed_files.append(path)
            console.print(f"[green]Created commentary: {path}[/green]")
        elif content_type == "media":
            append_media_press(entry)
            changed_files.append(SITE_CONTENT_YAML)
            console.print(f"[green]Added media mention: {entry.get('title', '')[:60]}[/green]")

    return list(set(changed_files))


# ---------------------------------------------------------------------------
# Git
# ---------------------------------------------------------------------------

def git_commit_and_push(n_items: int) -> bool:
    today = date.today().strftime("%Y-%m-%d")
    msg = f"Auto-update {today}: {n_items} new item(s) added"
    try:
        subprocess.run(["git", "-C", REPO_ROOT, "add", "."], check=True)
        subprocess.run(["git", "-C", REPO_ROOT, "commit", "-m", msg], check=True)
        subprocess.run(["git", "-C", REPO_ROOT, "push"], check=True)
        console.print(f"[bold green]Pushed to GitHub: '{msg}'[/bold green]")
        return True
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Git error: {e}[/red]")
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    args = sys.argv[1:]
    scholar_only = "--scholar-only" in args
    csmap_only = "--csmap-only" in args
    dry_run = "--dry-run" in args

    if dry_run:
        console.print("[bold magenta]DRY RUN mode — no files will be changed.[/bold magenta]\n")

    proposals = {"publications": [], "commentary": [], "media": []}

    # --- Scholar scan ---
    if not csmap_only:
        try:
            from scan_scholar import scan as scholar_scan
            console.rule("[bold cyan]Scanning Google Scholar[/bold cyan]")
            scholar_proposals = scholar_scan(verbose=False)
            proposals["publications"].extend(scholar_proposals)
            console.print(f"[dim]Scholar: {len(scholar_proposals)} potential new publication(s)[/dim]")
        except Exception as e:
            console.print(f"[red]Scholar scan failed: {e}[/red]")

    # --- CSMAP scan ---
    if not scholar_only:
        try:
            from scan_csmap import scan as csmap_scan
            console.rule("[bold cyan]Scanning CSMAP[/bold cyan]")
            csmap_results = csmap_scan(verbose=False)
            proposals["publications"].extend(csmap_results.get("publications", []))
            proposals["commentary"].extend(csmap_results.get("commentary", []))
            proposals["media"].extend(csmap_results.get("media", []))
            total_csmap = sum(len(v) for v in csmap_results.values())
            console.print(f"[dim]CSMAP: {total_csmap} potential new item(s)[/dim]")
        except Exception as e:
            console.print(f"[red]CSMAP scan failed: {e}[/red]")

    # Deduplicate across sources by normalized title (Scholar + CSMAP may overlap)
    seen_keys = set()
    for content_type in proposals:
        deduped = []
        for entry in proposals[content_type]:
            key = normalize_title(entry.get("title", ""))
            if key not in seen_keys:
                seen_keys.add(key)
                deduped.append(entry)
        proposals[content_type] = deduped

    # --- Review loop ---
    console.rule("[bold]Review Proposed Additions[/bold]")
    approved, snoozed = review_proposals(proposals, dry_run=dry_run)

    if not approved:
        console.print("[green]No items approved. Nothing to commit.[/green]")
        return

    # --- Apply ---
    console.rule("[bold]Applying Changes[/bold]")
    changed = apply_approved(approved, dry_run=dry_run)

    if not dry_run and changed:
        if Confirm.ask(f"\nCommit and push {len(approved)} item(s) to GitHub?"):
            git_commit_and_push(len(approved))
        else:
            console.print("[yellow]Changes saved locally. Push manually when ready.[/yellow]")


if __name__ == "__main__":
    main()
