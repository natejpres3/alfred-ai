"""Resource Service: verify that recommended resources exist before students see them.

* YouTube links are checked through the public oEmbed endpoint (also returns the real title,
  which must roughly match the claimed title — catches real-but-wrong video IDs).
* Other http(s) links get a GET (redirects followed, small timeout).
* Results are cached in `educational_resources` for 30 days.
Unverifiable links are stripped (url → null) and the resource is marked "failed"; the student view
never renders a failed URL.
"""

from __future__ import annotations

import re
from datetime import timedelta
from urllib.parse import quote, urlparse

import httpx
from sqlalchemy import select

from app.db import session_scope, utcnow
from app.models import EducationalResource
from app.schemas.lesson import LessonContent, Resource

CACHE_DAYS = 30
USER_AGENT = "AI-Academy-LinkChecker/1.0"
YOUTUBE_HOSTS = {"www.youtube.com", "youtube.com", "youtu.be", "m.youtube.com"}


def _title_matches(claimed: str, actual: str) -> bool:
    a = set(re.findall(r"[a-z0-9]{4,}", claimed.lower()))
    b = set(re.findall(r"[a-z0-9]{4,}", actual.lower()))
    return not a or len(a & b) / len(a) >= 0.5


def check_url(url: str, claimed_title: str = "", client: httpx.Client | None = None) -> tuple[str, int | None, dict]:
    """Return (status, http_status, metadata). status ∈ verified|failed|unverified."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return "failed", None, {"reason": "invalid scheme"}
    own = client is None
    client = client or httpx.Client(timeout=10, follow_redirects=True, headers={"User-Agent": USER_AGENT})
    try:
        if parsed.netloc in YOUTUBE_HOSTS:
            resp = client.get(f"https://www.youtube.com/oembed?url={quote(url, safe='')}&format=json")
            if resp.status_code != 200:
                return "failed", resp.status_code, {"reason": "youtube video not found"}
            meta = resp.json()
            if claimed_title and not _title_matches(claimed_title, meta.get("title", "")):
                return "failed", 200, {"reason": "title mismatch", "actual_title": meta.get("title")}
            return "verified", 200, {"actual_title": meta.get("title"), "author": meta.get("author_name")}
        resp = client.get(url)
        if resp.status_code < 400:
            return "verified", resp.status_code, {}
        if resp.status_code in (401, 403, 429):
            return "unverified", resp.status_code, {"reason": "site refused automated check"}
        return "failed", resp.status_code, {}
    except httpx.HTTPError as e:
        return "unverified", None, {"reason": f"network: {type(e).__name__}"}
    finally:
        if own:
            client.close()


def verify_resource(res: Resource) -> Resource:
    if not res.url:
        return res.model_copy(update={"verification": "unverified"})
    with session_scope() as db:
        row = db.scalar(select(EducationalResource).where(EducationalResource.url == res.url))
        fresh = row and row.checked_at and row.checked_at > utcnow() - timedelta(days=CACHE_DAYS)
        if not fresh:
            status, http_status, meta = check_url(res.url, res.title)
            if row is None:
                row = EducationalResource(url=res.url, kind=res.kind, title=res.title)
                db.add(row)
            row.verification_status, row.http_status, row.checked_at = status, http_status, utcnow()
            row.resource_metadata, row.authors, row.publisher = meta, res.authors, res.publisher
        status = row.verification_status
    update: dict = {"verification": status}
    if status == "failed":
        update["url"] = None
    return res.model_copy(update=update)


def verify_lesson_resources(content: LessonContent, report) -> None:
    verified = []
    for res in content.resources:
        new = verify_resource(res)
        if new.verification == "failed":
            report.warnings.append(f"resource {res.id} ({res.url}) failed verification and was unlinked")
        verified.append(new)
    content.resources = verified
    report.checks["links"] = True
