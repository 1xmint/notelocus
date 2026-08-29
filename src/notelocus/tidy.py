"""Moving loose notes on a desktop into topic folders.

The scope rule is the whole design, so it is enforced rather than documented:
**this reads exactly one directory and never descends into any of them.**

`corpus.find_notes` recurses, which is right for `index` and `find` because they
only read. Sharing one walker between a read command and a move command is how a
scope bug becomes a data-loss bug, so this has its own, and its own cannot
recurse - there is no depth parameter to pass wrong.

What that means on a real desktop: folders are invisible, repositories are
invisible, and so is everything that is not a note file sitting loose at the top
level. Someone who dumps `.txt` files on their desktop gets those filed and
nothing else touched.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from .manifest import MANIFEST_DIR, Move
from .topics import Profile, Topic, group, profiles

#: Extensions treated as notes.
NOTE_SUFFIXES = frozenset({".txt", ".md", ".markdown", ".text"})

#: Where a note goes when it resembles nothing else. A folder of one is a worse
#: outcome than an honest pile, and this name says which it is.
UNSORTED = "unsorted"

#: Beyond this a file is not a note, it is an export or a log.
MAX_NOTE_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class Plan:
    """What a run would do, before it does any of it."""

    root: Path
    destination: Path
    moves: tuple[Move, ...]
    topics: tuple[Topic, ...]
    #: Notes that are already filed where they belong.
    settled: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.moves


def loose_notes(root: Path) -> list[Path]:
    """Note files sitting directly in `root`.

    No recursion, by construction. `iterdir` rather than `walk`, and directories
    are filtered out rather than descended.
    """
    if not root.is_dir():
        return []
    found = [
        entry
        for entry in root.iterdir()
        if entry.is_file() and entry.suffix.lower() in NOTE_SUFFIXES
    ]
    return sorted(found, key=lambda p: p.name)


def readable(path: Path) -> str | None:
    """The text of a note, or `None` if it is not usable as one."""
    try:
        size = path.stat().st_size
        if size == 0 or size > MAX_NOTE_BYTES:
            return None
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return text if text.strip() else None


def existing_topics(destination: Path) -> dict[str, list[Path]]:
    """Topic folders already under `destination`, and what is filed in them.

    Read so that a second run puts a new note into the folder it belongs in
    rather than inventing a near-duplicate beside it. Filing that reshuffles
    itself every run is worse than no filing.
    """
    if not destination.is_dir():
        return {}
    out: dict[str, list[Path]] = {}
    for entry in sorted(destination.iterdir()):
        if not entry.is_dir() or entry.name == MANIFEST_DIR or entry.name.startswith("."):
            continue
        out[entry.name] = [
            note
            for note in sorted(entry.iterdir())
            if note.is_file() and note.suffix.lower() in NOTE_SUFFIXES
        ]
    return out


def plan(root: Path, destination: Path) -> Plan:
    """Work out where every loose note should go, moving nothing."""
    notes = [path for path in loose_notes(root) if _is_outside(path, destination)]
    documents: dict[str, tuple[str, str]] = {}
    for path in notes:
        if (text := readable(path)) is not None:
            documents[path.name] = (path.name, text)

    anchors: dict[str, list[Profile]] = {}
    for name, filed in existing_topics(destination).items():
        already: dict[str, tuple[str, str]] = {}
        for note in filed:
            if (text := readable(note)) is not None:
                already[note.name] = (note.name, text)
        if already:
            anchors[name] = profiles(already)

    if not documents:
        return Plan(root=root, destination=destination, moves=(), topics=(), settled=())

    topics = group(profiles(documents), anchors=anchors)

    moves: list[Move] = []
    settled: list[str] = []
    for topic in topics:
        # A group of one goes to `unsorted` rather than getting a folder to
        # itself - unless it joined a topic that already exists, where being the
        # only new arrival says nothing about whether it belongs.
        alone = topic.is_singleton and topic.name not in anchors
        folder = destination / (UNSORTED if alone else topic.name)
        for key in topic.keys:
            source = root / key
            target = _free_name(folder / key, source)
            if target is None:
                settled.append(key)
                continue
            moves.append(Move(source=str(source), destination=str(target)))

    return Plan(
        root=root,
        destination=destination,
        moves=tuple(moves),
        topics=tuple(topics),
        settled=tuple(sorted(settled)),
    )


def apply(plan_: Plan) -> list[Move]:
    """Carry out a plan, and return what actually moved.

    A move is skipped rather than forced if the source has gone or the
    destination has appeared since the plan was made. The window is small and
    the cost of being wrong is somebody's note, so it is checked at the moment
    of the move rather than assumed from the moment of the plan.
    """
    done: list[Move] = []
    for move in plan_.moves:
        source, target = Path(move.source), Path(move.destination)
        if not source.is_file() or target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        source.rename(target)
        done.append(move)
    return done


def _is_outside(path: Path, destination: Path) -> bool:
    """Whether `path` is somewhere other than the destination tree.

    Guards the case where somebody points `tidy` at a folder that contains its
    own output, which would file the filing.
    """
    try:
        path.resolve().relative_to(destination.resolve())
    except ValueError:
        return True
    return False


def _digest(path: Path) -> str:
    return hashlib.blake2b(path.read_bytes(), digest_size=8).hexdigest()


def _free_name(target: Path, source: Path) -> Path | None:
    """A path to move `source` to, or `None` if it is already filed there.

    Three cases. Nothing there: use it. Something there with identical bytes:
    the note is already filed and moving it again would create a second copy, so
    return `None`. Something there with different bytes: pick a suffixed name,
    because two different notes that happen to share a filename are two notes.
    """
    if not target.exists():
        return target
    try:
        if target.is_file() and _digest(target) == _digest(source):
            return None
    except OSError:
        pass

    stem, suffix = target.stem, target.suffix
    for n in range(2, 100):
        candidate = target.with_name(f"{stem} ({n}){suffix}")
        if not candidate.exists():
            return candidate
        try:
            if candidate.is_file() and _digest(candidate) == _digest(source):
                return None
        except OSError:
            pass
    return None
