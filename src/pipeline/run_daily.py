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
    """Single source of truth for the day's content

    v4.3 Edition Coherence:
    - primary_theme: 今日主線投資主題（如 ai_chips, quantum）
    - deep_dive_ticker: 必須是 primary_theme.matched_tickers 之一
    - recent_earnings: 必須是 deep_dive_ticker 的財報
    - 三篇文章（Flash/Earnings/Deep）共用同一個主題
    """
    meta: Dict[str, Any]
    date: str
    edition: str
    primary_event: Optional[Dict] = None
    primary_theme: Optional[Dict] = None  # v4.3: 今日主線主題
    news_items: List[Dict] = field(default_factory=list)
    market_data: Dict[str, Dict] = field(default_factory=dict)
    earnings_calendar: List[Dict] = field(default_factory=list)
    key_stocks: List[Dict] = field(default_factory=list)
    peer_data: Dict[str, Dict] = field(default_factory=dict)
    peer_table: Optional[Dict] = None  # Formatted peer comparison table
    valuations: Dict[str, Dict] = field(default_factory=dict)
    deep_dive_ticker: Optional[str] = None  # v4.3: 必須與 primary_theme 一致
    deep_dive_reason: Optional[str] = None
    deep_dive_data: Optional[Dict] = None  # P1-2: Thicker data pack for deep dive
    recent_earnings: Optional[Dict] = None  # v4.2: 必須是 deep_dive_ticker 的財報
    edition_coherence: Optional[Dict] = None  # v4.3: 記錄主題一致性狀態

    def to_dict(self) -> Dict:
        return asdict(self)

    @property
    def run_id(self) -> Optional[str]:
        """Convenience accessor for meta.run_id."""
        return (self.meta or {}).get("run_id")

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
# Checkpoint Functions (斷點續跑)
# =============================================================================

CHECKPOINT_PATH = Path("out/checkpoint.json")


def _init_checkpoint(run_id: str, run_date: str) -> Dict:
    """Initialize a new checkpoint file"""
    ckpt = {
        "run_id": run_id,
        "date": run_date,
        "started_at": datetime.now().isoformat(),
        "stages": {},
    }
    CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CHECKPOINT_PATH, "w", encoding="utf-8") as f:
        json.dump(ckpt, f, indent=2, ensure_ascii=False)
    return ckpt


def _load_checkpoint(run_date: str) -> Optional[Dict]:
    """Load checkpoint if it exists and matches the current date"""
    if not CHECKPOINT_PATH.exists():
        return None
    try:
        with open(CHECKPOINT_PATH, "r", encoding="utf-8") as f:
            ckpt = json.load(f)
        # Only use checkpoint from same day
        if ckpt.get("date") != run_date:
            console.print(f"  [yellow]Checkpoint from {ckpt.get('date')}, ignoring[/yellow]")
            return None
        return ckpt
    except Exception as e:
        console.print(f"  [yellow]Failed to load checkpoint: {e}[/yellow]")
        return None


def _update_checkpoint(stage: str, completed: bool = True, error: str = None) -> None:
    """Update checkpoint with stage status"""
    try:
        if CHECKPOINT_PATH.exists():
            with open(CHECKPOINT_PATH, "r", encoding="utf-8") as f:
                ckpt = json.load(f)
        else:
            ckpt = {"stages": {}}

        ckpt["stages"][stage] = {
            "completed": completed,
            "timestamp": datetime.now().isoformat(),
        }
        if error:
            ckpt["stages"][stage]["error"] = error

        with open(CHECKPOINT_PATH, "w", encoding="utf-8") as f:
            json.dump(ckpt, f, indent=2, ensure_ascii=False)
    except Exception as e:
        console.print(f"  [yellow]Failed to update checkpoint: {e}[/yellow]")


def _is_stage_completed(ckpt: Optional[Dict], stage: str) -> bool:
    """Check if a stage is marked as completed in checkpoint"""
    if not ckpt:
        return False
    return ckpt.get("stages", {}).get(stage, {}).get("completed", False)


def _load_existing_post(post_type: str) -> Optional[PostOutput]:
    """Load an existing post from out/ directory"""
    json_path = Path(f"out/post_{post_type}.json")
    if not json_path.exists():
        return None

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            post_dict = json.load(f)

        return PostOutput(
            post_type=post_type,
            title=post_dict.get("title", ""),
            slug=post_dict.get("slug", ""),
            json_data=post_dict,
            html_content=post_dict.get("html", ""),
        )
    except Exception as e:
        console.print(f"  [yellow]Failed to load {post_type}: {e}[/yellow]")
        return None


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


def resolve_visibility(visibility: Optional[str] = None) -> str:
    """Resolve post visibility from explicit value or environment default."""
    resolved = (visibility or os.getenv("GHOST_POST_VISIBILITY", "members")).strip().lower()
    if resolved not in {"public", "members", "paid"}:
        console.print(f"[yellow]Invalid visibility '{resolved}', defaulting to 'members'[/yellow]")
        resolved = "members"
    return resolved


