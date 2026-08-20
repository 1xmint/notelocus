"""The `notelocus` command.

Two verbs in v0.1, both read-only with respect to the notes:

    notelocus index <notes-dir> --out <dir>   build the corpus
    notelocus find  <notes-dir> <query>       search it without building

Nothing in this version moves, renames or deletes a note. That is a property of
the code rather than a promise about flags: there is no call that writes outside
`--out`, so there is no `--apply` to get wrong at two in the morning.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .corpus import Note, entries_of, read_corpus, sources_by_id
from .identity import find_duplicates, normalise
from .render import relative, render_duplicates, render_index, render_segment

#: Default similarity above which two segments are reported as near-duplicates.
#: High on purpose. A false positive here costs a person's attention on a pair
#: that turns out to be different, which is the expensive mistake; a false
#: negative just leaves a duplicate un-flagged, which is where they already are.
DEFAULT_THRESHOLD = 0.8


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="notelocus",
        description="Converge scattered notes into the ideas they are about.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    index = sub.add_parser("index", help="build a corpus from a folder of notes")
    index.add_argument("notes", type=Path, help="folder to read notes from")
    index.add_argument(
        "--out",
        type=Path,
        required=True,
        help="folder to write the corpus into. Created if absent; never the notes folder.",
    )
    index.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help=f"near-duplicate similarity, 0.0 to 1.0 (default {DEFAULT_THRESHOLD})",
    )
    index.add_argument(
        "--max-depth",
        type=int,
        default=None,
        help="how many folders deep to descend. Unlimited by default; 2 is right for a "
        "desktop where notes sit at the top and projects sit below.",
    )
    index.add_argument(
        "--segments",
        action="store_true",
        help="also write one file per idea, for tools that read a directory of documents",
    )

    find = sub.add_parser("find", help="search notes without writing anything")
    find.add_argument("notes", type=Path, help="folder to read notes from")
    find.add_argument("query", nargs="+", help="words to look for")
    find.add_argument("--limit", type=int, default=20, help="how many matches to show")
    find.add_argument(
        "--max-depth", type=int, default=None, help="how many folders deep to descend"
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    notes_dir: Path = args.notes

    if not notes_dir.is_dir():
        print(f"notelocus: {notes_dir} is not a directory", file=sys.stderr)
        return 2

    if args.command == "index":
        return _index(notes_dir, args.out, args.threshold, args.segments, args.max_depth)
    return _find(notes_dir, args.query, args.limit, args.max_depth)


def _index(
    notes_dir: Path,
    out: Path,
    threshold: float,
    write_segments: bool,
    max_depth: int | None = None,
) -> int:
    # Writing the corpus inside the notes folder would make the next run index
    # its own output, which grows without bound and quietly corrupts the ids.
    if _is_within(out.resolve(), notes_dir.resolve()):
        print(
            f"notelocus: --out {out} is inside the notes folder; the next run would "
            "index its own output",
            file=sys.stderr,
        )
        return 2

    notes = read_corpus(notes_dir, max_depth=max_depth)
    if not notes:
        print(f"notelocus: no readable notes under {notes_dir}", file=sys.stderr)
        return 1

    entries = {entry.id: entry for entry in entries_of(notes)}
    duplicates = find_duplicates(
        {eid: entry.text for eid, entry in entries.items()}, threshold=threshold
    )

    out.mkdir(parents=True, exist_ok=True)
    _write(out / "INDEX.md", render_index(notes, notes_dir, duplicates))
    if duplicates:
        _write(out / "DUPLICATES.md", render_duplicates(duplicates, entries, notes_dir))

    if write_segments:
        sources = sources_by_id(notes)
        segments_dir = out / "ideas"
        segments_dir.mkdir(exist_ok=True)
        for eid, entry in sorted(entries.items()):
            also = [p for p in sources.get(eid, []) if p != entry.source]
            _write(segments_dir / f"{eid}.md", render_segment(entry, notes_dir, also))

    print(_summary(notes, entries, duplicates, out, notes_dir))
    return 0


def _summary(notes: list[Note], entries: dict, duplicates: list, out: Path, root: Path) -> str:
    repeated = sum(1 for paths in sources_by_id(notes).values() if len(paths) > 1)
    lines = [
        f"read    {len(notes)} files under {root}",
        f"ideas   {len(entries)} distinct",
    ]
    if repeated:
        lines.append(f"exact   {repeated} appear in more than one file")
    if duplicates:
        lines.append(f"near    {len(duplicates)} pairs above the threshold")
    lines.append(f"wrote   {out}")
    lines.append("")
    lines.append("Nothing was moved, renamed or deleted.")
    return "\n".join(lines)


def _find(notes_dir: Path, query: list[str], limit: int, max_depth: int | None = None) -> int:
    """Substring search over normalised text.

    Deliberately not clever. It is here so that the index is not the only way to
    get at a note, and so that `find` can be trusted to show everything that
    matches rather than what a ranking function thought was best.
    """
    terms = [normalise(term) for term in query if normalise(term)]
    if not terms:
        print("notelocus: nothing to search for", file=sys.stderr)
        return 2

    notes = read_corpus(notes_dir, max_depth=max_depth)
    hits = 0
    for entry in entries_of(notes):
        haystack = normalise(entry.text)
        if all(term in haystack for term in terms):
            hits += 1
            if hits <= limit:
                print(f"{entry.id}  {relative(entry.source, notes_dir)}")
                print(f"          {entry.title}")
    if hits > limit:
        print(f"... and {hits - limit} more")
    if not hits:
        print("no matches")
        return 1
    return 0


def _is_within(candidate: Path, parent: Path) -> bool:
    return candidate == parent or parent in candidate.parents


def _write(path: Path, text: str) -> None:
    # Newline is pinned so the output is identical on Windows and Linux; the
    # index is meant to be committed and a line-ending difference would make
    # every regeneration look like a total rewrite.
    path.write_text(text, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    raise SystemExit(main())
