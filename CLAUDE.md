# Working in this repo

Read `.claude/CONTEXT.md` for what this project is, the constraints it holds
itself to, and the decisions already settled. This file is how to work in it;
`README.md` is the one written for people.

## Commands

```bash
PYTHONPATH=. uv run pytest -q   # tests — PYTHONPATH is required
uv run ruff format .            # format
uv run ruff check .             # lint
```

## Conventions

**PEP 287 – reStructuredText Docstring Format.** One line imperative summary; a body only where
  something is not obvious.

**Inline comments.** Use sparingly. Reserve them for a line whose *reason* is
not obvious from reading it — a workaround, a constraint, a choice that looks
arbitrary but is not. Never restate what the code already says.
