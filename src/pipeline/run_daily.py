"""
Daily Pipeline Runner - 每日三篇美股研究產出

Stages:
1. Ingest - Collect news, market data, earnings calendar
2. Pack - Build edition_pack.json (single source of truth)
3. Write - Generate Post A (Flash), Post B (Earnings), Post C (Deep Dive)
4. QA - Run quality gates on all posts
5. Publish - Ghost publish with safety rails
6. Smoke Test - Verify rendering (optional)
7. Archive - Save artifacts

Usage:
    python -m src.pipeline.run_daily --mode test
    python -m src.pipeline.run_daily --mode prod --confirm-high-risk
"""

import json
import os
import sys
import time
from datetime import datetime, date
from pathlib import Path
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field, asdict

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn

load_dotenv()

console = Console()


# =============================================================================
# Data Models
# =============================================================================

@dataclass
class EditionPack:
    """Single source of truth for the day's content"""
    meta: Dict[str, Any]
    date: str
    edition: str
    primary_event: Optional[Dict] = None
    primary_theme: Optional[Dict] = None
    news_items: List[Dict] = field(default_factory=list)
    market_data: Dict[str, Dict] = field(default_factory=dict)
    earnings_calendar: List[Dict] = field(default_factory=list)
    key_stocks: List[Dict] = field(default_factory=list)
    peer_data: Dict[str, Dict] = field(default_factory=dict)
    peer_table: Optional[Dict] = None  # Formatted peer comparison table
    valuations: Dict[str, Dict] = field(default_factory=dict)
    deep_dive_ticker: Optional[str] = None
    deep_dive_reason: Optional[str] = None
    deep_dive_data: Optional[Dict] = None  # P1-2: Thicker data pack for deep dive
    recent_earnings: Optional[Dict] = None  # v4.2: 最近一次財報資料（用於 Earnings 文章）

    def to_dict(self) -> Dict:
        return asdict(self)

    def save(self, path: str = "out/edition_pack.json") -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
        return p


@dataclass
class PostOutput:
    """Generated post output"""
    post_type: str  # flash, earnings, deep
    title: str
    slug: str
    json_data: Dict
    html_content: str
    quality_passed: bool = False
    quality_report: Optional[Dict] = None
    publish_result: Optional[Dict] = None


@dataclass
class DailyPipelineResult:
    """Results from the daily pipeline run"""
    run_id: str
    date: str
    mode: str
    posts: Dict[str, Optional[PostOutput]] = field(default_factory=dict)
    edition_pack_path: Optional[str] = None
    quality_gates_passed: bool = False
    publish_results: Dict[str, Dict] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0


# =============================================================================
# Slug Rules (CRITICAL - Prevents collision)
# =============================================================================

def generate_slug(post_type: str, topic: str, ticker: Optional[str], run_date: str) -> str:
    """
    Generate unique slug for each post type.

    Format:
    - Flash: {topic}-{YYYY-MM-DD}-flash
    - Earnings: {ticker}-earnings-{context}-{YYYY-MM-DD}-earnings
    - Deep: {ticker}-deep-dive-{YYYY-MM-DD}-deep
    """
    # Normalize topic (lowercase, replace spaces with hyphens)
    topic_slug = topic.lower().replace(" ", "-").replace("_", "-")
    topic_slug = "".join(c for c in topic_slug if c.isalnum() or c == "-")

    if post_type == "flash":
        return f"{topic_slug}-{run_date}-flash"
    elif post_type == "earnings":
        ticker = ticker or "market"
        return f"{ticker.lower()}-earnings-preview-{run_date}-earnings"
    elif post_type == "deep":
        ticker = ticker or "focus"
        return f"{ticker.lower()}-deep-dive-{run_date}-deep"
    else:
        raise ValueError(f"Unknown post type: {post_type}")


def validate_slug(slug: str, post_type: str) -> bool:
    """Validate slug matches expected format"""
    suffixes = {
        "flash": "-flash",
        "earnings": "-earnings",
        "deep": "-deep"
    }
    expected = suffixes.get(post_type)
    if not expected:
        return False
    return slug.endswith(expected)


# =============================================================================
# Quality Gate Integration
# =============================================================================

