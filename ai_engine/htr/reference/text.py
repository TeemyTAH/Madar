"""Script-aware text handling: normalization, right-to-left ordering, display cleanup.

Right-to-left (Arabic) lines are mirrored horizontally before the CNN, so the model
reads them in logical (reading) order. Digits and Latin words inside Arabic text are
written left-to-right, so after mirroring they come out reversed; `swap_ltr_runs`
reverses those runs. It is its own inverse, so the same function maps logical labels
to training targets and model output back to logical text.
"""

from __future__ import annotations

import re
import unicodedata

SCRIPTS = ("latin", "arabic", "mixed")

_ARABIC_DIACRITICS = re.compile("[\u064B-\u0652\u0670]")  # tanween, harakat, shadda, sukun, dagger alef
_LTR_CHAR = "0-9A-Za-z\u0660-\u0669\u06F0-\u06F9"  # ASCII + Arabic-Indic + Persian digits
_LTR_RUN = re.compile(f"%?[{_LTR_CHAR}]+(?:[.,:/][{_LTR_CHAR}]+)*%?")  # optional % on either side keeps this an involution
_SPACES = re.compile(r"\s+")
_SPACE_BEFORE_PUNCT = re.compile(r" ([,.;:!?)\]]|n't|'s|'re|'ll|'ve|'d|'m)(?=\s|$|[,.;:!?])")
_SPACE_AFTER_OPEN = re.compile(r"([(\[]) ")


# ------------------------------------------------------------ mixed script (visual order)
# The joint Latin+Arabic model reads every line left to right as it appears on the page
# (no mirroring), so its targets are in *visual* order. These helpers convert between
# logical (reading) order and visual order for lines mixing Arabic and Latin text, a
# small subset of the Unicode bidi algorithm: the paragraph direction is the majority
# script, and runs of the other direction keep their own internal order.

_LATIN = "0-9A-Za-z\u00C0-\u00D6\u00D8-\u00F6\u00F8-\u024F\u0660-\u0669\u06F0-\u06F9"
_ARABIC = "\u0621-\u063A\u0640-\u064A\u0671-\u06D3"  # letters + tatweel (no digits)
_NEUTRAL = " .,;:!?()\"'/&#*+=_-"
_ATTACHED = re.escape(".,;:!?()\"'/&#*+=_-") + "\u060C\u061B\u061F"  # punctuation glued to a word (no space)
_LTR_TOKEN = f"[%°€]?[{_LATIN}]+(?:[.,:/'’-][{_LATIN}]+)*[%°€]?"
# A run keeps the punctuation glued to its first/last word: in handwriting "شمشم،" or "Bonjour," is
# written as one unit, so the comma stays on the word's side, whatever the paragraph direction.
_JOIN = re.escape(_NEUTRAL) + "\u060C\u061B\u061F"  # what may sit between two words of one run
# The joiner set must be the same for both run types and both directions, or runs found in a
# mirrored string differ from the original and the conversion stops being reversible.
_LTR_PHRASE = re.compile(f"[{_ATTACHED}]*{_LTR_TOKEN}(?:[{_JOIN}]*\\s[{_JOIN}]*{_LTR_TOKEN})*[{_ATTACHED}]*")
_RTL_PHRASE = re.compile(f"[{_ATTACHED}]*[{_ARABIC}]+(?:[{_JOIN}]*[{_ARABIC}]+)*[{_ATTACHED}]*")
_ARABIC_LETTER = re.compile(f"[{_ARABIC}]")
_LATIN_LETTER = re.compile("[A-Za-z\u00C0-\u00D6\u00D8-\u00F6\u00F8-\u024F]")


def base_is_rtl(text: str) -> bool:
    """Paragraph direction: right-to-left when Arabic letters are at least as many as Latin ones."""
    n_ar = len(_ARABIC_LETTER.findall(text))
    return n_ar > 0 and n_ar >= len(_LATIN_LETTER.findall(text))


def to_visual(text: str) -> str:
    """Logical order -> left-to-right visual order. Its own inverse is from_visual."""
    if base_is_rtl(text):
        return _LTR_PHRASE.sub(lambda m: m.group(0)[::-1], text)[::-1]
    return _RTL_PHRASE.sub(lambda m: m.group(0)[::-1], text)


def visual_permutation(text: str) -> list[int]:
    """Indices into `text` in visual left-to-right order: to_visual(text) == "".join(text[i] for i in perm).

    Same steps as to_visual, applied to positions, so callers that lay out pieces of a
    line (the synthetic line generator) place them exactly where the target says."""
    idx = list(range(len(text)))
    if base_is_rtl(text):
        for m in _LTR_PHRASE.finditer(text):
            idx[m.start(): m.end()] = idx[m.start(): m.end()][::-1]
        return idx[::-1]
    for m in _RTL_PHRASE.finditer(text):
        idx[m.start(): m.end()] = idx[m.start(): m.end()][::-1]
    return idx


def from_visual(text: str) -> str:
    """Left-to-right visual order -> logical order."""
    if base_is_rtl(text):
        return _LTR_PHRASE.sub(lambda m: m.group(0)[::-1], text[::-1])
    return _RTL_PHRASE.sub(lambda m: m.group(0)[::-1], text)


def is_rtl(script: str) -> bool:
    return script == "arabic"


def normalize(text: str, script: str) -> str:
    """Label normalization applied to training targets and references."""
    text = unicodedata.normalize("NFC", text)
    if script in ("arabic", "mixed"):
        text = _ARABIC_DIACRITICS.sub("", text)  # too rare in KHATT to learn (<10 occurrences each)
    return _SPACES.sub(" ", text).strip()


def swap_ltr_runs(text: str) -> str:
    return _LTR_RUN.sub(lambda m: m.group(0)[::-1], text)


def to_target(text: str, script: str) -> str:
    """Logical text -> the order the model emits it in."""
    if script == "mixed":
        return to_visual(text)
    return swap_ltr_runs(text) if is_rtl(script) else text


def from_output(text: str, script: str) -> str:
    """Model output -> logical text."""
    if script == "mixed":
        return from_visual(text)
    return swap_ltr_runs(text) if is_rtl(script) else text


def detokenize(text: str) -> str:
    """Undo IAM-style spaced punctuation for display: 'great , let me' -> 'great, let me',
    'I \\'m' -> "I'm", 'to " prop up " an' -> 'to "prop up" an'."""
    text = _SPACE_AFTER_OPEN.sub(r"\1", _SPACE_BEFORE_PUNCT.sub(r"\1", text))
    parts = text.split(' " ')
    if len(parts) > 1:  # pair straight double quotes: open, close, open, ...
        out = parts[0]
        for i, part in enumerate(parts[1:]):
            out += (' "' if i % 2 == 0 else '" ') + part
        text = out
    return text
