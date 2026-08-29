"""What `tidy` is allowed to touch, and what it must put back.

This module moves files on somebody's desktop. The negative tests are the
product: what it must *not* reach matters more than what it files correctly.
"""

from pathlib import Path

from notelocus.manifest import Move, Run, latest, record, undo
from notelocus.tidy import UNSORTED, apply, existing_topics, loose_notes, plan


def write(path: Path, text: str = "some note content worth keeping") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# --- scope, which is the whole point ------------------------------------------


def test_only_notes_at_the_top_level_are_seen(tmp_path: Path):
    write(tmp_path / "loose.txt")
    write(tmp_path / "also.md")
    write(tmp_path / "folder" / "buried.txt")
    write(tmp_path / "folder" / "deeper" / "deeper.md")
    assert [p.name for p in loose_notes(tmp_path)] == ["also.md", "loose.txt"]


def test_a_repository_on_the_desktop_is_never_descended_into(tmp_path: Path):
    """Not because `.git` is filtered - because nothing is descended into."""
    write(tmp_path / "notes.txt")
    write(tmp_path / "project" / ".git" / "config", "[core]")
    write(tmp_path / "project" / "README.md", "# a project readme")
    assert [p.name for p in loose_notes(tmp_path)] == ["notes.txt"]


def test_files_that_are_not_notes_are_invisible(tmp_path: Path):
    write(tmp_path / "keep.txt")
    write(tmp_path / "photo.png", "not really a png")
    write(tmp_path / "script.py", "print('hi')")
    write(tmp_path / "shortcut.cmd", "@echo off")
    assert [p.name for p in loose_notes(tmp_path)] == ["keep.txt"]


def test_the_destination_is_never_filed_into_itself(tmp_path: Path):
    write(tmp_path / "note.txt")
    destination = tmp_path / "Notes"
    write(destination / "already" / "filed.txt")
    moved = {Path(m.source).name for m in plan(tmp_path, destination).moves}
    assert moved == {"note.txt"}


# --- filing --------------------------------------------------------------------


def test_related_notes_land_in_one_folder(tmp_path: Path):
    body = "cortex scheduling and the execution plan for the cortex worker pool "
    write(tmp_path / "cortex plan.txt", body * 20)
    write(tmp_path / "cortex notes.txt", body * 20)
    result = plan(tmp_path, tmp_path / "Notes")
    folders = {Path(m.destination).parent.name for m in result.moves}
    assert len(folders) == 1
    assert UNSORTED not in folders


def test_a_note_resembling_nothing_goes_to_unsorted(tmp_path: Path):
    write(tmp_path / "hoisin sauce.txt", "plum sauce fermented soybean garlic vinegar " * 20)
    write(tmp_path / "quantum decoherence.txt", "wavefunction collapse einselection " * 20)
    result = plan(tmp_path, tmp_path / "Notes")
    assert all(Path(m.destination).parent.name == UNSORTED for m in result.moves)


def test_a_second_run_joins_the_folder_the_first_one_made(tmp_path: Path):
    """Filing that reshuffles itself every run is worse than no filing."""
    body = "cortex scheduling execution plan worker pool migration counter "
    destination = tmp_path / "Notes"
    write(destination / "cortex" / "cortex plan.txt", body * 20)
    write(tmp_path / "cortex followup.txt", body * 20)
    result = plan(tmp_path, destination)
    assert [Path(m.destination).parent.name for m in result.moves] == ["cortex"]


def test_nothing_to_do_is_reported_rather_than_failing(tmp_path: Path):
    assert plan(tmp_path, tmp_path / "Notes").is_empty


# --- moving, and not overwriting ----------------------------------------------


def test_applying_a_plan_moves_the_files(tmp_path: Path):
    write(tmp_path / "one.txt", "alpha beta gamma " * 30)
    destination = tmp_path / "Notes"
    done = apply(plan(tmp_path, destination))
    assert len(done) == 1
    assert not (tmp_path / "one.txt").exists()
    assert Path(done[0].destination).is_file()


def test_an_identical_note_already_filed_is_not_copied_again(tmp_path: Path):
    text = "the same note content exactly " * 30
    destination = tmp_path / "Notes"
    write(destination / UNSORTED / "note.txt", text)
    write(tmp_path / "note.txt", text)
    result = plan(tmp_path, destination)
    assert result.is_empty
    assert "note.txt" in result.settled


def test_a_different_note_with_the_same_name_is_not_overwritten(tmp_path: Path):
    destination = tmp_path / "Notes"
    write(destination / UNSORTED / "note.txt", "the original, which must survive " * 20)
    write(tmp_path / "note.txt", "a completely different note " * 20)
    apply(plan(tmp_path, destination))
    assert (
        (destination / UNSORTED / "note.txt").read_text(encoding="utf-8").startswith("the original")
    )
    assert any(p.name.startswith("note (") for p in (destination / UNSORTED).iterdir())


def test_running_twice_moves_nothing_the_second_time(tmp_path: Path):
    write(tmp_path / "one.txt", "alpha beta gamma " * 30)
    write(tmp_path / "two.txt", "delta epsilon zeta " * 30)
    destination = tmp_path / "Notes"
    apply(plan(tmp_path, destination))
    assert plan(tmp_path, destination).is_empty


# --- undo ----------------------------------------------------------------------


def test_undo_puts_every_file_back_exactly(tmp_path: Path):
    contents = {"one.txt": "alpha beta " * 30, "two.txt": "gamma delta " * 30}
    for name, text in contents.items():
        write(tmp_path / name, text)
    destination = tmp_path / "Notes"

    done = apply(plan(tmp_path, destination))
    record(destination, tmp_path, done)
    assert not (tmp_path / "one.txt").exists()

    restored = undo(latest(destination))
    assert restored.complete
    for name, text in contents.items():
        assert (tmp_path / name).read_text(encoding="utf-8") == text


def test_undo_refuses_to_overwrite_something_that_appeared_since(tmp_path: Path):
    write(tmp_path / "one.txt", "the note that was filed " * 30)
    destination = tmp_path / "Notes"
    done = apply(plan(tmp_path, destination))
    record(destination, tmp_path, done)

    write(tmp_path / "one.txt", "something new with the same name")
    restored = undo(latest(destination))
    assert not restored.complete
    assert restored.blocked
    assert (tmp_path / "one.txt").read_text(encoding="utf-8") == "something new with the same name"


def test_undo_reports_a_file_that_is_no_longer_where_it_was_put(tmp_path: Path):
    write(tmp_path / "one.txt", "a note " * 40)
    destination = tmp_path / "Notes"
    done = apply(plan(tmp_path, destination))
    record(destination, tmp_path, done)

    Path(done[0].destination).unlink()
    restored = undo(latest(destination))
    assert restored.missing and not restored.moved_back


def test_a_second_run_does_not_destroy_the_first_ones_manifest(tmp_path: Path):
    destination = tmp_path / "Notes"
    first = record(destination, tmp_path, [Move(source="a", destination="b")])
    second = record(destination, tmp_path, [Move(source="c", destination="d")])
    assert first.exists() and second.exists()


def test_a_manifest_round_trips(tmp_path: Path):
    run = Run(at="2026-08-20T00:00:00+00:00", root="r", moves=(Move("a", "b"),))
    assert Run.from_json(run.to_json()) == run


def test_existing_topics_ignores_its_own_bookkeeping(tmp_path: Path):
    destination = tmp_path / "Notes"
    write(destination / "cortex" / "a.txt")
    write(destination / ".notelocus" / "manifest-x.json", "{}")
    assert list(existing_topics(destination)) == ["cortex"]
