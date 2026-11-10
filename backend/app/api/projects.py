from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.db import get_db
from app.models import CodingProject, ProjectMilestone, ProjectSubmission, User, UserModuleProgress
from app.services import projects

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _unlocked(db: Session, user: User, project: CodingProject) -> None:
    mp = db.scalar(select(UserModuleProgress).where(UserModuleProgress.user_id == user.id, UserModuleProgress.module_id == project.module_id))
    if mp is None or mp.state == "locked":
        raise HTTPException(403, "This project's module is locked")


@router.get("/{key}")
def get_project(key: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    project = db.scalar(select(CodingProject).where(CodingProject.key == key))
    if project is None:
        raise HTTPException(404, "Project not found")
    _unlocked(db, user, project)
    return projects.project_status(db, user.id, project)


class MilestoneSubmissionIn(BaseModel):
    source: str = Field(default="editor", pattern="^(editor|github|upload)$")
    code: str = Field(default="", max_length=200_000)
    repo_url: str | None = Field(default=None, max_length=500)


@router.post("/milestones/{milestone_id}/submissions")
def submit_milestone(milestone_id: str, body: MilestoneSubmissionIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ms = db.get(ProjectMilestone, milestone_id)
    if ms is None:
        raise HTTPException(404, "Milestone not found")
    project = db.get(CodingProject, ms.project_id)
    _unlocked(db, user, project)
    if body.source == "github":
        if not body.repo_url or not projects.GITHUB_BLOB.match(body.repo_url):
            raise HTTPException(422, "Link to a single .py file: https://github.com/<user>/<repo>/blob/<branch>/<path>.py")
    elif not body.code.strip():
        raise HTTPException(422, "No code submitted")
    ps = projects.submit(db, user.id, ms, code=body.code, repo_url=body.repo_url, source=body.source)
    db.commit()
    return {"id": ps.id, "version": ps.version, "status": ps.status}


@router.get("/submissions/{submission_id}")
def get_project_submission(submission_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ps = db.get(ProjectSubmission, submission_id)
    if ps is None or ps.user_id != user.id:
        raise HTTPException(404, "Not found")
    return {"id": ps.id, "status": ps.status, "score": ps.score, "passed": ps.passed, "feedback": ps.feedback,
            "public_tests": (ps.test_results or {}).get("public", []), "hidden": (ps.test_results or {}).get("hidden")}
