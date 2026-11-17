"""LLM engines with schema-enforced structured output.

The model never returns prose. OpenAI is called with a JSON Schema
``response_format`` built from the Pydantic model; Anthropic is called
with a forced tool whose ``input_schema`` is the same model. Either
way the payload is validated with ``CodeReviewPayload.model_validate``
— and if validation fails, the error is fed back for exactly one
repair retry before giving up loudly. Zero regex scraping of free text.

These engines activate only when their API key is in the environment;
the default engine is the deterministic static analyzer.
"""

from __future__ import annotations

import json
import os

import httpx
from pydantic import BaseModel, Field, ValidationError

from .chunking import DiffChunk
from .schema import ReviewIssue

SYSTEM_PROMPT = (
    "You are a senior code reviewer. Review the diff chunk and return "
    "ONLY findings that match the schema: real defects a maintainer "
    "would act on (security, performance, error handling, correctness, "
    "missing tests, maintainability). Anchor every issue to the exact "
    "line number in the NEW file shown in the chunk header. Do not "
    "invent issues to fill space; an empty list is a valid review."
)


class CodeReviewPayload(BaseModel):
    """What the LLM is allowed to return — nothing else parses."""

    issues: list[ReviewIssue] = Field(default_factory=list)


def _chunk_prompt(chunk: DiffChunk) -> str:
    fn = f" (in {chunk.function})" if chunk.function else ""
    return (
        f"File: {chunk.file}{fn}\n"
        f"New-file lines {chunk.start_line}-{chunk.end_line}\n"
        f"Diff chunk (+ added, - removed, space = context):\n"
        f"```diff\n{chunk.text}\n```"
    )


class OpenAIAnalyzer:
    name = "openai"

    def __init__(self, model: str = "gpt-4o-2024-08-06", api_key: str | None = None):
        self.model = model
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")

    def review_chunks(self, chunks: list[DiffChunk]) -> list[ReviewIssue]:
        issues: list[ReviewIssue] = []
        schema = CodeReviewPayload.model_json_schema()
        for chunk in chunks:
            payload = self._call(chunk, schema)
            issues.extend(payload.issues)
        return issues

    def _call(self, chunk: DiffChunk, schema: dict) -> CodeReviewPayload:
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": _chunk_prompt(chunk)},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "code_review", "strict": False,
                                "schema": schema},
            },
        }
        last_error: Exception | None = None
        for _attempt in range(2):  # one schema-repair retry
            resp = httpx.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=body, timeout=120,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            try:
                return CodeReviewPayload.model_validate_json(content)
            except ValidationError as exc:
                last_error = exc
                body["messages"].append(
                    {"role": "user",
                     "content": f"Your previous output failed schema "
                                f"validation: {exc}. Return corrected JSON "
                                f"only."})
        raise RuntimeError(f"OpenAI output failed schema validation: {last_error}")


class AnthropicAnalyzer:
    name = "anthropic"

    def __init__(self, model: str = "claude-sonnet-4-5", api_key: str | None = None):
        self.model = model
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")

    def review_chunks(self, chunks: list[DiffChunk]) -> list[ReviewIssue]:
        issues: list[ReviewIssue] = []
        for chunk in chunks:
            resp = httpx.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": self.api_key,
                         "anthropic-version": "2023-06-01"},
                json={
                    "model": self.model,
                    "max_tokens": 4096,
                    "system": SYSTEM_PROMPT,
                    "tools": [{
                        "name": "submit_review",
                        "description": "Submit the structured code review.",
                        "input_schema": CodeReviewPayload.model_json_schema(),
                    }],
                    "tool_choice": {"type": "tool", "name": "submit_review"},
                    "messages": [{"role": "user",
                                  "content": _chunk_prompt(chunk)}],
                },
                timeout=120,
            )
            resp.raise_for_status()
            for block in resp.json()["content"]:
                if block.get("type") == "tool_use":
                    payload = CodeReviewPayload.model_validate(block["input"])
                    issues.extend(payload.issues)
        return issues


def get_llm_analyzer(engine: str):
    if engine == "openai":
        return OpenAIAnalyzer()
    if engine == "anthropic":
        return AnthropicAnalyzer()
    raise ValueError(f"unknown LLM engine: {engine}")