def run_quality_gates(
    post_data: Dict,
    edition_pack: Dict,
    post_type: str
) -> Dict:
    """Run quality gates on a single post"""
    from ..quality.quality_gate import QualityGate

    gate = QualityGate()

    # Run all gates
    result = gate.run_all_gates(
        post_data,
        edition_pack,
        mode="draft",
        newsletter_slug="",
        email_segment="",
        run_id=edition_pack.get("meta", {}).get("run_id", ""),
    )

    return result.to_dict()


# =============================================================================
# Ghost Publisher Integration
# =============================================================================

def validate_publish_config(mode: str, newsletter: str, segment: str) -> List[str]:
    """Validate publish configuration"""
    errors = []

    # High-risk segment check
    HIGH_RISK_SEGMENTS = {"all", "status:free", "status:-free"}

    if mode == "test":
        if segment in HIGH_RISK_SEGMENTS and segment != "label:internal":
            errors.append(f"Segment '{segment}' blocked in test mode")
        if newsletter != "daily-brief-test":
            errors.append(f"Newsletter must be 'daily-brief-test' in test mode")

    # Check allowlists
    newsletter_allowlist = os.getenv("GHOST_NEWSLETTER_ALLOWLIST", "daily-brief,daily-brief-test").split(",")
    if newsletter not in newsletter_allowlist:
        errors.append(f"Newsletter '{newsletter}' not in allowlist")

    return errors


def publish_post(
    post: PostOutput,
    mode: str,
    newsletter: str,
    segment: str,
    send_email: bool = False,
    confirm_high_risk: bool = False,
    visibility: str = "paid",  # P0-4: Default to paid for paywall
) -> Dict:
    """Publish a single post to Ghost with safety rails

    Args:
        post: PostOutput object with json_data
        mode: 'test' or 'prod'
        newsletter: Newsletter slug
        segment: Email segment for newsletter
        send_email: Whether to send newsletter email
        confirm_high_risk: Confirm high-risk segments
        visibility: Post visibility - 'public', 'members', or 'paid'
            - public: Visible to all (no paywall)
            - members: Requires free membership to unlock
            - paid: Requires paid membership to unlock
    """
    from ..publishers.ghost_admin import GhostPublisher

    # Support both PostOutput object and duck typing
    slug = getattr(post, 'slug', '')
    post_type = getattr(post, 'post_type', '')
    json_data = getattr(post, 'json_data', {})
    quality_passed = getattr(post, 'quality_passed', True)

    result = {
        "success": False,
        "slug": slug,
        "post_type": post_type,
        "mode": mode,
        "error": None,
        "url": None,
        "newsletter_sent": False
    }

    # Validate config
    errors = validate_publish_config(mode, newsletter, segment)
    if errors and not confirm_high_risk:
        result["error"] = "; ".join(errors)
        return result

    # Quality gate check
    if send_email and not quality_passed:
        result["error"] = "Quality gates not passed - blocking newsletter send"
        send_email = False

    # Determine Ghost publish mode
    ghost_mode = "publish" if mode == "prod" else "draft"

    try:
        with GhostPublisher(newsletter_slug=newsletter) as publisher:
            # Create the post with all parameters (P0-4 fix)
            pub_result = publisher.publish(
                json_data,
                mode=ghost_mode,
                send_newsletter=send_email,
                email_segment=segment,
                visibility=visibility,
            )

            result["success"] = pub_result.success
            result["url"] = pub_result.url
            result["newsletter_sent"] = pub_result.newsletter_sent
            if not pub_result.success:
                result["error"] = pub_result.error

    except Exception as e:
        result["error"] = str(e)

    return result


# =============================================================================
# Pipeline Stages
# =============================================================================

