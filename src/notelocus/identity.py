"""Stable identity for a segment, and finding the same idea twice.

Two properties matter here and they pull in opposite directions.

An id must be **stable**: reindexing a folder that has not changed must produce
the same ids, or every regeneration is an unreadable diff and no external
reference to a segment survives. So the id is a hash of normalised content, not
a counter, not a path, and not anything involving a clock.

Similarity must be **fuzzy**: the same idea pasted into two notes is rarely
byte-identical — a word changes, a heading is added, whitespace differs. So
near-duplicate detection uses shingles rather than equality.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass

#: Length of the hex id. Eight bytes is 16 hex characters, which is short enough
#: to read aloud and long enough that a collision across a personal corpus is
#: not a thing that happens.
ID_BYTES = 8

#: Words per shingle. Five is the usual choice for prose: short enough to
#: survive small edits, long enough that common phrases do not match everything.
SHINGLE = 5

_WHITESPACE = re.compile(r"\s+")
_PUNCTUATION = re.compile(r"[^\w\s]")


def normalise(text: str) -> str:
    """Reduce text to what it says, dropping how it was typed.

    Unicode is folded to NFKC first so that a smart quote and a straight quote
    are the same character before anything else looks at them — otherwise the
    same paragraph pasted from two applications gets two different ids.
    """
    text = unicodedata.normalize("NFKC", text).casefold()
    text = _PUNCTUATION.sub(" ", text)
    return _WHITESPACE.sub(" ", text).strip()


def content_id(text: str) -> str:
    """A stable id for this content.

    Derived from the normalised text, so reformatting a note does not renumber
    it, and unrelated notes never collide. Blake2b rather than SHA-256 only
    because it takes a digest size directly.
    """
    digest = hashlib.blake2b(normalise(text).encode("utf-8"), digest_size=ID_BYTES)
    return digest.hexdigest()


def shingles(text: str, size: int = SHINGLE) -> frozenset[str]:
    """Overlapping word n-grams of the normalised text.

    A document shorter than one shingle yields a single shingle of the whole
    thing, so short notes still compare against each other rather than silently
    matching nothing.
    """
    words = normalise(text).split()
    if not words:
        return frozenset()
    # Shrink the window for short texts. At five words a nine-word sentence has
    # five shingles and every one of them contains word five, so changing that
    # one word drops similarity to zero — which is wrong, and was wrong in the
    # first thing this function was ever asked. Long texts, which is what
    # duplicate detection actually runs on, are unaffected.
    size = min(size, max(2, len(words) // 3))
    if len(words) <= size:
        return frozenset([" ".join(words)])
    return frozenset(" ".join(words[i : i + size]) for i in range(len(words) - size + 1))


def similarity(left: str, right: str) -> float:
    """Jaccard similarity of two texts, between 0.0 and 1.0.

    Symmetric, and 1.0 only when the normalised shingle sets are identical —
    which is *not* the same as the texts being identical, since normalisation
    drops punctuation and case. That is the intended behaviour: two notes that
    differ only in typography are the same idea.
    """
    a, b = shingles(left), shingles(right)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


@dataclass(frozen=True)
class Duplicate:
    """Two segments that appear to say the same thing."""

    left: str
    right: str
    score: float


#: Above this many segments, candidates are narrowed by banding before pairs are
#: compared. Below it, every pair is compared and the answer is complete.
#:
#: The number is where the honest guarantee changes, so it is a constant rather
#: than a magic value: 2,000 segments is two million pairs, which takes a couple
#: of seconds. The first real run over a Desktop produced 38,860 segments and
#: 755 million pairs, and did not finish.
EXACT_LIMIT = 2000

#: Minhash signature length, and rows per band. `128 = 16 bands x 8 rows` puts
#: the point where a pair is more likely than not to become a candidate at
#: `(1/16) ** (1/8)`, about 0.71 - comfortably under the 0.8 default, so the
#: pairs that matter are found.
SIGNATURE = 128
BAND_ROWS = 8


def find_duplicates(texts: dict[str, str], threshold: float = 0.8) -> list[Duplicate]:
    """Pairs of segments above the similarity threshold.

    **Complete below `EXACT_LIMIT` segments, approximate above it.** Every
    reported pair has had its real Jaccard similarity computed either way; what
    changes is whether every pair was *considered*. Above the limit, candidates
    come from minhash banding, which can miss a pair whose similarity is near
    the threshold.

    Saying that plainly matters more than the speed does. The alternative on a
    large corpus is not a slower complete answer, it is no answer: the first run
    over a real Desktop had 755 million pairs to compare and never finished.

    Results are sorted by descending score, then by id, so the output is stable
    across runs and diffable.
    """
    prepared = {key: shingles(text) for key, text in texts.items() if text.strip()}
    keys = sorted(prepared)

    if len(keys) <= EXACT_LIMIT:
        candidates = ((keys[i], right) for i in range(len(keys)) for right in keys[i + 1 :])
    else:
        candidates = _banded_candidates(prepared, keys)

    found: list[Duplicate] = []
    for left, right in candidates:
        a, b = prepared[left], prepared[right]
        if not a or not b:
            continue
        score = len(a & b) / len(a | b)
        if score >= threshold:
            found.append(Duplicate(left=left, right=right, score=round(score, 4)))
    found.sort(key=lambda d: (-d.score, d.left, d.right))
    return found


def _minhash(items: frozenset[str], length: int = SIGNATURE) -> tuple[int, ...]:
    """A minhash signature, derived only from the content.

    No random permutations and no seed: the i-th hash is blake2b of the shingle
    salted with `i`. Two runs, two machines and two Python versions therefore
    produce the same signature, which keeps duplicate detection reproducible -
    the same property `content_id` exists for.
    """
    signature = []
    for i in range(length):
        salt = str(i).encode("utf-8")
        signature.append(
            min(
                int.from_bytes(
                    hashlib.blake2b(item.encode("utf-8"), digest_size=8, salt=salt[:16]).digest(),
                    "big",
                )
                for item in items
            )
        )
    return tuple(signature)


def _banded_candidates(
    prepared: dict[str, frozenset[str]], keys: list[str]
) -> list[tuple[str, str]]:
    """Pairs sharing a band of their minhash signature.

    Two documents that agree on all eight rows of any one band are very likely
    similar; two that agree on none are very likely not. That is the whole
    trick, and it turns a quadratic sweep into a bucket lookup.
    """
    signatures = {key: _minhash(prepared[key]) for key in keys if prepared[key]}
    buckets: dict[tuple[int, tuple[int, ...]], list[str]] = {}
    for key, signature in signatures.items():
        for band in range(SIGNATURE // BAND_ROWS):
            rows = signature[band * BAND_ROWS : (band + 1) * BAND_ROWS]
            buckets.setdefault((band, rows), []).append(key)

    pairs: set[tuple[str, str]] = set()
    for members in buckets.values():
        if len(members) < 2:
            continue
        members.sort()
        for i, left in enumerate(members):
            for right in members[i + 1 :]:
                pairs.add((left, right))
    return sorted(pairs)
