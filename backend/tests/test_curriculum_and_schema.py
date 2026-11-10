import copy

from sqlalchemy import func, select

from app.ai.schema_utils import strict_json_schema
from app.models import CurriculumVersion, Lesson, LessonVersion
from app.schemas.grading import RubricGrade
from app.schemas.lesson import LessonContent, RemediationContent
from app.services.curriculum import load_seed_lesson, load_spec, sync_curriculum, validate_spec
from app.services.lesson_validation import latex_problems, validate_lesson


def test_spec_is_valid_dag_in_topological_order():
    assert validate_spec(load_spec()) == []


def test_cycle_and_order_violations_detected():
    spec = copy.deepcopy(load_spec())
    by = {c["key"]: c for c in spec["concepts"]}
    by["la.scalars_vectors"]["requires"] = ["la.matmul"]
    errs = validate_spec(spec)
    assert any(e.startswith("cycle") for e in errs)
    spec = copy.deepcopy(load_spec())
    m01 = spec["blocks"][0]["modules"][0]
    m01["lessons"] = list(reversed(m01["lessons"]))  # matmul before dot product
    assert any("no earlier lesson teaches" in e for e in validate_spec(spec))


def test_sync_is_idempotent(db):
    n_versions = db.scalar(select(func.count(CurriculumVersion.id)))
    n_lessons = db.scalar(select(func.count(Lesson.id)))
    sync_curriculum(db)
    db.commit()
    assert db.scalar(select(func.count(CurriculumVersion.id))) == n_versions
    assert db.scalar(select(func.count(Lesson.id))) == n_lessons
    assert db.scalar(select(func.count(LessonVersion.id)).where(LessonVersion.source == "seed")) == 6


def test_full_program_outline_present(db):
    spec = load_spec()
    assert len(spec["blocks"]) == 18
    assert spec["blocks"][0]["status"] == "authored"


def test_student_view_strips_grader_data():
    for path in ["lessons/b01_m01_l01.yaml", "lessons/b01_m03_l05.yaml"]:
        view = load_seed_lesson(path).student_view()
        blob = str(view)
        assert "variant_bank" not in view
        assert all("grading" not in q for q in view["questions"])
        assert "reference_solution" not in blob and "hidden_tests" not in blob and "correct_option_ids" not in blob


def _all_objects(node):
    if isinstance(node, dict):
        if node.get("type") == "object":
            yield node
        for v in node.values():
            yield from _all_objects(v)
    elif isinstance(node, list):
        for v in node:
            yield from _all_objects(v)


def test_structured_output_schemas_are_closed_and_supported():
    for model in (LessonContent, RemediationContent, RubricGrade):
        s = strict_json_schema(model)
        text = str(s)
        assert "oneOf" not in text and "discriminator" not in text and "minLength" not in text
        for obj in _all_objects(s):
            assert obj["additionalProperties"] is False
            assert set(obj["required"]) == set(obj["properties"])


def test_validator_catches_alignment_and_question_errors():
    c = load_seed_lesson("lessons/b01_m01_l01.yaml")
    spec = {"key": c.lesson_key, "objectives": [{"key": o.id} for o in c.objectives]}
    bad = c.model_copy(deep=True)
    bad.questions = [q for q in bad.questions if "b01.m01.l01.o3" not in q.objective_ids]
    bad.questions[1].grading.correct_option_ids = ["zzz"]
    r = validate_lesson(bad, spec, execute_code=False, check_links=False)
    assert any("o3 is not assessed" in e for e in r.errors)
    assert any("correct_option_ids" in e for e in r.errors)
    assert validate_lesson(c, spec, budget_minutes=30, execute_code=False, check_links=False).errors  # over the time budget
    assert validate_lesson(c, spec, allowed_prerequisites=set(), execute_code=False, check_links=False).ok  # L1 has no prereqs
    l3 = load_seed_lesson("lessons/b01_m02_l03.yaml")
    r = validate_lesson(l3, {"key": l3.lesson_key}, allowed_prerequisites={"la.scalars_vectors"}, execute_code=False, check_links=False)
    assert any("not demonstrated" in e for e in r.errors)


def test_latex_checks():
    assert latex_problems("ok $a^{2}$ and $$\\frac{1}{2}$$") == []
    assert latex_problems("broken $\\frac{1}{2$") != []
    assert latex_problems("odd $ sign") != []
    assert latex_problems("code `$x` is fine") == []