def stage_ingest(run_date: str, theme: Optional[str] = None) -> Dict:
    """
    Stage 1: Ingest data from all sources
    - News (Google RSS)
    - Layer 2 Radar Fillers (SEC, Market Movers, Macro Calendar)
    - Market data (FMP)
    - Earnings calendar
    """
    from ..collectors.google_news_rss import GoogleNewsCollector
    from ..collectors.radar_fillers import ensure_minimum_news_items
    from ..enrichers.fmp import FMPEnricher

    console.print("\n[bold cyan]Stage 1: Ingest[/bold cyan]")

    # Universe tickers for radar fillers
    universe_tickers = [
        "NVDA", "AMD", "AVGO", "TSM", "ASML",  # AI Chips
        "MSFT", "GOOGL", "AMZN", "META",       # AI Cloud
        "MRVL", "CRDO", "ALAB",                # AI Networking
        "CRWD", "PANW", "FTNT", "ZS",          # AI Security
        "CEG", "VST", "NEE",                   # Power
        "OKLO", "NNE", "SMR",                  # Nuclear
        "PLTR", "AXON", "ASTS",                # Drones/Defense
        "RKLB", "LUNR",                        # Space
        "IONQ", "RGTI",                        # Quantum
        "COIN", "MSTR", "MARA", "RIOT",        # Crypto
        "AAPL", "TSLA",                        # Consumer
    ]

    data = {
        "news_items": [],
        "market_data": {},
        "earnings_calendar": [],
        "companies": {},
        "universe_tickers": universe_tickers,
        "market_snapshot": {},
    }

    # Collect news from Google RSS
    console.print("  Collecting news from Google RSS...")
    collector = GoogleNewsCollector()
    events = collector.collect_from_universe(items_per_query=5)
    data["news_items"] = [e.to_dict() for e in events]
    console.print(f"  ✓ Collected {len(events)} news items from Google RSS")

    # Collect earnings calendar for universe tickers
    console.print("  Collecting earnings calendar...")
    with FMPEnricher() as enricher:
        # Get earnings for next 7 days for our universe
        earnings = enricher.get_upcoming_earnings_for_universe(universe_tickers, days_ahead=7)
        data["earnings_calendar"] = earnings
        console.print(f"  ✓ Found {len(earnings)} upcoming earnings in universe")

        # Get market snapshot
        data["market_snapshot"] = enricher.get_market_snapshot()
        console.print("  ✓ Collected market snapshot")

    # Ensure minimum 8 news items with Layer 2 Radar Fillers
    MIN_NEWS_ITEMS = 8
    if len(data["news_items"]) < MIN_NEWS_ITEMS:
        console.print(f"  [yellow]⚠ Only {len(data['news_items'])} news items, need {MIN_NEWS_ITEMS}[/yellow]")
        console.print("  Collecting Layer 2 Radar Fillers...")
        data["news_items"] = ensure_minimum_news_items(
            news_items=data["news_items"],
            universe_tickers=universe_tickers,
            min_count=MIN_NEWS_ITEMS,
        )
        console.print(f"  ✓ Now have {len(data['news_items'])} news items (with fillers)")
    else:
        console.print(f"  ✓ Sufficient news items ({len(data['news_items'])} >= {MIN_NEWS_ITEMS})")

    # Enrich key tickers
    console.print("  Enriching market data...")
    default_tickers = ["NVDA", "AMD", "AVGO", "TSM", "MSFT", "GOOGL", "AMZN", "META"]

    enriched_companies = {}
    with FMPEnricher() as enricher:
        for ticker in default_tickers[:6]:
            try:
                company = enricher.enrich(ticker)
                enriched_companies[ticker] = company
                if company.price:
                    data["market_data"][ticker] = {
                        "price": company.price.last,
                        "change_pct": company.price.change_pct_1d,  # Fixed: use correct field name
                        "market_cap": company.price.market_cap,
                        "volume": company.price.volume,
                    }
            except Exception as e:
                console.print(f"  [yellow]⚠ Failed to enrich {ticker}: {e}[/yellow]")

    console.print(f"  ✓ Enriched {len(data['market_data'])} tickers")

    # Fill null financial values (v4.1: Deep Dive 數據補齊)
    from ..enrichers.fill_nulls import fill_all_companies, generate_fill_disclosure

    console.print("  Filling null financial values...")
    filled_companies, fill_results = fill_all_companies(enriched_companies)

    # Convert to dict and store
    for ticker, company in filled_companies.items():
        data["companies"][ticker] = company.to_dict()

    if fill_results:
        fill_count = sum(len(r) for r in fill_results.values())
        console.print(f"  ✓ Filled {fill_count} null values across {len(fill_results)} tickers")
        data["fill_disclosure"] = generate_fill_disclosure(fill_results)
    else:
        console.print("  ✓ No null values to fill")

    return data


