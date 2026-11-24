from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CodeAuditItem(StrictModel):
    paper_module: str
    file_path: str
    status: Literal["exists", "missing", "stub_only", "unclear"]


class ExperimentSummary(StrictModel):
    datasets: list[str]
    key_results: str
    red_flags: str


class PaperAnalysis(StrictModel):
    tldr: str = Field(min_length=1, max_length=50)
    problem: str
    method_details: list[str]
    experiments: ExperimentSummary
    tags: list[str]
    repo_url: str | None = None
    code_status: Literal["complete", "partial", "empty_repo", "no_repo"]
    code_audit: list[CodeAuditItem]
    missing_assets: list[str]
    hype_flag: bool
    hype_reason: str = ""
    paper_type: Literal["empirical", "theoretical", "survey", "mixed"] = "empirical"
    note_body: str = ""

    @field_validator("note_body")
    @classmethod
    def validate_note_body(cls, body: str) -> str:
        import re

        if body and ("## Overview" not in body or "## Paper Analysis" not in body):
            raise ValueError("note_body requires Overview and Paper Analysis sections")
        if (
            re.search(r"^# |^tags?::|^## Personal Notes", body, re.M)
            or "<!-- paper-analysis:" in body
        ):
            raise ValueError(
                "note_body must contain only the managed analysis: no H1, tags, personal notes or markers"
            )
        return body

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, tags: list[str]) -> list[str]:
        import re

        if any(not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", tag) for tag in tags):
            raise ValueError("Tags must be lowercase ASCII words separated by hyphens")
        return list(dict.fromkeys(tags))

    @model_validator(mode="after")
    def validate_evidence(self):
        if self.hype_flag and not self.hype_reason.strip():
            raise ValueError("hype_reason is required when hype_flag is true")
        if self.code_status == "no_repo" and self.repo_url:
            raise ValueError("no_repo cannot have a repo_url")
        return self


class PaperMetadata(BaseModel):
    arxiv_id: str
    title: str
    authors: list[str]
    abstract: str
    published: str
    url: str
    pdf_url: str
    doi: str = ""
