"""Specimen metadata from the image file name.

Convention (parts separated by ``separator``, a regex; default: underscores
and/or spaces):

    Genus_species_<bar>um_<specimen id>.ext     Hyalosphenia_papilio_25um_001.png
    <bar> Genus species [specimen id].ext       20 Nebela collaris.png

- genus: first part, capitalised letters only (e.g. "Hyalosphenia")
- species: second part; may start with "cf." / "aff.", or be "sp", "sp.",
  "sp1" ... A capitalised epithet ("Papilio") is lower-cased. "cf" / "aff"
  written as a part of its own ("Nebela_cf_collaris", "Nebela cf. collaris")
  is joined to the epithet: species "cf.collaris".
- bar length: any part like "25um", "25µm", "12.5um", "12,5um", or a bare
  number as the FIRST part ("20 Nebela collaris"). A bare number outside
  ``bar_range_um`` (default 5-500 µm) is not taken as a bar length (it is
  more likely a date or a counter, e.g. "20231005_..." or "003_..."); a
  length with a unit outside that range is used but reported.
- specimen id: all remaining parts, joined with "_"

Anything that does not fit is left empty and reported in ``messages``;
nothing is guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

GENUS = re.compile(r"^[A-Z][a-z]+$")
SPECIES = re.compile(r"^(?:(?:cf|aff)\.?-?)?(?:[a-z][a-z-]*|sp\.?\d*)$")
BAR = re.compile(r"^(\d+(?:[.,]\d+)?)\s*(?:um|µm|μm|microns?)$", re.IGNORECASE)
BARE_NUMBER = re.compile(r"^(\d+(?:[.,]\d+)?)$")
QUALIFIERS = ("cf", "aff")    # written apart from the epithet ("cf_collaris"): joined as "cf.collaris"
DEFAULT_SEPARATOR = r"[_\s]+"
DEFAULT_BAR_RANGE_UM = (5.0, 500.0)


@dataclass
class FileMetadata:
    """Fields parsed from one file name (None when absent)."""

    genus: str | None = None
    species: str | None = None
    bar_length_um: float | None = None
    specimen_id: str | None = None
    messages: list[str] = field(default_factory=list)


def _number(text: str) -> float:
    return float(text.replace(",", "."))


def parse_filename(stem: str, separator: str = DEFAULT_SEPARATOR,
                   bar_range_um: tuple[float, float] = DEFAULT_BAR_RANGE_UM) -> FileMetadata:
    """Parse genus, species, scale bar length and specimen id from a file stem."""
    parts = [p for p in re.split(separator, stem.strip()) if p]
    md = FileMetadata()
    lo, hi = bar_range_um

    bars = [i for i, p in enumerate(parts) if BAR.match(p)]
    bare_ignored = None
    if not bars and parts and BARE_NUMBER.match(parts[0]):
        if lo <= _number(parts[0]) <= hi:
            bars = [0]
        else:
            bare_ignored = parts[0]
    if len(bars) == 1:
        m = BAR.match(parts[bars[0]]) or BARE_NUMBER.match(parts[bars[0]])
        md.bar_length_um = _number(m.group(1))
        if not lo <= md.bar_length_um <= hi:
            md.messages.append(f"bar length {md.bar_length_um:g} µm in file name is outside "
                               f"{lo:g}-{hi:g} µm; check it")
    elif bare_ignored is not None:
        md.messages.append(f"no bar length (e.g. '25um') in file name; leading number "
                           f"'{bare_ignored}' is outside {lo:g}-{hi:g} µm, not used as one")
    elif len(bars) > 1:
        md.messages.append(f"several bar lengths in file name ({', '.join(parts[i] for i in bars)})")
    else:
        md.messages.append("no bar length (e.g. '25um') in file name")
    rest = [p for i, p in enumerate(parts) if i not in bars]
    lead = []
    if bare_ignored is not None:              # a leading counter/date: kept as specimen id
        lead, rest = rest[:1], rest[1:]

    qualifier = rest[1].lower().rstrip(".") if len(rest) >= 3 else ""
    if qualifier in QUALIFIERS and GENUS.match(rest[0]) and SPECIES.match(rest[2].lower()):
        rest = [rest[0], f"{qualifier}.{rest[2]}", *rest[3:]]    # "cf_collaris", "cf. collaris"
    if len(rest) >= 2 and GENUS.match(rest[0]) and SPECIES.match(rest[1].lower()):
        md.genus, md.species = rest[0], rest[1].lower()
        rest = rest[2:]
    else:
        md.messages.append("file name does not start with Genus species")
    md.specimen_id = "_".join(lead + rest) or None
    return md
