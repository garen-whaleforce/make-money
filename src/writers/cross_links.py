"""Cross-Links Generator for Daily Package

生成三篇每日文章之間的互連連結。

規則：
- Flash: {topic}-{date}-flash
- Earnings: {ticker}-earnings-preview-{date}-earnings
- Deep Dive: {ticker}-deep-dive-{date}-deep

連結格式：
- flash_url: /posts/{flash_slug}
- earnings_url: /posts/{earnings_slug}
- deep_url: /posts/{deep_slug}
"""

import os
from typing import Dict, Optional
from datetime import date


def generate_cross_links(
    run_date: str,
    base_url: Optional[str] = None,
    topic: str = "market",
    deep_dive_ticker: Optional[str] = None,
    earnings_ticker: Optional[str] = None,
    has_earnings: bool = False,
) -> Dict[str, str]:
    """生成三篇文章的互連 URLs

    Args:
        run_date: 發布日期 (YYYY-MM-DD)
        base_url: Ghost 站點 URL (預設從環境變數讀取)
        topic: Flash 主題 slug
        deep_dive_ticker: Deep Dive 目標股票
        earnings_ticker: Earnings 目標股票
        has_earnings: 今日是否有 Earnings 文章

    Returns:
        Dict with keys: flash_url, earnings_url, deep_url
    """
    base_url = base_url or os.getenv("GHOST_API_URL", "https://rocket-screener.ghost.io")

    # 清理 base_url (移除尾部斜線)
    base_url = base_url.rstrip("/")

    # 生成 slugs
    topic_slug = topic.lower().replace(" ", "-").replace("_", "-")
    topic_slug = "".join(c for c in topic_slug if c.isalnum() or c == "-")

    flash_slug = f"{topic_slug}-{run_date}-flash"

    if deep_dive_ticker:
        deep_slug = f"{deep_dive_ticker.lower()}-deep-dive-{run_date}-deep"
    else:
        deep_slug = f"focus-deep-dive-{run_date}-deep"

    if has_earnings and earnings_ticker:
        earnings_slug = f"{earnings_ticker.lower()}-earnings-preview-{run_date}-earnings"
    else:
        earnings_slug = None

    # 生成 URLs
    links = {
        "flash_url": f"{base_url}/{flash_slug}/",
        "deep_url": f"{base_url}/{deep_slug}/",
    }

    if earnings_slug:
        links["earnings_url"] = f"{base_url}/{earnings_slug}/"
    else:
        # 沒有 Earnings 時，連結到法說行事曆或其他頁面
        links["earnings_url"] = f"{base_url}/tag/earnings/"

    return links


def inject_cross_links(
    post_data: Dict,
    links: Dict[str, str],
    post_type: str,
) -> Dict:
    """將 cross-links 注入到 post_data 中

    Args:
        post_data: 原始 post 資料
        links: cross-links dict
        post_type: flash, earnings, deep

    Returns:
        更新後的 post_data
    """
    # 注入到頂層
    post_data["flash_url"] = links.get("flash_url", "")
    post_data["earnings_url"] = links.get("earnings_url", "")
    post_data["deep_url"] = links.get("deep_url", "")

    # 根據 post_type 設定「本篇」標記
    post_data["is_flash"] = post_type == "flash"
    post_data["is_earnings"] = post_type == "earnings"
    post_data["is_deep"] = post_type == "deep"

    return post_data


def generate_package_metadata(
    run_date: str,
    topic: str,
    deep_dive_ticker: Optional[str] = None,
    earnings_ticker: Optional[str] = None,
    has_earnings: bool = False,
) -> Dict:
    """生成完整的 Package Metadata

    用於在三篇文章之間共享的上下文資訊。

    Args:
        run_date: 發布日期
        topic: Flash 主題
        deep_dive_ticker: Deep Dive 目標股票
        earnings_ticker: Earnings 目標股票
        has_earnings: 是否有 Earnings

    Returns:
        Package metadata dict
    """
    links = generate_cross_links(
        run_date=run_date,
        topic=topic,
        deep_dive_ticker=deep_dive_ticker,
        earnings_ticker=earnings_ticker,
        has_earnings=has_earnings,
    )

    return {
        "date": run_date,
        "topic": topic,
        "links": links,
        "posts": {
            "flash": {
                "slug": f"{topic.lower()}-{run_date}-flash",
                "title_prefix": "Daily Brief",
            },
            "deep": {
                "ticker": deep_dive_ticker,
                "slug": f"{deep_dive_ticker.lower() if deep_dive_ticker else 'focus'}-deep-dive-{run_date}-deep",
                "title_prefix": "Deep Dive",
            },
            "earnings": {
                "ticker": earnings_ticker,
                "slug": f"{earnings_ticker.lower() if earnings_ticker else ''}-earnings-preview-{run_date}-earnings" if has_earnings else None,
                "title_prefix": "Earnings",
                "available": has_earnings,
            },
        },
    }


def main():
    """CLI demo"""
    from rich.console import Console
    from rich.table import Table

    console = Console()

    run_date = date.today().isoformat()

    # 生成範例
    links = generate_cross_links(
        run_date=run_date,
        topic="AI Chips",
        deep_dive_ticker="NVDA",
        earnings_ticker="AMD",
        has_earnings=True,
    )

    console.print("[bold cyan]Cross-Links Generator[/bold cyan]\n")

    table = Table(title=f"Today's Package ({run_date})")
    table.add_column("Post Type", style="cyan")
    table.add_column("URL")

    for key, url in links.items():
        post_type = key.replace("_url", "").capitalize()
        table.add_row(post_type, url)

    console.print(table)

    # Package metadata
    metadata = generate_package_metadata(
        run_date=run_date,
        topic="AI Chips",
        deep_dive_ticker="NVDA",
        earnings_ticker="AMD",
        has_earnings=True,
    )

    console.print("\n[bold]Package Metadata:[/bold]")
    import json
    console.print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
