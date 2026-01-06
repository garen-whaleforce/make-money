#!/usr/bin/env python3
"""Ghost CMS Smoke Test

三段式安全測試：
1. Draft - 只建立草稿
2. Publish-no-email - 發佈但不寄信
3. Publish-send - 發佈並寄信到測試分眾

使用方式：
    # 第一段：只建 Draft
    python scripts/ghost_smoke_test.py --html-file out/post.html \
        --title "Test" --slug "test-draft" --mode draft

    # 第二段：Publish 但不寄信
    python scripts/ghost_smoke_test.py --html-file out/post.html \
        --title "Test" --slug "test-publish" --mode publish-no-email

    # 第三段：寄 Newsletter（需先設好 allowlist）
    export GHOST_NEWSLETTER_ALLOWLIST="daily-brief-test"
    export GHOST_SEGMENT_ALLOWLIST="label:internal"
    python scripts/ghost_smoke_test.py --html-file out/post.html \
        --title "Test" --slug "test-send" --mode publish-send \
        --newsletter daily-brief-test --segment "label:internal"
"""

import os
import time
import json
import argparse
from urllib.parse import urljoin, urlencode

import requests
import jwt
from dotenv import load_dotenv

load_dotenv()


def _require_env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise SystemExit(f"Missing env: {name}")
    return v


def make_ghost_jwt(admin_api_key: str) -> str:
    """
    admin_api_key format: "{id}:{secret_hex}"
    Ghost expects HS256 signed JWT with:
      headers: {kid: id}
      payload: {iat, exp, aud: '/admin/'}
    """
    key_id, secret_hex = admin_api_key.split(":")
    iat = int(time.time())
    payload = {"iat": iat, "exp": iat + 5 * 60, "aud": "/admin/"}
    headers = {"kid": key_id}
    secret = bytes.fromhex(secret_hex)  # IMPORTANT: secret is hex -> bytes
    token = jwt.encode(payload, secret, algorithm="HS256", headers=headers)
    return token


def ghost_request(method: str, path: str, *, params: dict = None, json_body: dict = None) -> dict:
    base_url = _require_env("GHOST_API_URL").rstrip("/") + "/"
    accept_version = os.getenv("GHOST_ACCEPT_VERSION", "v5.0")
    admin_api_key = _require_env("GHOST_ADMIN_API_KEY")

    token = make_ghost_jwt(admin_api_key)

    # Admin API base path is /ghost/api/admin/
    url = urljoin(base_url, "ghost/api/admin/" + path.lstrip("/"))

    if params:
        url = url + ("&" if "?" in url else "?") + urlencode(params)

    headers = {
        "Authorization": f"Ghost {token}",
        "Accept-Version": accept_version,
        "Content-Type": "application/json",
    }

    resp = requests.request(method, url, headers=headers, json=json_body, timeout=30)
    if resp.status_code >= 400:
        raise RuntimeError(f"{method} {url} -> {resp.status_code}\n{resp.text}")
    return resp.json()


def allowlist_check(newsletter: str = None, segment: str = None) -> None:
    """
    Hard safety gate: do NOT allow sending newsletters unless explicitly allowlisted.
    """
    if not newsletter and not segment:
        return

    nl_allow = set([s.strip() for s in os.getenv("GHOST_NEWSLETTER_ALLOWLIST", "").split(",") if s.strip()])
    seg_allow = set([s.strip() for s in os.getenv("GHOST_SEGMENT_ALLOWLIST", "").split(",") if s.strip()])

    if newsletter and nl_allow and newsletter not in nl_allow:
        raise SystemExit(f"newsletter '{newsletter}' NOT in allowlist: {sorted(nl_allow)}")
    if segment and seg_allow and segment not in seg_allow:
        raise SystemExit(f"segment '{segment}' NOT in allowlist: {sorted(seg_allow)}")


def read_html(html_file: str) -> str:
    with open(html_file, "r", encoding="utf-8") as f:
        return f.read()


def site_smoke_test() -> None:
    data = ghost_request("GET", "site/")
    title = data.get("site", {}).get("title", "(unknown)")
    print(f"[OK] Auth smoke test. Site title: {title}")


def create_post_draft(*, title: str, slug: str, html: str, tags: list) -> dict:
    body = {
        "posts": [
            {
                "title": title,
                "slug": slug,
                "html": html,
                "status": "draft",
                "tags": [{"name": t} for t in tags],
            }
        ]
    }
    # Use source=html so Ghost converts HTML to its editor format
    data = ghost_request("POST", "posts/", params={"source": "html"}, json_body=body)
    post = data["posts"][0]
    print(f"[OK] Draft created: id={post['id']} slug={post['slug']} status={post['status']}")
    return post


def publish_post(
    *,
    post_id: str,
    updated_at: str,
    newsletter: str = None,
    segment: str = None,
    email_only: bool = False,
) -> dict:
    allowlist_check(newsletter, segment)

    params = {}
    if newsletter:
        params["newsletter"] = newsletter
    if segment:
        params["email_segment"] = segment

    body = {
        "posts": [
            {
                "id": post_id,
                "status": "published",
                "updated_at": updated_at,
                "email_only": bool(email_only),
            }
        ]
    }
    data = ghost_request("PUT", f"posts/{post_id}/", params=params if params else None, json_body=body)
    post = data["posts"][0]
    print(f"[OK] Published: id={post['id']} status={post['status']} email_only={post.get('email_only')}")
    return post


def main():
    ap = argparse.ArgumentParser(description="Ghost CMS Smoke Test")
    ap.add_argument("--html-file", required=True, help="HTML file to publish (e.g., out/post.html)")
    ap.add_argument("--title", required=True)
    ap.add_argument("--slug", required=True)
    ap.add_argument("--tags", default="us-stocks,daily-brief,theme-test", help="comma-separated")
    ap.add_argument("--mode", choices=["draft", "publish-no-email", "publish-send"], default="draft")
    ap.add_argument("--newsletter", default=None, help="newsletter slug (for publish-send)")
    ap.add_argument("--segment", default=None, help="email segment filter (for publish-send)")
    ap.add_argument("--email-only", action="store_true", help="send as email-only post")
    ap.add_argument("--out", default="out/publish_result.json")
    args = ap.parse_args()

    site_smoke_test()

    html = read_html(args.html_file)
    tags = [t.strip() for t in args.tags.split(",") if t.strip()]

    draft = create_post_draft(title=args.title, slug=args.slug, html=html, tags=tags)

    result = {"draft": draft}

    if args.mode == "publish-no-email":
        published = publish_post(
            post_id=draft["id"],
            updated_at=draft["updated_at"],
            newsletter=None,
            segment=None,
            email_only=False,
        )
        result["published"] = published

    if args.mode == "publish-send":
        if not args.newsletter or not args.segment:
            raise SystemExit("publish-send requires --newsletter and --segment")
        published = publish_post(
            post_id=draft["id"],
            updated_at=draft["updated_at"],
            newsletter=args.newsletter,
            segment=args.segment,
            email_only=args.email_only,
        )
        result["published"] = published

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"[OK] Wrote {args.out}")


if __name__ == "__main__":
    main()
