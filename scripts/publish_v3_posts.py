#!/usr/bin/env python3
"""
Publish v3 posts to Ghost (Flash, Earnings, Deep Dive)

Usage:
    python scripts/publish_v3_posts.py --mode test
    python scripts/publish_v3_posts.py --mode prod --confirm-high-risk
"""

import json
import os
import sys
from pathlib import Path

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

load_dotenv()

console = Console()


def load_post(post_type: str) -> dict:
    """Load v3 preview post JSON"""
    json_path = Path(f"out/post_{post_type}_v3_preview.json")
    html_path = Path(f"out/post_{post_type}_v3_preview.html")

    if not json_path.exists():
        raise FileNotFoundError(f"Post JSON not found: {json_path}")

    with open(json_path) as f:
        data = json.load(f)

    # Load HTML if exists
    if html_path.exists():
        with open(html_path) as f:
            data["html"] = f.read()
    else:
        raise FileNotFoundError(f"Post HTML not found: {html_path}")

    return data


def publish_to_ghost(post_data: dict, mode: str, send_email: bool = False, visibility: str = "members") -> dict:
    """Publish a single post to Ghost

    Args:
        post_data: Post data dict
        mode: "draft" or "publish"
        send_email: Whether to send newsletter
        visibility: "public", "members", or "paid"
    """
    from src.publishers.ghost_admin import GhostPublisher
    from src.writers.codex_runner import PostOutput

    # Convert to PostOutput format
    post = PostOutput(
        meta=post_data.get("meta", {}),
        title=post_data.get("title", ""),
        title_candidates=post_data.get("headline_variants", {}).get("zh", []),
        slug=post_data.get("slug", ""),
        excerpt=post_data.get("excerpt", ""),
        tldr=post_data.get("tldr", []),
        sections={},
        markdown="",
        html=post_data.get("html", ""),
        tags=post_data.get("tags", []),
        tickers_mentioned=[s.get("ticker") for s in post_data.get("key_stocks", [])],
        theme=post_data.get("meta", {}).get("primary_theme", {}),
        what_to_watch=[],
        sources=post_data.get("sources", []),
        disclosures={"not_investment_advice": True},
    )

    with GhostPublisher() as publisher:
        result = publisher.publish(
            post,
            mode=mode,
            send_newsletter=send_email,
            visibility=visibility,
        )

    return {
        "success": result.success,
        "url": result.url,
        "error": result.error,
        "newsletter_sent": result.newsletter_sent,
    }


@click.command()
@click.option("--mode", "-m", default="test", type=click.Choice(["test", "prod"]),
              help="Publish mode")
@click.option("--posts", "-p", multiple=True, type=click.Choice(["flash", "earnings", "deep"]),
              help="Specific posts to publish (default: all)")
@click.option("--confirm-high-risk", is_flag=True, help="Confirm high-risk segment")
@click.option("--dry-run", is_flag=True, help="Just show what would be published")
@click.option("--visibility", "-v", default="members", type=click.Choice(["public", "members", "paid"]),
              help="Post visibility (public/members/paid)")
def main(mode: str, posts: tuple, confirm_high_risk: bool, dry_run: bool, visibility: str):
    """Publish v3 posts (Flash, Earnings, Deep Dive) to Ghost"""

    console.print(Panel.fit(
        f"[bold]Publish v3 Preview Posts to Ghost[/bold]\n"
        f"Mode: {mode}\n"
        f"Posts: {', '.join(posts) if posts else 'all'}\n"
        f"Visibility: {visibility}",
        border_style="blue",
    ))

    if mode == "test":
        console.print("[yellow]TEST MODE - Publishing to internal only[/yellow]\n")
    else:
        console.print("[red]PRODUCTION MODE[/red]\n")
        if not confirm_high_risk:
            console.print("[yellow]Add --confirm-high-risk for newsletter send[/yellow]\n")

    # Determine which posts to publish
    post_types = list(posts) if posts else ["flash", "earnings", "deep"]

    # Load posts
    loaded_posts = {}
    for post_type in post_types:
        try:
            loaded_posts[post_type] = load_post(post_type)
            html_len = len(loaded_posts[post_type].get("html", ""))
            console.print(f"  Loaded {post_type}: {loaded_posts[post_type].get('title', 'N/A')[:50]}... (HTML: {html_len} chars)")
        except FileNotFoundError as e:
            console.print(f"  [yellow]{post_type}: {e}[/yellow]")

    if not loaded_posts:
        console.print("[red]No posts to publish![/red]")
        return

    # Show what will be published
    console.print("\n[bold]Posts to publish:[/bold]")
    table = Table()
    table.add_column("Type")
    table.add_column("Slug")
    table.add_column("Title")
    table.add_column("Email")

    for post_type, post_data in loaded_posts.items():
        send_email = (post_type == "flash" and mode == "prod" and confirm_high_risk)
        table.add_row(
            post_type,
            post_data.get("slug", "N/A"),
            post_data.get("title", "N/A")[:40] + "...",
            "Yes" if send_email else "No",
        )

    console.print(table)

    if dry_run:
        console.print("\n[yellow]DRY RUN - No actual publishing[/yellow]")
        return

    # Confirm
    if not click.confirm("\nProceed with publishing?"):
        console.print("Cancelled.")
        return

    # Publish
    console.print("\n[bold]Publishing...[/bold]")
    results = {}

    # Publish order: earnings, deep first (no email), then flash (with email)
    publish_order = ["earnings", "deep", "flash"]

    for post_type in publish_order:
        if post_type not in loaded_posts:
            continue

        post_data = loaded_posts[post_type]
        send_email = (post_type == "flash" and mode == "prod" and confirm_high_risk)

        console.print(f"  Publishing {post_type}...")

        try:
            result = publish_to_ghost(
                post_data,
                mode="publish" if mode == "prod" else "draft",
                send_email=send_email,
                visibility=visibility,
            )
            results[post_type] = result

            if result["success"]:
                console.print(f"    [green]{result['url']}[/green]")
                if result["newsletter_sent"]:
                    console.print("      [cyan]Newsletter sent[/cyan]")
            else:
                console.print(f"    [red]{result['error']}[/red]")

        except Exception as e:
            console.print(f"    [red]Error: {e}[/red]")
            results[post_type] = {"success": False, "error": str(e)}

    # Summary
    console.print("\n[bold]Summary:[/bold]")
    success_count = sum(1 for r in results.values() if r.get("success"))
    console.print(f"  Published: {success_count}/{len(results)}")

    # Save results
    results_path = Path("out/publish_v3_results.json")
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    console.print(f"  Results saved to: {results_path}")


if __name__ == "__main__":
    main()
