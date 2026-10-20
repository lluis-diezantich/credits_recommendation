# D12: CI installs from hashed lockfiles; `ruff format` is advisory

- **Status:** Accepted
- **Date:** 2026-10-17
- **Where it lives:** [`requirements.lock`](../../requirements.lock),
  [`requirements-dev.lock`](../../requirements-dev.lock),
  [`.pre-commit-config.yaml`](../../.pre-commit-config.yaml),
  `.github/workflows/tests.yml`

## Context

The Friday radar runs unattended, and a release somebody else ships should not
be able to turn it red. Separately, two files in this repo are formatted by hand
on purpose: the aligned columns in `policy.py` and the comment-per-value `SCHEMA`
in `stages/load.py`, where the alignment is what makes a divergent value visible.

## Options

1. **Floating versions, `ruff format` enforced**: standard, and both a transitive
   release and an autoformatter can change behaviour or erase the alignment.
2. **Two hashed lockfiles, `ruff format --diff` only**: reproducible installs and
   the deliberate formatting survives; the diff hook can never pass.

## Decision

Option 2. Runtime and dev are separate locks, resolved for the 3.11 floor so one
file serves the 3.11/3.12/3.13 matrix, installed with `--require-hashes` and the
project with `--no-deps` so the lock stays authoritative. `pytest` and `ty` stay
out of pre-commit: both read the whole project, and a hook that runs the suite is
a hook people pass `--no-verify` to, which costs the lint checks as well.

## Evidence

A test-only package can no longer break the Friday job, because it is not in
that job's environment at all. `ty` found two real defects on its first run:
`radars/qobuz.py` overrode `add_arguments(self, ap)` against a base taking
`parser`, so a keyword call broke on that one subclass, and `radars/remezcla.py`
called `find(attrs=...)` in a form bs4's own overloads reject.

## Consequences

- The `ruff-format` pre-commit hook **can never pass**: `--diff` exits non-zero
  whenever a diff exists, and it fails on the committed `policy.py` on `main`
  with no changes at all. It blocked a commit on 2026-10-18. Either exclude the
  two files or drop the hook and let `ruff check` gate alone — open in
  [../../todo.md](../../todo.md).
- Both locks are generated; regenerate with the `uv pip compile` line in their
  headers after changing `pyproject.toml`.
- There is still no required status check on `main` and no vulnerability scan;
  `dependabot.yml` bumps versions without knowing which are vulnerable.