def stage_pack(ingest_data: Dict, run_date: str, run_id: str) -> EditionPack:
    """
    Stage 2: Build edition_pack.json (single source of truth)
    """
    from ..analyzers.event_scoring import EventScorer
    from ..analyzers.valuation_models import ValuationAnalyzer
    from ..analyzers.peer_comp import PeerComparisonBuilder
    from ..enrichers.fmp import FMPEnricher

    console.print("\n[bold cyan]Stage 2: Pack[/bold cyan]")

    # Score and select primary event
    scorer = EventScorer()
    events = []
    for item in ingest_data.get("news_items", []):
        from ..collectors.google_news_rss import CandidateEvent
        events.append(CandidateEvent(**item))

    scored = scorer.score_events(events)
    primary = scorer.select_primary(scored)

    # Determine theme
    primary_theme = None
    if primary:
        primary_theme = {
            "id": primary.event_type,
            "matched_tickers": primary.matched_tickers,
        }

    # Select deep dive ticker
    deep_ticker = None
    deep_reason = None
    companies_data = ingest_data.get("companies", {})

    if primary and primary.matched_tickers:
        # 優先使用 primary event 的 ticker，但必須在 companies_data 中有資料
        for candidate in primary.matched_tickers:
            if candidate in companies_data:
                deep_ticker = candidate
                deep_reason = "highest_impact"
                break

    # Fallback: 如果沒有找到，使用 companies_data 中的第一個 ticker
    if not deep_ticker and companies_data:
        deep_ticker = list(companies_data.keys())[0]
        deep_reason = "fallback_default"
        console.print(f"  [yellow]⚠ No matching ticker in companies, using fallback: {deep_ticker}[/yellow]")

    # Build key stocks list
    key_stocks = []
    for ticker, data in ingest_data.get("market_data", {}).items():
        key_stocks.append({
            "ticker": ticker,
            "price": data.get("price"),
            "change_pct": data.get("change_pct"),
            "market_cap": data.get("market_cap"),
        })

    # Run valuations
    console.print("  Running valuation analysis...")
    valuations = {}
    val_analyzer = ValuationAnalyzer()
    for ticker in list(ingest_data.get("companies", {}).keys())[:4]:
        try:
            val = val_analyzer.analyze(ticker, ingest_data["companies"])
            valuations[ticker] = val.to_dict()
        except Exception as e:
            console.print(f"  [yellow]⚠ Valuation failed for {ticker}: {e}[/yellow]")

    # Build peer_data from companies (companies_data already defined above)
    peer_data = {}
    for ticker, company in companies_data.items():
        peer_data[ticker] = {
            "ticker": ticker,
            "name": company.get("name", ""),
            "market_cap": company.get("price", {}).get("market_cap"),
            "fundamentals": company.get("fundamentals", {}),
            "estimates": company.get("estimates", {}),
        }

    # Build peer_table (formatted comparison)
    console.print("  Building peer comparison table...")
    peer_table = None
    if deep_ticker and companies_data:
        try:
            # Convert dict to CompanyData objects for peer_comp
            from ..enrichers.base import CompanyData, PriceData, Fundamentals, Estimates
            company_objects = {}
            for t, c in companies_data.items():
                try:
                    price_data = None
                    if c.get("price"):
                        price_data = PriceData(**c["price"])

                    fund_data = None
                    if c.get("fundamentals"):
                        fund_data = Fundamentals(**c["fundamentals"])

                    est_data = None
                    if c.get("estimates"):
                        est_data = Estimates(**c["estimates"])

                    company_objects[t] = CompanyData(
                        ticker=t,
                        name=c.get("name", ""),
                        sector=c.get("sector", ""),
                        industry=c.get("industry", ""),
                        price=price_data,
                        fundamentals=fund_data,
                        estimates=est_data,
                        peers=c.get("peers", []),
                    )
                except Exception as e:
                    console.print(f"  [dim]Skipping {t} for peer table: {e}[/dim]")

            if company_objects:
                builder = PeerComparisonBuilder()
                table = builder.build(deep_ticker, company_objects)
                peer_table = table.to_dict()
                console.print(f"  ✓ Built peer table with {len(table.rows)} companies")
        except Exception as e:
            console.print(f"  [yellow]⚠ Peer table build failed: {e}[/yellow]")

    # P1-2: Build thicker deep dive data pack
    deep_dive_data = None
    if deep_ticker and deep_ticker in companies_data:
        console.print(f"  Building deep dive data for {deep_ticker}...")
        try:
            company = companies_data[deep_ticker]
            deep_dive_data = {
                "ticker": deep_ticker,
                "company_profile": {
                    "name": company.get("name", ""),
                    "sector": company.get("sector", ""),
                    "industry": company.get("industry", ""),
                    "peers": company.get("peers", []),
                },
                "price_data": company.get("price", {}),
                "fundamentals": company.get("fundamentals", {}),
                "estimates": company.get("estimates", {}),
                "valuation": valuations.get(deep_ticker, {}),
                "peer_comparison": peer_table,
                # Add quarterly data if available
                "quarterly_history": [],
                # Add segment breakdown if available
                "segment_breakdown": [],
                # Add competitive position
                "competitive_moat": {
                    "type": [],
                    "durability": "moderate",
                    "description": "",
                },
            }

            # Get related news for deep dive ticker
            ticker_news = [
                item for item in ingest_data.get("news_items", [])
                if deep_ticker in item.get("affected_tickers", []) or
                   deep_ticker in item.get("headline", "")
            ]
            deep_dive_data["related_news"] = ticker_news[:5]

            # Get upcoming earnings for deep dive ticker
            ticker_earnings = [
                e for e in ingest_data.get("earnings_calendar", [])
                if e.get("ticker") == deep_ticker
            ]
            deep_dive_data["upcoming_earnings"] = ticker_earnings

            console.print(f"  ✓ Built deep dive data pack with {len(ticker_news)} related news items")
        except Exception as e:
            console.print(f"  [yellow]⚠ Deep dive data build failed: {e}[/yellow]")

    # v4.2: 取得 deep dive ticker 的最近財報（用於 Earnings 文章）
    # 使用 income-statement 取得實際歷史財報，而非未來預期
    recent_earnings = None
    if deep_ticker:
        console.print(f"  Fetching recent earnings for {deep_ticker}...")
        try:
            with FMPEnricher() as enricher:
                earnings_history = enricher.get_recent_earnings(deep_ticker, limit=4)
                if earnings_history:
                    latest = earnings_history[0]
                    recent_earnings = {
                        "ticker": deep_ticker,
                        "earnings_date": latest.get("date"),
                        "fiscal_period": latest.get("fiscal_period"),
                        "fiscal_year": latest.get("fiscal_year"),
                        "eps_actual": latest.get("eps_actual"),
                        "eps_diluted": latest.get("eps_diluted"),
                        "revenue_actual": latest.get("revenue_actual"),
                        "gross_profit": latest.get("gross_profit"),
                        "operating_income": latest.get("operating_income"),
                        "net_income": latest.get("net_income"),
                        "gross_margin": latest.get("gross_margin"),
                        "operating_margin": latest.get("operating_margin"),
                        "net_margin": latest.get("net_margin"),
                        "history": earnings_history,  # 最近 4 季
                    }
                    eps_display = f"${latest.get('eps_diluted'):.2f}" if latest.get('eps_diluted') else "N/A"
                    rev_display = f"${latest.get('revenue_actual')/1e9:.1f}B" if latest.get('revenue_actual') else "N/A"
                    console.print(f"  ✓ Found recent earnings: {latest.get('fiscal_year')} {latest.get('fiscal_period')} (EPS: {eps_display}, Rev: {rev_display})")
                else:
                    console.print(f"  [yellow]⚠ No earnings history found for {deep_ticker}[/yellow]")
        except Exception as e:
            console.print(f"  [yellow]⚠ Failed to fetch recent earnings: {e}[/yellow]")

    # Build pack
    pack = EditionPack(
        meta={
            "run_id": run_id,
            "created_at": datetime.now().isoformat(),
            "version": "2.0",
        },
        date=run_date,
        edition="postclose",
        primary_event=primary.to_dict() if primary else None,
        primary_theme=primary_theme,
        news_items=ingest_data.get("news_items", [])[:20],
        market_data=ingest_data.get("market_data", {}),
        earnings_calendar=ingest_data.get("earnings_calendar", []),  # P0-2: Added earnings calendar
        key_stocks=key_stocks,
        peer_data=peer_data,  # Contains fundamentals for all companies
        peer_table=peer_table,  # Formatted peer comparison table
        valuations=valuations,
        deep_dive_ticker=deep_ticker,
        deep_dive_reason=deep_reason,
        deep_dive_data=deep_dive_data,  # P1-2: Thicker data pack for deep dive
        recent_earnings=recent_earnings,  # v4.2: 最近財報資料
    )

    # Add market_snapshot to pack meta
    if ingest_data.get("market_snapshot"):
        pack.meta["market_snapshot"] = ingest_data["market_snapshot"]

    # Save
    pack_path = pack.save()
    console.print(f"  ✓ Edition pack saved to {pack_path}")

    return pack


