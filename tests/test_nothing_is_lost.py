"""The one invariant this tool cannot be allowed to break.

Everything else here is a convenience. This is the promise: run notelocus over a
folder of notes and no word of them disappears. It is stated over *arbitrary*
input rather than over examples, because the notes it will actually meet are
pasted from everywhere and look like nothing anyone would think to write down as
a test case.

There is no property-testing dependency: the generator below is deliberate and
seeded, so a failure names the exact document that caused it and reruns
identically. A random test that cannot be replayed is a flaky test.
"""

import random
import unicodedata

from notelocus.identity import normalise
from notelocus.segment import split

#: Fragments that resemble what actually lands in a `.txt` on a desktop.
PIECES = [
    "# A heading",
    "## A smaller heading",
    "You:",
    "Assistant:",
    "---",
    "",
    "   ",
    "a short line",
    "a considerably longer line that carries an actual thought about something",
    "```",
    "code_like(thing)",
    "#tagged content here",
    "1. a numbered point",
    "- a bullet",
    "Some prose. With sentences. And punctuation!",
    "ｕｎｉｃｏｄｅ ｗｉｄｔｈ",
    "trailing whitespace   ",
    "\ta tab indent",
    "an em — dash and a 'quote' and a \"double\"",
]


def documents(count: int = 250, seed: int = 20260820):
    """Deterministically generated documents that look like real notes."""
    rng = random.Random(seed)
    for _ in range(count):
        length = rng.randint(1, 40)
        yield "\n".join(rng.choice(PIECES) for _ in range(length))


def words_of(text: str) -> list[str]:
    return normalise(text).split()


def test_no_word_of_any_document_is_lost_by_splitting():
    """A speaker label counts as kept: it moves to `Segment.speaker` rather than
    remaining in the body. This test is what found it was being dropped."""
    for document in documents():
        before = sorted(words_of(document))
        after = sorted(
            word
            for segment in split(document)
            for word in words_of(segment.text) + words_of(segment.speaker or "")
        )
        assert before == after, f"words changed for:\n{document!r}"


def test_a_speaker_label_is_captured_rather_than_discarded():
    segments = split("You:\nmy own thinking here\n\nAssistant:\nthe reply to it\n")
    assert [s.speaker for s in segments] == ["you", "assistant"]


def test_splitting_is_deterministic_over_arbitrary_documents():
    for document in documents():
        first = [(s.title, s.body, s.start_line, s.strategy) for s in split(document)]
        second = [(s.title, s.body, s.start_line, s.strategy) for s in split(document)]
        assert first == second, f"unstable for:\n{document!r}"


def test_splitting_never_raises_on_arbitrary_input():
    """The corpus reader treats an unreadable note as skippable. It cannot treat
    an *exception* that way without hiding a real bug, so splitting is total."""
    for document in documents():
        split(document)
    for pathological in ("", "\n", "\x00", "#", "#" * 1000, "\n" * 500, "```" * 100):
        split(pathological)


def test_every_segment_reports_a_line_that_exists():
    for document in documents():
        line_count = len(document.splitlines())
        for segment in split(document):
            assert 1 <= segment.start_line <= max(line_count, 1), (
                f"line {segment.start_line} outside 1..{line_count} for:\n{document!r}"
            )


def test_segments_are_in_document_order():
    for document in documents():
        starts = [s.start_line for s in split(document)]
        assert starts == sorted(starts), f"out of order for:\n{document!r}"


def test_normalisation_never_invents_characters():
    """NFKC can expand a character into several; it must never produce something
    that was not implied by the input."""
    for document in documents():
        assert normalise(document) == normalise(unicodedata.normalize("NFKC", document))
