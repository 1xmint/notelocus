"""The `notelocus` command.

    notelocus tidy                            file loose desktop notes by topic
    notelocus undo                            put the last tidy back
    notelocus shortcut                        put a one-click launcher on the desktop
    notelocus index <notes-dir> --out <dir>   build a corpus to ask questions of
    notelocus find  <notes-dir> <query>       search without writing anything

`index` and `find` never write outside `--out`. `tidy` moves files, which is the
point of it, and is reversible: every run records what it did and `undo` reads
that back. Nothing in this program deletes anything.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import manifest
from . import tidy as tidy_
from .corpus import Note, entries_of, read_corpus, sources_by_id
from .identity import find_duplicates, normalise
from .render import (
    relative,
    render_duplicates,
    render_folder_index,
    render_index,
    render_segment,
)

#: Default similarity above which two segments are reported as near-duplicates.
#: High on purpose. A false positive here costs a person's attention on a pair
#: that turns out to be different, which is the expensive mistake; a false
#: negative just leaves a duplicate un-flagged, which is where they already are.
DEFAULT_THRESHOLD = 0.8

#: Where tidied notes go, relative to the folder being tidied. One folder on the
#: desktop rather than somewhere in Documents: a clean desktop is the point, and
#: notes filed somewhere you have to go looking for are notes you stop using.
NOTES_FOLDER = "Notes"


def desktop() -> Path:
    """The desktop, which is the only folder `tidy` ever reads.

    `USERPROFILE\\Desktop` is right on an ordinary Windows install and wrong
    when OneDrive has redirected it, so that is checked too. Neither is a guess
    the user cannot override - `tidy --from` exists for the rest.
    """
    home = Path.home()
    redirected = home / "OneDrive" / "Desktop"
    if redirected.is_dir() and not (home / "Desktop").is_dir():
        return redirected
    return home / "Desktop"


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

    tidy = sub.add_parser("tidy", help="file loose desktop notes into topic folders")
    tidy.add_argument(
        "--from",
        dest="source",
        type=Path,
        default=None,
        help="folder to tidy. The desktop by default, and only its top level - "
        "folders and repositories inside it are never touched.",
    )
    tidy.add_argument(
        "--into",
        type=Path,
        default=None,
        help=f"where topic folders go (default: <folder>/{NOTES_FOLDER})",
    )
    tidy.add_argument(
        "--dry-run",
        action="store_true",
        help="say what would move and change nothing",
    )

    undo = sub.add_parser("undo", help="put the last tidy back")
    undo.add_argument("--into", type=Path, default=None, help="the folder that was tidied into")

    shortcut = sub.add_parser("shortcut", help="put a one-click launcher on the desktop")
    shortcut.add_argument("--into", type=Path, default=None, help="where to write it")

    find = sub.add_parser("find", help="search notes without writing anything")
    find.add_argument("notes", type=Path, help="folder to read notes from")
    find.add_argument("query", nargs="+", help="words to look for")
    find.add_argument("--limit", type=int, default=20, help="how many matches to show")
    find.add_argument(
        "--max-depth", type=int, default=None, help="how many folders deep to descend"
    )
    find.add_argument(
        "--speaker",
        help="only ideas attributed to this speaker, e.g. `you` for your own words "
        "rather than a model's answer",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "tidy":
        return _tidy(args.source or desktop(), args.into, args.dry_run)
    if args.command == "undo":
        return _undo(args.into or (desktop() / NOTES_FOLDER))
    if args.command == "shortcut":
        return _shortcut(args.into or desktop())

    notes_dir: Path = args.notes
    if not notes_dir.is_dir():
        print(f"notelocus: {notes_dir} is not a directory", file=sys.stderr)
        return 2

    if args.command == "index":
        return _index(notes_dir, args.out, args.threshold, args.segments, args.max_depth)
    return _find(notes_dir, args.query, args.limit, args.max_depth, args.speaker)


def _tidy(source: Path, into: Path | None, dry_run: bool) -> int:
    if not source.is_dir():
        print(f"notelocus: {source} is not a directory", file=sys.stderr)
        return 2

    destination = into or (source / NOTES_FOLDER)
    plan = tidy_.plan(source, destination)

    if plan.is_empty:
        settled = f", {len(plan.settled)} already filed" if plan.settled else ""
        print(f"nothing loose to file in {source}{settled}")
        return 0

    by_folder: dict[str, list[str]] = {}
    for move in plan.moves:
        by_folder.setdefault(Path(move.destination).parent.name, []).append(Path(move.source).name)

    verb = "would move" if dry_run else "moved"
    for folder in sorted(by_folder):
        print(f"{folder}/")
        for name in sorted(by_folder[folder]):
            print(f"    {name}")
    print()

    if dry_run:
        print(f"{verb} {len(plan.moves)} notes into {len(by_folder)} folders under {destination}")
        print("nothing was changed. Run `notelocus tidy` to do it.")
        return 0

    done = tidy_.apply(plan)
    record = manifest.record(destination, source, done)
    _write(
        destination / "INDEX.md",
        render_folder_index(tidy_.existing_topics(destination), destination),
    )

    print(f"{verb} {len(done)} notes into {len(by_folder)} folders under {destination}")
    print(f"index    {destination / 'INDEX.md'}")
    print(f"record   {record.name}")
    print()
    print("Nothing was deleted. `notelocus undo` puts it all back.")
    return 0


def _undo(destination: Path) -> int:
    run = manifest.latest(destination)
    if run is None:
        print(f"notelocus: no tidy on record under {destination}", file=sys.stderr)
        return 1

    restored = manifest.undo(run)
    print(f"put back {len(restored.moved_back)} notes")
    if restored.missing:
        print(f"{len(restored.missing)} were no longer where they were filed:")
        for move in restored.missing:
            print(f"    {Path(move.destination).name}")
    if restored.blocked:
        print(f"{len(restored.blocked)} could not be restored, something is already there:")
        for move in restored.blocked:
            print(f"    {Path(move.source).name}")
    return 0 if restored.complete else 1


#: The launcher.
#:
#: Tries the console script first and falls back to the module. Both need the
#: package installed, but which one is reachable depends on how `pip` put things
#: on PATH, and a shortcut that fails silently on a double-click is worse than
#: no shortcut. `py` rather than `python` in the fallback: the Windows launcher
#: is present on installs where the bare name is not.
#:
#: `pause` at the end because this is opened by double-clicking, and a console
#: window that closes before anything can be read tells you nothing.
LAUNCHER = """@echo off
rem Generated by `notelocus shortcut`. Double-click to file loose desktop notes.
where notelocus >nul 2>&1
if %errorlevel%==0 (
  notelocus tidy
) else (
  py -m notelocus.cli tidy
)
echo.
pause
"""


def _shortcut(where: Path) -> int:
    path = where / "Tidy Notes.cmd"
    path.write_text(LAUNCHER, encoding="utf-8", newline="\r\n")
    print(f"wrote {path}")
    print()
    print("Double-click it to file whatever is loose on the desktop.")
    print("It is a .cmd, so `tidy` ignores it - only note files are ever moved.")
    return 0


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


def _find(
    notes_dir: Path,
    query: list[str],
    limit: int,
    max_depth: int | None = None,
    speaker: str | None = None,
) -> int:
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
    wanted = speaker.lower() if speaker else None
    for entry in entries_of(notes):
        # In a vault of pasted conversations the useful question is usually
        # "what did *I* think", not "what did the model say".
        if wanted and entry.segment.speaker != wanted:
            continue
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
