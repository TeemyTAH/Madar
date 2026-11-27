"""Classical (non-neural) line segmentation for photos and scans of handwritten pages.

Two methods share the same preprocessing (lighting normalization, Otsu binarization,
speck and page-edge removal):

``blobs`` (default)
    Smears the ink with an elongated Gaussian at several orientations (-45..45 deg) and
    keeps the strongest response per pixel. Each text line becomes one blob that can be
    slanted or wavy, short lines are not lost, and separate columns stay separate. Every
    stroke (connected component) is assigned to the blob it overlaps, or to the nearest
    one (dots, diacritics). Each line is then straightened by its own angle.

``projection``
    The original method: global deskew, then peaks of the horizontal ink profile. It is
    fast, but it merges short lines into their neighbours, and only handles one dominant
    orientation and a single column.

Both cost tens of milliseconds per page on CPU. Lines come back in reading order:
columns left-to-right (or right-to-left when ``rtl``), top-to-bottom within a column.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class Line:
    image: np.ndarray  # uint8 grayscale crop, straightened, dark ink on white
    box: tuple[int, int, int, int]  # x0, y0, x1, y1 in original page coordinates
    polygon: np.ndarray  # (4, 2) float32 corners in original page coordinates
    angle: float  # baseline angle in degrees (positive = rising to the right)


# ------------------------------------------------------------------ shared steps


def normalize_background(gray: np.ndarray, scale: int = 4) -> np.ndarray:
    """Divide out paper colour and lighting. The background varies smoothly, so it is
    estimated at 1/scale resolution (about 10x cheaper than full resolution)."""
    h, w = gray.shape
    small = cv2.resize(gray, (max(1, w // scale), max(1, h // scale)), interpolation=cv2.INTER_AREA)
    k = max(5, (min(small.shape) // 15) | 1)
    bg = cv2.morphologyEx(small, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    bg = cv2.GaussianBlur(bg, (0, 0), k / 4)
    bg = cv2.resize(bg, (w, h), interpolation=cv2.INTER_LINEAR)
    return cv2.divide(gray, bg, scale=255)


def _components(norm: np.ndarray, min_area_frac: float):
    """Binarize and return connected components, minus specks and page-edge artifacts."""
    _, ink = cv2.threshold(norm, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    return _components_from_ink(ink, min_area_frac)


def _components_from_ink(ink: np.ndarray, min_area_frac: float):
    """Connected components of a binary ink image (uint8, nonzero = ink), filtered."""
    n, labels, stats, centroids = cv2.connectedComponentsWithStats(ink, connectivity=8)
    h, w = ink.shape
    min_area = max(4, int(min_area_frac * h * w))
    keep = []
    for i in range(1, n):
        x, y, cw, ch, area = stats[i]
        if area < min_area:
            continue
        touches_border = x == 0 or y == 0 or x + cw == w or y + ch == h
        if touches_border and (cw > 0.3 * w or ch > 0.3 * h):
            continue  # paper edge, table, shadow
        if cw > 25 * ch or ch > 25 * cw:
            continue  # ruled lines, margins
        keep.append(i)
    return labels, stats, centroids, keep


def _text_height(stats: np.ndarray, keep: list[int]) -> float:
    """Height of the component holding the median ink pixel: robust to dots and diacritics."""
    hs = stats[keep, cv2.CC_STAT_HEIGHT].astype(np.float64)
    areas = stats[keep, cv2.CC_STAT_AREA].astype(np.float64)
    order = np.argsort(hs)
    cum = np.cumsum(areas[order])
    return float(hs[order][np.searchsorted(cum, cum[-1] / 2)])


def _line_pitch(mask: np.ndarray, h: float) -> float:
    """Typical distance between text lines: first autocorrelation peak of the (globally
    deskewed) horizontal ink profile. Falls back to 2.5 text heights."""
    angle = estimate_skew(mask)
    hh, ww = mask.shape
    rot = cv2.warpAffine(mask.astype(np.uint8), cv2.getRotationMatrix2D((ww / 2, hh / 2), angle, 1.0), (ww, hh),
                         flags=cv2.INTER_NEAREST)
    prof = rot.sum(1).astype(np.float64)
    prof -= prof.mean()
    ac = np.correlate(prof, prof, "full")[len(prof) - 1:]
    if ac[0] <= 0:
        return 2.5 * h
    ac /= ac[0]
    lo, hi = int(0.8 * h), min(len(ac) - 1, int(8 * h))
    if hi <= lo + 2:
        return 2.5 * h
    seg = ac[lo:hi]
    peaks = [i for i in range(1, len(seg) - 1) if seg[i] >= seg[i - 1] and seg[i] >= seg[i + 1] and seg[i] > 0.1]
    return float(lo + peaks[0]) if peaks else 2.5 * h


def _prepare(page: np.ndarray, max_side: int, min_area_frac: float):
    gray = cv2.cvtColor(page, cv2.COLOR_BGR2GRAY) if page.ndim == 3 else page
    scale = 1.0
    if max(gray.shape) > max_side:  # phone photos: no need for 12 MP to find lines
        scale = max_side / max(gray.shape)
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    norm = normalize_background(gray)
    return norm, scale, _components(norm, min_area_frac)


def _member_mask(labels: np.ndarray, stats: np.ndarray, members) -> tuple[np.ndarray, int, int]:
    """Mask of the given components, cropped to their joint bounding box (+ offset)."""
    members = np.asarray(members)
    x0 = int(stats[members, cv2.CC_STAT_LEFT].min())
    y0 = int(stats[members, cv2.CC_STAT_TOP].min())
    x1 = int((stats[members, cv2.CC_STAT_LEFT] + stats[members, cv2.CC_STAT_WIDTH]).max())
    y1 = int((stats[members, cv2.CC_STAT_TOP] + stats[members, cv2.CC_STAT_HEIGHT]).max())
    return np.isin(labels[y0:y1, x0:x1], members), x0, y0


def _extract(norm: np.ndarray, member_mask: np.ndarray, angle: float, margin: float, scale: float,
             offset: tuple[int, int] = (0, 0)) -> Line | None:
    """Straighten and crop one line given the mask of its strokes. `member_mask` may be a
    crop of the working image starting at `offset` (x, y)."""
    ys, xs = np.nonzero(member_mask)
    if len(xs) == 0:
        return None
    xs = xs + offset[0]
    ys = ys + offset[1]
    full = np.zeros(norm.shape, np.uint8)
    full[offset[1]: offset[1] + member_mask.shape[0], offset[0]: offset[0] + member_mask.shape[1]] = member_mask
    member_mask = full
    center = (float(xs.mean()), float(ys.mean()))
    m = cv2.getRotationMatrix2D(center, -angle, 1.0)  # rotate clockwise by `angle` -> horizontal
    pts = np.column_stack([xs, ys, np.ones_like(xs)]).astype(np.float32) @ m.T
    x0, y0 = pts.min(0)
    x1, y1 = pts.max(0)
    pad = (y1 - y0) * margin
    x0, y0, x1, y1 = x0 - pad, y0 - pad, x1 + pad, y1 + pad
    m[:, 2] -= (x0, y0)
    size = (int(np.ceil(x1 - x0)) + 1, int(np.ceil(y1 - y0)) + 1)
    crop = cv2.warpAffine(norm, m, size, flags=cv2.INTER_LINEAR, borderValue=255)
    mask = cv2.warpAffine(member_mask.astype(np.uint8), m, size, flags=cv2.INTER_NEAREST, borderValue=0)
    mask = cv2.dilate(mask, np.ones((3, 3), np.uint8))  # keep anti-aliased stroke edges
    crop[mask == 0] = 255
    inv = cv2.invertAffineTransform(m)
    corners = np.array([[0, 0], [size[0], 0], [size[0], size[1]], [0, size[1]]], np.float32)
    poly = (np.column_stack([corners, np.ones(4, np.float32)]) @ inv.T) / scale
    bx0, by0 = np.floor(poly.min(0)).astype(int)
    bx1, by1 = np.ceil(poly.max(0)).astype(int)
    return Line(crop, (int(bx0), int(by0), int(bx1), int(by1)), poly.astype(np.float32), float(angle))


def _reading_order(lines: list[Line], rtl: bool) -> list[Line]:
    """Group lines into columns (horizontally overlapping lines), order columns by script
    direction, then lines top-to-bottom."""
    n = len(lines)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        for j in range(i + 1, n):
            a, b = lines[i].box, lines[j].box
            overlap = min(a[2], b[2]) - max(a[0], b[0])
            if overlap > 0.3 * min(a[2] - a[0], b[2] - b[0]):
                parent[find(i)] = find(j)
    cols: dict[int, list[Line]] = {}
    for i in range(n):
        cols.setdefault(find(i), []).append(lines[i])
    groups = list(cols.values())
    # Groups are only separate columns if they sit side by side (overlap vertically).
    # Groups stacked one above the other (e.g. an indented short line) are one column.
    merged = True
    while merged and len(groups) > 1:
        merged = False
        for a in range(len(groups)):
            for b in range(a + 1, len(groups)):
                ya = (min(l.box[1] for l in groups[a]), max(l.box[3] for l in groups[a]))
                yb = (min(l.box[1] for l in groups[b]), max(l.box[3] for l in groups[b]))
                overlap = min(ya[1], yb[1]) - max(ya[0], yb[0])
                if overlap < 0.5 * min(ya[1] - ya[0], yb[1] - yb[0]):
                    groups[a] += groups.pop(b)
                    merged = True
                    break
            if merged:
                break
    columns = sorted(groups, key=lambda c: np.mean([(l.box[0] + l.box[2]) / 2 for l in c]), reverse=rtl)
    return [l for c in columns for l in sorted(c, key=lambda l: (l.box[1] + l.box[3]) / 2)]


# ------------------------------------------------------------------ blob method


def _ridge_kernel(sx: float, sy: float, surround: float, angle_deg: float) -> np.ndarray:
    """Elongated centre-minus-surround kernel (sums to zero): responds to a band of ink
    with empty space on both sides, not to uniformly dense regions."""
    r = int(np.ceil(3 * max(sx, sy * surround)))
    ys, xs = np.mgrid[-r: r + 1, -r: r + 1].astype(np.float32)
    a = np.deg2rad(angle_deg)
    u = xs * np.cos(a) - ys * np.sin(a)  # along the direction (cos a, -sin a): rising to the right
    v = xs * np.sin(a) + ys * np.cos(a)
    g_along = np.exp(-u**2 / (2 * sx**2))
    centre = g_along * np.exp(-v**2 / (2 * sy**2))
    wide = g_along * np.exp(-v**2 / (2 * (surround * sy) ** 2))
    return (centre / centre.sum() - wide / wide.sum()).astype(np.float32)


def segment_lines_blobs(page: np.ndarray, rtl: bool = False, max_side: int = 2000, min_area_frac: float = 2e-5,
                        margin: float = 0.12, angles=(-45, -30, -15, 0, 15, 30, 45),
                        along: float = 2.5, across: float = 0.17, surround: float = 2.2,
                        rel_thresh: float = 0.3, off_axis_weight: float = 0.55) -> list[Line]:
    """Filter widths scale with the line pitch P (distance between lines): smear along
    the line over `along` text heights, centre band `across`*P, surround `surround`x wider."""
    norm, scale, (labels, stats, _, keep) = _prepare(page, max_side, min_area_frac)
    if not keep:
        return []
    h = _text_height(stats, keep)
    ink = np.isin(labels, keep)
    pitch = _line_pitch(ink, h)

    # 1. Line blobs: max over orientations of an elongated ridge filter, at a scale
    #    where text is ~8 px high (cheap, and the kernels stay small).
    s = min(1.0, 8.0 / max(h, 1.0))
    small = cv2.resize(ink.astype(np.float32), None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    hs = h * s
    ps = pitch * s
    responses = {}
    for a in angles:
        if a == 0:  # separable fast path
            r = (cv2.GaussianBlur(small, (0, 0), sigmaX=along * hs, sigmaY=across * ps)
                 - cv2.GaussianBlur(small, (0, 0), sigmaX=along * hs, sigmaY=surround * across * ps))
        else:
            r = cv2.filter2D(small, -1, _ridge_kernel(along * hs, across * ps, surround, a),
                             borderType=cv2.BORDER_CONSTANT)
        responses[a] = r
    # Orientation prior: angles far from the page's dominant direction must respond much
    # more strongly. Otherwise diagonal kernels catch chance alignments of ascenders and
    # descenders between neighbouring lines and stitch the lines together.
    dominant = max(responses, key=lambda a: float(np.clip(responses[a], 0, None).sum()))
    best = np.full(small.shape, -1.0, np.float32)
    best_a = np.zeros(small.shape, np.float32)
    for a, r in responses.items():
        if abs(a - dominant) > 15:
            r = r * off_axis_weight
        upd = r > best
        best[upd] = r[upd]
        best_a[upd] = a
    on_ink = best[(small > 0.25) & (best > 0)]
    core = float(np.median(on_ink)) if on_ink.size else float(best.max())
    blobs = (best > rel_thresh * core).astype(np.uint8)
    k = max(3, int(round(0.25 * ps)) | 1)  # remove thin spurs; line blobs are ~half a pitch thick
    blobs = cv2.morphologyEx(blobs, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    nb, blab_small = cv2.connectedComponents(blobs, connectivity=8)
    if nb <= 1:
        return []
    blob_angle = np.zeros(nb, np.float32)
    for b in range(1, nb):
        sel = blab_small == b
        blob_angle[b] = float(np.average(best_a[sel], weights=best[sel]))
    blab = cv2.resize(blab_small.astype(np.int32).astype(np.float32), (norm.shape[1], norm.shape[0]),
                      interpolation=cv2.INTER_NEAREST).astype(np.int32)

    # 2. Assign strokes to blobs: majority overlap, else the nearest blob within ~1.5 text heights.
    comp_ids = np.asarray(keep)
    lab_ink = labels[ink]
    blob_ink = blab[ink]
    nc = labels.max() + 1
    counts = np.bincount(lab_ink.astype(np.int64) * nb + blob_ink, minlength=nc * nb).reshape(nc, nb)
    counts[:, 0] = 0
    owner = np.where(counts[comp_ids].max(1) > 0, counts[comp_ids].argmax(1), 0)
    if (owner == 0).any():
        dist, idx = cv2.distanceTransformWithLabels((blab_small == 0).astype(np.uint8), cv2.DIST_L2, 5,
                                                    labelType=cv2.DIST_LABEL_PIXEL)
        zero_pts = np.column_stack(np.nonzero(blab_small > 0))  # label k -> k-th non-zero pixel (row-major)
        lut = np.zeros(idx.max() + 1, np.int32)
        lut[1: len(zero_pts) + 1] = blab_small[zero_pts[:, 0], zero_pts[:, 1]]
        for k in np.nonzero(owner == 0)[0]:
            i = comp_ids[k]
            x, y, cw, ch, _ = stats[i]
            cy, cx = int((y + ch / 2) * s), int((x + cw / 2) * s)
            cy, cx = min(cy, dist.shape[0] - 1), min(cx, dist.shape[1] - 1)
            if dist[cy, cx] / s <= 0.6 * pitch:
                owner[k] = lut[idx[cy, cx]]

    # 3. One line per blob that holds real ink (not just a dot or two).
    total_ink = stats[comp_ids, cv2.CC_STAT_AREA].sum()
    lines = []
    for b in np.unique(owner[owner > 0]):
        members = comp_ids[owner == b]
        if stats[members, cv2.CC_STAT_AREA].sum() < 0.004 * total_ink and stats[members, cv2.CC_STAT_HEIGHT].max() < 0.6 * h:
            continue
        mask, ox, oy = _member_mask(labels, stats, members)
        line = _extract(norm, mask, _refine_angle(mask, float(blob_angle[b])), margin, scale, (ox, oy))
        if line is not None:
            lines.append(line)
    return _reading_order(lines, rtl)


def _refine_angle(mask: np.ndarray, a0: float, max_delta: float = 10.0) -> float:
    """Least-squares slope of the line's ink in the frame of the coarse angle a0
    (orientations are only searched in 15-degree steps)."""
    ys, xs = np.nonzero(mask)
    if len(xs) < 50:
        return a0
    a = np.deg2rad(a0)
    u = xs * np.cos(a) - ys * np.sin(a)  # along the line
    v = xs * np.sin(a) + ys * np.cos(a)  # across (down)
    if np.ptp(u) < 3 * np.ptp(v):
        return a0  # a short word: slope estimate unreliable
    slope = np.cov(u, v)[0, 1] / np.var(u)
    return a0 - float(np.clip(np.degrees(np.arctan(slope)), -max_delta, max_delta))


# ------------------------------------------------------------------ projection method


def estimate_skew(mask: np.ndarray, max_angle: float = 10.0, step: float = 0.5) -> float:
    """Angle (degrees) that makes the horizontal ink profile sharpest."""
    scale = 600 / max(mask.shape)
    small = cv2.resize(mask.astype(np.uint8) * 255, None, fx=min(1.0, scale), fy=min(1.0, scale),
                       interpolation=cv2.INTER_AREA)
    h, w = small.shape
    best, best_score = 0.0, -1.0
    for angle in np.arange(-max_angle, max_angle + 1e-6, step):
        m = cv2.getRotationMatrix2D((w / 2, h / 2), float(angle), 1.0)
        prof = cv2.warpAffine(small, m, (w, h), flags=cv2.INTER_NEAREST).sum(axis=1).astype(np.float64)
        score = float((prof**2).sum())
        if score > best_score:
            best, best_score = float(angle), score
    return best


def segment_lines_projection(page: np.ndarray, rtl: bool = False, max_side: int = 2000,
                             min_area_frac: float = 2e-5, margin: float = 0.12,
                             peak_thresh: float = 0.15) -> list[Line]:
    norm, scale, (labels, stats, centroids, keep) = _prepare(page, max_side, min_area_frac)
    if not keep:
        return []
    clean = np.isin(labels, keep)
    angle = estimate_skew(clean)
    # Bands are found in a deskewed frame; strokes are then cut from the original frame.
    hh, ww = clean.shape
    rot = cv2.getRotationMatrix2D((ww / 2, hh / 2), angle, 1.0)
    cy = centroids[:, 0] * rot[1, 0] + centroids[:, 1] * rot[1, 1] + rot[1, 2]  # centroid y after deskew
    rotated = cv2.warpAffine(clean.astype(np.uint8), rot, (ww, hh), flags=cv2.INTER_NEAREST)

    h = _text_height(stats, keep)
    pitch = _line_pitch(clean, h)
    profile = rotated.sum(axis=1).astype(np.float32)
    profile = cv2.GaussianBlur(profile.reshape(-1, 1), (1, 0), sigmaX=1, sigmaY=max(2.0, pitch * 0.2)).ravel()
    min_gap = max(3, int(pitch * 0.6))
    thresh = peak_thresh * profile.max()
    peaks = []
    for y in np.argsort(-profile):
        if profile[y] < thresh:
            break
        if all(abs(int(y) - p) >= min_gap for p in peaks):
            peaks.append(int(y))
    peaks.sort()
    bounds = [-np.inf] + [a + int(np.argmin(profile[a:b])) for a, b in zip(peaks, peaks[1:])] + [np.inf]

    lines = []
    for k in range(len(peaks)):
        members = [i for i in keep if bounds[k] <= cy[i] < bounds[k + 1]]
        if not members or sum(stats[i, cv2.CC_STAT_AREA] for i in members) < 0.02 * clean.sum():
            continue
        mask, ox, oy = _member_mask(labels, stats, members)
        line = _extract(norm, mask, -angle, margin, scale, (ox, oy))
        if line is not None:
            lines.append(line)
    return _reading_order(lines, rtl)


def segment_lines(page: np.ndarray, method: str = "projection", rtl: bool = False, **kw) -> list[Line]:
    if method == "blobs":
        return segment_lines_blobs(page, rtl=rtl, **kw)
    if method == "projection":
        return segment_lines_projection(page, rtl=rtl, **kw)
    raise ValueError(f"unknown method {method!r}")
