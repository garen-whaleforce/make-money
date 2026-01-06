"""Daily Deep Brief - CLI Entry Point"""

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import click
import yaml
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from .utils.logging import setup_logging, get_logger
from .utils.time import get_run_id, get_now, format_datetime
from .storage.sqlite_store import SQLiteStore
from .replay.recorder import init_recorder, get_recorder

# Load environment variables
load_dotenv()

console = Console()
logger = get_logger(__name__)


def load_universe(path: str = "config/universe.yaml") -> dict:
    """Load universe configuration."""
    with open(path) as f:
        return yaml.safe_load(f)


def load_runtime_config(path: str = "config/runtime.yaml") -> dict:
    """Load runtime configuration."""
    with open(path) as f:
        return yaml.safe_load(f)


def ensure_directories() -> None:
    """Ensure required directories exist"""
    dirs = ["out", "data", "data/cache", "data/cache/news", "data/cache/fmp"]
    for d in dirs:
        Path(d).mkdir(parents=True, exist_ok=True)


def print_universe_summary(universe: dict) -> None:
    """Print universe summary table"""
    table = Table(title="Coverage Universe")
    table.add_column("Theme", style="cyan")
    table.add_column("Name", style="green")
    table.add_column("Tickers", style="yellow")
    table.add_column("Keywords", style="dim")

    themes = universe.get("themes", {})
    for theme_id, theme_data in themes.items():
        tickers = ", ".join(theme_data.get("tickers", []))
        keywords = ", ".join(theme_data.get("keywords", [])[:3])
        table.add_row(
            theme_id,
            theme_data.get("name", ""),
            tickers,
            keywords + "...",
        )

    console.print(table)

    all_tickers = universe.get("all_tickers", [])
    console.print(f"\n[bold]Total themes:[/bold] {len(themes)}")
    console.print(f"[bold]Total tickers:[/bold] {len(all_tickers)}")


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
@click.option("--log-level", default="INFO", help="Log level")
def cli(verbose: bool, log_level: str) -> None:
    """Daily Deep Brief - 每日美股深度研究筆記自動生成系統"""
    level = "DEBUG" if verbose else log_level
    setup_logging(level=level)


@cli.command()
def init() -> None:
    """Initialize project and verify configuration"""
    console.print(Panel.fit(
        "[bold blue]Daily Deep Brief[/bold blue]\n"
        "每日美股深度研究筆記自動生成系統",
        border_style="blue",
    ))

    console.print("\n[bold]Creating directories...[/bold]")
    ensure_directories()
    console.print("  ✓ out/")
    console.print("  ✓ data/")
    console.print("  ✓ data/cache/")

    console.print("\n[bold]Loading universe configuration...[/bold]")
    try:
        universe = load_universe()
        console.print("  ✓ config/universe.yaml loaded")
        print_universe_summary(universe)
    except FileNotFoundError:
        console.print("  ✗ config/universe.yaml not found", style="red")
        sys.exit(1)

    console.print("\n[bold]Loading runtime configuration...[/bold]")
    try:
        runtime = load_runtime_config()
        console.print("  ✓ config/runtime.yaml loaded")
        console.print(f"  Mode: {runtime.get('execution', {}).get('mode', 'N/A')}")
        console.print(f"  Edition: {runtime.get('execution', {}).get('edition', 'N/A')}")
    except FileNotFoundError:
        console.print("  ✗ config/runtime.yaml not found", style="red")
        sys.exit(1)

    console.print("\n[bold]Checking environment variables...[/bold]")
    required_vars = ["FMP_API_KEY"]
    optional_vars = ["ALPHAVANTAGE_API_KEY", "GHOST_API_URL", "GHOST_ADMIN_API_KEY", "ANTHROPIC_API_KEY"]

    for var in required_vars:
        if os.getenv(var):
            console.print(f"  ✓ {var} is set")
        else:
            console.print(f"  ✗ {var} is NOT set (required)", style="red")

    for var in optional_vars:
        if os.getenv(var):
            console.print(f"  ✓ {var} is set")
        else:
            console.print(f"  ○ {var} is not set (optional)", style="dim")

    console.print("\n[bold green]Initialization complete![/bold green]")


