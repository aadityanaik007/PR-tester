"""retrieve node: find code elsewhere in the project that the changed functions affect.

For each changed function: plain name search for callers + vector search on its code,
excluding the changed file itself. Callers rank first, then mentions (e.g. imports),
then vector hits by distance. Top 5 chunks per changed file.
"""

from pathlib import Path

from code_index import Chunk, CodeIndex
from diff_utils import changed_symbols, new_side_code
from state import ReviewState

TOP_K = 5
# Lower score = more relevant. Name hits always outrank vector hits (score 2 + distance).
CALL, MENTION, VECTOR = 0.0, 1.0, 2.0


def format_chunk(chunk: Chunk, reason: str) -> str:
    body = "\n".join(f"{n:>4} | {text}" for n, text in chunk.lines)
    return f"# {chunk.path}:{chunk.start}-{chunk.end}  {chunk.kind} {chunk.name}  [{reason}]\n{body}"


def retrieve(state: ReviewState) -> dict:
    index_dir = state.get("index_dir")  # evals: a fixture snapshot instead of project/
    index = CodeIndex(Path(index_dir) if index_dir else None)
    print(f"retrieve: indexed {len(index.chunks)} chunks from {index.root}")
    try:
        return {"context": _related_code(state, index)}
    finally:
        index.close()


def _related_code(state: ReviewState, index: CodeIndex) -> dict[str, list[str]]:
    context: dict[str, list[str]] = {}
    for f in state["files"]:
        path, patch = f["path"], f["diff"]
        best: dict[str, tuple[float, Chunk, str]] = {}

        def offer(chunk: Chunk, score: float, reason: str) -> None:
            if chunk.id not in best or score < best[chunk.id][0]:
                best[chunk.id] = (score, chunk, reason)

        symbols = changed_symbols(patch)
        for name, code in symbols.items():
            for chunk, is_call in index.mentions(name, exclude_path=path):
                offer(chunk, CALL if is_call else MENTION, f"{'calls' if is_call else 'mentions'} {name}")
            for chunk, dist in index.similar(code, exclude_path=path):
                offer(chunk, VECTOR + dist, f"similar to {name}, distance {dist:.2f}")
        if not symbols:  # e.g. a module-level or non-Python change
            for chunk, dist in index.similar(new_side_code(patch), exclude_path=path):
                offer(chunk, VECTOR + dist, f"similar to the changed lines, distance {dist:.2f}")

        top = sorted(best.values(), key=lambda t: t[0])[:TOP_K]
        context[path] = [format_chunk(chunk, reason) for _, chunk, reason in top]

        print(f"  {path}: changed {sorted(symbols) or '(no def/class found)'}")
        for _, chunk, reason in top:
            print(f"    {chunk.id:<50} {reason}")
    return context
