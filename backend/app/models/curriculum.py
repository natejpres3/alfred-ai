from __future__ import annotations

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, JSONType


class Curriculum(Base):
    __tablename__ = "curricula"

    key: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(String(200))


class CurriculumVersion(Base):
    __tablename__ = "curriculum_versions"
    __table_args__ = (UniqueConstraint("curriculum_id", "version"),)

    curriculum_id: Mapped[str] = mapped_column(ForeignKey("curricula.id"))
    version: Mapped[int] = mapped_column(Integer)
    spec: Mapped[dict] = mapped_column(JSONType)
    spec_hash: Mapped[str] = mapped_column(String(64), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Block(Base):
    __tablename__ = "blocks"
    __table_args__ = (UniqueConstraint("curriculum_version_id", "key"),)

    curriculum_version_id: Mapped[str] = mapped_column(ForeignKey("curriculum_versions.id"))
    key: Mapped[str] = mapped_column(String(64))
    position: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="outline")  # authored|outline
    topics: Mapped[list] = mapped_column(JSONType, default=list)

    modules: Mapped[list[Module]] = relationship(
        back_populates="block", order_by="Module.position", cascade="all, delete-orphan"
    )


class Module(Base):
    __tablename__ = "modules"
    __table_args__ = (UniqueConstraint("block_id", "key"),)

    block_id: Mapped[str] = mapped_column(ForeignKey("blocks.id"))
    key: Mapped[str] = mapped_column(String(64), index=True)
    position: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    project_key: Mapped[str | None] = mapped_column(String(64))
    requires_modules: Mapped[list] = mapped_column(JSONType, default=list)

    block: Mapped[Block] = relationship(back_populates="modules")
    lessons: Mapped[list[Lesson]] = relationship(
        back_populates="module", order_by="Lesson.position", cascade="all, delete-orphan"
    )


class Lesson(Base):
    __tablename__ = "lessons"
    __table_args__ = (UniqueConstraint("module_id", "key"),)

    module_id: Mapped[str] = mapped_column(ForeignKey("modules.id"))
    key: Mapped[str] = mapped_column(String(64), index=True)
    position: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(24), default="lesson")  # lesson|module_assessment|block_assessment
    title: Mapped[str] = mapped_column(String(200))
    spec: Mapped[dict] = mapped_column(JSONType, default=dict)
    seed_path: Mapped[str | None] = mapped_column(String(200))

    module: Mapped[Module] = relationship(back_populates="lessons")
    objectives: Mapped[list[LearningObjective]] = relationship(
        back_populates="lesson", cascade="all, delete-orphan"
    )


class Concept(Base):
    __tablename__ = "concepts"
    __table_args__ = (UniqueConstraint("curriculum_version_id", "key"),)

    curriculum_version_id: Mapped[str] = mapped_column(ForeignKey("curriculum_versions.id"))
    key: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    block_key: Mapped[str] = mapped_column(String(64))


class ConceptPrerequisite(Base):
    __tablename__ = "concept_prerequisites"
    __table_args__ = (UniqueConstraint("concept_id", "prerequisite_id"),)

    concept_id: Mapped[str] = mapped_column(ForeignKey("concepts.id"))
    prerequisite_id: Mapped[str] = mapped_column(ForeignKey("concepts.id"))
    strength: Mapped[str] = mapped_column(String(8), default="hard")


class LearningObjective(Base):
    __tablename__ = "learning_objectives"

    lesson_id: Mapped[str] = mapped_column(ForeignKey("lessons.id"))
    key: Mapped[str] = mapped_column(String(80), index=True)
    statement: Mapped[str] = mapped_column(Text)
    concept_key: Mapped[str] = mapped_column(String(64))
    critical: Mapped[bool] = mapped_column(Boolean, default=False)

    lesson: Mapped[Lesson] = relationship(back_populates="objectives")


class CodingProject(Base):
    __tablename__ = "coding_projects"

    module_id: Mapped[str] = mapped_column(ForeignKey("modules.id"))
    key: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(200))
    spec: Mapped[dict] = mapped_column(JSONType, default=dict)
    pass_threshold: Mapped[float] = mapped_column(Float, default=0.9)

    milestones: Mapped[list[ProjectMilestone]] = relationship(
        back_populates="project", order_by="ProjectMilestone.position", cascade="all, delete-orphan"
    )


class ProjectMilestone(Base):
    __tablename__ = "project_milestones"

    project_id: Mapped[str] = mapped_column(ForeignKey("coding_projects.id"))
    key: Mapped[str] = mapped_column(String(80))
    position: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    spec: Mapped[dict] = mapped_column(JSONType, default=dict)

    project: Mapped[CodingProject] = relationship(back_populates="milestones")
