"""Shared Claude setup and prompt input for the reviewer and verifier nodes."""

import os

from langchain_anthropic import ChatAnthropic

from diff_utils import annotate
from state import ChangedFile

DEFAULT_MODEL = "claude-opus-5-5"
# Models that accept the server-side refusal fallback (`fallbacks: "default"`).
FALLBACK_MODELS = ("claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-fable-5-2", "claude-sonnet-5-5")


def chat_model(effort: str = "high") -> ChatAnthropic:
    """Claude via langchain-anthropic. Reads ANTHROPIC_API_KEY; ANTHROPIC_MODEL overrides the model.

    Opus 5.5 always thinks adaptively; `effort` controls how hard. No `temperature`:
    this model rejects sampling parameters.
    """
    model = os.getenv("ANTHROPIC_MODEL") or DEFAULT_MODEL
    extra: dict = {}
    if model.startswith(FALLBACK_MODELS):
        # If the model declines a request (stop_reason "refusal"), the API reruns it on
        # a fallback model picked by refusal category, inside the same call.
        extra = {"betas": ["server-side-fallback-2026-07-01"], "model_kwargs": {"fallbacks": "default"}}
    return ChatAnthropic(model=model, max_tokens=16000, effort=effort, max_retries=3, **extra)


def render_files(files: list[ChangedFile], context: dict[str, list[str]]) -> str:
    """Each changed file's numbered diff followed by the related code retrieved for it."""
    parts = []
    for f in files:
        snippets = context.get(f["path"]) or ["(nothing related found outside this file)"]
        parts.append(
            f"## Changed file: {f['path']}\n\n"
            "Diff. The number on the left is the line in the new version of the file; "
            "only numbered lines can take a comment.\n"
            f"```diff\n{annotate(f['diff'])}\n```\n\n"
            "### Related code elsewhere in the repository (unchanged by this PR)\n\n"
            + "\n\n".join(f"```python\n{s}\n```" for s in snippets)
        )
    return "\n\n".join(parts)
