<!-- SPDX-License-Identifier: Apache-2.0 -->
# notelocus

Converge scattered notes into the ideas they are about.

A `locus`, in mathematics, is the set of points satisfying a condition. A note on
a desktop is rarely one idea — it is a conversation, a paste, a jotted line, a
model's long answer. notelocus finds the ideas inside those files, gives each one
a stable address, and tells you which ones you have written down more than once.

```bash
notelocus index ~/Desktop --max-depth 2 --out ~/notes-corpus
```

```
read    143 files under C:\Users\Josh\Desktop
ideas   1798 distinct
exact   142 appear in more than one file
near    5 pairs above the threshold
wrote   C:\Users\Josh\notes-corpus

Nothing was moved, renamed or deleted.
```

## It does not touch your notes

v0.1 reads. There is no code path that writes outside `--out`, so there is no
`--apply` to get wrong at two in the morning and no flag that turns this into
something destructive. Moving and archiving are a later version, and they will
arrive with an audit trail.

Repositories under the folder are skipped — a README inside a checked-out project
belongs to that project, not to your notes. Pointing an early version at a
Desktop that also held source checkouts found 8,703 files where the notes
numbered about fifty.

## What it gives a model

The output is markdown with front matter, because the reader this is built for is
an assistant being pointed at a directory:

- `INDEX.md` — every idea, grouped by file and by tag, with a stable id
- `DUPLICATES.md` — pairs that look like the same thought written twice
- `ideas/<id>.md` with `--segments` — one document per idea, with its sources

An id is a hash of the idea's normalised content, so it survives reformatting and
regeneration. You can refer to `4c3ad9f993b8dd91` and mean the same thing
tomorrow.

## Deterministic, and honest about where it is not

The core is reproducible: the same folder produces byte-identical output every
time. No clock, no randomness, no model. That is what makes the corpus safe to
regenerate and readable as a diff.

Similarity is Jaccard over word shingles. It measures **wording, not meaning** —
a high score is usually the same idea pasted twice and occasionally two different
ideas expressed alike. Nothing is merged on the strength of it; the pairs are
reported so a person can decide.

Duplicate detection is complete below 2,000 segments and approximate above it,
where candidates come from minhash banding. Every reported pair has had its real
similarity computed either way; what changes is whether every pair was
*considered*. The alternative on a large corpus was not a slower complete answer
but no answer at all — the first real run had 755 million pairs to compare and
never finished.

## Install

```bash
pip install -e .
```

## This repository is also an experiment

It runs [GitLocus](https://github.com/hey-vera/gitlocus) on its own pull
requests, in observation mode, as the first adoption of that project by a
repository that is not itself. See `AGENTS.md`.
