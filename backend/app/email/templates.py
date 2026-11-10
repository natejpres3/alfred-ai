"""Email rendering (HTML + plain text). Kept deliberately simple and readable."""

from __future__ import annotations

from html import escape

from app.config import get_settings


def _layout(title: str, body_html: str, cta: tuple[str, str] | None, unsubscribe_url: str) -> str:
    button = (
        f'<p style="margin:28px 0"><a href="{escape(cta[1])}" style="background:#1f4f8f;color:#fff;padding:12px 20px;'
        f'border-radius:6px;text-decoration:none;font-weight:600">{escape(cta[0])}</a></p>' if cta else ""
    )
    return f"""<!doctype html><html><body style="margin:0;background:#f5f5f2;font-family:Georgia,'Times New Roman',serif;color:#1d1d1b">
<div style="max-width:600px;margin:0 auto;padding:32px 24px">
<p style="font:600 12px/1 -apple-system,Segoe UI,sans-serif;letter-spacing:.08em;text-transform:uppercase;color:#6b6b66">AI Academy</p>
<h1 style="font-size:24px;line-height:1.3;margin:8px 0 16px">{escape(title)}</h1>
<div style="font-size:16px;line-height:1.6">{body_html}</div>{button}
<hr style="border:none;border-top:1px solid #ddd;margin:32px 0 12px">
<p style="font:12px/1.5 -apple-system,Segoe UI,sans-serif;color:#8a8a84">You receive this because you study with AI Academy.
<a href="{escape(unsubscribe_url)}" style="color:#8a8a84">Manage or unsubscribe</a>.</p></div></body></html>"""


def _ul(items: list[str]) -> str:
    return "<ul>" + "".join(f"<li>{escape(i)}</li>" for i in items) + "</ul>" if items else ""


def render(kind: str, payload: dict, unsubscribe_token: str) -> tuple[str, str, str]:
    """Return (subject, html, text)."""
    web = get_settings().public_web_url.rstrip("/")
    unsub = f"{web}/api/email/unsubscribe?token={unsubscribe_token}"
    lesson_url = f"{web}/lessons/{payload.get('lesson_id', '')}"
    score = payload.get("score")
    score_s = f"{score:.0%}" if isinstance(score, (int, float)) else ""

    if kind == "lesson_available":
        subject = f"Your next lesson is ready: {payload['lesson_title']}"
        lines = [
            f"<p><strong>{escape(payload.get('block', ''))} · {escape(payload.get('module', ''))}</strong><br>"
            f"Estimated time: {payload.get('minutes', 60)} minutes</p>",
            f"<p>{escape(payload.get('why', ''))}</p>",
            "<p><strong>Objectives</strong></p>" + _ul(payload.get("objectives", [])),
        ]
        if payload.get("connections"):
            lines.append("<p><strong>Builds on</strong></p>" + _ul(payload["connections"]))
        html = _layout(payload["lesson_title"], "".join(lines), ("Open the lesson", lesson_url), unsub)
        text = (f"{payload['lesson_title']}\n{payload.get('block', '')} · {payload.get('module', '')}\n"
                f"Estimated time: {payload.get('minutes', 60)} minutes\n\n{payload.get('why', '')}\n\nObjectives:\n"
                + "\n".join(f"- {o}" for o in payload.get("objectives", []))
                + ("\n\nBuilds on:\n" + "\n".join(f"- {c}" for c in payload.get("connections", [])) if payload.get("connections") else "")
                + f"\n\nOpen: {lesson_url}\n\nUnsubscribe: {unsub}")
        return subject, html, text

    if kind == "lesson_passed":
        subject = f"Passed: {payload['lesson_title']} ({score_s})"
        body = f"<p>{escape(payload.get('summary', ''))}</p><p>Your next lesson is being prepared; you'll get a separate email when it's ready.</p>"
        return subject, _layout(subject, body, ("Review your feedback", f"{web}/submissions/{payload.get('submission_id', '')}"), unsub), \
            f"{subject}\n\n{payload.get('summary', '')}\n\nFeedback: {web}/submissions/{payload.get('submission_id', '')}\n\nUnsubscribe: {unsub}"

    if kind == "submission_graded":
        status = "awaiting manual review" if payload.get("needs_review") else ("passed" if payload.get("passed") else "not yet passed")
        subject = f"Graded: {payload['lesson_title']} — {status}"
        body = f"<p>Score: <strong>{score_s}</strong></p><p>{escape(payload.get('summary', ''))}</p>"
        url = f"{web}/submissions/{payload.get('submission_id', '')}"
        return subject, _layout(subject, body, ("See detailed feedback", url), unsub), f"{subject}\n\n{payload.get('summary', '')}\n\n{url}\n\nUnsubscribe: {unsub}"

    if kind == "remediation_required":
        subject = f"Targeted review ready: {payload['lesson_title']}"
        body = ("<p>Your last attempt showed gaps in:</p>" + _ul(payload.get("failed_objectives", []))
                + ("<p>We'll first revisit: " + escape(", ".join(payload["prerequisites"])) + "</p>" if payload.get("prerequisites") else "")
                + "<p>A short, focused review with new questions is ready.</p>")
        return subject, _layout(subject, body, ("Start the review", lesson_url), unsub), \
            f"{subject}\n\n" + "\n".join(f"- {o}" for o in payload.get("failed_objectives", [])) + f"\n\n{lesson_url}\n\nUnsubscribe: {unsub}"

    if kind in ("module_completed", "section_unlocked"):
        subject = (f"Module complete: {payload['module_title']}" if kind == "module_completed" else f"Unlocked: {payload['module_title']}")
        body = "<p>" + ("You met every gate for this module." if kind == "module_completed" else "A new module is now open.") + "</p>"
        return subject, _layout(subject, body, ("Open your dashboard", f"{web}/"), unsub), f"{subject}\n\n{web}/\n\nUnsubscribe: {unsub}"

    if kind == "project_graded":
        subject = f"Project milestone graded: {payload.get('milestone_title', '')} ({score_s})"
        url = f"{web}/projects/{payload.get('project_key', '')}"
        body = f"<p>{escape(payload.get('summary', ''))}</p>"
        return subject, _layout(subject, body, ("See feedback", url), unsub), f"{subject}\n\n{payload.get('summary', '')}\n\n{url}\n\nUnsubscribe: {unsub}"

    if kind == "review_due":
        concepts = payload.get("concepts", [])
        subject = f"Quick review due: {', '.join(concepts[:3])}"
        body = "<p>A 5-minute retrieval check keeps these concepts from fading:</p>" + _ul(concepts)
        return subject, _layout(subject, body, ("Start review", f"{web}/reviews"), unsub), f"{subject}\n\n{web}/reviews\n\nUnsubscribe: {unsub}"

    if kind == "verify_email":
        subject = "Confirm your email for AI Academy"
        url = f"{web}/verify-email?token={payload['token']}"
        return subject, _layout(subject, "<p>Confirm this address to receive lesson notifications.</p>", ("Confirm email", url), unsub), \
            f"{subject}\n\n{url}"

    raise ValueError(f"unknown notification kind {kind}")