@cli.command()
@click.option("--edition", "-e", default="postclose", help="Edition: premarket/postclose/intraday")
@click.option("--mode", "-m", default="draft", help="Mode: draft/publish")
@click.option("--dry-run", is_flag=True, help="Dry run without publishing")
@click.option("--theme", "-t", help="Force specific theme")
@click.option("--newsletter", "-n", is_flag=True, help="Send newsletter (publish mode only)")
@click.option("--replay-mode", default=None, help="Replay mode: live/record/replay")
@click.option("--fixture-dir", default=None, help="Fixture directory for replay")
def run(edition: str, mode: str, dry_run: bool, theme: str, newsletter: bool,
        replay_mode: str, fixture_dir: str) -> None:
    """Run the daily brief pipeline"""
    from .collectors.google_news_rss import GoogleNewsCollector
    from .enrichers.fmp import FMPEnricher
    from .analyzers.event_scoring import EventScorer
    from .analyzers.research_pack_builder import ResearchPackBuilder
    from .analyzers.valuation_models import ValuationAnalyzer
    from .analyzers.peer_comp import PeerComparisonBuilder
    from .writers.codex_runner import CodexRunner
    from .publishers.ghost_admin import GhostPublisher
    from .quality.quality_gate import QualityGate
    from .quality.run_report import RunReportBuilder

    run_id = get_run_id()
    now = get_now()
    start_time = time.time()

    # Initialize replay recorder if requested
    replay_mode = replay_mode or os.getenv("REPLAY_MODE", "live")
    if replay_mode != "live":
        recorder = init_recorder(
            mode=replay_mode,
            fixture_dir=fixture_dir or "tests/fixtures/api_responses",
            run_id=run_id,
        )
        console.print(f"[yellow]Replay mode: {replay_mode}[/yellow]")

    # Initialize run report builder
    report_builder = RunReportBuilder(run_id=run_id, edition=edition)

    console.print(Panel.fit(
        f"[bold]Daily Deep Brief Pipeline[/bold]\n"
        f"Run ID: {run_id}\n"
        f"Edition: {edition}\n"
        f"Mode: {mode}\n"
        f"Time: {format_datetime(now, 'full')}",
        border_style="green",
    ))

    if dry_run:
        console.print("[yellow]DRY RUN - No actual publishing will occur[/yellow]\n")

    ensure_directories()
    store = SQLiteStore()

    # Track run
    run_record = {
        "run_id": run_id,
        "edition": edition,
        "status": "running",
        "created_at": time.time(),
    }

    try:
        # Step 1: Collect
        console.print("\n[bold cyan]Step 1: Collect[/bold cyan]")
        console.print("  Collecting candidate events from news sources...")

        collector = GoogleNewsCollector()
        if theme:
            universe = load_universe()
            theme_data = universe.get("themes", {}).get(theme, {})
            tickers = theme_data.get("tickers", [])[:4]
            events = []
            for ticker in tickers:
                events.extend(collector.fetch_query(f"{ticker} stock", limit=5, ticker=ticker, theme=theme))
        else:
            events = collector.collect_from_universe(items_per_query=5)

        console.print(f"  ✓ Collected {len(events)} candidate events")

        # Step 2: Score & Select
        console.print("\n[bold cyan]Step 2: Analyze[/bold cyan]")
        console.print("  Scoring events and selecting primary...")

        scorer = EventScorer()
        scored_events = scorer.score_events(events)
        primary_event = scorer.select_primary(scored_events)

        if not primary_event:
            raise ValueError("No suitable primary event found")

        console.print(f"  ✓ Primary event: {primary_event.event.title[:60]}...")
        console.print(f"  ✓ Score: {primary_event.total_score:.1f}, Type: {primary_event.event_type}")

        # Update run report with candidate events
        report_builder.set_candidate_events(events, scored_events)
        report_builder.set_selection(
            event=primary_event,
            reason=f"Highest score ({primary_event.total_score:.1f}) with type {primary_event.event_type}",
            tickers=primary_event.matched_tickers,
        )

        # Step 3: Enrich
        console.print("\n[bold cyan]Step 3: Enrich[/bold cyan]")
        console.print("  Enriching key tickers with financial data...")

        tickers_to_enrich = primary_event.matched_tickers[:4]
        if not tickers_to_enrich:
            tickers_to_enrich = ["NVDA"]  # Fallback

        companies = {}
        with FMPEnricher() as enricher:
            for ticker in tickers_to_enrich:
                console.print(f"    Enriching {ticker}...")
                companies[ticker] = enricher.enrich(ticker)

                # Also get peers
                if companies[ticker].peers:
                    for peer in companies[ticker].peers[:3]:
                        if peer not in companies:
                            console.print(f"    Enriching peer {peer}...")
                            companies[peer] = enricher.enrich(peer)

        console.print(f"  ✓ Enriched {len(companies)} companies")

        # Step 4: Build Research Pack
        console.print("\n[bold cyan]Step 4: Build Research Pack[/bold cyan]")

        builder = ResearchPackBuilder()
        research_pack = builder.build(scored_events, companies, edition=edition, run_id=run_id)

        # Add valuations
        console.print("  Running valuation analysis...")
        val_analyzer = ValuationAnalyzer()
        key_tickers = [s["ticker"] for s in research_pack.key_stocks]
        valuations = val_analyzer.analyze_multiple(key_tickers, companies)
        research_pack.valuations = {t: v.to_dict() for t, v in valuations.items()}

        # Add peer table
        console.print("  Building peer comparison table...")
        peer_builder = PeerComparisonBuilder()
        if key_tickers:
            peer_table = peer_builder.build(key_tickers[0], companies)
            research_pack.peer_table = peer_table.to_dict()

        # Validate
        is_valid, errors = builder.validate(research_pack)
        if not is_valid:
            console.print(f"  [yellow]⚠ Validation warnings: {len(errors)}[/yellow]")
            for err in errors[:3]:
                console.print(f"    - {err}")

        # Save research pack
        rp_path = builder.save(research_pack, "out/research_pack.json")
        console.print(f"  ✓ Research pack saved to {rp_path}")

        run_record["research_pack_path"] = str(rp_path)
        run_record["primary_event_id"] = primary_event.event.id

        # Step 5: Write
        console.print("\n[bold cyan]Step 5: Write[/bold cyan]")
        console.print("  Generating article with AI...")

        writer = CodexRunner()
        post = writer.generate(research_pack.to_dict(), run_id=run_id)

        if not post:
            raise ValueError("Failed to generate article")

        paths = writer.save(post, "out")
        console.print(f"  ✓ Article saved")
        for file_type, path in paths.items():
            console.print(f"    - {file_type}: {path}")

        run_record["post_path"] = str(paths.get("json"))

        # Step 6: Quality Gate
        console.print("\n[bold cyan]Step 6: Quality Gate[/bold cyan]")

        quality_gate = QualityGate()
        quality_report = quality_gate.run_all_gates(
            post.to_dict(),
            research_pack.to_dict(),
            mode=mode,
            newsletter_slug="" if not newsletter else os.getenv("GHOST_NEWSLETTER_SLUG", ""),
            email_segment="" if not newsletter else "all",
            run_id=run_id,
        )

        # Display gate results
        for gate in quality_report.gates:
            status_icon = "✓" if gate.passed else "✗"
            status_color = "green" if gate.passed else "red"
            console.print(f"  [{status_color}]{status_icon} {gate.name}[/{status_color}]: {gate.message[:50]}")

        if quality_report.overall_passed:
            console.print("\n  [green]✓ Quality check PASSED[/green]")
        else:
            console.print("\n  [red]✗ Quality check FAILED[/red]")
            for err in quality_report.errors[:5]:
                console.print(f"    - {err}")

        if quality_report.warnings:
            console.print("  [yellow]Warnings:[/yellow]")
            for warn in quality_report.warnings[:3]:
                console.print(f"    ⚠ {warn}")

        # Save quality report
        quality_gate.save_report(quality_report, "out/quality_report.json")

        # Update run report
        report_builder.set_quality_result(quality_report.to_dict())
        report_builder.set_content_stats(post.to_dict(), research_pack.to_dict())

        # Step 7: Publish
        console.print("\n[bold cyan]Step 7: Publish[/bold cyan]")

        # Fail-Closed: Quality check must pass for publish mode
        if dry_run:
            console.print("  [yellow]Skipped (dry run)[/yellow]")
            run_record["status"] = "dry_run"
        elif not quality_report.overall_passed and mode == "publish":
            console.print("  [red]Blocked by Quality Gate - downgrading to draft[/red]")
            mode = "draft"
            report_builder.add_warning("Publish blocked by quality gate, downgraded to draft")

        if not dry_run:
            if not os.getenv("GHOST_API_URL") or not os.getenv("GHOST_ADMIN_API_KEY"):
                console.print("  [yellow]Skipped (Ghost not configured)[/yellow]")
                run_record["status"] = "completed_no_publish"
            else:
                with GhostPublisher() as publisher:
                    result = publisher.publish(
                        post,
                        mode=mode,
                        send_newsletter=newsletter and mode == "publish" and quality_report.can_send_newsletter,
                    )

                if result.success:
                    console.print(f"  [green]✓ Published successfully![/green]")
                    console.print(f"    URL: {result.url}")
                    console.print(f"    Status: {result.status}")
                    if result.newsletter_sent:
                        console.print("    [cyan]Newsletter sent[/cyan]")
                    run_record["ghost_url"] = result.url
                    run_record["status"] = "published" if mode == "publish" else "draft"
                    report_builder.set_publish_result(result.to_dict())
                else:
                    console.print(f"  [red]✗ Publish failed: {result.error}[/red]")
                    run_record["status"] = "publish_failed"
                    report_builder.add_error(f"Publish failed: {result.error}")

                publisher.save_result(result, "out/publish_result.json")

        # Complete
        elapsed = time.time() - start_time
        run_record["completed_at"] = time.time()
        store.save_run(run_record)

        # Complete run report
        final_report = report_builder.complete(run_record["status"])
        report_path = report_builder.save(f"out/reports/run_report_{run_id[:8]}.json")

        # Save recordings if in record mode
        recorder = get_recorder()
        if recorder and replay_mode == "record":
            recorder.save_recordings()
            console.print(f"  [cyan]Saved API recordings[/cyan]")

        console.print(Panel.fit(
            f"[bold green]Pipeline Complete![/bold green]\n"
            f"Run ID: {run_id}\n"
            f"Duration: {elapsed:.1f}s\n"
            f"Status: {run_record['status']}\n"
            f"Quality: {'PASSED' if quality_report.overall_passed else 'FAILED'}",
            border_style="green",
        ))

        # Summary
        console.print("\n[bold]Output Files:[/bold]")
        console.print("  • out/research_pack.json")
        console.print("  • out/post.json")
        console.print("  • out/post.md")
        console.print("  • out/post.html")
        console.print("  • out/quality_report.json")
        console.print(f"  • {report_path}")

    except Exception as e:
        logger.exception(f"Pipeline failed: {e}")
        console.print(f"\n[red]Pipeline failed: {e}[/red]")
        run_record["status"] = "failed"
        run_record["completed_at"] = time.time()
        store.save_run(run_record)

        # Save error to run report
        report_builder.add_error(str(e))
        report_builder.complete("failed")
        report_builder.save(f"out/reports/run_report_{run_id[:8]}.json")

        sys.exit(1)


