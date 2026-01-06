# rs-ghost-publisher

## Overview
Safe Ghost CMS publishing skill with built-in safety rails to prevent accidental mass sends, slug collisions, and segment misconfigurations.

## Core Safety Principles
1. **Default to test mode** - Never publish to production without explicit confirmation
2. **Unique slugs per post type** - Prevent Ghost auto-appending `-2`
3. **Segment restrictions** - Block high-risk segments in test mode
4. **Quality gates required** - No publish-send without passing all gates

## Slug Naming Convention (CRITICAL)

### Format: `{date}-{type}-{topic}-{format}`

| Post Type | Slug Pattern | Example |
|-----------|--------------|---------|
| Flash (A) | `{topic}-{YYYY-MM-DD}-flash` | `ai-chips-ces-2026-01-05-flash` |
| Earnings (B) | `{ticker}-earnings-{context}-{YYYY-MM-DD}-earnings` | `nvda-earnings-preview-2026-01-05-earnings` |
| Deep Dive (C) | `{ticker}-deep-dive-{YYYY-MM-DD}-deep` | `nvda-deep-dive-2026-01-05-deep` |

### Slug Rules
```python
def validate_slug(slug, post_type):
    rules = {
        "flash": slug.endswith("-flash"),
        "earnings": slug.endswith("-earnings"),
        "deep": slug.endswith("-deep")
    }

    # Check format compliance
    if not rules.get(post_type):
        raise SlugError(f"Slug must end with -{post_type}")

    # Check for collision with existing posts
    existing = ghost_api.get_posts(filter=f"slug:{slug}")
    if existing:
        raise SlugCollisionError(f"Slug {slug} already exists")
```

### Why This Matters
Your previous `publish_result.json` showed:
- Same slug used twice → Ghost auto-appended `-2`
- This breaks cross-post navigation links
- This confuses analytics tracking

## Mode Configuration

### MODE=test (Default)
```python
TEST_MODE = {
    "newsletter": "daily-brief-test",
    "segment": "label:internal",
    "allowed_actions": ["draft", "publish"],
    "blocked_actions": ["publish-send to all"],
    "confirmation_required": False
}
```

### MODE=prod
```python
PROD_MODE = {
    "newsletter": "daily-brief",
    "segment": "status:-free",  # Paid members only
    "allowed_actions": ["draft", "publish", "publish-send"],
    "blocked_actions": [],
    "confirmation_required": True,
    "quality_gates_required": True
}
```

## High-Risk Segments (Blocked Without Confirmation)

```python
HIGH_RISK_SEGMENTS = {
    "all",           # All subscribers - NEVER use without explicit approval
    "status:free",   # All free members
    "status:-free",  # All paid members (requires confirmation in prod)
}

def validate_segment(segment, mode, confirmed=False):
    if segment in HIGH_RISK_SEGMENTS:
        if mode == "test":
            raise SegmentError(f"Segment '{segment}' blocked in test mode")
        if mode == "prod" and not confirmed:
            raise ConfirmationRequired(
                f"Segment '{segment}' requires --confirm-high-risk flag"
            )
```

## Environment Variables

```bash
# Required
GHOST_URL=https://rocket-screener.ghost.io
GHOST_ADMIN_API_KEY=...

# Newsletter allowlist
GHOST_NEWSLETTER_ALLOWLIST=daily-brief,daily-brief-test

# Segment allowlist
GHOST_SEGMENT_ALLOWLIST=label:internal,status:-free
```

## Publish Workflow

### Three-Stage Safe Publish

```bash
# Stage 1: Create Draft (Always safe)
make ghost-draft
# Creates draft, no publishing, no email

# Stage 2: Publish to Website (No email)
make ghost-publish
# Publishes to site, visible to appropriate tier
# Does NOT send newsletter

# Stage 3: Publish + Send Newsletter (Requires quality gates)
make ghost-send
# Only works if:
# - quality_gates_passed = true
# - MODE = prod (or test with internal segment)
# - Newsletter in allowlist
# - Segment in allowlist (or --confirm-high-risk)
```

### Decision Tree

