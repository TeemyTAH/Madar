"""Page-level steps for phone photos: find the sheet of paper, then find text lines with a
learned text detector before cutting them out.

1. find_paper: the sheet is the large bright, low-saturation region. Its outline gives a
   quadrilateral that is warped flat (perspective), and anything outside it (desk, folders,
   other pages) is painted white. Scans that are all paper are left alone.
2. TextDetector: PP-OCRv4 mobile text detector (DBNet, Apache-2.0, 4.6 MB ONNX, from
   PaddleOCR via RapidOCR). It outputs a per-pixel "this is text" probability. Trained on
   printed and scene text, it still marks handwriting well, and it does NOT mark drawings,
   arrows, table rules or the page edge, which is what the projection segmenter trips on.
3. segment_lines_db: text regions are grouped into lines (side-by-side regions that overlap
   vertically), and each ink component is assigned to the line region that covers most of
   it; ink outside every region (diagrams, specks, background) is dropped. The cut-out and
   straightening are shared with htr.segment.

segment_page() runs the whole thing and returns lines in the ORIGINAL photo's coordinates.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .segment import (Line, _components_from_ink, _extract, _member_mask, _reading_order, _refine_angle,
                      _text_height, normalize_background, segment_lines)

DEFAULT_DET = Path(__file__).resolve().parents[1] / "models" / "ppocr_det_v4.onnx"


# ------------------------------------------------------------------ 1. paper

def _order_corners(pts: np.ndarray) -> np.ndarray:
    """(4, 2) -> top-left, top-right, bottom-right, bottom-left."""
    s, d = pts.sum(1), np.diff(pts, axis=1).ravel()
    return np.float32([pts[s.argmin()], pts[d.argmin()], pts[s.argmax()], pts[d.argmax()]])


def find_paper(page: np.ndarray, work: int = 640, min_area: float = 0.15, min_background: float = 0.03,
               max_sat: int = 70) -> tuple[np.ndarray, np.ndarray] | None:
    """Return (flattened page, 3x3 homography photo -> flattened) or None when the image
    already is the page (scan, tight crop) or no sheet stands out from the background."""
    bgr = page if page.ndim == 3 else cv2.cvtColor(page, cv2.COLOR_GRAY2BGR)
    h, w = bgr.shape[:2]
    s = min(1.0, work / max(h, w))
    small = cv2.resize(bgr, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else bgr
    hsv = cv2.cvtColor(cv2.GaussianBlur(small, (5, 5), 0), cv2.COLOR_BGR2HSV)
    val, sat = hsv[..., 2], hsv[..., 1]
    thr, _ = cv2.threshold(val, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    # Low saturation is the main cue; the brightness floor is low because photos shade the
    # sheet (here the far end of a page reads 40% darker than the near end).
    mask = ((val > 0.6 * thr) & (sat < max_sat)).astype(np.uint8)
    k = max(5, int(0.03 * max(small.shape[:2])) | 1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))  # fill ink
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))  # cut bridges
    # Background = non-paper regions touching the photo's edge (desk, folder, hands). Ink,
    # logos and coloured print sit inside the sheet, so a scan or tight crop has (almost) none.
    n_bg, bg_lab, bg_stats, _ = cv2.connectedComponentsWithStats(1 - mask, connectivity=4)
    sh, sw = mask.shape
    edge = [i for i in range(1, n_bg) if bg_stats[i, 0] == 0 or bg_stats[i, 1] == 0
            or bg_stats[i, 0] + bg_stats[i, 2] == sw or bg_stats[i, 1] + bg_stats[i, 3] == sh]
    if bg_stats[edge, cv2.CC_STAT_AREA].sum() < min_background * sh * sw:
        return None
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    cnt = max(contours, key=cv2.contourArea)
    if cv2.contourArea(cnt) < min_area * sh * sw:
        return None
    hull = cv2.convexHull(cnt)
    quad = None
    peri = cv2.arcLength(hull, True)
    tol = 0.01 * peri
    for eps in (0.01, 0.02, 0.03, 0.05, 0.08):
        approx = cv2.approxPolyDP(hull, eps * peri, True)
        if len(approx) == 4:
            cand = approx.reshape(4, 2).astype(np.float32)
            # A 4-gon that cuts off part of the sheet (e.g. a sheet running off the photo
            # edge has 5+ corners) would lose text: it must contain every hull point.
            if all(cv2.pointPolygonTest(cand, (float(x), float(y)), True) >= -tol for x, y in hull.reshape(-1, 2)):
                quad = cand
            break
    if quad is None:
        quad = cv2.boxPoints(cv2.minAreaRect(hull)).astype(np.float32)  # always contains the sheet
    quad = _order_corners(quad / s)
    tl, tr, br, bl = quad
    out_w = int(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl)))
    out_h = int(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr)))
    if out_w < 100 or out_h < 100:
        return None
    dst = np.float32([[0, 0], [out_w - 1, 0], [out_w - 1, out_h - 1], [0, out_h - 1]])
    hmat = cv2.getPerspectiveTransform(quad, dst)
    flat = cv2.warpPerspective(page, hmat, (out_w, out_h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    # Paint what is outside the sheet white (folder, desk, page underneath).
    sheet = cv2.resize(cv2.drawContours(np.zeros(mask.shape, np.uint8), [hull], -1, 255, -1), (w, h),
                       interpolation=cv2.INTER_NEAREST)
    sheet = cv2.warpPerspective(sheet, hmat, (out_w, out_h), flags=cv2.INTER_NEAREST)
    flat[sheet == 0] = 255
    return flat, hmat


# ------------------------------------------------------------------ 2. text detector

class TextDetector:
    """PP-OCRv4 DBNet text detector: image -> text probability map."""

    def __init__(self, path: str | Path = DEFAULT_DET, threads: int = 1):
        try:
            import onnxruntime as ort
        except ImportError as exc:
            raise RuntimeError("onnxruntime is required for PP-OCRv4 text detection") from exc
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = threads
        opts.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(path), opts, providers=["CPUExecutionProvider"])
        self.input = self.session.get_inputs()[0].name

    def prob_map(self, page: np.ndarray, side: int = 1280) -> np.ndarray:
        """Text probability at the input resolution (float32 in [0, 1])."""
        bgr = page if page.ndim == 3 else cv2.cvtColor(page, cv2.COLOR_GRAY2BGR)
        h, w = bgr.shape[:2]
        s = min(1.0, side / max(h, w))
        nh, nw = max(32, int(round(h * s / 32)) * 32), max(32, int(round(w * s / 32)) * 32)
        x = cv2.resize(bgr, (nw, nh), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
        # RapidOCR's (x - 0.5) / 0.5; measured better here than ImageNet mean/std (IAM pages
        # 51-110: 82% vs 75% exact line count, page CER 16.4% vs 17.8%).
        x = ((x.astype(np.float32) / 255.0 - 0.5) / 0.5).transpose(2, 0, 1)[None]
        prob = self.session.run(None, {self.input: x})[0][0, 0]
        return cv2.resize(prob, (w, h), interpolation=cv2.INTER_LINEAR)


_DETECTOR: TextDetector | None = None


def default_detector() -> TextDetector:
    global _DETECTOR
    if _DETECTOR is None:
        _DETECTOR = TextDetector()
    return _DETECTOR


# ------------------------------------------------------------------ 3. ruled lines (forms, tables)

def _shift_any(mask: np.ndarray, d: int, axis: int, sign: int) -> np.ndarray:
    """True where `mask` has a pixel 1..d steps away along axis (sign -1: before, +1: after)."""
    out = np.zeros_like(mask)
    n = mask.shape[axis]
    for k in range(1, d + 1):
        if k >= n:
            break
        if axis == 0:
            if sign < 0:
                out[k:] |= mask[:-k]
            else:
                out[:-k] |= mask[k:]
        else:
            if sign < 0:
                out[:, k:] |= mask[:, :-k]
            else:
                out[:, :-k] |= mask[:, k:]
    return out


@dataclass
class Rules:
    removed: np.ndarray  # bool: rule pixels taken out of the ink (crossing strokes kept)
    h_boxes: list[tuple[int, int, int, int]]  # horizontal rules (underlines, table rows): x0, y0, x1, y1
    v_boxes: list[tuple[int, int, int, int]]  # vertical rules (table columns)


def find_rules(ink: np.ndarray, min_len: float = 0.05, cross: int = 5, text_h: float = 0.0) -> Rules:
    """Long straight strokes in a binary ink image (bool): printed underlines, table and box
    borders. A horizontal (vertical) opening with a kernel 5% of the page width (height), and at
    least 2.5 word heights (`text_h`), keeps only straight runs that long, which handwriting
    does not have (the tall straight strokes of l, d, h reach about two word heights). Shorter
    vertical runs (from 1.5 word heights) count only when both ends meet a horizontal rule: the
    sides of a box or a table cell. Where a handwritten stroke
    crosses a rule (ink within `cross` px on both sides), the rule pixels are kept, so the
    letter is not cut in two."""
    h, w = ink.shape
    u8 = ink.astype(np.uint8)
    lh = max(40, int(min_len * w), int(3.0 * text_h))  # > a handwritten T crossbar (~2.3)
    lv = max(40, int(min_len * h), int(2.5 * text_h))
    # Horizontal: pieces from 5% of the width, then collinear pieces joined (faint printed
    # lines break up when thresholded), and only joined rules of at least lh kept.
    piece = max(40, int(min_len * w))
    hc = cv2.morphologyEx(u8, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (piece, 1)))
    n_h, lab_h, st_h, _ = cv2.connectedComponentsWithStats(hc, connectivity=8)
    # Printed rules are thin; a straight handwritten stroke is as thick as the pen (or thicker).
    max_thick = max(5.0, 0.1 * text_h)
    pieces = [(int(x), int(y), int(x + cw), int(y + ch)) if ch <= max_thick else (0, 0, 0, 0)
              for x, y, cw, ch, _ in st_h[1:]]
    joined = _merge_collinear([q for q in pieces if q[2] > q[0]], 0, 0.02 * w)
    ok = np.zeros(n_h, bool)
    for j in joined:
        if j[2] - j[0] < lh:
            continue
        inside = [k for k, (x0, y0, x1, y1) in enumerate(pieces, start=1)
                  if x1 > x0 and j[0] <= x0 and x1 <= j[2] and j[1] <= y0 and y1 <= j[3]]
        # A broken printed line is mostly there; handwriting strokes that happen to line up are not.
        if sum(pieces[k - 1][2] - pieces[k - 1][0] for k in inside) >= 0.6 * (j[2] - j[0]):
            ok[inside] = True
    hr = ok[lab_h].astype(np.uint8)
    vr = cv2.morphologyEx(u8, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, lv)))
    ls = max(20, int(1.5 * text_h))
    if ls < lv and hr.any():
        short = cv2.morphologyEx(u8, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, ls)))
        near_h = cv2.dilate(hr, np.ones((9, 9), np.uint8)) > 0
        n_s, lab_s, st_s, _ = cv2.connectedComponentsWithStats(short, connectivity=8)
        for i in range(1, n_s):
            x, y, cw, ch, _ = st_s[i]
            cx = x + cw // 2
            if near_h[y, cx] and near_h[y + ch - 1, cx]:
                vr[lab_s == i] = 1
        lv = ls  # for the box list below
    hr = (cv2.dilate(hr, np.ones((3, 1), np.uint8)) > 0) & ink  # anti-aliased edges of the rule
    vr = (cv2.dilate(vr, np.ones((1, 3), np.uint8)) > 0) & ink
    rules = hr | vr
    rest = ink & ~rules
    keep = (hr & _shift_any(rest, cross, 0, -1) & _shift_any(rest, cross, 0, 1)) | \
           (vr & _shift_any(rest, cross, 1, -1) & _shift_any(rest, cross, 1, 1))

    def boxes(m, along):
        n, _, st, _ = cv2.connectedComponentsWithStats(m.astype(np.uint8), connectivity=8)
        return [(int(x), int(y), int(x + cw), int(y + ch)) for x, y, cw, ch, _ in st[1:]
                if along == 0 or ch >= lv]

    return Rules(rules & ~keep, _merge_collinear(boxes(hr > 0, 0), 0, 0.03 * w),
                 _merge_collinear(boxes(vr, 1), 1, 0.03 * h))


def _merge_collinear(bs: list, along: int, max_gap: float) -> list:
    """Join pieces of one rule broken where strokes cross it or the print is faint: a broken
    line would otherwise fake field boundaries at each break."""
    out: list[list[int]] = []
    key = (lambda b: (b[1], b[0])) if along == 0 else (lambda b: (b[0], b[1]))
    for b in sorted(bs, key=key):
        for m in out:
            if along == 0:
                same = abs((b[1] + b[3]) / 2 - (m[1] + m[3]) / 2) <= 4 and b[0] - m[2] <= max_gap and m[0] - b[2] <= max_gap
            else:
                same = abs((b[0] + b[2]) / 2 - (m[0] + m[2]) / 2) <= 4 and b[1] - m[3] <= max_gap and m[1] - b[3] <= max_gap
            if same:
                m[0], m[1], m[2], m[3] = min(m[0], b[0]), min(m[1], b[1]), max(m[2], b[2]), max(m[3], b[3])
                break
        else:
            out.append(list(b))
    return [tuple(m) for m in out]


def _separated(a, b, rules: Rules | None) -> bool:
    """Is there a ruled-line boundary between side-by-side text regions a and b (x0, y0, x1, y1)?
    A vertical rule in the gap (table column), or an underline that starts or ends in the gap
    (one field's write-on line, a label before its value)."""
    if rules is None:
        return False
    if a[0] > b[0]:
        a, b = b, a
    gx0, gx1 = a[2], b[0]
    if gx1 <= gx0:
        return False
    hh = max(a[3] - a[1], b[3] - b[1], 1)
    tol = 0.5 * hh
    ylo, yhi = min(a[1], b[1]), max(a[3], b[3])
    for x0, y0, x1, y1 in rules.v_boxes:
        if gx0 - tol <= x0 and x1 <= gx1 + tol and y0 <= ylo + tol and y1 >= yhi - tol:
            return True
    for x0, y0, x1, y1 in rules.h_boxes:
        if not (min(a[3], b[3]) - tol <= y0 <= max(a[3], b[3]) + 1.2 * hh):
            continue  # not this text's underline
        # (the rule may start under a label's last character, or end under a value's last one)
        if gx0 - tol <= x1 <= gx1 + 3 * tol and x1 < b[2] - tol:
            return True  # a's line ends in the gap
        if gx0 - 3 * tol <= x0 <= gx1 + tol and x0 > a[0] + tol:
            return True  # b's line starts in the gap
    return False


def _cut_at_rules(text: np.ndarray, rules: Rules) -> np.ndarray:
    """Split detector regions that run across a field boundary: where an underline starts or
    ends inside a region lying just above it (a printed label before its write-on line), or a
    vertical rule crosses it. Only when at least two text heights lie on both sides of the cut,
    so a capital overhanging the start of its line is not chopped off."""
    n, lab, st, _ = cv2.connectedComponentsWithStats(text, connectivity=8)
    hs = st[1:, 3][st[1:, 4] >= 20]
    if not len(hs):
        return text
    mh = float(np.median(hs))
    out = text.copy()
    for r in range(1, n):
        x, y, w, h, area = st[r]
        if area < 20:
            continue
        cuts = [ex for x0, y0, x1, y1 in rules.h_boxes if y + h - 0.5 * mh <= y0 <= y + h + 1.2 * mh
                for ex in (x0, x1)]
        cuts += [(x0 + x1) // 2 for x0, y0, x1, y1 in rules.v_boxes if y0 <= y + h and y1 >= y]
        for cx in cuts:
            if x + 2 * mh <= cx <= x + w - 2 * mh:
                band = out[y:y + h, max(0, cx - 2):cx + 3]
                band[lab[y:y + h, max(0, cx - 2):cx + 3] == r] = 0
    return out


# ------------------------------------------------------------------ 4. lines from text regions

def _group_regions(boxes: np.ndarray, min_overlap: float = 0.5, near_gap: float = 8.0,
                   far_gap: float = 30.0, far_overlap: float = 0.6, max_ratio: float = 2.0,
                   rules: Rules | None = None) -> list[list[int]]:
    """Union side-by-side regions into lines. Heights are those of DBNet's shrunk text kernels.
    Two tiers: regions within near_gap heights merge when they overlap vertically by
    min_overlap of the smaller height; across wider gaps (generous word spacing) they merge only
    when closely aligned (far_overlap) and of similar height, so a side note next to a line
    (a margin comment, a field label) stays separate."""
    n = len(boxes)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    hs = boxes[:, 3] - boxes[:, 1]
    cands = []
    for i in range(n):
        for j in range(i + 1, n):
            lo, hi = min(hs[i], hs[j]), max(hs[i], hs[j])
            ov = (min(boxes[i, 3], boxes[j, 3]) - max(boxes[i, 1], boxes[j, 1])) / max(lo, 1)
            if ov < min_overlap:
                continue
            gap = (max(boxes[i, 0], boxes[j, 0]) - min(boxes[i, 2], boxes[j, 2])) / max(hi, 1)
            if gap < near_gap or (gap < far_gap and ov >= far_overlap and hi <= max_ratio * lo):
                cands.append((gap, i, j))
    # Closest pairs first, and the separator test between the two GROUPS' horizontal extents:
    # a label's colon (its own region) must not chain the label to the value after the rule.
    x0 = boxes[:, 0].astype(float).copy()
    x1 = boxes[:, 2].astype(float).copy()
    for _, i, j in sorted(cands):
        ri, rj = find(i), find(j)
        if ri == rj:
            continue
        a = (x0[ri], boxes[i, 1], x1[ri], boxes[i, 3])
        b = (x0[rj], boxes[j, 1], x1[rj], boxes[j, 3])
        if _separated(a, b, rules):
            continue
        parent[ri] = rj
        x0[rj], x1[rj] = min(x0[ri], x0[rj]), max(x1[ri], x1[rj])
    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def _is_long(mask: np.ndarray) -> bool:
    """Enough ink, and wide enough, for a per-line slope estimate."""
    ys, xs = np.nonzero(mask)
    return len(xs) >= 50 and np.ptp(xs) >= 3 * max(1, np.ptp(ys))


def segment_lines_db(page: np.ndarray, rtl: bool = False, max_side: int = 2000, min_area_frac: float = 2e-6,
                     margin: float = 0.12, det: TextDetector | None = None, det_side: int = 1280,
                     thresh: float = 0.3, box_thresh: float = 0.5, remove_rules: bool = True,
                     wipe_rules_for_detector: bool = False) -> list[Line]:
    gray = cv2.cvtColor(page, cv2.COLOR_BGR2GRAY) if page.ndim == 3 else page
    scale = min(1.0, max_side / max(gray.shape))
    if scale < 1:
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    work = cv2.resize(page, (gray.shape[1], gray.shape[0]), interpolation=cv2.INTER_AREA) if scale < 1 else page
    norm = normalize_background(gray)
    _, ink = cv2.threshold(norm, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    rules = None
    if remove_rules:
        # Underlines and table borders touch the handwriting: removed from the ink and whitened
        # in the line crops, then used as separators. NOT whitened in the detector's input: it
        # finds handwriting better with its writing lines in view (job sheet photo: value CER
        # 18.5% vs 28.1%).
        _, st0, _, k0 = _components_from_ink(ink, min_area_frac)
        # Word height, ignoring components taller than 10% of the page (a table grid, a box).
        k0 = [i for i in k0 if 6 <= st0[i, cv2.CC_STAT_HEIGHT] <= 0.1 * ink.shape[0]]
        rules = find_rules(ink > 0, text_h=_text_height(st0, k0) if k0 else 0.0)
        ink[rules.removed] = 0
        wipe = cv2.dilate(rules.removed.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
        wipe &= ink == 0
        norm = norm.copy()
        norm[wipe] = 255
        if wipe_rules_for_detector:
            work = work.copy()
            work[wipe] = 255
    # min_area_frac is 10x lower than the classic segmenters: faint pen strokes in photos break
    # into tiny fragments, and specks outside text regions are dropped below anyway.
    labels, stats, centroids, keep = _components_from_ink(ink, min_area_frac)
    if not keep:
        return []
    det = det or default_detector()
    prob = det.prob_map(work, det_side)
    text = (prob > thresh).astype(np.uint8)
    if rules is not None:
        text = _cut_at_rules(text, rules)
    n_reg, reg, rstats, _ = cv2.connectedComponentsWithStats(text, connectivity=8)
    regions = []
    for r in range(1, n_reg):
        x, y, cw, ch, area = rstats[r]
        if area < 20 or ch < 4:
            continue
        if prob[y:y + ch, x:x + cw][reg[y:y + ch, x:x + cw] == r].mean() < box_thresh:
            continue
        regions.append(r)
    if not regions:
        return []
    # DBNet predicts shrunk text kernels; grow them back (like PaddleOCR's unclip) so the
    # ascenders, descenders and diacritics of the line fall inside.
    boxes = np.array([[rstats[r, 0], rstats[r, 1], rstats[r, 0] + rstats[r, 2], rstats[r, 1] + rstats[r, 3]]
                      for r in regions], np.float64)
    groups = _group_regions(boxes, rules=rules)
    lut = np.zeros(n_reg, np.uint16)
    for li, g in enumerate(groups, start=1):
        lut[[regions[i] for i in g]] = li
    core = lut[reg]
    med_h = float(np.median(boxes[:, 3] - boxes[:, 1]))
    grow = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * int(0.4 * med_h) + 1,) * 2)
    grown = cv2.dilate(core, grow)  # one pass for all lines; where grown lines meet, the kernels win
    line_map = np.where(core > 0, core, grown).astype(np.int64)
    # Assign every ink component to the line region covering most of its pixels.
    n_lab, n_lines = int(labels.max()) + 1, len(groups) + 1
    sel = labels.ravel() > 0
    counts = np.bincount(labels.ravel()[sel].astype(np.int64) * n_lines + line_map.ravel()[sel],
                         minlength=n_lab * n_lines).reshape(n_lab, n_lines)
    members: dict[int, list[int]] = {}
    orphans = []
    for i in keep:
        c = counts[i, 1:]
        if c.max() > 0 and c.max() >= 0.3 * stats[i, cv2.CC_STAT_AREA]:
            members.setdefault(int(c.argmax()) + 1, []).append(i)
        else:
            orphans.append(i)
    # Tall first capitals and loops (F, N, M, D...) lie mostly outside the detector's text
    # kernels: attach a sizeable leftover component to the line it sits beside, if its centre
    # is within that line's band and it is at most one line height from the line's ends.
    line_box = {}
    for li, g in enumerate(groups, start=1):
        b = boxes[g]
        line_box[li] = (b[:, 0].min(), b[:, 1].min(), b[:, 2].max(), b[:, 3].max(), float(np.median(b[:, 3] - b[:, 1])))
    min_orphan = max(4.0, 0.5 * med_h * med_h)  # ignore specks and dots
    for i in orphans:
        x, y, cw, ch, area = stats[i]
        if area < min_orphan:
            continue
        cy = centroids[i][1]
        best, best_d = None, None
        for li, (x0, y0, x1, y1, hh) in line_box.items():
            band = 1.5 * hh
            if not (y0 - band <= cy <= y1 + band):
                continue
            if x + cw < x0 - 2 * hh or x > x1 + 2 * hh:
                continue
            d = abs(cy - (y0 + y1) / 2)
            if best is None or d < best_d:
                best, best_d = li, d
        if best is not None:
            members.setdefault(best, []).append(i)
    # Angles: per long line; short lines take the page's median angle.
    masks = {li: _member_mask(labels, stats, mem) for li, mem in members.items()}
    angles = {li: _refine_angle(mk[0], 0.0, 15.0) if _is_long(mk[0]) else None for li, mk in masks.items()}
    known = [a for a in angles.values() if a is not None]
    page_angle = float(np.median(known)) if known else 0.0
    lines = []
    for li, (mask, ox, oy) in masks.items():
        a = angles[li] if angles[li] is not None else page_angle
        line = _extract(norm, mask, a, margin, scale, (ox, oy))
        if line is not None and line.image.shape[1] >= 8:
            lines.append(line)
    return _reading_order(lines, rtl)


# ------------------------------------------------------------------ whole page

def segment_page(page: np.ndarray, method: str = "db", rtl: bool = False, paper: bool = True,
                 **kw) -> list[Line]:
    """Paper detection (optional) + line segmentation; polygons/boxes in the input's coordinates."""
    work, hmat = page, None
    if paper:
        found = find_paper(page)
        if found is not None:
            work, hmat = found
    lines = segment_lines_db(work, rtl=rtl, **kw) if method == "db" else segment_lines(work, method, rtl=rtl, **kw)
    if hmat is not None:
        inv = np.linalg.inv(hmat)
        for ln in lines:
            poly = cv2.perspectiveTransform(ln.polygon.reshape(-1, 1, 2).astype(np.float64), inv).reshape(-1, 2)
            ln.polygon = poly.astype(np.float32)
            x0, y0 = np.floor(poly.min(0)).astype(int)
            x1, y1 = np.ceil(poly.max(0)).astype(int)
            ln.box = (int(x0), int(y0), int(x1), int(y1))
    return lines
