#!/usr/bin/env python3
"""Ghost CMS Safe Publisher

整合 pipeline 產出，加入品質檢查防呆。

使用方式：
    # 只建 Draft（最安全）
    python scripts/ghost_publish_safe.py --mode draft

    # Publish 但不寄信
    python scripts/ghost_publish_safe.py --mode publish-no-email

    # 寄 Newsletter（需要品質檢查通過 + allowlist）
    python scripts/ghost_publish_safe.py --mode publish-send \
        --newsletter daily-brief-test --segment "label:internal"

前置要求：
    - out/post.json 存在
    - out/post.html 存在
    - out/quality_report.json 存在（publish-send 模式必須）
    - 環境變數設好：GHOST_API_URL, GHOST_ADMIN_API_KEY
    - （建議）GHOST_NEWSLETTER_ALLOWLIST, GHOST_SEGMENT_ALLOWLIST
"""

import os
import sys
import time
import json
import argparse
from datetime import datetime
from urllib.parse import urljoin, urlencode
from pathlib import Path

import requests
import jwt
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# Configuration
# ============================================================

DEFAULT_POST_JSON = "out/post.json"
DEFAULT_POST_HTML = "out/post.html"
DEFAULT_QUALITY_REPORT = "out/quality_report.json"
DEFAULT_OUTPUT = "out/publish_result.json"


# ============================================================
# Ghost API Helpers
# ============================================================

def _require_env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise SystemExit(f"[ERROR] Missing env: {name}")
    return v


def make_ghost_jwt(admin_api_key: str) -> str:
    key_id, secret_hex = admin_api_key.split(":")
    iat = int(time.time())
    payload = {"iat": iat, "exp": iat + 5 * 60, "aud": "/admin/"}
    headers = {"kid": key_id}
    secret = bytes.fromhex(secret_hex)
    token = jwt.encode(payload, secret, algorithm="HS256", headers=headers)
    return token


def ghost_request(method: str, path: str, *, params: dict = None, json_body: dict = None) -> dict:
    base_url = _require_env("GHOST_API_URL").rstrip("/") + "/"
    accept_version = os.getenv("GHOST_ACCEPT_VERSION", "v5.0")
    admin_api_key = _require_env("GHOST_ADMIN_API_KEY")

    token = make_ghost_jwt(admin_api_key)
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
        raise RuntimeError(f"Ghost API error: {method} {url} -> {resp.status_code}\n{resp.text}")
    return resp.json()


# ============================================================
# Safety Checks
# ============================================================

# 高風險 segment（需要額外確認）
HIGH_RISK_SEGMENTS = {"all", "status:free", "status:-free"}


def allowlist_check(newsletter: str = None, segment: str = None) -> None:
    """Hard safety gate: 必須在 allowlist 內才能寄信"""
    if not newsletter and not segment:
        return

    nl_allow = set([s.strip() for s in os.getenv("GHOST_NEWSLETTER_ALLOWLIST", "").split(",") if s.strip()])
    seg_allow = set([s.strip() for s in os.getenv("GHOST_SEGMENT_ALLOWLIST", "").split(",") if s.strip()])

    if newsletter and nl_allow and newsletter not in nl_allow:
        raise SystemExit(f"[BLOCKED] newsletter '{newsletter}' NOT in allowlist: {sorted(nl_allow)}")
    if segment and seg_allow and segment not in seg_allow:
        raise SystemExit(f"[BLOCKED] segment '{segment}' NOT in allowlist: {sorted(seg_allow)}")


def high_risk_segment_check(segment: str, confirm_high_risk: bool = False) -> None:
    """檢查是否使用高風險 segment（會發給大量用戶）

    Args:
        segment: 要使用的 segment
        confirm_high_risk: 是否已確認高風險操作
    """
    if segment in HIGH_RISK_SEGMENTS:
        if not confirm_high_risk:
            raise SystemExit(
                f"[BLOCKED] High-risk segment '{segment}' 會發給大量用戶！\n"
                f"  如果確定要這麼做，請加上 --confirm-high-risk 參數"
            )
        print(f"[WARNING] 使用高風險 segment: {segment}")


def check_enhanced_quality_gates(post_json: dict) -> bool:
    """檢查增強文章的品質閘門是否通過

    Args:
        post_json: post.json 內容

    Returns:
        是否通過品質閘門
    """
    meta = post_json.get("meta", {})

    # 如果是增強過的文章，必須通過品質閘門
    if meta.get("enhanced"):
        quality_passed = meta.get("quality_gates_passed", False)
        if not quality_passed:
            print("[ERROR] 增強文章的品質閘門未通過！")
            quality_gates = meta.get("quality_gates", {})
            gates = quality_gates.get("gates", {})
            for gate_name, gate_result in gates.items():
                if not gate_result.get("passed"):
                    print(f"  - {gate_name}: FAILED")
                    violations = gate_result.get("violations", [])
                    if violations:
                        print(f"    違規項目: {violations[:5]}{'...' if len(violations) > 5 else ''}")
            return False
        print("[OK] 增強文章品質閘門已通過")

    return True


