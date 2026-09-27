import httpx
from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from copilot.data_collection.merge_into_one_record import read_advisories
from copilot.dependencies.check_my_dependencies import (
    DependencyReport,
    Finding,
    check_requirements,
    index_local_advisories,
)
from copilot.dependencies.read_requirements_file import read_requirements_text
from copilot.rag.answer_with_citations import CitedAnswer, answer_question
from copilot.rag.route_question import wants_dependency_check
from copilot.rag.split_into_chunks import STRUCTURED
from copilot.settings import MissingGroqKeyError, get_settings

app = FastAPI(
    title="Security Copilot",
    description="Checks Python dependencies against public advisories and explains them.",
)

_advisory_index: dict | None = None


@app.exception_handler(Exception)
async def any_unhandled_error(request: Request, error: Exception) -> JSONResponse:
    """Answer with JSON whatever goes wrong, so callers never have to parse an HTML page."""
    return JSONResponse(
        status_code=500,
        content={"detail": f"{type(error).__name__}: {error}"},
    )


def advisory_index() -> dict:
    """Load the merged advisory records once and keep them for the life of the process."""
    global _advisory_index
    if _advisory_index is None:
        path = get_settings().data_dir / "processed" / "advisories.jsonl"
        if not path.exists():
            raise HTTPException(503, "The advisory corpus is not built yet. Run make data.")
        _advisory_index = index_local_advisories(read_advisories(path))
    return _advisory_index


class CheckRequest(BaseModel):
    requirements: str = Field(description="The contents of a requirements.txt file.")


class CheckResponse(BaseModel):
    packages_checked: int
    packages_affected: list[str]
    findings: list[Finding]
    warnings: list[str]


class AskRequest(BaseModel):
    question: str
    requirements: str | None = Field(
        default=None, description="Optional requirements.txt contents to check first."
    )
    strategy: str = STRUCTURED


class AskResponse(BaseModel):
    answer: str
    citations: list[str]
    unverified_citations: list[str]
    affected_packages: list[str]
    confidence: float
    refused: bool
    checked_dependencies: bool
    sources: list[dict]


def to_check_response(report: DependencyReport) -> CheckResponse:
    return CheckResponse(
        packages_checked=report.packages_checked,
        packages_affected=report.affected_packages,
        findings=report.findings,
        warnings=report.warnings,
    )


def run_check(requirements_text: str) -> DependencyReport:
    parsed = read_requirements_text(requirements_text)
    with httpx.Client(timeout=60.0) as client:
        return check_requirements(parsed, advisory_index(), client)


@app.get("/health")
def health() -> dict[str, object]:
    settings = get_settings()
    corpus = settings.data_dir / "processed" / "advisories.jsonl"
    return {
        "status": "ok",
        "model": settings.model_name,
        "corpus_built": corpus.exists(),
        "groq_key_present": settings.has_groq_key(),
    }


@app.post("/check-dependencies", response_model=CheckResponse)
def check_dependencies(request: CheckRequest) -> CheckResponse:
    return to_check_response(run_check(request.requirements))


@app.post("/check-dependencies/upload", response_model=CheckResponse)
async def check_uploaded_file(file: UploadFile) -> CheckResponse:
    contents = (await file.read()).decode("utf-8", errors="replace")
    return to_check_response(run_check(contents))


@app.post("/ask", response_model=AskResponse)
def ask(request: AskRequest) -> AskResponse:
    findings: list[Finding] = []
    checked = False
    if request.requirements and wants_dependency_check(request.question):
        findings = run_check(request.requirements).findings
        checked = True

    try:
        answer: CitedAnswer = answer_question(
            request.question, findings=findings, strategy=request.strategy
        )
    except MissingGroqKeyError as error:
        raise HTTPException(503, str(error)) from error

    return AskResponse(
        answer=answer.answer,
        citations=answer.citations,
        unverified_citations=answer.unverified_citations,
        affected_packages=answer.affected_packages,
        confidence=answer.confidence,
        refused=answer.refused,
        checked_dependencies=checked,
        sources=[
            {
                "advisory_id": passage.advisory_id,
                "package": passage.package,
                "score": passage.score,
                "text": passage.chunk.text,
                "url": f"https://osv.dev/vulnerability/{passage.advisory_id}",
            }
            for passage in answer.passages
        ],
    )
