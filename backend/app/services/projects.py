"""Coding projects: milestone submissions (editor, GitHub file link, upload) graded in the sandbox."""

from __future__ import annotations

import re

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import CodingProject, ProjectMilestone, ProjectSubmission
from app.services import jobs, progression
from app.services.audit import audit
from app.services.grading import review_code, run_code_question, score_code
from app.services.notifications import notify

GITHUB_BLOB = re.compile(r"^https://github\.com/([\w.-]+)/([\w.-]+)/blob/([\w./-]+?)/([\w./-]+\.py)$")
MAX_FILE_BYTES = 200_000


def milestone_specs(ms: ProjectMilestone) -> tuple[dict, dict]:
    s = ms.spec
    spec = {"required_functions": s.get("required_functions", []), "public_tests": s.get("public_tests", []),
            "allowed_imports": None, "time_limit_seconds": s.get("time_limit_seconds", 30)}
    grading = {"hidden_tests": s.get("hidden_tests", []), "forbidden_imports": s.get("forbidden_imports", []),
               "forbidden_calls": s.get("forbidden_calls", []), "reference_solution": s.get("reference_solution", ""),
               "review_focus": s.get("review_focus", [])}
    return spec, grading


def public_milestone(ms: ProjectMilestone) -> dict:
    s = ms.spec
    return {"id": ms.id, "key": ms.key, "title": ms.title, "position": ms.position, "description": s.get("description", ""),
            "starter_code": s.get("starter_code", ""), "required_functions": s.get("required_functions", []),
            "public_tests": s.get("public_tests", []), "hidden_test_count": len(s.get("hidden_tests", []))}


def submit(db: Session, user_id: str, milestone: ProjectMilestone, *, code: str = "", repo_url: str | None = None, source: str = "editor") -> ProjectSubmission:
    version = (db.scalar(select(func.max(ProjectSubmission.version)).where(ProjectSubmission.user_id == user_id,
                                                                          ProjectSubmission.milestone_id == milestone.id)) or 0) + 1
    ps = ProjectSubmission(user_id=user_id, milestone_id=milestone.id, version=version, source=source, code=code, repo_url=repo_url, status="submitted")
    db.add(ps)
    db.flush()
    jobs.enqueue(db, "grade_project", {"project_submission_id": ps.id}, key=f"grade_project:{ps.id}")
    audit(db, "project.submitted", user_id=user_id, actor="user", entity_type="project_submission", entity_id=ps.id, version=version)
    return ps


def fetch_github_file(url: str) -> str:
    m = GITHUB_BLOB.match(url)
    if not m:
        raise ValueError("Link to a single .py file: https://github.com/<user>/<repo>/blob/<branch>/<path>.py")
    owner, repo, ref, path = m.groups()
    resp = httpx.get(f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}", timeout=15, follow_redirects=True)
    if resp.status_code != 200:
        raise ValueError(f"Could not fetch file from GitHub (HTTP {resp.status_code}); is the repository public?")
    if len(resp.content) > MAX_FILE_BYTES:
        raise ValueError("File is larger than 200 KB")
    return resp.text


def grade(db: Session, ps_id: str) -> dict:
    ps = db.get(ProjectSubmission, ps_id)
    if ps.status == "graded":
        return {"already": True}
    ms = db.get(ProjectMilestone, ps.milestone_id)
    project = db.get(CodingProject, ms.project_id)
    if ps.source == "github" and not ps.code:
        try:
            ps.code = fetch_github_file(ps.repo_url or "")
        except ValueError as e:
            ps.status, ps.feedback, ps.score, ps.passed = "graded", str(e), 0.0, False
            return {"error": str(e)}
    spec, grading = milestone_specs(ms)
    report, violations = run_code_question(ps.code, spec, grading)
    review, _ = review_code({"milestone": ms.title, "description": ms.spec.get("description", "")}, ps.code, report, violations, grading, ps.user_id)
    frac, reasons = score_code(report, violations, review)
    ps.score, ps.passed = frac, frac >= project.pass_threshold
    ps.test_results, ps.review = report, review or {}
    parts = [f"Public tests {sum(t['status'] == 'passed' for t in report['public'])}/{len(report['public'])}, "
             f"hidden tests {report['hidden']['passed']}/{report['hidden']['total']}. Score {frac:.0%} "
             f"({'meets' if ps.passed else 'below'} the {project.pass_threshold:.0%} bar)."]
    if report.get("compile_error"):
        parts.insert(0, f"Your file failed to load: {report['compile_error']}")
    parts += reasons + [f"Static check: {v}" for v in violations]
    if review and review.get("feedback"):
        parts.append(review["feedback"])
    ps.feedback = "\n\n".join(parts)
    ps.status = "graded"
    db.flush()
    notify(db, ps.user_id, "project_graded", f"project_graded:{ps.id}",
           {"project_key": project.key, "milestone_title": ms.title, "score": frac, "summary": parts[0]})
    progression.on_project_graded(db, ps.user_id, ms)
    return {"score": frac, "passed": ps.passed, "graded_at": utcnow().isoformat()}


def project_status(db: Session, user_id: str, project: CodingProject) -> dict:
    passed, score = progression.project_passed(db, user_id, project)
    milestones = []
    for ms in project.milestones:
        subs = db.scalars(select(ProjectSubmission).where(ProjectSubmission.user_id == user_id, ProjectSubmission.milestone_id == ms.id)
                          .order_by(ProjectSubmission.version.desc())).all()
        best = max([s.score for s in subs if s.score is not None], default=None)
        milestones.append(public_milestone(ms) | {
            "best_score": best, "passed": best is not None and best >= project.pass_threshold,
            "submissions": [{"id": s.id, "version": s.version, "status": s.status, "score": s.score, "passed": s.passed,
                             "feedback": s.feedback, "source": s.source, "created_at": s.created_at.isoformat(),
                             "public_tests": (s.test_results or {}).get("public", []), "hidden": (s.test_results or {}).get("hidden"),
                             "stdout": (s.test_results or {}).get("stdout", ""), "code": s.code} for s in subs[:10]],
        })
    return {"key": project.key, "title": project.title, "summary": project.spec.get("summary", ""),
            "pass_threshold": project.pass_threshold, "passed": passed, "score": score, "milestones": milestones}
