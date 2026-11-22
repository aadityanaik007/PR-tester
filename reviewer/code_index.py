"""Chunk the project under review into functions/classes with ast and index them in Chroma.

Only project/ is indexed (override with PROJECT_DIR); reviewer/ is always excluded.
The index lives in memory and is rebuilt every run, so it can never be stale.
"""

import ast
import os
import re
from dataclasses import dataclass
from pathlib import Path

import chromadb
from chromadb.config import Settings

REVIEWER_DIR = Path(__file__).resolve().parent
REPO_ROOT = REVIEWER_DIR.parent
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules", ".chroma"}

FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef)


def project_dir() -> Path:
    return Path(os.getenv("PROJECT_DIR") or REPO_ROOT / "project").resolve()


@dataclass
class Chunk:
    path: str                          # repo-relative, matches GitHub's PR file paths
    name: str                          # "func", "Class", "Class.method" or "<module>"
    kind: str                          # function | class | method | module
    lines: list[tuple[int, str]]       # (line number, text); may skip lines covered elsewhere

    @property
    def id(self) -> str:
        return f"{self.path}::{self.name}"

    @property
    def start(self) -> int:
        return self.lines[0][0]

    @property
    def end(self) -> int:
        return self.lines[-1][0]

    @property
    def code(self) -> str:
        return "\n".join(text for _, text in self.lines)


def _span(node: ast.AST) -> range:
    """Lines of a def/class including its decorators (1-based, inclusive)."""
    start = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])
    return range(start, node.end_lineno + 1)


def chunk_file(path: Path) -> list[Chunk]:
    """One chunk per top-level function, per method, per class body (minus its methods),
    plus one <module> chunk for whatever is left (imports, constants, __main__ block)."""
    source = path.read_text(encoding="utf-8")
    rel = path.relative_to(REPO_ROOT).as_posix()
    text = source.splitlines()
    numbered = lambda rng: [(n, text[n - 1]) for n in rng if text[n - 1].strip()]  # noqa: E731

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return [Chunk(rel, "<module>", "module", numbered(range(1, len(text) + 1)))] if text else []

    chunks: list[Chunk] = []
    covered: set[int] = set()
    for node in tree.body:
        if isinstance(node, FUNCS):
            span = _span(node)
            chunks.append(Chunk(rel, node.name, "function", numbered(span)))
            covered.update(span)
        elif isinstance(node, ast.ClassDef):
            class_span, method_lines = _span(node), set()
            for item in node.body:
                if isinstance(item, FUNCS):
                    span = _span(item)
                    chunks.append(Chunk(rel, f"{node.name}.{item.name}", "method", numbered(span)))
                    method_lines.update(span)
            header = numbered(n for n in class_span if n not in method_lines)
            if header:
                chunks.append(Chunk(rel, node.name, "class", header))
            covered.update(class_span)

    rest = numbered(n for n in range(1, len(text) + 1) if n not in covered)
    if rest:
        chunks.append(Chunk(rel, "<module>", "module", rest))
    return chunks


def python_files(root: Path):
    for p in sorted(root.rglob("*.py")):
        if SKIP_DIRS.intersection(p.parts) or p.is_relative_to(REVIEWER_DIR):
            continue  # never index the reviewer itself, even if PROJECT_DIR points at the repo root
        yield p


class CodeIndex:
    def __init__(self, root: Path | None = None):
        self.root = root or project_dir()
        self.chunks = [c for f in python_files(self.root) for c in chunk_file(f)]
        self.by_id = {c.id: c for c in self.chunks}

        client = chromadb.EphemeralClient(settings=Settings(anonymized_telemetry=False))
        # Chroma's default embedding function: all-MiniLM-L6-v2 via ONNX, runs locally.
        self.collection = client.get_or_create_collection(
            "code_chunks", configuration={"hnsw": {"space": "cosine"}}
        )
        if self.chunks:
            self.collection.upsert(
                ids=[c.id for c in self.chunks],
                documents=[f"{c.path} {c.name}\n{c.code}" for c in self.chunks],
                metadatas=[
                    {"path": c.path, "name": c.name, "kind": c.kind, "start": c.start, "end": c.end}
                    for c in self.chunks
                ],
            )

    def similar(self, code: str, exclude_path: str, k: int = 10) -> list[tuple[Chunk, float]]:
        """Vector search: chunks most similar to `code`, outside `exclude_path`, with cosine distance."""
        candidates = sum(1 for c in self.chunks if c.path != exclude_path)
        if not candidates or not code.strip():
            return []
        res = self.collection.query(
            query_texts=[code],
            n_results=min(k, candidates),
            where={"path": {"$ne": exclude_path}},
        )
        return [(self.by_id[i], d) for i, d in zip(res["ids"][0], res["distances"][0])]

    def mentions(self, name: str, exclude_path: str) -> list[tuple[Chunk, bool]]:
        """Plain name search: chunks outside `exclude_path` containing `name` as a whole word.
        The bool is True when it looks like a call (`name(`), False for imports and other mentions."""
        word = re.compile(rf"\b{re.escape(name)}\b")
        call = re.compile(rf"\b{re.escape(name)}\s*\(")
        return [
            (c, bool(call.search(c.code)))
            for c in self.chunks
            if c.path != exclude_path and word.search(c.code)
        ]
