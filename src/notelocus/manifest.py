"""A record of what a run moved, and how to put it back.

v0.1 was non-destructive by construction: no code path wrote outside `--out`, so
there was nothing to undo. `tidy` moves files, so that guarantee is gone and has
to be replaced by something built rather than something implied.

This is that thing. Every run writes exactly what it did, and `undo` reads it
back. It is the reason clicking a shortcut with no confirmation prompt is a
reasonable design: the cost of a wrong grouping is one command, not an evening
spent finding notes.

Nothing here deletes. `undo` moves files back to where they came from; it does
not remove the folders it emptied, because an empty folder is harmless and a
folder deleted by mistake is not.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

#: Where manifests live. Inside the destination folder, dot-prefixed so the
#: corpus walker skips it and so it does not clutter what a person opens.
MANIFEST_DIR = ".notelocus"


@dataclass(frozen=True)
class Move:
    """One file, from where it was to where it went."""

    source: str
    destination: str


@dataclass(frozen=True)
class Run:
    """Everything one `tidy` did."""

    at: str
    root: str
    moves: tuple[Move, ...]

    def to_json(self) -> str:
        return json.dumps(
            {
                "at": self.at,
                "root": self.root,
                "moves": [{"source": m.source, "destination": m.destination} for m in self.moves],
            },
            indent=2,
            ensure_ascii=False,
        )

    @staticmethod
    def from_json(text: str) -> Run:
        data = json.loads(text)
        return Run(
            at=data["at"],
            root=data["root"],
            moves=tuple(
                Move(source=m["source"], destination=m["destination"]) for m in data["moves"]
            ),
        )


def record(destination_root: Path, root: Path, moves: list[Move]) -> Path:
    """Write a manifest for a run and return its path.

    Timestamped rather than overwritten. A second `tidy` after a first must not
    destroy the record that would undo the first, or a two-run mistake becomes
    unrecoverable at exactly the moment somebody needs it most.
    """
    folder = destination_root / MANIFEST_DIR
    folder.mkdir(parents=True, exist_ok=True)
    at = datetime.now(tz=UTC)
    path = folder / f"manifest-{at.strftime('%Y%m%dT%H%M%SZ')}.json"
    run = Run(at=at.isoformat(), root=str(root), moves=tuple(moves))
    path.write_text(run.to_json(), encoding="utf-8", newline="\n")
    return path


def manifests(destination_root: Path) -> list[Path]:
    """Every manifest, oldest first.

    Sorted by filename, which is an ISO timestamp, so lexical order is
    chronological order.
    """
    folder = destination_root / MANIFEST_DIR
    if not folder.is_dir():
        return []
    return sorted(folder.glob("manifest-*.json"))


def latest(destination_root: Path) -> Run | None:
    """The most recent run, or `None` if nothing has been recorded."""
    found = manifests(destination_root)
    if not found:
        return None
    return Run.from_json(found[-1].read_text(encoding="utf-8"))


@dataclass(frozen=True)
class Restored:
    """What an undo managed, and what it could not."""

    moved_back: tuple[Move, ...]
    missing: tuple[Move, ...]
    blocked: tuple[Move, ...]

    @property
    def complete(self) -> bool:
        return not self.missing and not self.blocked


def undo(run: Run) -> Restored:
    """Move everything in `run` back where it came from.

    Three outcomes per move, and the difference matters:

    - **moved back** - the file was where the manifest said and its origin was
      free.
    - **missing** - the file is not at its destination any more. Somebody moved
      or renamed it since the run, and guessing which file they meant would be
      worse than saying so.
    - **blocked** - something already occupies the original path. Overwriting it
      would destroy whatever that is, which is precisely the thing this module
      exists to prevent.

    Nothing is deleted and nothing is overwritten in any of the three cases.
    """
    moved_back: list[Move] = []
    missing: list[Move] = []
    blocked: list[Move] = []

    for move in run.moves:
        destination, source = Path(move.destination), Path(move.source)
        if not destination.exists():
            missing.append(move)
            continue
        if source.exists():
            blocked.append(move)
            continue
        source.parent.mkdir(parents=True, exist_ok=True)
        destination.rename(source)
        moved_back.append(move)

    return Restored(moved_back=tuple(moved_back), missing=tuple(missing), blocked=tuple(blocked))
