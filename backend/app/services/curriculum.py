"""Curriculum Service: load/validate the curriculum spec, sync it to the DB, seed content,
and answer graph questions (prerequisites, eligibility inputs)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import (
    Block,
    CodingProject,
    Concept,
    ConceptPrerequisite,
    Curriculum,
    CurriculumVersion,
    LearningObjective,
    Lesson,
    LessonVersion,
    Module,
    ProjectMilestone,
)
from app.schemas.lesson import LessonContent

SEED_DIR = Path(__file__).resolve().parents[1] / "seed"


def content_hash(data) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


@lru_cache
def load_spec(path: str | None = None) -> dict:
    with open(path or SEED_DIR / "curriculum.yaml") as f:
        return yaml.safe_load(f)


def load_seed_lesson(rel_path: str) -> LessonContent:
    with open(SEED_DIR / rel_path) as f:
        return LessonContent.model_validate(yaml.safe_load(f))


# ------------------------------------------------------------------ graph


@dataclass
class ConceptGraph:
    requires: dict[str, set[str]]  # hard prerequisites
    soft: dict[str, set[str]]
    names: dict[str, str]

    def ancestors(self, key: str) -> set[str]:
        seen: set[str] = set()
        stack = list(self.requires.get(key, ()))
        while stack:
            k = stack.pop()
            if k not in seen:
                seen.add(k)
                stack.extend(self.requires.get(k, ()))
        return seen


def concept_graph(spec: dict | None = None) -> ConceptGraph:
    spec = spec or load_spec()
    req = {c["key"]: set(c.get("requires", [])) for c in spec["concepts"]}
    soft = {c["key"]: set(c.get("soft_requires", [])) for c in spec["concepts"]}
    return ConceptGraph(req, soft, {c["key"]: c["name"] for c in spec["concepts"]})


def iter_lessons(spec: dict):
    for bi, block in enumerate(spec["blocks"]):
        for mi, module in enumerate(block.get("modules", [])):
            for li, lesson in enumerate(module.get("lessons", [])):
                yield bi, block, mi, module, li, lesson


def lesson_external_prereqs(lesson_spec: dict, graph: ConceptGraph) -> set[str]:
    teaches = set(lesson_spec.get("teaches", []))
    needed: set[str] = set()
    for c in teaches:
        needed |= graph.requires.get(c, set())
    return needed - teaches


def validate_spec(spec: dict) -> list[str]:
    errors: list[str] = []
    graph = concept_graph(spec)
    keys = set(graph.requires)
    for c, reqs in graph.requires.items():
        for r in reqs | graph.soft[c]:
            if r not in keys:
                errors.append(f"concept {c} requires unknown concept {r}")
    # cycle detection (DFS colouring)
    color: dict[str, int] = {}

    def visit(k: str, path: list[str]):
        color[k] = 1
        for r in graph.requires.get(k, ()):
            if color.get(r) == 1:
                errors.append("cycle: " + " -> ".join(path + [k, r]))
            elif color.get(r) is None and r in keys:
                visit(r, path + [k])
        color[k] = 2

    for k in keys:
        if k not in color:
            visit(k, [])

    taught_before: set[str] = set()
    lesson_keys: set[str] = set()
    objective_keys: set[str] = set()
    for *_, lesson in iter_lessons(spec):
        lk = lesson["key"]
        if lk in lesson_keys:
            errors.append(f"duplicate lesson key {lk}")
        lesson_keys.add(lk)
        teaches = set(lesson.get("teaches", []))
        for c in teaches:
            if c not in keys:
                errors.append(f"lesson {lk} teaches unknown concept {c}")
        for o in lesson.get("objectives", []):
            if o["key"] in objective_keys:
                errors.append(f"duplicate objective key {o['key']}")
            objective_keys.add(o["key"])
            if o["concept"] not in teaches:
                errors.append(f"objective {o['key']} concept {o['concept']} not in lesson {lk} teaches")
        if lesson.get("kind", "lesson") == "lesson":
            missing = lesson_external_prereqs(lesson, graph) - taught_before
            if missing:
                errors.append(f"lesson {lk} needs {sorted(missing)} which no earlier lesson teaches")
        taught_before |= teaches
    for p in spec.get("projects", []):
        if not any(m["key"] == p["module"] for b in spec["blocks"] for m in b.get("modules", [])):
            errors.append(f"project {p['key']} references unknown module {p['module']}")
    return errors


# ------------------------------------------------------------------ DB sync


def sync_curriculum(db: Session, spec: dict | None = None) -> CurriculumVersion:
    """Upsert the curriculum by stable keys. Idempotent. A new CurriculumVersion snapshot is recorded
    whenever the spec changes; structural rows are updated in place so progress (keyed by lesson
    id) survives edits."""
    spec = spec or load_spec()
    errors = validate_spec(spec)
    if errors:
        raise ValueError("curriculum spec invalid:\n" + "\n".join(errors))
    h = content_hash(spec)

    cur = db.scalar(select(Curriculum).where(Curriculum.key == spec["key"]))
    if cur is None:
        cur = Curriculum(key=spec["key"], title=spec["title"])
        db.add(cur)
        db.flush()
    versions = db.scalars(select(CurriculumVersion).where(CurriculumVersion.curriculum_id == cur.id).order_by(CurriculumVersion.version)).all()
    base = versions[0] if versions else None
    if versions and versions[-1].spec_hash == h:
        return versions[-1]
    for v in versions:
        v.is_active = False
    version = CurriculumVersion(curriculum_id=cur.id, version=len(versions) + 1, spec=spec, spec_hash=h, is_active=True)
    db.add(version)
    db.flush()
    owner_id = (base or version).id

    concepts = {c.key: c for c in db.scalars(select(Concept).where(Concept.curriculum_version_id == owner_id))}
    for c in spec["concepts"]:
        row = concepts.get(c["key"])
        if row is None:
            row = Concept(curriculum_version_id=owner_id, key=c["key"])
            db.add(row)
            concepts[c["key"]] = row
        row.name, row.description, row.block_key = c["name"], c.get("description", ""), c["block"]
    db.flush()
    existing_edges = {(e.concept_id, e.prerequisite_id): e for e in db.scalars(select(ConceptPrerequisite))}
    for c in spec["concepts"]:
        for strength, field in (("hard", "requires"), ("soft", "soft_requires")):
            for r in c.get(field, []):
                pair = (concepts[c["key"]].id, concepts[r].id)
                if pair not in existing_edges:
                    edge = ConceptPrerequisite(concept_id=pair[0], prerequisite_id=pair[1], strength=strength)
                    db.add(edge)
                    existing_edges[pair] = edge

    blocks = {b.key: b for b in db.scalars(select(Block).where(Block.curriculum_version_id == owner_id))}
    modules_by_key: dict[str, Module] = {}
    for bi, b in enumerate(spec["blocks"]):
        block = blocks.get(b["key"])
        if block is None:
            block = Block(curriculum_version_id=owner_id, key=b["key"], position=bi, title=b["title"])
            db.add(block)
            db.flush()
        block.position, block.title = bi, b["title"]
        block.description, block.status, block.topics = b.get("description", ""), b.get("status", "outline"), b.get("topics", [])
        existing_modules = {m.key: m for m in block.modules}
        prev_module_key = None
        for mi, m in enumerate(b.get("modules", [])):
            module = existing_modules.get(m["key"])
            if module is None:
                module = Module(block_id=block.id, key=m["key"], position=mi, title=m["title"])
                db.add(module)
                db.flush()
            module.position, module.title, module.description = mi, m["title"], m.get("description", "")
            module.project_key = m.get("project")
            module.requires_modules = m.get("requires_modules", [prev_module_key] if prev_module_key else [])
            prev_module_key = m["key"]
            modules_by_key[m["key"]] = module
            existing_lessons = {lesson.key: lesson for lesson in module.lessons}
            for li, ls in enumerate(m.get("lessons", [])):
                lesson = existing_lessons.get(ls["key"])
                if lesson is None:
                    lesson = Lesson(module_id=module.id, key=ls["key"], position=li, title=ls["title"])
                    db.add(lesson)
                    db.flush()
                lesson.position, lesson.title = li, ls["title"]
                lesson.kind = ls.get("kind", "lesson")
                lesson.seed_path = ls.get("seed")
                lesson.spec = {
                    "key": ls["key"],
                    "kind": ls.get("kind", "lesson"),
                    "title": ls["title"],
                    "teaches": ls.get("teaches", []),
                    "covers": ls.get("covers", []),
                    "estimated_minutes": ls.get("estimated_minutes", 60),
                    "objectives": ls.get("objectives", []),
                    "module_key": m["key"],
                    "block_key": b["key"],
                }
                existing_obj = {o.key: o for o in lesson.objectives}
                for o in ls.get("objectives", []):
                    obj = existing_obj.get(o["key"])
                    if obj is None:
                        obj = LearningObjective(lesson_id=lesson.id, key=o["key"])
                        db.add(obj)
                    obj.statement, obj.concept_key, obj.critical = o["statement"], o["concept"], bool(o.get("critical"))
    db.flush()

    for p in spec.get("projects", []):
        _sync_project(db, p, modules_by_key[p["module"]])
    seed_lesson_content(db)
    return version


def _sync_project(db: Session, p: dict, module: Module) -> None:
    with open(SEED_DIR / p["seed"]) as f:
        pspec = yaml.safe_load(f)
    project = db.scalar(select(CodingProject).where(CodingProject.key == p["key"]))
    if project is None:
        project = CodingProject(module_id=module.id, key=p["key"], title=pspec["title"])
        db.add(project)
        db.flush()
    project.title = pspec["title"]
    project.pass_threshold = pspec.get("pass_threshold", 0.9)
    project.spec = {"summary": pspec["summary"]}
    existing = {m.key: m for m in project.milestones}
    for i, ms in enumerate(pspec["milestones"]):
        row = existing.get(ms["key"])
        if row is None:
            row = ProjectMilestone(project_id=project.id, key=ms["key"], position=i, title=ms["title"])
            db.add(row)
        row.position, row.title, row.spec = i, ms["title"], ms
    db.flush()


def seed_lesson_content(db: Session) -> int:
    """Publish hand-authored seed lessons as shared (user_id NULL) versions. Idempotent by content hash."""
    from app.services.lesson_validation import validate_lesson

    created = 0
    for lesson in db.scalars(select(Lesson).where(Lesson.seed_path.is_not(None))):
        content = load_seed_lesson(lesson.seed_path)
        report = validate_lesson(content, lesson.spec, execute_code=False, check_links=False)
        if report.errors:
            raise ValueError(f"seed lesson {lesson.key} failed validation: {report.errors}")
        data = content.model_dump(mode="json")
        h = content_hash(data)
        existing = db.scalars(
            select(LessonVersion).where(LessonVersion.lesson_id == lesson.id, LessonVersion.user_id.is_(None))
            .order_by(LessonVersion.version.desc())
        ).first()
        if existing and existing.content_hash == h:
            continue
        db.add(
            LessonVersion(
                lesson_id=lesson.id, user_id=None, version=(existing.version + 1 if existing else 1),
                purpose="primary", status="published", source="seed", content=data, content_hash=h,
                validation_report=report.as_dict(), published_at=utcnow(),
            )
        )
        created += 1
    db.flush()
    return created


# ------------------------------------------------------------------ queries


def ordered_lessons(db: Session) -> list[Lesson]:
    """All lessons in curriculum order (block, module, lesson position)."""
    rows = db.execute(
        select(Lesson, Module, Block).join(Module, Lesson.module_id == Module.id).join(Block, Module.block_id == Block.id)
        .order_by(Block.position, Module.position, Lesson.position)
    ).all()
    return [r[0] for r in rows]


def ordered_modules(db: Session) -> list[Module]:
    rows = db.execute(select(Module, Block).join(Block, Module.block_id == Block.id).order_by(Block.position, Module.position)).all()
    return [r[0] for r in rows]