@cli.command()
@click.option("--limit", "-n", default=10, help="Number of items per query")
@click.option("--query", "-q", help="Custom search query")
@click.option("--output", "-o", default="out/events.json", help="Output file")
def collect(limit: int, query: str, output: str) -> None:
    """Collect candidate events from news sources"""
    from .collectors.google_news_rss import GoogleNewsCollector

    console.print("[bold]Collecting news events...[/bold]")

    collector = GoogleNewsCollector()

    if query:
        events = collector.fetch_query(query, limit=limit)
    else:
        events = collector.collect_from_universe(items_per_query=limit)

    console.print(f"Collected {len(events)} events")

    # Save
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump([e.to_dict() for e in events], f, indent=2, ensure_ascii=False)

    console.print(f"Saved to {output_path}")


@cli.command()
@click.argument("tickers", nargs=-1)
@click.option("--output", "-o", default="out/companies.json", help="Output file")
def enrich(tickers: tuple, output: str) -> None:
    """Enrich tickers with financial data"""
    from .enrichers.fmp import FMPEnricher

    if not tickers:
        console.print("[yellow]No tickers specified. Using defaults.[/yellow]")
        tickers = ("NVDA", "AMD", "TSM")

    console.print(f"[bold]Enriching tickers: {', '.join(tickers)}[/bold]")

    with FMPEnricher() as enricher:
        results = enricher.enrich_multiple(list(tickers))

    # Display
    table = Table(title="Company Data")
    table.add_column("Ticker", style="cyan")
    table.add_column("Name")
    table.add_column("Price", style="yellow")
    table.add_column("Market Cap", style="green")

    for ticker, data in results.items():
        price = f"${data.price.last:.2f}" if data.price and data.price.last else "N/A"
        mcap = f"${data.price.market_cap/1e9:.1f}B" if data.price and data.price.market_cap else "N/A"
        table.add_row(ticker, data.name or "N/A", price, mcap)

    console.print(table)

    # Save
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump({t: d.to_dict() for t, d in results.items()}, f, indent=2, ensure_ascii=False)

    console.print(f"Saved to {output_path}")


