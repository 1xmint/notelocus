"""Split a note into the ideas it contains.

A note on this Desktop is rarely about one thing. It is usually a whole
conversation pasted into a `.txt`: a question, a long answer, an objection, a
revision. Treating the file as the unit means "find my notes on concept A"
returns a 1200-line transcript that mentions concept A once.

So the unit here is the *segment* — one addressable idea — and a file is a
sequence of them.

Splitting is deterministic. Three strategies, tried in order of how much
structure the document actually has, because guessing wrong is worse than
splitting coarsely: a segment that is too large is still findable, while a
segment split through the middle of an argument is misleading.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# A markdown heading, ATX style. Setext headings are not matched: they are rare
# in pasted model output and the underline is ambiguous with a horizontal rule.
HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")

# A speaker turn, as it appears when a conversation is copied out of a chat
# interface. Deliberately narrow: a line that is *only* a short label.
TURN = re.compile(
    r"^\s{0,3}(?:\*\*)?"
    r"(?P<who>You|User|Me|Assistant|Claude|ChatGPT|GPT|Grok|Gemini)"
    r"(?:\*\*)?\s*[:：]\s*$",
    re.IGNORECASE,
)

# A horizontal rule, which people paste as a divider between pasted answers.
RULE = re.compile(r"^\s{0,3}(?:-{3,}|\*{3,}|_{3,})\s*$")

# Below this, a "segment" is a fragment rather than an idea, and merging it into
# its neighbour loses nothing.
MIN_SEGMENT_CHARS = 200


@dataclass(frozen=True)
class Segment:
    """One addressable idea, and where it came from."""

    title: str
    body: str
    #: 1-based line number of the segment's first line in the source document.
    start_line: int
    #: How the split was made, so a reader can judge how much to trust it.
    strategy: str
    heading_level: int | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)
    #: Who said this, when the note is a pasted conversation. Kept rather than
    #: discarded because in a vault of model output the useful question is
    #: usually "what did *I* think", and the speaker label is the only thing
    #: that answers it.
    speaker: str | None = None

    @property
    def text(self) -> str:
        """The segment as it would be read.

        A heading is prepended because it was lifted out of the body. A derived
        title is not: it was taken *from* the body and is still in there, so
        including it would count the same words twice - which matters, because
        this length is what decides whether a segment is a fragment.
        """
        if self.heading_level is None:
            return self.body.strip()
        return f"{self.title}\n\n{self.body}".strip()


def split(document: str) -> list[Segment]:
    """Split a document into segments, deterministically.

    The same input always produces the same output: no clock, no randomness, no
    model. That is what makes the index rebuildable and diffable, which is the
    property that makes it safe to regenerate over a folder you care about.
    """
    lines = document.splitlines()
    if not lines:
        return []

    for strategy, boundaries in (
        ("heading", _heading_boundaries(lines)),
        ("turn", _turn_boundaries(lines)),
        ("rule", _rule_boundaries(lines)),
    ):
        # One boundary means the strategy found nothing to split on: the whole
        # document is a single span, which is what the paragraph fallback is for.
        if len(boundaries) > 1:
            # A heading, a speaker label and a divider are boundaries the author
            # typed. A short segment under one of those is a short idea, not a
            # fragment, and folding it into its neighbour would throw away the
            # structure the author bothered to write.
            return _build(lines, boundaries, strategy)

    return _merge_fragments(_build(lines, _paragraph_boundaries(lines), "paragraph"))


def _heading_boundaries(lines: list[str]) -> list[int]:
    """Indexes where a markdown heading starts a new segment."""
    inside_code = False
    out = [0]
    for i, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            inside_code = not inside_code
            continue
        # A `#` inside a fenced block is code or a shell comment, not a heading.
        if not inside_code and HEADING.match(line) and i != 0:
            out.append(i)
    return out


def _turn_boundaries(lines: list[str]) -> list[int]:
    out = [0]
    for i, line in enumerate(lines):
        if TURN.match(line) and i != 0:
            out.append(i)
    return out


def _rule_boundaries(lines: list[str]) -> list[int]:
    out = [0]
    for i, line in enumerate(lines):
        if RULE.match(line) and i != 0:
            out.append(i)
    return out


def _paragraph_boundaries(lines: list[str]) -> list[int]:
    """Every run of blank lines starts a new segment.

    The coarsest strategy, and the one that applies to an unstructured wall of
    text. It over-splits, which `_merge_fragments` then corrects.
    """
    out = [0]
    blank = False
    for i, line in enumerate(lines):
        if not line.strip():
            blank = True
            continue
        if blank and i != 0:
            out.append(i)
        blank = False
    return out


def _build(lines: list[str], boundaries: list[int], strategy: str) -> list[Segment]:
    segments: list[Segment] = []
    for n, start in enumerate(boundaries):
        end = boundaries[n + 1] if n + 1 < len(boundaries) else len(lines)
        span = lines[start:end]
        if not any(line.strip() for line in span):
            continue
        title, level, speaker, body_lines = _title_of(span)
        segments.append(
            Segment(
                title=title,
                body="\n".join(body_lines).strip(),
                start_line=start + 1,
                strategy=strategy,
                heading_level=level,
                tags=extract_tags("\n".join(span)),
                speaker=speaker,
            )
        )
    return segments


def _title_of(span: list[str]) -> tuple[str, int | None, str | None, list[str]]:
    """A title for the span, and the body with the title line removed.

    A heading is used verbatim. Otherwise the first sentence stands in, because
    an untitled idea is unfindable and a truncated first sentence is a better
    handle than a filename plus a line number.
    """
    speaker: str | None = None
    for i, line in enumerate(span):
        if not line.strip():
            continue
        if match := HEADING.match(line):
            return match.group(2).strip(), len(match.group(1)), speaker, span[i + 1 :]
        # Only the *first* label in the leading run is this segment's speaker.
        # A second one means the first turn was empty, so it is content rather
        # than a boundary - and consuming it too would keep only the last of
        # them and silently drop the rest.
        if speaker is None and (turn := TURN.match(line)):
            speaker = turn.group("who").lower()
            continue
        if RULE.match(line):
            continue
        # No heading: the title is *derived from* the body rather than taken out
        # of it. Returning `span[i + 1:]` here would drop this line from the body
        # entirely, and for a single-line paragraph that line is the whole
        # segment - truncated to a 120-character title and silently lost.
        return _first_sentence(line), None, speaker, span[i:]
    # Every line was a label, a divider or blank - a truncated paste, most often
    # a trailing `Assistant:` with nothing after it. The body is empty rather
    # than the whole span: a speaker label already captured above would
    # otherwise appear twice, and a divider carries no words at all.
    return "(untitled)", None, speaker, []


def _first_sentence(line: str) -> str:
    text = line.strip().lstrip("#*->_ ").strip()
    # Cut at a sentence end if there is one early enough to be a title rather
    # than a paragraph.
    if match := re.search(r"(?<=[.!?])\s", text[:160]):
        text = text[: match.start()]
    return (text[:117] + "...") if len(text) > 120 else text or "(untitled)"


def _merge_fragments(segments: list[Segment]) -> list[Segment]:
    """Fold anything too short to be an idea into the segment before it.

    Only ever applied to paragraph splitting, where the boundaries are inferred
    from blank lines rather than written by the author. That strategy
    over-splits: a wall of prose becomes one segment per paragraph, most of
    which are not ideas on their own.

    Merging backwards keeps a fragment attached to the idea it belongs to rather
    than discarding it, because a stray line in a note is sometimes the whole
    point of the note.
    """
    merged: list[Segment] = []
    for segment in segments:
        if merged and len(segment.text) < MIN_SEGMENT_CHARS:
            previous = merged[-1]
            merged[-1] = Segment(
                title=previous.title,
                body=f"{previous.body}\n\n{segment.text}".strip(),
                start_line=previous.start_line,
                strategy=previous.strategy,
                heading_level=previous.heading_level,
                tags=tuple(dict.fromkeys(previous.tags + segment.tags)),
                speaker=previous.speaker or segment.speaker,
            )
            continue
        merged.append(segment)
    return merged


TAG = re.compile(r"(?:^|\s)#(?P<tag>[a-z][a-z0-9_-]{2,30})\b", re.IGNORECASE)


def extract_tags(text: str) -> tuple[str, ...]:
    """Hashtags, lowercased and de-duplicated, order preserved.

    A markdown heading is `#` followed by a space; a tag is `#` followed
    immediately by a letter. That one character is the whole distinction, which
    is why headings are matched with `\\s+` and tags without.
    """
    found = (match.group("tag").lower() for match in TAG.finditer(text))
    return tuple(dict.fromkeys(found))