def stage_write(
    edition_pack: EditionPack,
    run_id: str,
    post_types: List[str] = None
) -> Dict[str, Optional[PostOutput]]:
    """
    Stage 3: Generate posts using skills
    - Post A (Flash): Always - uses postA.prompt.md and postA.schema.json
    - Post B (Earnings): Conditional - uses postB.prompt.md and postB.schema.json
    - Post C (Deep Dive): Always - uses postC.prompt.md and postC.schema.json
    """
    from ..writers.codex_runner import CodexRunner
    from ..writers.cross_links import generate_cross_links, inject_cross_links

    console.print("\n[bold cyan]Stage 3: Write[/bold cyan]")

    if post_types is None:
        # v4.2: Earnings 永遠觸發，分析 deep dive ticker 的最近一次財報
        post_types = ["flash", "earnings", "deep"]

    # Generate cross-links for all posts
    topic = "market"
    if edition_pack.primary_theme:
        topic = edition_pack.primary_theme.get("id", "market")

    cross_links = generate_cross_links(
        run_date=edition_pack.date,
        topic=topic,
        deep_dive_ticker=edition_pack.deep_dive_ticker,
        earnings_ticker=edition_pack.deep_dive_ticker,  # TODO: separate earnings ticker
        has_earnings="earnings" in post_types,
    )
    console.print(f"  ✓ Generated cross-links for {len(post_types)} posts")

    posts = {}

    for post_type in post_types:
        console.print(f"  Generating {post_type}...")

        try:
            # Create post-type specific writer with corresponding prompt and schema
            writer = CodexRunner(post_type=post_type)
            console.print(f"    Using prompt: {writer.prompt_path}")

            # Determine slug parameters
            ticker = None

            if post_type in ["earnings", "deep"]:
                ticker = edition_pack.deep_dive_ticker

            slug = generate_slug(
                post_type=post_type,
                topic=topic,
                ticker=ticker,
                run_date=edition_pack.date
            )

            # Validate slug
            if not validate_slug(slug, post_type):
                raise ValueError(f"Invalid slug format: {slug}")

            # Generate content using post-type specific prompt
            post = writer.generate(
                edition_pack.to_dict(),
                run_id=run_id,
            )

            if post:
                # Override slug with our generated one
                post_dict = post.to_dict()
                post_dict["slug"] = slug
                post_dict["meta"]["post_type"] = post_type

                # Inject cross-links into post data
                post_dict = inject_cross_links(post_dict, cross_links, post_type)

                posts[post_type] = PostOutput(
                    post_type=post_type,
                    title=post_dict.get("title", ""),
                    slug=slug,
                    json_data=post_dict,
                    html_content=post_dict.get("html", ""),
                )
                console.print(f"    ✓ {post_type}: {slug}")
            else:
                console.print(f"    [yellow]⚠ Failed to generate {post_type}[/yellow]")
                posts[post_type] = None

        except Exception as e:
            console.print(f"    [red]✗ Error generating {post_type}: {e}[/red]")
            posts[post_type] = None

    return posts