@cli.command()
@click.option("--input", "-i", "input_path", default="out/research_pack.json", help="Input research pack")
@click.option("--output", "-o", default="out", help="Output directory")
def write(input_path: str, output: str) -> None:
    """Generate article from research pack"""
    from .writers.codex_runner import CodexRunner

    console.print(f"[bold]Loading research pack from {input_path}...[/bold]")
    with open(input_path) as f:
        research_pack = json.load(f)

    console.print("[bold]Generating article...[/bold]")
    writer = CodexRunner()
    post = writer.generate(research_pack)

    if post:
        paths = writer.save(post, output)
        console.print("[green]✓ Article generated[/green]")
        for file_type, path in paths.items():
            console.print(f"  - {file_type}: {path}")
    else:
        console.print("[red]✗ Failed to generate article[/red]")


@cli.command()
@click.option("--input", "-i", "input_path", default="out/post.json", help="Input post.json")
@click.option("--mode", "-m", default="draft", help="Mode: draft/publish")
@click.option("--newsletter", "-n", is_flag=True, help="Send newsletter")
def publish(input_path: str, mode: str, newsletter: bool) -> None:
    """Publish to Ghost CMS"""
    from .writers.codex_runner import PostOutput
    from .publishers.ghost_admin import GhostPublisher

    console.print(f"[bold]Loading post from {input_path}...[/bold]")
    with open(input_path) as f:
        post_data = json.load(f)

    post = PostOutput(**post_data)

    console.print(f"[bold]Publishing (mode: {mode})...[/bold]")
    with GhostPublisher() as publisher:
        result = publisher.publish(post, mode=mode, send_newsletter=newsletter)

    if result.success:
        console.print(f"[green]✓ Published: {result.url}[/green]")
    else:
        console.print(f"[red]✗ Failed: {result.error}[/red]")


@cli.command()
def status() -> None:
    """Show current status and recent runs"""
    store = SQLiteStore()
    runs = store.get_recent_runs(10)

    if not runs:
        console.print("[dim]No runs recorded yet[/dim]")
        return

    table = Table(title="Recent Runs")
    table.add_column("Run ID", style="cyan")
    table.add_column("Edition")
    table.add_column("Status")
    table.add_column("Time")

    for run in runs:
        created = datetime.fromtimestamp(run["created_at"]).strftime("%Y-%m-%d %H:%M")
        status_style = "green" if run["status"] == "published" else "yellow" if run["status"] == "draft" else "red"
        table.add_row(
            run["run_id"][:20] + "...",
            run["edition"] or "N/A",
            f"[{status_style}]{run['status']}[/{status_style}]",
            created,
        )

    console.print(table)


def main() -> None:
    """Main entry point"""
    cli()


if __name__ == "__main__":
    main()
