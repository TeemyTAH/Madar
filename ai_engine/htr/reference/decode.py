"""CTC decoding: greedy, prefix beam search, and beam search constrained to a pattern.

Constrained decoding is what makes short form fields reliable: a "date" field can only
produce strings that are (prefixes of) dates, an "amount" field only amounts, and so on.
The confidence of a constrained result is measured against the *unconstrained* search,
so if the model clearly wrote something that is not a valid date, the forced date gets a
low confidence and is flagged for review instead of being silently "fixed".
"""

from __future__ import annotations

import math
from collections import defaultdict
from functools import lru_cache
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np

from .charset import Charset

NEG_INF = -1e30


class Constraint(Protocol):
    def viable(self, text: str) -> bool: ...  # can `text` still grow into a valid value?

    def complete(self, text: str) -> bool: ...  # is `text` a valid value?


@dataclass
class Decoded:
    text: str
    confidence: float  # estimated posterior of `text` given the image, in [0, 1]
    valid: bool  # satisfies the constraint (always True without one)
    # Hypotheses found by the search with their posterior share, best first. Lets callers
    # measure confidence in a *value* ("11 / 05 / 2003" and "11/05/2003" are the same date).
    alternatives: list[tuple[str, float]] = field(default_factory=list)


def log_softmax(x: np.ndarray) -> np.ndarray:
    x = x - x.max(-1, keepdims=True)
    return x - np.log(np.exp(x).sum(-1, keepdims=True))


def _lse(a: float, b: float) -> float:
    if a < b:
        a, b = b, a
    if b <= NEG_INF:
        return a
    return a + math.log1p(math.exp(b - a))


def greedy(logits: np.ndarray, charset: Charset) -> Decoded:
    lp = log_softmax(logits)
    ids = lp.argmax(-1)
    # Confidence proxy for greedy: probability of the best path's weakest emitted frame.
    emitted = [lp[t, i] for t, i in enumerate(ids) if i != 0 and (t == 0 or ids[t - 1] != i)]
    conf = float(np.exp(min(emitted))) if emitted else float(np.exp(lp[:, 0].min()))
    return Decoded(charset.decode_greedy(ids), conf, True)


def _prefix_beam(lp: np.ndarray, beam: int, prune: float, viable, lm_step=None,
                 lm_end=None) -> list[tuple[tuple[int, ...], float, float]]:
    """CTC prefix beam search -> [(prefix, ranking score, image-only score)]. With
    lm_step(prefix, c) (shallow fusion), each prefix also carries a language-model score that
    is added for ranking; lm_end(prefix) is added once at the end (end-of-text probability).
    Without a language model both scores are the same."""
    beams: dict[tuple[int, ...], list[float]] = {(): [0.0, NEG_INF]}  # prefix -> [p_blank, p_nonblank]
    lmsc: dict[tuple[int, ...], float] = {(): 0.0}
    log_prune = math.log(prune)
    for t in range(lp.shape[0]):
        row = lp[t]
        cand = [int(c) for c in np.nonzero(row > log_prune)[0] if c != 0]
        nxt: dict[tuple[int, ...], list[float]] = defaultdict(lambda: [NEG_INF, NEG_INF])
        for prefix, (pb, pnb) in beams.items():
            total = _lse(pb, pnb)
            entry = nxt[prefix]
            entry[0] = _lse(entry[0], total + row[0])
            last = prefix[-1] if prefix else None
            for c in cand:
                p = float(row[c])
                new = prefix + (c,)
                if c == last:
                    entry[1] = _lse(entry[1], pnb + p)  # repeat collapses into the same prefix
                    if viable(new):
                        e = nxt[new]
                        e[1] = _lse(e[1], pb + p)  # repeat separated by a blank extends it
                elif viable(new):
                    e = nxt[new]
                    e[1] = _lse(e[1], total + p)
                if lm_step is not None and new in nxt and new not in lmsc:
                    lmsc[new] = lmsc[prefix] + lm_step(prefix, c)
        ranked = sorted(nxt.items(), key=lambda kv: -(_lse(*kv[1]) + lmsc.get(kv[0], 0.0)))[:beam]
        beams = dict(ranked)
    out = []
    for p, v in beams.items():
        ac = _lse(*v)
        out.append((p, ac + lmsc.get(p, 0.0) + (lm_end(p) if lm_step is not None else 0.0), ac))
    return out


def _posteriors(entries: dict) -> dict:
    """{prefix: image-only log score} -> {prefix: share of the total}."""
    norm = -math.inf
    for s in entries.values():
        norm = _lse(norm, s) if norm > -math.inf else s
    return {p: math.exp(s - norm) for p, s in entries.items()}


def beam_search(logits: np.ndarray, charset: Charset, beam: int = 16, constraint: Constraint | None = None,
                prune: float = 1e-3, lm=None) -> Decoded:
    """CTC prefix beam search over (T, C) logits, optionally restricted by `constraint` and
    guided by a language model (`lm`: htr.lm.LMScorer).

    The language model only helps CHOOSE the text. Confidence and the alternatives' shares are
    measured on the image alone (CTC posterior over the hypotheses found), so a reading that
    the language model prefers but the image does not support gets low confidence and is
    flagged for review, and thresholds calibrated without an LM keep their meaning."""
    lp = log_softmax(logits.astype(np.float64))

    def text(prefix):
        return "".join(charset.chars[i - 1] for i in prefix)

    lm_step = lm_end = None
    if lm is not None:
        n = lm.lm.order - 1
        chars = charset.chars

        @lru_cache(maxsize=1 << 16)
        def _step(context, c):  # keyed on the last n characters only
            return lm.alpha * lm.lm.logp("".join(chars[i - 1] for i in context), chars[c - 1]) + lm.beta

        def lm_step(prefix, c):
            return _step(prefix[-n:] if n else (), c)

        def lm_end(prefix):
            return lm.alpha * lm.lm.logp("".join(chars[i - 1] for i in prefix[-n:]), "\x03")

    free = _prefix_beam(lp, beam, prune, lambda p: True, lm_step, lm_end)
    if constraint is None:
        best = max(free, key=lambda x: x[1])[0]
        post = _posteriors({p: ac for p, _, ac in free})
        alts = sorted(((text(p), post[p]) for p, _, _ in free), key=lambda x: -x[1])
        return Decoded(text(best), float(post[best]), True, alts)

    cache: dict[tuple[int, ...], bool] = {}

    def viable(prefix):
        if prefix not in cache:
            cache[prefix] = constraint.viable(text(prefix))
        return cache[prefix]

    finals = _prefix_beam(lp, beam, prune, viable, lm_step, lm_end)
    complete = [e for e in finals if constraint.complete(text(e[0]))]
    pool = complete or finals
    best = max(pool, key=lambda x: x[1])[0]
    # Posterior relative to everything the model found plausible, constrained or not. Take the
    # union of both searches so a hypothesis found by both (the usual case) is counted once.
    union = {p: ac for p, _, ac in free}
    union.update({p: ac for p, _, ac in finals})
    post = _posteriors(union)
    alts = sorted(((text(p), q) for p, q in post.items()), key=lambda x: -x[1])
    return Decoded(text(best), float(post[best]), bool(complete), alts)
