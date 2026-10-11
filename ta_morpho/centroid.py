"""Centroid of the test mask."""

from __future__ import annotations

import numpy as np


def mask_centroid(mask: np.ndarray) -> tuple[float, float]:
    """Centroid (x, y) in pixels of a binary mask (mean of its pixel coordinates).

    Raises ValueError for an empty mask.
    """
    ys, xs = np.nonzero(mask)
    if xs.size == 0:
        raise ValueError("Empty mask has no centroid")
    return float(xs.mean()), float(ys.mean())
