"""Character set and CTC greedy decoding. Index 0 is the CTC blank."""

from __future__ import annotations

from collections.abc import Iterable, Sequence


class Charset:
    def __init__(self, chars: str):
        if len(set(chars)) != len(chars):
            raise ValueError("charset contains duplicate characters")
        self.chars = chars
        self._index = {c: i + 1 for i, c in enumerate(chars)}

    @classmethod
    def from_texts(cls, texts: Iterable[str]) -> Charset:
        return cls("".join(sorted(set("".join(texts)))))

    @property
    def num_classes(self) -> int:
        return len(self.chars) + 1  # + blank

    def encode(self, text: str) -> list[int]:
        return [self._index[c] for c in text if c in self._index]

    def decode_greedy(self, ids: Sequence[int]) -> str:
        """Collapse repeats, then drop blanks."""
        out = []
        prev = 0
        for i in ids:
            i = int(i)
            if i != prev and i != 0:
                out.append(self.chars[i - 1])
            prev = i
        return "".join(out)
