"""Typed lesson schema — the contract between generator, validator, grader and frontend.

Rules:
* Everything a student must not see before grading lives under `Question.grading` or
  `LessonContent.variant_bank`. `student_view()` drops both.
* The schema is non-recursive and every object is closed, so it can be used directly as a
  Claude structured-output schema (see app/ai/schema_utils.py).
* Mirrored for the frontend in frontend/src/lib/lesson-schema.ts (student view only).
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- objectives & resources


class Objective(Closed):
    id: str = Field(description="Stable key, e.g. 'b01.m01.l01.o1'")
    statement: str = Field(description="Observable, assessable behaviour: 'Compute…', 'Explain why…'")
    concept_key: str
    critical: bool = Field(description="Failing this objective fails the lesson regardless of total score")
    bloom: Literal["remember", "understand", "apply", "analyze", "evaluate", "create"] = "understand"


ResourceKind = Literal["video", "article", "book", "paper", "docs", "course", "repo"]


class Resource(Closed):
    id: str
    kind: ResourceKind
    title: str
    url: str | None = Field(default=None, description="Canonical URL. Never invent one; null if unknown.")
    authors: list[str] = []
    publisher: str = ""
    details: str = Field(default="", description="Chapter/section/timestamp range, e.g. 'Ch. 2.1–2.3'")
    why: str = Field(default="", description="What the student gets from this resource")
    required: bool = False
    verification: Literal["verified", "unverified", "failed"] = "unverified"


class Connection(Closed):
    concept_key: str
    direction: Literal["builds_on", "leads_to"]
    note: str


# ---------------------------------------------------------------- questions


class Option(Closed):
    id: str
    text: str


class RubricCriterion(Closed):
    id: str
    description: str = Field(description="One gradeable idea. Never about style or length.")
    points: float
    required_for_mastery: bool = False


class Rubric(Closed):
    criteria: list[RubricCriterion]
    reference_answer: str
    common_misconceptions: list[str] = []


class NumericAnswer(Closed):
    value: float
    abs_tol: float = 1e-6
    rel_tol: float = 1e-3
    unit: str | None = None


class CodeTest(Closed):
    name: str = Field(description="test_* function name")
    code: str = Field(description="Python source defining the test function; uses plain asserts")
    weight: float = 1.0


class CodeSpec(Closed):
    """Student-visible part of a coding question."""

    language: Literal["python"] = "python"
    starter_code: str
    required_functions: list[str]
    public_tests: list[CodeTest] = []
    allowed_imports: list[str] = Field(default_factory=lambda: ["math", "numpy", "random"])
    time_limit_seconds: int = 10


class CodeGrading(Closed):
    hidden_tests: list[CodeTest]
    forbidden_imports: list[str] = []
    forbidden_calls: list[str] = Field(default=[], description="Dotted call names, e.g. 'np.linalg.lstsq'")
    reference_solution: str
    review_focus: list[str] = Field(default=[], description="What the code reviewer should check")


class Grading(Closed):
    correct_option_ids: list[str] | None = None
    numeric: NumericAnswer | None = None
    rubric: Rubric | None = None
    code: CodeGrading | None = None
    explanation: str = Field(description="Worked explanation shown to the student after grading")


QuestionType = Literal["mcq", "multi_select", "numeric", "short_answer", "long_answer", "derivation", "code"]
Category = Literal["conceptual", "math", "coding", "recall"]


class Question(Closed):
    id: str
    type: QuestionType
    category: Category
    prompt: str = Field(description="Markdown + $LaTeX$")
    objective_ids: list[str]
    critical: bool = False
    required: bool = True
    points: float = 1.0
    options: list[Option] | None = None
    code: CodeSpec | None = None
    hints: list[str] = Field(default=[], description="Progressively more explicit; never the answer")
    grading: Grading


# ---------------------------------------------------------------- content blocks

WidgetName = Literal[
    "vector_dot_product",
    "matrix_transform_2d",
    "derivative_tangent",
    "gradient_descent_2d",
    "attention_matrix",
]


class WidgetParam(Closed):
    name: str
    value: float


class MarkdownBlock(Closed):
    type: Literal["markdown"]
    text: str


class EquationBlock(Closed):
    type: Literal["equation"]
    latex: str = Field(description="Display-mode LaTeX without surrounding $$")
    caption: str = ""


class CodeBlock(Closed):
    type: Literal["code"]
    language: str = "python"
    code: str
    caption: str = ""
    runnable: bool = Field(default=False, description="If true the validator executes it in the sandbox")


class CalloutBlock(Closed):
    type: Literal["callout"]
    variant: Literal["intuition", "key_idea", "warning", "history", "connection", "example"]
    title: str
    text: str


class InteractiveBlock(Closed):
    type: Literal["interactive"]
    widget: WidgetName
    params: list[WidgetParam] = []
    caption: str = ""
    instructions: str = Field(default="", description="What to try, and what to notice")


class ResourceBlock(Closed):
    type: Literal["resource"]
    resource_id: str
    note: str = ""


class QuestionBlock(Closed):
    type: Literal["question"]
    question_id: str


ContentBlock = Annotated[
    MarkdownBlock | EquationBlock | CodeBlock | CalloutBlock | InteractiveBlock | ResourceBlock | QuestionBlock,
    Field(discriminator="type"),
]

SectionKind = Literal["retrieval", "concept", "math", "demo", "recall", "coding", "summary", "remediation"]


class Section(Closed):
    id: str
    kind: SectionKind
    title: str
    estimated_minutes: int
    required: bool = True
    blocks: list[ContentBlock]


class CompletionCriteria(Closed):
    required_section_ids: list[str]
    required_question_ids: list[str]
    pass_threshold: float = 0.85


class LessonContent(Closed):
    schema_version: Literal["1.0"] = "1.0"
    lesson_key: str
    title: str
    subtitle: str = ""
    summary: str
    why_it_matters: str
    explanation_strategy: str = Field(
        default="",
        description="Short label of the teaching approach (e.g. 'geometric-first'); used to avoid repeating it in remediation",
    )
    objectives: list[Objective]
    prerequisites: list[str] = Field(description="Concept keys this lesson assumes")
    connections: list[Connection] = []
    estimated_minutes: int
    sections: list[Section]
    questions: list[Question]
    resources: list[Resource] = []
    homework: list[str] = Field(default=[], description="Optional ungraded practice")
    completion: CompletionCriteria
    variant_bank: list[Question] = Field(
        default=[], description="Extra, distinct questions per objective for remediation/review. Never shown."
    )

    # ------------------------------------------------------------ helpers

    def question(self, qid: str) -> Question:
        for q in self.questions:
            if q.id == qid:
                return q
        raise KeyError(qid)

    def student_view(self) -> dict:
        """Projection safe to send to the browser: no grading data, no variant bank,
        and unverified/failed resource URLs removed."""
        data = self.model_dump(mode="json", exclude={"variant_bank": True})
        for q in data["questions"]:
            q.pop("grading", None)
        for r in data["resources"]:
            if r["verification"] == "failed":
                r["url"] = None
        return data


# ---------------------------------------------------------------- LLM-authored remediation


class RemediationContent(Closed):
    strategy: str = Field(description="Teaching approach used; must differ from previously used strategies")
    title: str
    diagnosis_summary: str = Field(description="What the student likely misunderstands, addressed to them")
    sections: list[Section]
    questions: list[Question] = Field(description="New questions on the failed objectives; distinct from earlier ones")
    resources: list[Resource] = []
