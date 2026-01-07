"""Ghost Admin API Publisher

使用 Ghost Admin API 發佈文章。
"""

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
import jwt

from ..utils.logging import get_logger
from ..writers.codex_runner import PostOutput

logger = get_logger(__name__)


@dataclass
class PublishResult:
    """發佈結果"""

    success: bool
    post_id: Optional[str] = None
    url: Optional[str] = None
    slug: Optional[str] = None
    status: Optional[str] = None
    updated_at: Optional[str] = None
    newsletter_sent: bool = False
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "post_id": self.post_id,
            "url": self.url,
            "slug": self.slug,
            "status": self.status,
            "updated_at": self.updated_at,
            "newsletter_sent": self.newsletter_sent,
            "error": self.error,
        }


class GhostPublisher:
    """Ghost Admin API 發佈器"""

    # 預設 newsletter slug 對照表 (環境變數名稱 -> 實際 Ghost slug)
    DEFAULT_NEWSLETTER_SLUG = "daily-en"  # Ghost 上的實際 slug

    def __init__(
        self,
        api_url: Optional[str] = None,
        admin_api_key: Optional[str] = None,
        newsletter_slug: Optional[str] = None,
        default_tags: Optional[list[str]] = None,
    ):
        """初始化 Ghost 發佈器

        Args:
            api_url: Ghost API URL
            admin_api_key: Ghost Admin API Key (格式: {id}:{secret})
            newsletter_slug: Newsletter slug (Ghost 上的實際 slug)
            default_tags: 預設標籤
        """
        self.api_url = api_url or os.getenv("GHOST_API_URL", "").rstrip("/")
        self.admin_api_key = admin_api_key or os.getenv("GHOST_ADMIN_API_KEY")
        self.newsletter_slug = newsletter_slug or os.getenv("GHOST_NEWSLETTER_SLUG") or self.DEFAULT_NEWSLETTER_SLUG
        self.default_tags = default_tags or ["Daily Deep Brief", "Research"]

        if not self.api_url:
            logger.warning("GHOST_API_URL not set")
        if not self.admin_api_key:
            logger.warning("GHOST_ADMIN_API_KEY not set")

        self._client = httpx.Client(timeout=httpx.Timeout(30.0))

    def _generate_jwt(self) -> Optional[str]:
        """生成 Ghost Admin API JWT token

        Returns:
            JWT token 或 None
        """
        if not self.admin_api_key:
            return None

        try:
            # Split the key into ID and SECRET
            key_parts = self.admin_api_key.split(":")
            if len(key_parts) != 2:
                logger.error("Invalid GHOST_ADMIN_API_KEY format. Expected {id}:{secret}")
                return None

            key_id, key_secret = key_parts

            # Prepare header and payload
            iat = int(time.time())
            header = {
                "alg": "HS256",
                "typ": "JWT",
                "kid": key_id,
            }
            payload = {
                "iat": iat,
                "exp": iat + 5 * 60,  # Token expires in 5 mins
                "aud": "/admin/",
            }

            # Create the token
            token = jwt.encode(
                payload,
                bytes.fromhex(key_secret),
                algorithm="HS256",
                headers=header,
            )

            return token

        except Exception as e:
            logger.error(f"Failed to generate JWT: {e}")
            return None

    def _get_headers(self) -> dict:
        """取得 API 請求 headers

        Returns:
            Headers 字典
        """
        token = self._generate_jwt()
        if not token:
            return {}

        return {
            "Authorization": f"Ghost {token}",
            "Content-Type": "application/json",
        }

    def _build_post_data(
        self,
        post,  # PostOutput or dict
        status: str = "draft",
        visibility: str = "members",
    ) -> dict:
        """建構 Ghost 文章資料

        Args:
            post: 文章輸出 (PostOutput 物件或 dict)
            status: 文章狀態 (draft/published)
            visibility: 可見度 (public/members/paid)
                - public: 所有人可見
                - members: 需登入（免費會員即可）
                - paid: 需付費會員

        Returns:
            Ghost API 格式的文章資料
        """
        # 支援 dict 和 PostOutput 物件
        def get_attr(name, default=None):
            if isinstance(post, dict):
                return post.get(name, default)
            return getattr(post, name, default)

        # 建構 tags
        tags = []
        post_tags = get_attr('tags', [])
        for tag_name in self.default_tags + post_tags:
            if tag_name and tag_name not in [t.get("name") for t in tags]:
                tags.append({"name": tag_name})

        # 建構文章資料
        excerpt = get_attr('excerpt', '')
        post_data = {
            "title": get_attr('title', ''),
            "slug": get_attr('slug', ''),
            "custom_excerpt": excerpt[:300] if excerpt else None,
            "tags": tags,
            "status": status,
            "visibility": visibility,  # 會員牆設定
        }

        # 使用 lexical 格式來保留 inline styles 並支援 paywall
        # Ghost 的 source=html 會過濾 inline styles，但 lexical HTML 卡片不會
        html = get_attr('html', '')
        if html:
            # 檢查是否有 paywall 標記
            paywall_markers = ["<!--members-only-->", "<!-- members-only -->"]
            html_parts = None

            for marker in paywall_markers:
                if marker in html:
                    html_parts = html.split(marker, 1)
                    break

            if html_parts and len(html_parts) == 2:
                # 有 paywall：拆成兩個 HTML card，中間插入 paywall card
                public_html, members_html = html_parts

                # 移除 paywall 前面的 CTA box（如果存在的話）
                # 尋找並移除類似 "解鎖全文（會員）" 的 CTA 區塊
                cta_start_markers = [
                    '<div style="border-radius:14px; padding:16px; margin:18px 0; background:#0b1220;',
                    '<div style="border-radius:14px; padding:16px; margin:18px 0; background:#0b1220',
                ]
                for cta_marker in cta_start_markers:
                    if cta_marker in public_html:
                        # 找到 CTA 開始位置
                        cta_start = public_html.find(cta_marker)
                        # 找到對應的結束 </div>（需要計算嵌套）
                        depth = 0
                        i = cta_start
                        while i < len(public_html):
                            if public_html[i:i+4] == '<div':
                                depth += 1
                            elif public_html[i:i+6] == '</div>':
                                depth -= 1
                                if depth == 0:
                                    # 移除這個 CTA box
                                    public_html = public_html[:cta_start] + public_html[i+6:]
                                    break
                            i += 1
                        break

                # 同樣移除會員專屬的提示區塊
                members_notice_markers = [
                    '<div style="border:1px dashed #1565c0; background:#eff6ff;',
                    '🔒 會員專屬',
                ]
                for notice_marker in members_notice_markers:
                    if notice_marker in public_html:
                        notice_start = public_html.find(notice_marker)
                        if notice_start > 0:
                            # 往前找 <div
                            search_start = max(0, notice_start - 200)
                            div_pos = public_html.rfind('<div', search_start, notice_start + 50)
                            if div_pos >= 0:
                                depth = 0
                                i = div_pos
                                while i < len(public_html):
                                    if public_html[i:i+4] == '<div':
                                        depth += 1
                                    elif public_html[i:i+6] == '</div>':
                                        depth -= 1
                                        if depth == 0:
                                            public_html = public_html[:div_pos] + public_html[i+6:]
                                            break
                                    i += 1
                        break

                lexical = {
                    "root": {
                        "children": [
                            {
                                "type": "html",
                                "version": 1,
                                "html": public_html.strip()
                            },
                            {
                                "type": "paywall",
                                "version": 1
                            },
                            {
                                "type": "html",
                                "version": 1,
                                "html": members_html.strip()
                            }
                        ],
                        "direction": None,
                        "format": "",
                        "indent": 0,
                        "type": "root",
                        "version": 1
                    }
                }
            else:
                # 沒有 paywall：用單一 HTML card
                lexical = {
                    "root": {
                        "children": [
                            {
                                "type": "html",
                                "version": 1,
                                "html": html
                            }
                        ],
                        "direction": None,
                        "format": "",
                        "indent": 0,
                        "type": "root",
                        "version": 1
                    }
                }
            post_data["lexical"] = json.dumps(lexical)

        return post_data

    def get_post_by_slug(self, slug: str) -> Optional[dict]:
        """根據 slug 取得文章

        Args:
            slug: 文章 slug

        Returns:
            文章資料或 None
        """
        if not self.api_url:
            return None

        headers = self._get_headers()
        if not headers:
            return None

        try:
            url = f"{self.api_url}/ghost/api/admin/posts/slug/{slug}/"
            response = self._client.get(url, headers=headers)

            if response.status_code == 404:
                return None

            response.raise_for_status()
            data = response.json()
            return data.get("posts", [{}])[0] if data.get("posts") else None

        except Exception as e:
            logger.error(f"Failed to get post: {e}")
            return None

    def create_post(
        self,
        post: PostOutput,
        status: str = "draft",
        send_newsletter: bool = False,
        email_segment: str = "all",
        visibility: str = "members",
    ) -> PublishResult:
        """建立新文章

        Ghost newsletter 發送必須使用兩步驟流程：
        1. 先建立 draft
        2. 再用 PUT + query parameter (?newsletter=slug&email_segment=segment) 發佈

        Args:
            post: 文章輸出
            status: 文章狀態 (draft/published)
            send_newsletter: 是否發送 newsletter (僅 published 有效)
            email_segment: 收件人群組 (all/status:free/status:-free/label:xxx)
            visibility: 文章可見度 (public/members/paid)

        Returns:
            PublishResult 實例
        """
        if not self.api_url:
            return PublishResult(success=False, error="GHOST_API_URL not configured")

        headers = self._get_headers()
        if not headers:
            return PublishResult(success=False, error="Failed to generate auth token")

        try:
            # 如果要發 newsletter，必須先建立 draft 再 publish
            if send_newsletter and status == "published":
                return self._create_post_with_newsletter(
                    post, headers, email_segment, visibility
                )

            # 一般建立流程（不發 newsletter）
            url = f"{self.api_url}/ghost/api/admin/posts/"
            post_data = self._build_post_data(post, status, visibility)

            response = self._client.post(
                url,
                headers=headers,
                json={"posts": [post_data]},
            )

            response.raise_for_status()
            data = response.json()

            if not data.get("posts"):
                return PublishResult(success=False, error="No post in response")

            ghost_post = data["posts"][0]

            return PublishResult(
                success=True,
                post_id=ghost_post.get("id"),
                url=ghost_post.get("url"),
                slug=ghost_post.get("slug"),
                status=ghost_post.get("status"),
                updated_at=ghost_post.get("updated_at"),
                newsletter_sent=False,
            )

        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP {e.response.status_code}: {e.response.text}"
            logger.error(f"Failed to create post: {error_msg}")
            return PublishResult(success=False, error=error_msg)
        except Exception as e:
            logger.error(f"Failed to create post: {e}")
            return PublishResult(success=False, error=str(e))

    def _create_post_with_newsletter(
        self,
        post,  # PostOutput or dict
        headers: dict,
        email_segment: str = "all",
        visibility: str = "members",
    ) -> PublishResult:
        """兩步驟發佈文章並發送 newsletter

        Ghost API 要求：
        1. 先建立 draft
        2. 用 PUT 加上 ?newsletter=slug&email_segment=segment 參數來發佈

        Args:
            post: 文章輸出 (PostOutput 物件或 dict)
            headers: API headers
            email_segment: 收件人群組
            visibility: 文章可見度 (public/members/paid)

        Returns:
            PublishResult 實例
        """
        # 支援 dict 和 PostOutput 物件
        slug = post.get('slug', '') if isinstance(post, dict) else getattr(post, 'slug', '')

        try:
            # Step 1: 建立 draft
            logger.info(f"Creating draft for newsletter: {slug}")
            url = f"{self.api_url}/ghost/api/admin/posts/"
            post_data = self._build_post_data(post, status="draft", visibility=visibility)

            response = self._client.post(
                url,
                headers=headers,
                json={"posts": [post_data]},
            )
            response.raise_for_status()
            data = response.json()

            if not data.get("posts"):
                return PublishResult(success=False, error="No post in response (draft)")

            ghost_post = data["posts"][0]
            post_id = ghost_post.get("id")
            updated_at = ghost_post.get("updated_at")

            logger.info(f"Draft created: {post_id}")

            # Step 2: 用 query parameter 發佈並發送 newsletter
            logger.info(f"Publishing with newsletter: {self.newsletter_slug}")
            publish_url = (
                f"{self.api_url}/ghost/api/admin/posts/{post_id}/"
                f"?newsletter={self.newsletter_slug}&email_segment={email_segment}"
            )

            publish_data = {
                "updated_at": updated_at,
                "status": "published",
            }

            response = self._client.put(
                publish_url,
                headers=headers,
                json={"posts": [publish_data]},
            )
            response.raise_for_status()
            data = response.json()

            if not data.get("posts"):
                return PublishResult(success=False, error="No post in response (publish)")

            ghost_post = data["posts"][0]

            # 檢查 email 是否有設定
            email_info = ghost_post.get("email")
            newsletter_sent = email_info is not None and email_info.get("status") in ["pending", "submitted", "delivered"]

            logger.info(f"Published with newsletter_sent={newsletter_sent}")

            return PublishResult(
                success=True,
                post_id=ghost_post.get("id"),
                url=ghost_post.get("url"),
                slug=ghost_post.get("slug"),
                status=ghost_post.get("status"),
                updated_at=ghost_post.get("updated_at"),
                newsletter_sent=newsletter_sent,
            )

        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP {e.response.status_code}: {e.response.text}"
            logger.error(f"Failed to create post with newsletter: {error_msg}")
            return PublishResult(success=False, error=error_msg)
        except Exception as e:
            logger.error(f"Failed to create post with newsletter: {e}")
            return PublishResult(success=False, error=str(e))

    def update_post(
        self,
        post_id: str,
        post: PostOutput,
        status: str = "draft",
        visibility: str = "members",
    ) -> PublishResult:
        """更新現有文章

        注意：Ghost 不支援對已發佈文章補發 newsletter。
        如需發送 newsletter，請刪除文章後用 create_post(send_newsletter=True)。

        Args:
            post_id: Ghost 文章 ID
            post: 文章輸出
            status: 文章狀態
            visibility: 文章可見度 (public/members/paid)

        Returns:
            PublishResult 實例
        """
        if not self.api_url:
            return PublishResult(success=False, error="GHOST_API_URL not configured")

        headers = self._get_headers()
        if not headers:
            return PublishResult(success=False, error="Failed to generate auth token")

        try:
            # 先取得現有文章以獲取 updated_at
            get_url = f"{self.api_url}/ghost/api/admin/posts/{post_id}/"
            get_response = self._client.get(get_url, headers=headers)
            get_response.raise_for_status()
            existing = get_response.json().get("posts", [{}])[0]

            # 更新文章
            url = f"{self.api_url}/ghost/api/admin/posts/{post_id}/"
            post_data = self._build_post_data(post, status, visibility)
            post_data["updated_at"] = existing.get("updated_at")

            response = self._client.put(
                url,
                headers=headers,
                json={"posts": [post_data]},
            )

            response.raise_for_status()
            data = response.json()

            if not data.get("posts"):
                return PublishResult(success=False, error="No post in response")

            ghost_post = data["posts"][0]

            return PublishResult(
                success=True,
                post_id=ghost_post.get("id"),
                url=ghost_post.get("url"),
                slug=ghost_post.get("slug"),
                status=ghost_post.get("status"),
                updated_at=ghost_post.get("updated_at"),
                newsletter_sent=False,
            )

        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP {e.response.status_code}: {e.response.text}"
            logger.error(f"Failed to update post: {error_msg}")
            return PublishResult(success=False, error=error_msg)
        except Exception as e:
            logger.error(f"Failed to update post: {e}")
            return PublishResult(success=False, error=str(e))

    def delete_post(self, post_id: str) -> bool:
        """刪除文章

        Args:
            post_id: Ghost 文章 ID

        Returns:
            是否成功
        """
        if not self.api_url:
            return False

        headers = self._get_headers()
        if not headers:
            return False

        try:
            url = f"{self.api_url}/ghost/api/admin/posts/{post_id}/"
            response = self._client.delete(url, headers=headers)
            return response.status_code == 204
        except Exception as e:
            logger.error(f"Failed to delete post: {e}")
            return False

    def publish(
        self,
        post: PostOutput,
        mode: str = "draft",
        send_newsletter: bool = False,
        email_segment: str = "all",
        visibility: str = "members",
    ) -> PublishResult:
        """發佈文章

        Args:
            post: 文章輸出 (PostOutput 物件或 dict)
            mode: 模式 (draft/publish)
            send_newsletter: 是否發送 newsletter (僅 publish 模式有效)
            email_segment: newsletter 收件人群組 (all/status:free/status:-free/label:xxx)
            visibility: 文章可見度 (public/members/paid)
                - public: 所有人可見（無會員牆）
                - members: 需登入（免費會員即可解鎖）
                - paid: 需付費會員才能解鎖

        Returns:
            PublishResult 實例
        """
        # 支援 dict 和 PostOutput 物件
        slug = post.get('slug', '') if isinstance(post, dict) else getattr(post, 'slug', '')

        status = "published" if mode == "publish" else "draft"

        # 檢查是否已存在
        existing = self.get_post_by_slug(slug)

        if existing:
            # 如果需要發 newsletter 且文章已存在，需要先刪除再建立
            # 因為 Ghost 不支援對已存在的文章發 newsletter
            if send_newsletter and status == "published":
                logger.info(f"Deleting existing post for newsletter re-send: {existing.get('id')}")
                if self.delete_post(existing["id"]):
                    logger.info(f"Creating new post with newsletter: {slug}")
                    return self.create_post(
                        post,
                        status=status,
                        send_newsletter=True,
                        email_segment=email_segment,
                        visibility=visibility,
                    )
                else:
                    return PublishResult(
                        success=False,
                        error="Failed to delete existing post for newsletter re-send"
                    )
            else:
                logger.info(f"Updating existing post: {existing.get('id')}")
                return self.update_post(
                    existing["id"],
                    post,
                    status=status,
                    visibility=visibility,
                )
        else:
            logger.info(f"Creating new post: {slug}")
            return self.create_post(
                post,
                status=status,
                send_newsletter=send_newsletter,
                email_segment=email_segment,
                visibility=visibility,
            )

    def upsert_by_slug(
        self,
        post,  # PostOutput or dict
        status: str = "published",
        send_newsletter: bool = False,
        email_segment: str = "all",
        visibility: str = "members",
    ) -> PublishResult:
        """P0-7: Upsert by slug - 若 slug 存在則更新，不存在則建立

        規則：
        1. 以 slug 為 unique key 查詢
        2. 若存在：更新內容（不重發 newsletter）
        3. 若不存在：建立新文章（可選發 newsletter）
        4. newsletter 只在首次建立時發送

        Args:
            post: 文章輸出 (PostOutput 物件或 dict)
            status: 文章狀態 (draft/published)
            send_newsletter: 首次建立時是否發送 newsletter
            email_segment: newsletter 收件人群組
            visibility: 文章可見度 (public/members/paid)

        Returns:
            PublishResult 實例（含 is_update 標記）
        """
        # 支援 dict 和 PostOutput 物件
        slug = post.get('slug', '') if isinstance(post, dict) else getattr(post, 'slug', '')

        if not slug:
            return PublishResult(success=False, error="Slug is required for upsert")

        # 檢查是否已存在
        existing = self.get_post_by_slug(slug)

        if existing:
            # 存在則更新（不發 newsletter）
            logger.info(f"[Upsert] Updating existing post: {slug} (id={existing.get('id')})")
            result = self.update_post(
                existing["id"],
                post,
                status=status,
                visibility=visibility,
            )
            # 標記這是更新操作
            if result.success:
                logger.info(f"[Upsert] Updated: {result.url}")
            return result
        else:
            # 不存在則建立
            logger.info(f"[Upsert] Creating new post: {slug}")
            result = self.create_post(
                post,
                status=status,
                send_newsletter=send_newsletter,
                email_segment=email_segment,
                visibility=visibility,
            )
            if result.success:
                logger.info(f"[Upsert] Created: {result.url}")
            return result

    def save_result(
        self,
        result: PublishResult,
        output_path: str = "out/publish_result.json",
    ) -> Path:
        """儲存發佈結果

        Args:
            result: 發佈結果
            output_path: 輸出路徑

        Returns:
            輸出檔案路徑
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w") as f:
            json.dump(result.to_dict(), f, indent=2, ensure_ascii=False)

        return output_path

    def close(self) -> None:
        """關閉 HTTP client"""
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


def main():
    """CLI demo"""
    import argparse
    from rich.console import Console

    parser = argparse.ArgumentParser(description="Ghost Publisher")
    parser.add_argument(
        "--input", "-i",
        default="out/post.json",
        help="Input post.json path",
    )
    parser.add_argument(
        "--mode", "-m",
        default="draft",
        choices=["draft", "publish"],
        help="Publish mode",
    )
    parser.add_argument(
        "--newsletter", "-n",
        action="store_true",
        help="Send newsletter (only for publish mode)",
    )
    args = parser.parse_args()

    console = Console()

    # 載入 post
    console.print(f"[bold]Loading post from {args.input}...[/bold]")
    with open(args.input) as f:
        post_data = json.load(f)

    # 建構 PostOutput
    post = PostOutput(
        meta=post_data.get("meta", {}),
        title=post_data.get("title", ""),
        title_candidates=post_data.get("title_candidates", []),
        slug=post_data.get("slug", ""),
        excerpt=post_data.get("excerpt", ""),
        tldr=post_data.get("tldr", []),
        sections=post_data.get("sections", {}),
        markdown=post_data.get("markdown", ""),
        html=post_data.get("html", ""),
        tags=post_data.get("tags", []),
        tickers_mentioned=post_data.get("tickers_mentioned", []),
        theme=post_data.get("theme", {}),
        what_to_watch=post_data.get("what_to_watch", []),
        sources=post_data.get("sources", []),
        disclosures=post_data.get("disclosures", {}),
    )

    # 發佈
    console.print(f"[bold]Publishing (mode: {args.mode})...[/bold]")

    with GhostPublisher() as publisher:
        result = publisher.publish(
            post,
            mode=args.mode,
            send_newsletter=args.newsletter and args.mode == "publish",
        )

    # 顯示結果
    if result.success:
        console.print("[green]✓ Published successfully![/green]")
        console.print(f"  Post ID: {result.post_id}")
        console.print(f"  URL: {result.url}")
        console.print(f"  Status: {result.status}")
        if result.newsletter_sent:
            console.print("  [cyan]Newsletter sent[/cyan]")
    else:
        console.print(f"[red]✗ Failed: {result.error}[/red]")

    # 儲存結果
    output_path = publisher.save_result(result)
    console.print(f"\nResult saved to {output_path}")


if __name__ == "__main__":
    main()