def stage_qa(
    posts: Dict[str, Optional[PostOutput]],
    edition_pack: EditionPack
) -> Dict[str, Dict]:
    """
    Stage 4: Run quality gates on all posts
    """
    console.print("\n[bold cyan]Stage 4: Quality Gate[/bold cyan]")

    results = {}
    all_passed = True

    for post_type, post in posts.items():
        if post is None:
            results[post_type] = {"passed": False, "error": "Post not generated"}
            all_passed = False
            continue

        console.print(f"  Checking {post_type}...")

        try:
            report = run_quality_gates(
                post.json_data,
                edition_pack.to_dict(),
                post_type
            )

            passed = report.get("overall_passed", False)
            post.quality_passed = passed
            post.quality_report = report
            results[post_type] = report

            status = "✓" if passed else "✗"
            color = "green" if passed else "red"
            console.print(f"    [{color}]{status} {post_type}[/{color}]")

            if not passed:
                all_passed = False
                for error in report.get("errors", [])[:3]:
                    console.print(f"      - {error}")

        except Exception as e:
            console.print(f"    [red]✗ QA failed for {post_type}: {e}[/red]")
            results[post_type] = {"passed": False, "error": str(e)}
            all_passed = False

    console.print(f"\n  Overall: {'[green]PASSED[/green]' if all_passed else '[red]FAILED[/red]'}")

    return results


