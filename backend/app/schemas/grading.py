"""Structured outputs requested from LLM roles (grading, review, diagnosis)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CriterionScore(Closed):
    criterion_id: str
    points_awarded: float
    evidence: list[str] = Field(description="Verbatim quotes from the student's answer that justify the points")
    rationale: str


class RubricGrade(Closed):
    criteria: list[CriterionScore]
    correct_concepts: list[str]
    missing_concepts: list[str]
    incorrect_claims: list[str]
    misconceptions: list[str] = Field(description="Underlying misunderstandings, phrased as the belief the student holds")
    feedback: str = Field(description="Direct, specific feedback to the student explaining errors")
    next_steps: list[str]
    confidence: float = Field(description="0-1: how confident you are this grade is correct")


class CodeReview(Closed):
    implements_required_algorithm: bool
    algorithm_assessment: str
    correctness_notes: list[str]
    quality_notes: list[str]
    edge_cases_missed: list[str]
    feedback: str
    next_steps: list[str]
    confidence: float


class LessonReviewIssue(Closed):
    severity: Literal["blocker", "major", "minor"]
    location: str
    problem: str
    fix: str


class LessonReview(Closed):
    verdict: Literal["approve", "revise"]
    mathematically_correct: bool
    objectives_aligned: bool
    appropriate_level: bool
    issues: list[LessonReviewIssue]
    summary: str


class ObjectiveDiagnosis(Closed):
    objective_id: str
    likely_misconception: str
    evidence: str
    prerequisite_gap: str | None = Field(description="Concept key of a prerequisite the student seems to lack, or null")


class Diagnosis(Closed):
    objectives: list[ObjectiveDiagnosis]
    recommended_strategy: str


class ResourceCandidate(Closed):
    kind: Literal["video", "article", "book", "paper", "docs", "course", "repo"]
    title: str
    url: str
    authors: list[str]
    publisher: str
    details: str
    why: str


class ResourceCandidates(Closed):
    resources: list[ResourceCandidate]