```
Is quality_gates_passed true?
├─ No → ONLY draft allowed
└─ Yes → Continue

Is MODE = test?
├─ Yes →
│   ├─ newsletter = daily-brief-test
│   ├─ segment = label:internal
│   └─ publish-send allowed to internal only
└─ No (prod) →
    ├─ Is --confirm-high-risk set?
    │   ├─ No → Draft or publish only
    │   └─ Yes → publish-send allowed
    └─ Continue
```

## Post A Special Handling (Daily Email)

Post A (Flash) is the only post that gets `publish-send`:
- Post A: `publish-send` to newsletter
- Post B: `publish` only (no email)
- Post C: `publish` only (no email)

Post A content includes "TODAY'S PACKAGE" linking to B and C.

```python
def daily_publish_sequence(posts, mode):
    # 1. Publish all three as drafts first
    for post in [posts.flash, posts.earnings, posts.deep]:
        ghost.create_draft(post)

    # 2. Publish B and C to website (no email)
    if posts.earnings:
        ghost.publish(posts.earnings, send_email=False)
    ghost.publish(posts.deep, send_email=False)

    # 3. Update Post A with correct URLs for B and C
    posts.flash = update_cross_links(posts.flash, posts.earnings, posts.deep)

    # 4. Publish Post A with email (if prod mode)
    if mode == "prod" and posts.flash.quality_gates_passed:
        ghost.publish_send(posts.flash, newsletter="daily-brief")
    else:
        ghost.publish(posts.flash, send_email=False)
```

## Paywall Divider

Insert at correct location:
```html
<!-- Public preview content above -->

<!--members-only-->

<!-- Premium content below -->
```

Validation:
```python
def validate_paywall(html):
    if "<!--members-only-->" not in html:
        raise PaywallError("Missing paywall divider")

    parts = html.split("<!--members-only-->")
    if len(parts) != 2:
        raise PaywallError("Multiple paywall dividers found")

    public, private = parts
    if len(public) < 1000:
        raise PaywallError("Public preview too short (min 1000 chars)")
```

## Tag Requirements

```python
REQUIRED_TAGS = {
    "flash": ["us-stocks", "daily-brief", "#format-flash"],
    "earnings": ["us-stocks", "earnings", "#format-earnings"],
    "deep": ["us-stocks", "deep-dive", "#format-deep"]
}

AUTO_TAGS = ["#autogen", "#edition-postclose"]

def validate_tags(post):
    for tag in REQUIRED_TAGS[post.type]:
        if tag not in post.tags:
            raise TagError(f"Missing required tag: {tag}")
```

## Error Recovery

### Slug Collision
```python
if ghost_error.code == "SLUG_EXISTS":
    # DO NOT auto-append -2
    # Instead, fail and alert
    raise PublishError(
        f"Slug '{slug}' already exists. "
        f"Check if this post was already published today."
    )
```

### Newsletter Not in Allowlist
```python
if newsletter not in GHOST_NEWSLETTER_ALLOWLIST.split(","):
    raise NewsletterError(
        f"Newsletter '{newsletter}' not in allowlist. "
        f"Add to GHOST_NEWSLETTER_ALLOWLIST env var."
    )
```

## Makefile Commands

```makefile
# Safe defaults
ghost-draft:
	python scripts/ghost_publish_safe.py --mode draft

ghost-publish:
	python scripts/ghost_publish_safe.py --mode publish

ghost-send:
	python scripts/ghost_publish_safe.py --mode publish-send

# Test mode (internal only)
ghost-send-test:
	python scripts/ghost_publish_safe.py --mode publish-send \
		--newsletter daily-brief-test \
		--segment label:internal

# Production (requires confirmation)
ghost-send-prod:
	python scripts/ghost_publish_safe.py --mode publish-send \
		--newsletter daily-brief \
		--segment status:-free \
		--confirm-high-risk
```

## Logging

All publish actions are logged:
```python
{
    "timestamp": "2026-01-06T06:00:00-05:00",
    "action": "publish-send",
    "post_type": "flash",
    "slug": "ai-chips-ces-2026-01-05-flash",
    "newsletter": "daily-brief",
    "segment": "status:-free",
    "mode": "prod",
    "quality_gates_passed": true,
    "confirmed_high_risk": true,
    "result": "success",
    "ghost_post_id": "..."
}
```

## Files
- `scripts/ghost_publish_safe.py` - Main publisher
- `config/ghost.yml` - Ghost configuration
- `out/publish_result_*.json` - Publish logs