def stage_publish(
    posts: Dict[str, Optional[PostOutput]],
    mode: str,
    confirm_high_risk: bool = False,
    visibility: str = "paid",  # P0-4: Default visibility for paywall
) -> Dict[str, Dict]:
    """
    Stage 5: Publish to Ghost

    Strategy:
    - Post A (Flash): publish-send (email)
    - Post B (Earnings): publish only (no email)
    - Post C (Deep Dive): publish only (no email)

    All posts use paywall (visibility=paid) by default.
    """
    console.print("\n[bold cyan]Stage 5: Publish[/bold cyan]")

    results = {}

    # Determine newsletter/segment based on mode
    if mode == "test":
        newsletter = "daily-brief-test"
        segment = "label:internal"
    else:
        newsletter = "daily-brief"
        segment = "status:-free"  # Paid members only

    console.print(f"  Newsletter: {newsletter}, Segment: {segment}, Visibility: {visibility}")

    # Publish order: B, C first (no email), then A (with email)
    publish_order = ["earnings", "deep", "flash"]

    for post_type in publish_order:
        post = posts.get(post_type)
        if post is None:
            results[post_type] = {"skipped": True, "reason": "Post not generated"}
            continue

        # Validate post type
        if not isinstance(post, PostOutput):
            console.print(f"    [red]✗ Invalid post type: {type(post).__name__}[/red]")
            results[post_type] = {"skipped": True, "reason": f"Invalid post type: {type(post).__name__}"}
            continue

        # Only Post A (Flash) gets email
        send_email = (post_type == "flash" and mode == "prod")

        console.print(f"  Publishing {post_type}...")

        result = publish_post(
            post=post,
            mode=mode,
            newsletter=newsletter,
            segment=segment,
            send_email=send_email,
            confirm_high_risk=confirm_high_risk,
            visibility=visibility,  # P0-4: Pass visibility to Ghost
        )

        results[post_type] = result
        post.publish_result = result

        if result.get("success"):
            console.print(f"    [green]✓ {result.get('url')}[/green]")
            if result.get("newsletter_sent"):
                console.print("      [cyan]Newsletter sent[/cyan]")
        else:
            console.print(f"    [red]✗ {result.get('error')}[/red]")

    return results


def stage_archive(
    result: DailyPipelineResult,
    posts: Dict[str, Optional[PostOutput]]
) -> Path:
    """
    Stage 6: Archive all artifacts
    """
    console.print("\n[bold cyan]Stage 6: Archive[/bold cyan]")

    archive_dir = Path(f"data/artifacts/{result.date}")
    archive_dir.mkdir(parents=True, exist_ok=True)

    # Save posts
    for post_type, post in posts.items():
        if post:
            # JSON
            json_path = archive_dir / f"post_{post_type}.json"
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(post.json_data, f, indent=2, ensure_ascii=False)

            # HTML
            html_path = archive_dir / f"post_{post_type}.html"
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(post.html_content)

    # Save pipeline result
    result_path = archive_dir / "pipeline_result.json"
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump({
            "run_id": result.run_id,
            "date": result.date,
            "mode": result.mode,
            "quality_passed": result.quality_gates_passed,
            "duration_seconds": result.duration_seconds,
            "errors": result.errors,
            "warnings": result.warnings,
            "publish_results": result.publish_results,
        }, f, indent=2, ensure_ascii=False)

    console.print(f"  ✓ Archived to {archive_dir}")

    return archive_dir


# =============================================================================
# Main Pipeline
# =============================================================================

@click.command()
@click.option("--mode", "-m", default="test", type=click.Choice(["test", "prod"]),
              help="Run mode: test (internal only) or prod (live)")
