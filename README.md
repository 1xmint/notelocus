<!-- SPDX-License-Identifier: Apache-2.0 -->
# notelocus

Converge scattered notes into the ideas they are about.

A `locus`, in mathematics, is the set of points satisfying a condition. A note on
a desktop is rarely one idea — it is a conversation, a paste, a jotted line, a
model's long answer. notelocus finds the ideas inside those files, gives each one
a stable address, and tells you which ones you have written down more than once.

Dump `.txt` files on your desktop. Run one command. The desktop is clean and the
notes are filed by what they are about.

```bash
notelocus tidy
```

```
cortex/
    CORTEX.txt
    cortex foundation.txt
vera/
    HEY-VERA-ORG-PLAN.md
    VERA AND WORLD CURRENCY.txt
    vera.txt
unsorted/
    hoisin sauce.txt

moved 34 notes into 9 folders under C:\Users\Josh\Desktop\Notes

Nothing was deleted. `notelocus undo` puts it all back.
```

`notelocus shortcut` puts a **Tidy Notes.cmd** on the desktop, so after that it
is one double-click.

## What it will and will not touch

**Only note files sitting loose at the top level of the desktop.** Not folders,
not repositories, not anything inside them. That is a separate code path with no
recursion in it rather than a default somebody can raise — an earlier version
walked the whole tree and found 8,703 files where the notes numbered about fifty.

**Nothing is ever deleted or overwritten.** Files are moved. Every run records
what it did, `notelocus undo` reads that back, and an identical note already
filed is left where it is rather than copied again.

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

## Grouping

Notes are grouped by **distinctive vocabulary** — the words common inside a note
and rare across the pile, which is TF-IDF — compared by cosine over the weights.
Filenames count too, and match by containment above four characters, so `vera`,
`verayes` and `HEYVERA-VISION` meet, and `grok` meets `grokyoo`. A folder is
named for the shortest stem its members share, which is almost always the word
you would have picked.

Deterministic: same desktop, same folders, every run. A second run reads the
folders the first one made and puts new notes into them rather than inventing
near-duplicates beside them. Anything resembling nothing else goes to
`unsorted/` rather than getting a folder of its own.

A model-assisted layer that proposes better groupings is a later addition. The
offline grouping stays the default, because it is free, instant and repeatable.

## Install

```bash
pip install -e .
notelocus shortcut
```

## This repository is also an experiment

It runs [GitLocus](https://github.com/hey-vera/gitlocus) on its own pull
requests, in observation mode, as the first adoption of that project by a
repository that is not itself. See `AGENTS.md`.