def quality_gate_check(quality_report_path: str, mode: str) -> dict:
    """
    檢查品質報告 - P0-4 Fail-Closed 策略

    - draft: 只警告（允許預覽）
    - publish-no-email: 必須通過才能繼續（防止爛稿上線）
    - publish-send: 必須通過才能繼續（防止爛稿進信箱）
    """
    if not Path(quality_report_path).exists():
        if mode in ["publish-send", "publish-no-email"]:
            raise SystemExit(f"[BLOCKED] Quality report not found: {quality_report_path}")
        print(f"[WARN] Quality report not found: {quality_report_path}")
        return {}

    with open(quality_report_path) as f:
        report = json.load(f)

    passed = report.get("overall_passed", False)
    can_send = report.get("can_send_newsletter", False)

    print(f"[INFO] Quality Report:")
    print(f"       overall_passed: {passed}")
    print(f"       can_send_newsletter: {can_send}")

    # P0-4: Fail-closed for any publish mode (not just send)
    if mode in ["publish-send", "publish-no-email"]:
        if not passed:
            raise SystemExit(f"[BLOCKED] Quality check FAILED - cannot {mode}. Use 'draft' mode to preview.")

    # Additional check for newsletter
    if mode == "publish-send":
        if not can_send:
            raise SystemExit("[BLOCKED] can_send_newsletter is False")

    return report


# ============================================================
# Post Loading
# ============================================================

def load_post_data(post_json_path: str, post_html_path: str) -> tuple:
    """載入 pipeline 產出的 post 資料

    Returns:
        (post_data dict for Ghost, full post_json for quality checks)
    """
    if not Path(post_json_path).exists():
        raise SystemExit(f"[ERROR] Post JSON not found: {post_json_path}")
    if not Path(post_html_path).exists():
        raise SystemExit(f"[ERROR] Post HTML not found: {post_html_path}")

    with open(post_json_path) as f:
        post_json = json.load(f)

    with open(post_html_path) as f:
        html_content = f.read()

    post_data = {
        "title": post_json.get("title", "Untitled"),
        "slug": post_json.get("slug", f"post-{datetime.now().strftime('%Y%m%d-%H%M%S')}"),
        "html": html_content,
        "tags": post_json.get("tags", []),
        "excerpt": post_json.get("excerpt", ""),
        "meta": post_json.get("meta", {}),
    }

    return post_data, post_json


# ============================================================
# Ghost Operations
# ============================================================

def site_smoke_test() -> None:
    """驗證 Ghost 連線"""
    data = ghost_request("GET", "site/")
    title = data.get("site", {}).get("title", "(unknown)")
    print(f"[OK] Ghost connection verified. Site: {title}")


def create_draft(post_data: dict) -> dict:
    """建立 Draft"""
    body = {
        "posts": [
            {
                "title": post_data["title"],
                "slug": post_data["slug"],
                "html": post_data["html"],
                "status": "draft",
                "tags": [{"name": t} for t in post_data["tags"]],
                "custom_excerpt": post_data["excerpt"][:300] if post_data["excerpt"] else None,
            }
        ]
    }

    data = ghost_request("POST", "posts/", params={"source": "html"}, json_body=body)
    post = data["posts"][0]
    print(f"[OK] Draft created:")
    print(f"     id: {post['id']}")
    print(f"     slug: {post['slug']}")
    print(f"     status: {post['status']}")
    return post


def publish_post(
    post_id: str,
    updated_at: str,
    newsletter: str = None,
    segment: str = None,
    email_only: bool = False,
) -> dict:
    """發佈文章"""
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

    print(f"[OK] Published:")
    print(f"     id: {post['id']}")
    print(f"     url: {post.get('url', 'N/A')}")
    print(f"     status: {post['status']}")
    if newsletter:
        print(f"     newsletter: {newsletter}")
    if segment:
        print(f"     segment: {segment}")

    return post


# ============================================================
# Main
# ============================================================