@click.option("--date", "-d", "run_date", default=None, help="Date override (YYYY-MM-DD)")
@click.option("--theme", "-t", help="Force specific theme")
@click.option("--skip-publish", is_flag=True, help="Skip Ghost publishing")
@click.option("--confirm-high-risk", is_flag=True, help="Confirm high-risk segment")
@click.option("--posts", "-p", multiple=True, type=click.Choice(["flash", "earnings", "deep"]),
              help="Specific posts to generate (default: all)")
def main(
    mode: str,
    run_date: Optional[str],
    theme: Optional[str],
    skip_publish: bool,
    confirm_high_risk: bool,
    posts: tuple
):
    """
    Run the daily 3-post pipeline.

    \b
    Posts generated:
    - Flash (Post A): Market news impact brief - ALWAYS
    - Earnings (Post B): Earnings reaction & fair value - CONDITIONAL
    - Deep Dive (Post C): Full investment memo - ALWAYS
    """
    from ..utils.time import get_run_id

    start_time = time.time()
    run_id = get_run_id()
    run_date = run_date or date.today().isoformat()

    console.print(Panel.fit(
        f"[bold]Daily Brief Pipeline v2[/bold]\n"
        f"Run ID: {run_id[:12]}...\n"
        f"Date: {run_date}\n"
        f"Mode: {mode}\n"
        f"Posts: {', '.join(posts) if posts else 'all'}",
        border_style="blue",
    ))

    if mode == "test":
        console.print("[yellow]TEST MODE - Publishing to internal only[/yellow]\n")
    else:
        console.print("[red]PRODUCTION MODE - Publishing to live[/red]\n")
        if not confirm_high_risk:
            console.print("[yellow]⚠ Add --confirm-high-risk to enable newsletter send[/yellow]\n")

    result = DailyPipelineResult(
        run_id=run_id,
        date=run_date,
        mode=mode,
    )

    try:
        # Stage 1: Ingest
        ingest_data = stage_ingest(run_date, theme)

        # Stage 2: Pack
        edition_pack = stage_pack(ingest_data, run_date, run_id)
        result.edition_pack_path = str(Path("out/edition_pack.json"))

        # Stage 3: Write
        post_types = list(posts) if posts else None
        generated_posts = stage_write(edition_pack, run_id, post_types)
        result.posts = generated_posts

        # Stage 4: QA
        qa_results = stage_qa(generated_posts, edition_pack)
        result.quality_gates_passed = all(
            r.get("passed", False) for r in qa_results.values()
        )

        # Stage 5: Publish
        if not skip_publish:
            if not os.getenv("GHOST_API_URL"):
                console.print("\n[yellow]Ghost not configured - skipping publish[/yellow]")
            else:
                publish_results = stage_publish(
                    generated_posts,
                    mode=mode,
                    confirm_high_risk=confirm_high_risk,
                )
                result.publish_results = publish_results
        else:
            console.print("\n[yellow]Publish skipped (--skip-publish)[/yellow]")

        # Stage 6: Archive
        archive_path = stage_archive(result, generated_posts)

    except Exception as e:
        console.print(f"\n[red]Pipeline failed: {e}[/red]")
        result.errors.append(str(e))
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # Complete
    result.duration_seconds = time.time() - start_time

    console.print(Panel.fit(
        f"[bold green]Pipeline Complete![/bold green]\n"
        f"Duration: {result.duration_seconds:.1f}s\n"
        f"Quality: {'PASSED' if result.quality_gates_passed else 'FAILED'}\n"
        f"Posts: {len([p for p in result.posts.values() if p])} generated",
        border_style="green",
    ))

    # Summary table
    table = Table(title="Output Summary")
    table.add_column("Post", style="cyan")
    table.add_column("Slug")
    table.add_column("Quality")
    table.add_column("Published")

    for post_type, post in result.posts.items():
        if post:
            slug = getattr(post, 'slug', '-')
            quality = "✓" if getattr(post, 'quality_passed', False) else "✗"
            publish_result = getattr(post, 'publish_result', None)
            published = "✓" if publish_result and publish_result.get("success") else "✗"
            table.add_row(post_type, slug, quality, published)
        else:
            table.add_row(post_type, "-", "-", "-")

    console.print(table)


if __name__ == "__main__":
    main()
