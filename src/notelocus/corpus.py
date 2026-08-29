"""Reading a folder of notes into an addressable corpus.

Reading only, and recursive - this is what `index` and `find` walk with.

`tidy` deliberately does **not** use this. It has its own walker in `tidy.py`
that cannot descend at all, because sharing one traversal between a command that
reads and a command that moves files is how a scope bug becomes a data-loss bug.
Nothing in this module writes anything.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .identity import content_id
from .segment import Segment, split

#: Extensions treated as notes. Deliberately short: a `.py` or a `.json` on a
#: desktop is a file that belongs to something else, and sweeping it into a
#: notes index would be the tool overreaching.
NOTE_SUFFIXES = frozenset({".txt", ".md", ".markdown", ".text"})

#: Directories never descended into. Anything here is somebody else's data.
SKIP_DIRS = frozenset(
    {".git", ".svn", "node_modules", "__pycache__", "venv", ".venv", "target", "dist", "build"}
)

#: Beyond this a file is not a note. The largest note on the corpus this was
#: built for is 54 KB; a megabyte of text is a log or an export.
MAX_NOTE_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class Note:
    """One source file, and the ideas found in it."""

    path: Path
    modified: datetime
    size: int
    segments: tuple[Entry, ...]


@dataclass(frozen=True)
class Entry:
    """A segment, with the identity and provenance that make it addressable."""

    id: str
    segment: Segment
    source: Path
    modified: datetime

    @property
    def title(self) -> str:
        return self.segment.title

    @property
    def text(self) -> str:
        return self.segment.text


def find_notes(root: Path, max_depth: int | None = None) -> Iterator[Path]:
    """Every note file under `root`, in a stable order.

    Sorted, so two runs over an unchanged folder walk it identically and the
    index diff is empty. `os.walk` order is filesystem-dependent and would make
    the output churn for no reason.

    **Nested repositories are not descended into.** Pointing this at a Desktop
    that also holds checked-out projects otherwise sweeps in every README,
    CHANGELOG and doc page in every one of them: the first real run over this
    author's Desktop found 8,703 files where the notes number about fifty. Those
    files belong to a project, not to your notes, and the same reasoning already
    keeps `.py` and `.json` out.
    """
    root = Path(root)
    for dirpath, dirnames, filenames in os.walk(root):
        here = Path(dirpath)
        # Depth is counted from `root`, and a limit stops the walk descending
        # rather than filtering afterwards. Archive and backup folders are the
        # common case: they hold thousands of documents that are a record of a
        # project rather than anybody's notes.
        if max_depth is not None and len(here.relative_to(root).parts) >= max_depth:
            dirnames[:] = []
        # A directory holding `.git` is somebody else's repository. Its own
        # contents are skipped, but the check happens after `root` itself so
        # that running this *inside* a repository still works.
        if here != root and (here / ".git").exists():
            dirnames[:] = []
            continue
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        for name in sorted(filenames):
            path = here / name
            if path.suffix.lower() in NOTE_SUFFIXES:
                yield path


def read_note(path: Path) -> Note | None:
    """Read and segment one note, or `None` if it is not usable as one.

    Returns `None` rather than raising for anything that is merely not a note —
    too large, unreadable, empty. A folder of real files will contain a few of
    those and stopping the whole index for one of them would be the wrong
    trade.
    """
    try:
        stat = path.stat()
        if stat.st_size > MAX_NOTE_BYTES or stat.st_size == 0:
            return None
        # Desktop notes are pasted from everywhere; a stray byte should not cost
        # the whole file. `errors="replace"` keeps the rest readable.
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    if not text.strip():
        return None

    modified = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
    entries = tuple(
        Entry(id=content_id(segment.text), segment=segment, source=path, modified=modified)
        for segment in split(text)
    )
    if not entries:
        return None
    return Note(path=path, modified=modified, size=stat.st_size, segments=entries)


def read_corpus(root: Path, max_depth: int | None = None) -> list[Note]:
    """Every readable note under `root`."""
    notes = []
    for path in find_notes(root, max_depth=max_depth):
        if note := read_note(path):
            notes.append(note)
    return notes


def entries_of(notes: list[Note]) -> list[Entry]:
    """Every segment across every note, first occurrence winning on id.

    The same idea pasted into two files produces one entry, not two, because the
    id is derived from content. The duplicate is not lost: `find_duplicates`
    reports near-matches, and exact matches are visible as a segment with more
    than one source.
    """
    seen: dict[str, Entry] = {}
    for note in notes:
        for entry in note.segments:
            seen.setdefault(entry.id, entry)
    return list(seen.values())


def sources_by_id(notes: list[Note]) -> dict[str, list[Path]]:
    """Every file each segment id appears in.

    A segment with more than one source is the same text pasted twice — the
    cheapest possible duplicate, found without any similarity threshold at all.
    """
    out: dict[str, list[Path]] = {}
    for note in notes:
        for entry in note.segments:
            paths = out.setdefault(entry.id, [])
            if entry.source not in paths:
                paths.append(entry.source)
    return out