def main():
    ap = argparse.ArgumentParser(
        description="Ghost CMS Safe Publisher - 整合 pipeline 產出",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # 只建 Draft
  python scripts/ghost_publish_safe.py --mode draft

  # Publish 但不寄信
  python scripts/ghost_publish_safe.py --mode publish-no-email

  # 寄 Newsletter 到測試分眾
  python scripts/ghost_publish_safe.py --mode publish-send \\
      --newsletter daily-brief-test --segment "label:internal"
        """
    )

    # Input files
    ap.add_argument("--post-json", default=DEFAULT_POST_JSON, help="Post JSON file")
    ap.add_argument("--post-html", default=DEFAULT_POST_HTML, help="Post HTML file")
    ap.add_argument("--quality-report", default=DEFAULT_QUALITY_REPORT, help="Quality report file")

    # Mode
    ap.add_argument(
        "--mode",
        choices=["draft", "publish-no-email", "publish-send"],
        default="draft",
        help="Publishing mode"
    )

    # Newsletter options
    ap.add_argument("--newsletter", default=None, help="Newsletter slug (for publish-send)")
    ap.add_argument("--segment", default=None, help="Email segment (for publish-send)")
    ap.add_argument("--email-only", action="store_true", help="Send as email-only post")

    # Output
    ap.add_argument("--out", default=DEFAULT_OUTPUT, help="Output result file")

    # Safety flags
    ap.add_argument("--skip-quality-check", action="store_true", help="Skip quality gate (NOT recommended)")
    ap.add_argument("--skip-enhanced-check", action="store_true", help="Skip enhanced quality gates check")
    ap.add_argument("--confirm-high-risk", action="store_true", help="確認高風險 segment（如 'all'）")
    ap.add_argument("--dry-run", action="store_true", help="Print what would happen without executing")

    args = ap.parse_args()

    print("=" * 60)
    print("Ghost CMS Safe Publisher")
    print("=" * 60)
    print(f"Mode: {args.mode}")
    print(f"Post JSON: {args.post_json}")
    print(f"Post HTML: {args.post_html}")
    print()

    # Dry run warning
    if args.dry_run:
        print("[DRY RUN] No actual API calls will be made")
        print()

    # Step 1: Quality Gate Check
    print("[Step 1] Quality Gate Check")
    if args.skip_quality_check:
        print("[WARN] Quality check SKIPPED (--skip-quality-check)")
        quality_report = {}
    else:
        quality_report = quality_gate_check(args.quality_report, args.mode)
    print()

    # Step 2: Load Post Data
    print("[Step 2] Load Post Data")
    post_data, full_post_json = load_post_data(args.post_json, args.post_html)
    print(f"     title: {post_data['title'][:60]}...")
    print(f"     slug: {post_data['slug']}")
    print(f"     tags: {', '.join(post_data['tags'][:5])}")
    is_enhanced = full_post_json.get("meta", {}).get("enhanced", False)
    if is_enhanced:
        print("     [Enhanced Post]")
    print()

    # Step 2.5: Enhanced Post Quality Gates Check
    if is_enhanced and args.mode == "publish-send":
        print("[Step 2.5] Enhanced Quality Gates Check")
        if args.skip_enhanced_check:
            print("[WARN] Enhanced quality gates check SKIPPED (--skip-enhanced-check)")
        else:
            if not check_enhanced_quality_gates(full_post_json):
                raise SystemExit("[BLOCKED] Enhanced post failed quality gates")
        print()

    # Step 2.6: High-Risk Segment Check
    if args.mode == "publish-send" and args.segment:
        print("[Step 2.6] High-Risk Segment Check")
        high_risk_segment_check(args.segment, args.confirm_high_risk)
        print()

    if args.dry_run:
        print("[DRY RUN] Would create draft and optionally publish")
        print(f"         Mode: {args.mode}")
        if args.mode == "publish-send":
            print(f"         Newsletter: {args.newsletter}")
            print(f"         Segment: {args.segment}")
        return

    # Step 3: Verify Ghost Connection
    print("[Step 3] Verify Ghost Connection")
    site_smoke_test()
    print()

    # Step 4: Create Draft
    print("[Step 4] Create Draft")
    draft = create_draft(post_data)
    print()

    result = {
        "mode": args.mode,
        "post_data": {
            "title": post_data["title"],
            "slug": post_data["slug"],
        },
        "draft": {
            "id": draft["id"],
            "slug": draft["slug"],
            "status": draft["status"],
        },
        "quality_passed": quality_report.get("overall_passed"),
        "timestamp": datetime.utcnow().isoformat(),
    }

    # Step 5: Publish (if not draft mode)
    if args.mode in ["publish-no-email", "publish-send"]:
        print("[Step 5] Publish")

        newsletter = args.newsletter if args.mode == "publish-send" else None
        segment = args.segment if args.mode == "publish-send" else None

        if args.mode == "publish-send":
            if not newsletter or not segment:
                raise SystemExit("[ERROR] publish-send requires --newsletter and --segment")

        published = publish_post(
            post_id=draft["id"],
            updated_at=draft["updated_at"],
            newsletter=newsletter,
            segment=segment,
            email_only=args.email_only,
        )

        result["published"] = {
            "id": published["id"],
            "url": published.get("url"),
            "status": published["status"],
            "newsletter": newsletter,
            "segment": segment,
        }
        print()

    # Save result
    print("[Step 6] Save Result")
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"[OK] Result saved to {args.out}")

    print()
    print("=" * 60)
    print("[DONE] Publishing complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
