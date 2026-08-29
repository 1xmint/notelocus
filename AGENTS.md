<!-- SPDX-License-Identifier: Apache-2.0 -->
# AGENTS.md

Instructions for coding agents working in this repository. Follows the
[AGENTS.md](https://agents.md) convention.

## What this is

A tool that reads a folder of notes and finds the ideas in them. It also serves
as the first adoption of [GitLocus](https://github.com/hey-vera/gitlocus) by a
repository other than GitLocus itself — see "The experiment" below.

## The commands

```
notelocus tidy            file loose desktop notes into Desktop/Notes/<topic>/
notelocus tidy --dry-run  say what would move, change nothing
notelocus undo            put the last tidy back
notelocus shortcut        write a one-click launcher to the desktop
notelocus index <dir> --out <dir>   build a segment-level corpus for a model
notelocus find <dir> <query>        search without writing anything
```

## Build and test

```bash
pip install -e ".[dev]" || pip install pytest ruff
python -m pytest
python -m ruff check .
python -m ruff format --check .
```

Those three are the checks CI runs, and their names — `tests`, `lint`, `format` —
are what `.gitlocus/policy.yml` requires.

## The rule that is not negotiable

**Nothing may delete a note, and nothing may overwrite one.**

This used to read "nothing may move, rename or delete", held by construction
because no code path wrote outside `--out`. `tidy` moves files, which is the
point of it, so that guarantee is gone and this section says what replaced it
rather than being left to imply something it no longer means.

What protects a note now is built rather than absent:

- **`src/notelocus/manifest.py`** — every run records each source and
  destination, timestamped so a second run cannot destroy the record that would
  undo the first.
- **`notelocus undo`** — reads it back. It refuses to overwrite anything that
  has appeared at the original path since, and reports what it could not
  restore rather than guessing.
- **`_free_name` in `tidy.py`** — an identical note already filed is left alone;
  a different note with the same name gets a suffix. Neither is overwritten.
- **Scope is a code path, not a flag.** `tidy` reads one directory and cannot
  descend into any of them; there is no depth parameter to pass wrong.
  `corpus.py` keeps the recursive walker for `index` and `find`, which only
  read. Sharing one walker between a read command and a move command is how a
  scope bug becomes a data-loss bug.

`tests/test_nothing_is_lost.py` is the enforcement. It generates documents that
look like real pasted notes and asserts that splitting one never loses a word.
That test found four bugs the example-based tests missed, in one sitting:

- a single-line paragraph had its content eaten by its own derived title
- speaker labels were dropped
- a trailing `Assistant:` was counted twice
- with two labels in one span, only the last survived

Every one of those would have silently damaged somebody's notes.

## Conventions

- Tests are named as the claim they make, and the negative ones are the point.
- Comments explain **why**. If a comment restates the code, delete it.
- No runtime dependencies. This reads files from a personal machine, and every
  dependency is something else that gets to see them.
- Determinism is a feature: no clock, no randomness, no model in the core. The
  same folder must produce byte-identical output every run.

## The experiment

`.github/workflows/gate.yml` runs GitLocus on every pull request, in observation
mode. Two things are deliberately *not* configured around:

1. **The job is called `notes-gate`.** GitLocus's default `exclude` regex is
   `^(gitlocus|gate|arm|Scorecard|analyze)` — a list of its own job names. The
   action's documentation says that regex must match the job running it, or the
   job waits for itself. Whether a natural job name breaks a first adoption is
   the thing being measured.

2. **`fixtures` is path-filtered and skips on most pull requests.** GitLocus's
   evidence collector handles a `skipped` conclusion in code and says in a
   comment that it has never seen one, because nothing in that repository is
   ever skipped.

Findings go to that repository as issues, with the verdict quoted. If either
turns out to be a non-issue, that gets written down too — a prediction quietly
dropped because it was inconvenient is worse than one that was wrong.