def publish_post(
    post: PostOutput,
    mode: str,
    newsletter: str,
    segment: str,
    send_email: bool = False,
    confirm_high_risk: bool = False,
    visibility: Optional[str] = None,  # Default to members (free) unless overridden
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
    visibility = resolve_visibility(visibility)

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

    # P0-5: 至少 7-8 條新聞 (Flash News Radar 最小結構)
    MIN_NEWS_ITEMS = 8
    TARGET_NEWS_ITEMS = 8
    if len(data["news_items"]) < MIN_NEWS_ITEMS:
        console.print(f"  [yellow]⚠ Only {len(data['news_items'])} news items, need {MIN_NEWS_ITEMS}-{TARGET_NEWS_ITEMS}[/yellow]")
        console.print("  Collecting Layer 2 Radar Fillers...")
        data["news_items"] = ensure_minimum_news_items(
            news_items=data["news_items"],
            universe_tickers=universe_tickers,
            min_count=TARGET_NEWS_ITEMS,  # 目標 12 條
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

    # Determine theme (v4.3: 使用投資主題而非 event_type)
    primary_theme = None
    if primary:
        # 優先使用 matched_themes（投資主題如 ai_chips, quantum）
        theme_id = primary.matched_themes[0] if primary.matched_themes else primary.event_type
        primary_theme = {
            "id": theme_id,
            "matched_tickers": primary.matched_tickers,
            "matched_themes": primary.matched_themes,  # v4.3: 新增完整主題列表
            "event_type": primary.event_type,  # v4.3: 保留事件類型供參考
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

    # v4.3: Build edition coherence check
    edition_coherence = {
        "theme_id": primary_theme.get("id") if primary_theme else None,
        "theme_tickers": primary_theme.get("matched_tickers", []) if primary_theme else [],
        "deep_ticker_in_theme": deep_ticker in (primary_theme.get("matched_tickers", []) if primary_theme else []),
        "earnings_ticker_match": recent_earnings.get("ticker") == deep_ticker if recent_earnings else None,
        "coherent": False,  # Will be set below
    }
    # Check if all three posts will be coherent
    edition_coherence["coherent"] = (
        edition_coherence["deep_ticker_in_theme"] and
        edition_coherence["earnings_ticker_match"] is not False
    )
    if edition_coherence["coherent"]:
        console.print(f"  ✓ Edition coherence: {edition_coherence['theme_id']} → {deep_ticker}")
    else:
        console.print(f"  [yellow]⚠ Edition coherence check failed: {edition_coherence}[/yellow]")

    # Build pack
    pack = EditionPack(
        meta={
            "run_id": run_id,
            "created_at": datetime.now().isoformat(),
            "version": "4.3",  # v4.3: Edition Coherence
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
        recent_earnings=recent_earnings,  # v4.2: 必須是 deep_dive_ticker 的財報
        edition_coherence=edition_coherence,  # v4.3: 主題一致性
    )

    # Add market_snapshot to pack meta
    if ingest_data.get("market_snapshot"):
        pack.meta["market_snapshot"] = ingest_data["market_snapshot"]

    # Save
    pack_path = pack.save()
    console.print(f"  ✓ Edition pack saved to {pack_path}")

    return pack


def _should_generate_earnings(edition_pack: EditionPack, max_days_old: int = 90) -> tuple:
    """P0-2: 判斷是否生成 Earnings 文章

    規則：
    1. 必須有 recent_earnings 資料
    2. 財報日期不能太舊（預設 90 天內）

    Args:
        edition_pack: 今日版本資料包
        max_days_old: 財報最大天數

    Returns:
        (should_generate: bool, reason: str)
    """
    if not edition_pack.recent_earnings:
        return False, "no_earnings_data"

    earnings_date = edition_pack.recent_earnings.get("earnings_date")
    if not earnings_date:
        return False, "no_earnings_date"

    # 檢查財報是否太舊
    try:
        from datetime import datetime
        earnings_dt = datetime.fromisoformat(earnings_date.replace("Z", "+00:00"))
        days_old = (datetime.now(earnings_dt.tzinfo or None) - earnings_dt).days if earnings_dt.tzinfo else (datetime.now() - datetime.fromisoformat(earnings_date)).days
        if days_old > max_days_old:
            return False, f"earnings_too_old_{days_old}d"
    except Exception:
        pass  # 無法解析日期時，仍然生成

    return True, "recent_earnings_available"


def stage_write(
    edition_pack: EditionPack,
    run_id: str,
    post_types: List[str] = None,
    checkpoint: Optional[Dict] = None,  # Checkpoint for resume support
) -> Dict[str, Optional[PostOutput]]:
    """
    Stage 3: Generate posts using skills (P0-1: 使用三篇專用 prompts + schemas)

    - Post A (Flash): Always - uses prompts/postA.prompt.md + schemas/postA.schema.json
    - Post B (Earnings): Conditional* - uses prompts/postB.prompt.md + schemas/postB.schema.json
    - Post C (Deep Dive): Always - uses prompts/postC.prompt.md + schemas/postC.schema.json

    *P0-2: Earnings 只在有近期財報資料時生成

    Output files (P0-1):
    - out/post_flash.json, out/post_flash.html
    - out/post_earnings.json, out/post_earnings.html (可選)
    - out/post_deep.json, out/post_deep.html
    """
    from ..writers.codex_runner import CodexRunner
    from ..writers.cross_links import generate_cross_links, inject_cross_links

    console.print("\n[bold cyan]Stage 3: Write (P0-1: Three Prompts/Schemas)[/bold cyan]")

    # P0-2: 判斷是否生成 Earnings
    should_earnings, earnings_reason = _should_generate_earnings(edition_pack)

    if post_types is None:
        # v4.3: 預設生成 flash 和 deep，Earnings 條件觸發
        post_types = ["flash", "deep"]
        if should_earnings:
            post_types.insert(1, "earnings")  # 插入到 flash 和 deep 之間
            console.print(f"  ✓ Earnings 觸發: {earnings_reason}")
        else:
            console.print(f"  [yellow]⚠ Earnings 跳過: {earnings_reason}[/yellow]")

    # Generate cross-links for all posts
    topic = "market"
    if edition_pack.primary_theme:
        topic = edition_pack.primary_theme.get("id", "market")

    cross_links = generate_cross_links(
        run_date=edition_pack.date,
        topic=topic,
        deep_dive_ticker=edition_pack.deep_dive_ticker,
        earnings_ticker=edition_pack.deep_dive_ticker,  # Same ticker for coherence
        has_earnings="earnings" in post_types,
    )
    console.print(f"  ✓ Generated cross-links for {len(post_types)} posts")

    # P0-1: Add cross_links to edition_pack for prompts to use
    pack_dict = edition_pack.to_dict()
    pack_dict["cross_links"] = cross_links

    posts = {}

    # Resume: Load completed posts from checkpoint
    for pt in post_types:
        stage_name = f"write_{pt}"
        if _is_stage_completed(checkpoint, stage_name):
            existing = _load_existing_post(pt)
            if existing:
                posts[pt] = existing
                console.print(f"  ✓ {pt}: loaded from checkpoint (skipped)")
            else:
                console.print(f"  [yellow]⚠ {pt}: checkpoint says completed but file not found[/yellow]")

    # Filter to only posts that need generation
    posts_to_generate = [pt for pt in post_types if pt not in posts]
    if not posts_to_generate:
        console.print("  ✓ All posts loaded from checkpoint")
        return posts

    console.print(f"  Generating: {', '.join(posts_to_generate)}")

    def _generate_one(pt: str) -> tuple[str, Optional[PostOutput]]:
        console.print(f"  Generating {pt}...")
        try:
            writer = CodexRunner(post_type=pt)
            console.print(f"    Using prompt: {writer.prompt_path}")
            console.print(f"    Using schema: {writer.schema_path}")

            ticker = edition_pack.deep_dive_ticker if pt in ["earnings", "deep"] else None

            slug = generate_slug(
                post_type=pt,
                topic=topic,
                ticker=ticker,
                run_date=edition_pack.date
            )

            if not validate_slug(slug, pt):
                raise ValueError(f"Invalid slug format: {slug}")

            post = writer.generate(
                pack_dict,
                run_id=run_id,
            )

            if not post:
                console.print(f"    [yellow]⚠ Failed to generate {pt}[/yellow]")
                return pt, None

            post_dict = post.to_dict()
            post_dict["slug"] = slug
            post_dict["meta"]["post_type"] = pt
            post_dict["meta"]["market_snapshot"] = edition_pack.meta.get("market_snapshot")
            if edition_pack.market_data:
                post_dict["market_data"] = edition_pack.market_data
            post_dict["meta"]["lang"] = "zh"
            _ensure_lang_tag(post_dict, "zh")
            site_url = _resolve_site_url()
            if site_url:
                post_dict["canonical_url"] = f"{site_url}/{slug}/"

            post_dict = inject_cross_links(post_dict, cross_links, pt)

            output = PostOutput(
                post_type=pt,
                title=post_dict.get("title", ""),
                slug=slug,
                json_data=post_dict,
                html_content=post_dict.get("html", ""),
            )

            _save_post_output(post_dict, pt)
            # Update checkpoint after successful save
            _update_checkpoint(f"write_{pt}", completed=True)
            console.print(f"    ✓ {pt}: {slug}")
            return pt, output

        except Exception as e:
            console.print(f"    [red]✗ Error generating {pt}: {e}[/red]")
            # Update checkpoint with error
            _update_checkpoint(f"write_{pt}", completed=False, error=str(e))
            import traceback
            traceback.print_exc()
            return pt, None

    use_parallel = os.getenv("PARALLEL_WRITE", "true").lower() == "true"
    if use_parallel and len(posts_to_generate) > 1:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        with ThreadPoolExecutor(max_workers=min(3, len(posts_to_generate))) as executor:
            futures = {executor.submit(_generate_one, pt): pt for pt in posts_to_generate}
            for future in as_completed(futures):
                pt, output = future.result()
                posts[pt] = output
    else:
        for pt in posts_to_generate:
            _, output = _generate_one(pt)
            posts[pt] = output

    return posts


def _save_post_output(post_dict: Dict, post_type: str) -> None:
    """P0-1: Save post output to out/ directory with type-specific naming

    P0-4/P0-5: 在存檔前進行 HTML 規範化
    """
    from ..writers.html_components import normalize_html, validate_paywall

    out_dir = Path("out")
    out_dir.mkdir(parents=True, exist_ok=True)

    # P0-4/P0-5: HTML 規範化
    html_content = post_dict.get("html", "")
    if html_content:
        html_content = normalize_html(html_content, post_type)
        post_dict["html"] = html_content

        # 驗證 paywall
        is_valid, msg = validate_paywall(html_content)
        if not is_valid:
            console.print(f"    [yellow]⚠ Paywall 驗證: {msg}[/yellow]")

    # Save JSON
    json_path = out_dir / f"post_{post_type}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(post_dict, f, indent=2, ensure_ascii=False)

    # Save HTML
    html_path = out_dir / f"post_{post_type}.html"
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)


def _resolve_site_url() -> str:
    site_url = os.getenv("GHOST_SITE_URL") or os.getenv("GHOST_API_URL") or ""
    return site_url.rstrip("/")


def _ensure_lang_tag(post_dict: Dict, lang: str) -> None:
    tags = post_dict.get("tags") or []
    lang_tag = f"lang-{lang}"
    if lang_tag not in tags:
        tags.append(lang_tag)
    post_dict["tags"] = tags


def stage_translate_posts(
    posts: Dict[str, Optional[PostOutput]],
    lang: str = "en",
) -> Dict[str, Optional[PostOutput]]:
    """Create translated posts for publishing."""
    from ..writers.translation import TranslationRunner

    console.print("\n[bold cyan]Stage 3.5: Translate Posts[/bold cyan]")
    translated_posts: Dict[str, Optional[PostOutput]] = {}
    runner = TranslationRunner()
    site_url = _resolve_site_url()

    for post_type, post in posts.items():
        if post is None:
            continue

        post_dict = post.json_data
        translated = runner.translate(post_dict)
        if not translated:
            console.print(f"  [yellow]⚠ {post_type}: translation failed[/yellow]")
            translated_posts[post_type] = None
            continue

        slug = post.slug
        if not slug.endswith(f"-{lang}"):
            slug = f"{slug}-{lang}"
        translated["slug"] = slug
        translated.setdefault("meta", {})
        translated["meta"]["lang"] = lang
        translated["meta"]["source_lang"] = "zh"
        translated["title_en"] = translated.get("title") or translated.get("title_en")
        _ensure_lang_tag(translated, lang)
        if site_url:
            translated["canonical_url"] = f"{site_url}/{slug}/"

        if post_dict.get("feature_image_path"):
            translated["feature_image_path"] = post_dict.get("feature_image_path")
            translated["feature_image_alt"] = post_dict.get("feature_image_alt")

        translated_posts[post_type] = PostOutput(
            post_type=f"{post_type}_{lang}",
            title=translated.get("title", ""),
            slug=slug,
            json_data=translated,
            html_content=translated.get("html", ""),
        )

        console.print(f"  ✓ {post_type}: {slug}")

    return translated_posts


def stage_enhance_posts(
    posts: Dict[str, Optional[PostOutput]],
    research_pack_path: str = "out/research_pack.json",
) -> Dict[str, Optional[PostOutput]]:
    """Enhance flash/earnings posts with a second editing pass."""
    if os.getenv("ENABLE_ENHANCE", "true").lower() != "true":
        return posts

    try:
        from scripts.enhance_post import enhance_post
    except Exception:
        console.print("[yellow]⚠ enhance_post import failed, skipping enhance[/yellow]")
        return posts

    console.print("\n[bold cyan]Stage 3.3: Enhance Posts[/bold cyan]")

    for post_type, post in posts.items():
        if post is None or post_type not in {"flash", "earnings"}:
            continue

        draft_path = f"out/post_{post_type}.json"
        output_path = f"out/post_{post_type}_enhanced.json"

        console.print(f"  Enhancing {post_type}...")
        success = enhance_post(
            research_pack_path=research_pack_path,
            draft_path=draft_path,
            output_path=output_path,
            use_litellm=True,
            model=os.getenv("CODEX_MODEL") or os.getenv("LITELLM_MODEL"),
            skip_quality_gates=False,
        )

        if not success:
            console.print(f"  [yellow]⚠ {post_type}: enhance failed, keeping draft[/yellow]")
            continue

        try:
            with open(output_path, "r", encoding="utf-8") as f:
                enhanced = json.load(f)
            post.json_data = enhanced
            post.title = enhanced.get("title", post.title)
            post.slug = enhanced.get("slug", post.slug)
            post.html_content = enhanced.get("html", post.html_content)
            _save_post_output(enhanced, post_type)
            console.print(f"  ✓ {post_type}: enhanced")
        except Exception as e:
            console.print(f"  [yellow]⚠ {post_type}: failed to load enhanced ({e})[/yellow]")

    return posts


def stage_qa(
    posts: Dict[str, Optional[PostOutput]],
    edition_pack: EditionPack,
    run_id: str = "",
) -> Dict[str, Dict]:
    """
    Stage 4: Run quality gates on all posts (P0-6: 三篇各自 + 總 Gate)

    P0-6 實作：
    1. 每篇文章獨立執行品質 Gate
    2. 總 Gate 檢查跨篇一致性（Edition Coherence）
    3. 任何一篇 fail = 總體 fail（Fail-Closed）
    """
    from ..quality.quality_gate import run_daily_quality_gate

    console.print("\n[bold cyan]Stage 4: Quality Gate (P0-6: Daily Gate)[/bold cyan]")

    # 收集文章 dict
    posts_dict = {}
    for post_type, post in posts.items():
        if post is not None:
            posts_dict[post_type] = post.json_data

    effective_run_id = run_id or edition_pack.meta.get("run_id", "")

    # P0-6: 執行 Daily Quality Gate
    daily_report = run_daily_quality_gate(
        posts=posts_dict,
        edition_pack=edition_pack.to_dict(),
        run_id=effective_run_id,
        date=edition_pack.date,
    )

    # 更新各篇 PostOutput 的 quality 狀態
    for post_type, post in posts.items():
        if post is not None and post_type in daily_report.post_reports:
            report = daily_report.post_reports[post_type]
            post.quality_passed = report.overall_passed
            post.quality_report = report.to_dict()

    # 顯示各篇結果
    for post_type, report in daily_report.post_reports.items():
        status = "✓" if report.overall_passed else "✗"
        color = "green" if report.overall_passed else "red"
        console.print(f"  [{color}]{status} {post_type}[/{color}]")

        if not report.overall_passed:
            for error in report.errors[:3]:
                console.print(f"      - {error}")

    # 顯示 Daily Gate 結果
    daily_status = "✓" if daily_report.daily_gate.passed else "✗"
    daily_color = "green" if daily_report.daily_gate.passed else "red"
    console.print(f"  [{daily_color}]{daily_status} Daily Edition Coherence[/{daily_color}]")

    if not daily_report.daily_gate.passed:
        console.print(f"      - {daily_report.daily_gate.message}")

    # 總結
    console.print(f"\n  Overall: {'[green]PASSED[/green]' if daily_report.overall_passed else '[red]FAILED[/red]'}")
    console.print(f"  Can Publish: {daily_report.can_publish_all}")

    # 儲存 quality report
    report_path = Path("out/quality_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(daily_report.to_dict(), f, indent=2, ensure_ascii=False)
    console.print(f"  Report saved to: {report_path}")

    return {
        "overall_passed": daily_report.overall_passed,
        "can_publish_all": daily_report.can_publish_all,
        "post_reports": {
            pt: r.to_dict() for pt, r in daily_report.post_reports.items()
        },
        "daily_gate": {
            "passed": daily_report.daily_gate.passed,
            "message": daily_report.daily_gate.message,
            "details": daily_report.daily_gate.details,
        },
        "errors": daily_report.errors,
        "warnings": daily_report.warnings,
    }


def stage_feature_images(
    posts: Dict[str, Optional[PostOutput]],
    output_dir: str = "out/feature_images",
) -> Dict[str, Dict]:
    """Stage 4.5: Generate feature images for posts."""
    from ..writers.feature_images import generate_feature_image

    console.print("\n[bold cyan]Stage 4.5: Feature Images[/bold cyan]")
    results: Dict[str, Dict] = {}

    for post_type, post in posts.items():
        if post is None:
            continue

        post_dict = post.json_data
        result = generate_feature_image(post_type, post_dict, output_dir=output_dir)
        if not result:
            console.print(f"  [yellow]⚠ {post_type}: feature image skipped[/yellow]")
            continue

        post_dict["feature_image_path"] = str(result.path)
        post_dict["feature_image_alt"] = result.alt_text
        meta = post_dict.get("meta", {})
        meta["feature_image_kind"] = result.kind
        post_dict["meta"] = meta

        results[post_type] = {
            "path": str(result.path),
            "alt": result.alt_text,
            "kind": result.kind,
        }

        console.print(f"  ✓ {post_type}: {result.path}")

    return results


def stage_run_report(
    posts: Dict[str, Optional[PostOutput]],
    run_id: str,
    run_date: str,
    output_dir: str = "data/run_reports",
) -> Path:
    """Stage 4.8: Save run report stats and compare with golden snapshot if present."""
    import re

    console.print("\n[bold cyan]Stage 4.8: Run Report[/bold cyan]")
    stats = {"run_id": run_id, "date": run_date, "posts": {}}

    for post_type, post in posts.items():
        if post is None:
            continue
        data = post.json_data
        markdown = data.get("markdown", "") or ""
        html = data.get("html", "") or ""
        stats["posts"][post_type] = {
            "word_count": len(markdown.split()),
            "char_count": len(markdown),
            "tldr_count": len(data.get("tldr") or []),
            "sources_count": len(data.get("sources") or []),
            "html_length": len(html),
            "table_count": len(re.findall(r"<table", html, flags=re.IGNORECASE)),
            "heading_count": len(re.findall(r"<h[2-4]", html, flags=re.IGNORECASE)),
        }

    output_path = Path(output_dir) / f"run_report_{run_id[:8]}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)

    golden_path = Path("qa/golden_snapshot.json")
    if golden_path.exists():
        try:
            with open(golden_path, "r", encoding="utf-8") as f:
                golden = json.load(f)
            for post_type, metrics in stats["posts"].items():
                baseline = (golden.get("posts") or {}).get(post_type, {})
                if not baseline:
                    continue
                word_delta = metrics["word_count"] - baseline.get("word_count", metrics["word_count"])
                if abs(word_delta) > baseline.get("word_count", metrics["word_count"]) * 0.3:
                    console.print(f"  [yellow]⚠ {post_type}: word_count drift {word_delta}[/yellow]")
        except Exception:
            console.print("[yellow]⚠ Golden snapshot compare failed[/yellow]")

    console.print(f"  ✓ Run report saved to {output_path}")
    return output_path


def stage_publish(
    posts: Dict[str, Optional[PostOutput]],
    mode: str,
    confirm_high_risk: bool = False,
    visibility: Optional[str] = None,  # Default visibility for free members
    en_posts: Optional[Dict[str, Optional[PostOutput]]] = None,
) -> Dict[str, Dict]:
    """
    Stage 5: Publish to Ghost (P0-7: Upsert by slug)

    P0-7 實作：
    - 以 slug 為 unique key 執行 upsert
    - 若 slug 已存在：更新內容（不重發 newsletter）
    - 若 slug 不存在：建立新文章

    Strategy:
    - Post A (Flash): publish-send (email on first create only)
    - Post B (Earnings): publish only (no email)
    - Post C (Deep Dive): publish only (no email)

    All posts default to members visibility unless overridden.
    """
    from ..publishers.ghost_admin import GhostPublisher

    console.print("\n[bold cyan]Stage 5: Publish (P0-7: Upsert by slug)[/bold cyan]")

    results = {}
    visibility = resolve_visibility(visibility)

    # Determine newsletter/segment based on mode
    if mode == "test":
        segment = "label:internal"
    else:
        segment = "status:-free"  # Paid members only

    console.print(f"  Mode: {mode}, Segment: {segment}, Visibility: {visibility}")

    send_all_newsletters = os.getenv("GHOST_SEND_ALL_NEWSLETTERS", "").lower() == "true"

    # Publish order: B, C first (no email), then A (with email on first create)
    # Set GHOST_SEND_ALL_NEWSLETTERS=true to send for all posts.
    publish_order = ["earnings", "deep", "flash"]

    with GhostPublisher() as publisher:
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

            if send_all_newsletters:
                send_newsletter = (mode == "prod")
            else:
                # Only Post A (Flash) gets email on first create
                send_newsletter = (post_type == "flash" and mode == "prod")

            console.print(f"  Publishing {post_type} (slug: {post.slug})...")

            # Upload feature image if present
            feature_path = post.json_data.get("feature_image_path")
            if feature_path and os.getenv("GHOST_FEATURE_IMAGE_UPLOAD", "true").lower() != "false":
                image_url = publisher.upload_image(Path(feature_path))
                if image_url:
                    post.json_data["feature_image"] = image_url
                    if post.json_data.get("feature_image_alt"):
                        post.json_data["feature_image_alt"] = post.json_data.get("feature_image_alt")
                else:
                    console.print(f"    [yellow]⚠ Feature image upload failed for {post_type}[/yellow]")

            # P0-7: Use upsert_by_slug
            result = publisher.upsert_by_slug(
                post=post.json_data,
                status="published" if mode == "prod" else "draft",
                send_newsletter=send_newsletter,
                email_segment=segment,
                visibility=visibility,
            )

            results[post_type] = result.to_dict()
            post.publish_result = result.to_dict()

            if result.success:
                console.print(f"    [green]✓ {result.url}[/green]")
                if result.newsletter_sent:
                    console.print("      [cyan]Newsletter sent[/cyan]")
            else:
                console.print(f"    [red]✗ {result.error}[/red]")

        # Publish English variants (no newsletter)
        if en_posts:
            console.print("\n  Publishing English variants...")
            for post_type, post in en_posts.items():
                if post is None:
                    continue
                console.print(f"  Publishing {post.post_type} (slug: {post.slug})...")

                feature_path = post.json_data.get("feature_image_path")
                if feature_path and os.getenv("GHOST_FEATURE_IMAGE_UPLOAD", "true").lower() != "false":
                    image_url = publisher.upload_image(Path(feature_path))
                    if image_url:
                        post.json_data["feature_image"] = image_url

                result = publisher.upsert_by_slug(
                    post=post.json_data,
                    status="published" if mode == "prod" else "draft",
                    send_newsletter=False,
                    email_segment=segment,
                    visibility=visibility,
                )
                results[f"{post.post_type}"] = result.to_dict()

                if result.success:
                    console.print(f"    [green]✓ {result.url}[/green]")
                else:
                    console.print(f"    [red]✗ {result.error}[/red]")

    return results


def stage_archive(
    result: DailyPipelineResult,
    posts: Dict[str, Optional[PostOutput]],
    en_posts: Optional[Dict[str, Optional[PostOutput]]] = None,
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

            feature_path = post.json_data.get("feature_image_path")
            if feature_path and Path(feature_path).exists():
                dest = archive_dir / Path(feature_path).name
                try:
                    dest.write_bytes(Path(feature_path).read_bytes())
                except Exception:
                    pass

    if en_posts:
        for post_type, post in en_posts.items():
            if post:
                json_path = archive_dir / f"post_{post.post_type}.json"
                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump(post.json_data, f, indent=2, ensure_ascii=False)

                html_path = archive_dir / f"post_{post.post_type}.html"
                with open(html_path, "w", encoding="utf-8") as f:
                    f.write(post.html_content)

                feature_path = post.json_data.get("feature_image_path")
                if feature_path and Path(feature_path).exists():
                    dest = archive_dir / Path(feature_path).name
                    try:
                        dest.write_bytes(Path(feature_path).read_bytes())
                    except Exception:
                        pass

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


def stage_minio_archive(run_date: str, out_dir: str = "out") -> Optional[Dict]:
    """
    Stage 7: Archive to MinIO (cloud backup)

    目錄結構:
    daily-brief/
    └── {year}/{month}/{day}/
        ├── edition_pack.json
        ├── post_flash.json
        ├── post_flash.html
        ├── post_earnings.json
        ├── post_earnings.html
        ├── post_deep.json
        ├── post_deep.html
        ├── quality_report.json
        └── feature_images/
            └── *.png
    """
    # Check if MinIO archiving is enabled
    if os.getenv("ENABLE_MINIO_ARCHIVE", "true").lower() != "true":
        console.print("\n[bold cyan]Stage 7: MinIO Archive[/bold cyan] [dim](disabled)[/dim]")
        return None

    console.print("\n[bold cyan]Stage 7: MinIO Archive[/bold cyan]")

    try:
        from ..publishers.minio_archiver import MinIOArchiver

        archiver = MinIOArchiver()
        result = archiver.archive_daily_run(run_date, out_dir)

        if result.success:
            console.print(
                f"  ✓ Uploaded {result.files_uploaded} files "
                f"({result.total_bytes / 1024:.1f} KB) to {result.bucket}/{result.prefix}"
            )
            return {
                "success": True,
                "files_uploaded": result.files_uploaded,
                "total_bytes": result.total_bytes,
                "bucket": result.bucket,
                "prefix": result.prefix,
            }
        else:
            console.print(f"  [yellow]⚠ MinIO archive failed: {result.error}[/yellow]")
            return {"success": False, "error": result.error}

    except ImportError as e:
        console.print(f"  [yellow]⚠ boto3 not installed, skipping MinIO archive[/yellow]")
        return {"success": False, "error": "boto3 not installed"}
    except Exception as e:
        console.print(f"  [red]✗ MinIO archive error: {e}[/red]")
        return {"success": False, "error": str(e)}


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
@click.option("--resume", "-r", is_flag=True, help="Resume from last checkpoint (skip completed stages)")
def main(
    mode: str,
    run_date: Optional[str],
    theme: Optional[str],
    skip_publish: bool,
    confirm_high_risk: bool,
    posts: tuple,
    resume: bool,
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
    run_date = run_date or date.today().isoformat()

    # Handle checkpoint/resume
    checkpoint = None
    if resume:
        checkpoint = _load_checkpoint(run_date)
        if checkpoint:
            run_id = checkpoint.get("run_id", get_run_id())
            console.print(f"[cyan]RESUME MODE - Loading checkpoint from {checkpoint.get('started_at')}[/cyan]\n")
        else:
            console.print("[yellow]No checkpoint found - starting fresh[/yellow]\n")
            run_id = get_run_id()
    else:
        run_id = get_run_id()

    console.print(Panel.fit(
        f"[bold]Daily Brief Pipeline v2[/bold]\n"
        f"Run ID: {run_id[:12]}...\n"
        f"Date: {run_date}\n"
        f"Mode: {mode}\n"
        f"Resume: {resume}\n"
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

    # Initialize or update checkpoint
    if not checkpoint:
        checkpoint = _init_checkpoint(run_id, run_date)

    try:
        # Stage 1: Ingest
        if _is_stage_completed(checkpoint, "ingest") and resume:
            console.print("\n[bold cyan]Stage 1: Ingest[/bold cyan] [dim](skipped - checkpoint)[/dim]")
            # Load from edition_pack
            if Path("out/edition_pack.json").exists():
                with open("out/edition_pack.json", "r") as f:
                    pack_dict = json.load(f)
                ingest_data = {
                    "news_items": pack_dict.get("news_items", []),
                    "market_data": pack_dict.get("market_data", {}),
                    "earnings_calendar": pack_dict.get("earnings_calendar", []),
                    "companies": {},  # Will be rebuilt in pack stage
                }
            else:
                console.print("  [yellow]⚠ edition_pack.json not found, re-ingesting[/yellow]")
                ingest_data = stage_ingest(run_date, theme)
                _update_checkpoint("ingest", completed=True)
        else:
            ingest_data = stage_ingest(run_date, theme)
            _update_checkpoint("ingest", completed=True)

        # Stage 2: Pack
        if _is_stage_completed(checkpoint, "pack") and resume:
            console.print("\n[bold cyan]Stage 2: Pack[/bold cyan] [dim](skipped - checkpoint)[/dim]")
            # Load edition_pack from file
            with open("out/edition_pack.json", "r") as f:
                pack_dict = json.load(f)
            edition_pack = EditionPack(
                meta=pack_dict.get("meta", {}),
                date=pack_dict.get("date", run_date),
                edition=pack_dict.get("edition", "postclose"),
                primary_event=pack_dict.get("primary_event"),
                primary_theme=pack_dict.get("primary_theme"),
                news_items=pack_dict.get("news_items", []),
                market_data=pack_dict.get("market_data", {}),
                earnings_calendar=pack_dict.get("earnings_calendar", []),
                key_stocks=pack_dict.get("key_stocks", []),
                peer_data=pack_dict.get("peer_data", {}),
                peer_table=pack_dict.get("peer_table"),
                valuations=pack_dict.get("valuations", {}),
                deep_dive_ticker=pack_dict.get("deep_dive_ticker"),
                deep_dive_reason=pack_dict.get("deep_dive_reason"),
                deep_dive_data=pack_dict.get("deep_dive_data"),
                recent_earnings=pack_dict.get("recent_earnings"),
                edition_coherence=pack_dict.get("edition_coherence"),
            )
            console.print(f"  ✓ Loaded edition_pack from checkpoint")
        else:
            edition_pack = stage_pack(ingest_data, run_date, run_id)
            _update_checkpoint("pack", completed=True)

        result.edition_pack_path = str(Path("out/edition_pack.json"))

        # Stage 3: Write (with checkpoint support)
        post_types = list(posts) if posts else None
        generated_posts = stage_write(edition_pack, run_id, post_types, checkpoint=checkpoint if resume else None)
        result.posts = generated_posts

        # Stage 3.3: Enhance
        generated_posts = stage_enhance_posts(generated_posts)
        result.posts = generated_posts

        # Stage 3.4: Feature Images
        stage_feature_images(generated_posts)

        # Stage 3.5: Translate (EN posts)
        en_posts = {}
        if os.getenv("ENABLE_EN_POSTS", "true").lower() == "true":
            en_posts = stage_translate_posts(generated_posts)

        # Stage 4: QA
        qa_results = stage_qa(generated_posts, edition_pack)
        result.quality_gates_passed = (
            bool(qa_results.get("overall_passed")) if isinstance(qa_results, dict) else False
        )

        # Stage 4.8: Run report
        stage_run_report(generated_posts, run_id, run_date)

        # Stage 5: Publish
        if not skip_publish:
            if not os.getenv("GHOST_API_URL"):
                console.print("\n[yellow]Ghost not configured - skipping publish[/yellow]")
            else:
                publish_results = stage_publish(
                    generated_posts,
                    mode=mode,
                    confirm_high_risk=confirm_high_risk,
                    en_posts=en_posts,
                )
                result.publish_results = publish_results
        else:
            console.print("\n[yellow]Publish skipped (--skip-publish)[/yellow]")

        # Stage 6: Archive (local)
        archive_path = stage_archive(result, generated_posts, en_posts=en_posts)

        # Stage 7: MinIO Archive (cloud backup)
        minio_result = stage_minio_archive(run_date)
        if minio_result:
            result.publish_results["minio_archive"] = minio_result

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
