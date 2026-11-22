# PR Review Agent

An AI reviewer for GitHub pull requests. When a PR is opened or updated, it reads the
diff, gathers related code from the rest of the repository, and asks Claude to find real
problems. That includes code the PR breaks in files it didn't touch. Findings are posted
on the PR as inline review comments. If any finding is a bug, merging waits for a human
to approve.

## Features

- Runs on every pull request (opened, reopened, new commits) through GitHub Actions, or by hand with a PR number.
- Fetches the PR's changed files and patches from the GitHub REST API.
- Skips lockfiles, binary files, deleted files and files with more than 500 changed lines.
- Splits the code under review into functions and classes with Python's `ast` module, and never indexes the reviewer itself.
- Finds code related to each changed function: callers by name search, similar code by Chroma vector search, top 5 per file.
- Reviews the diff plus that context with Claude Opus 5.5 through LangChain, returning structured comments.
- Keeps every comment on a line that appears in the diff, so GitHub can show it inline.
- Double-checks each comment with a second Claude call, and retries once if every comment was rejected *(in progress)*.
- Posts one GitHub review with an inline comment per finding, or a short "No issues found".
- Holds the merge for a human's approval whenever a bug is found.
- `DRY_RUN=true` prints the review instead of posting it.
- Traces every run as a single LangSmith trace.
- Reads the target PR from `GITHUB_REPOSITORY` / `PR_NUMBER`, falling back to `--repo` / `--pr`.

## Architecture

### How a PR flows through GitHub Actions

```text
                 GitHub: PR opened · reopened · new commit
                                     │
                                     ▼
┌─ review job · uv run graph.py · LangGraph · one LangSmith trace ───────┐
│                                                                        │
│   fetch_diff     changed files + patches     ◄── GitHub REST API       │
│       │                                                                │
│       ▼                                                                │
│   retrieve       top 5 related chunks/file   ◄── Chroma + ast index    │
│       │                                          of project/ only      │
│       ▼                                                                │
│   reviewer ◄──┐  draft comments              ◄── Claude                │
│       │       │                                                        │
│       │       │  retry once if every                                   │
│       ▼       │  comment was rejected                                  │
│   verifier ───┘  final comments              ◄── Claude                │
│       │                                                                │
│       ▼                                                                │
│   post_comment   review + inline comments    ──► GitHub PR             │
│                  bug_count                                             │
│                                                                        │
└────────────────────────────────────┬───────────────────────────────────┘
                                     │ bug_count > 0
                                     ▼
┌─ approval job · only if bug_count > 0 · environment pr-approval ───────┐
│                                                                        │
│   waits for a human to click Approve  ──►  merge allowed               │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

### The LangGraph graph (`graph.py`)

Each arrow is a graph edge. Next to each node: the `ReviewState` fields it reads and writes.

```text
                 ● START
                 │
                 ▼
          ┌──────────────┐
          │  fetch_diff  │   writes  files
          └──────┬───────┘
                 │
                 ▼
          ┌──────────────┐
          │   retrieve   │   reads   files
          └──────┬───────┘   writes  context
                 │
                 ▼
          ┌──────────────┐
     ┌───►│   reviewer   │   reads   files, context, rejected drafts (on a retry)
     │    └──────┬───────┘   writes  draft_comments, attempts
     │           │
     │           ▼
     │    ┌──────────────┐
     │    │   verifier   │   reads   draft_comments
     │    └──────┬───────┘   writes  final_comments, needs_retry
     │           │
     │           ▼
     │     after_verify      conditional edge (a routing function, not a node)
     │           │
     └── retry ──┤           retry if needs_retry and attempts < MAX_ATTEMPTS (2)
                 │ done
                 ▼
          ┌──────────────┐
          │ post_comment │   reads   final_comments
          └──────┬───────┘   posts   the review, writes bug_count for Actions
                 │
                 ▼
                 ● END
```

### ReAct loops and tools

- **No ReAct agent and no tools today.** `reviewer` and `verifier` each make a single
  Claude call that returns structured output. Claude doesn't call tools or loop by itself.
- **The only loop is the graph's retry edge** (`verifier` → `reviewer`), which runs at
  most once.
- **Planned for v3, not built:** a Wikipedia tool, OSV (open-source vulnerability
  database) and PyPI (package info). With them, `reviewer` becomes a ReAct loop:

```text
reviewer node (v3, planned)

  ┌──────────┐  tool call    ┌──────────────────────────┐
  │  Claude  │ ────────────► │  Wikipedia · OSV · PyPI  │
  │          │ ◄──────────── │                          │
  └────┬─────┘  tool result  └──────────────────────────┘
       │  repeats until Claude has what it needs
       ▼
  structured review → draft_comments
```

### Where things live

| Part | File |
|---|---|
| Graph wiring and entry point | `graph.py` |
| One file per node | `nodes/fetch_diff.py`, `retrieve.py`, `reviewer.py`, `verifier.py`, `post_comment.py` |
| State passed between nodes | `state.py` |
| GitHub REST calls | `github_api.py` |
| Patch parsing and diff line numbers | `diff_utils.py` |
| Code index (`ast` chunks + Chroma) | `code_index.py` |
| Claude setup and prompt input | `llm.py` |
| Target PR and `DRY_RUN` settings | `config.py` |
| GitHub Actions workflow | `../.github/workflows/pr-review.yml` |
