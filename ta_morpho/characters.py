"""Diagnostic characters of the hyalospheniid genera, per specimen.

The reference table ``genus_characters.csv`` (next to this module; one row per
genus, values from Kosakyan et al. 2025, see docs/CHARACTERS.md) gives the
characters of each genus. A specimen whose genus is in the table starts with
its genus's values; any of them, and the genus and species themselves, can be
set by hand (desktop program: Review > Characters; command line: the table
``paths.characters_csv``, columns image, name, value). Nothing is detected or
guessed: a value is either the genus's (source "genus") or set by hand
(source "hand"); a genus not in the table gives no values.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

import pandas as pd

from ta_morpho.tables import read_table

TABLE = Path(__file__).with_name("genus_characters.csv")

# (key, label, values a specimen can take). The key is the table's column; the
# values are the vocabulary of docs/CHARACTERS.md ("variable" and "rare" are
# genus-level answers: varies between species, or in one or two species).
CHARACTERS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("material", "Material",
     ("proteinaceous", "kleptosomic", "idiosomic", "mixed", "variable", "unresolved")),
    ("plate_shape", "Plate shape", ("none", "round-oval", "oval", "square", "variable")),
    ("lateral_pores", "Lateral pores", ("yes", "no", "variable")),
    ("keel", "Keel", ("no", "flat", "hollow", "variable", "rare")),
    ("horns_expansions", "Horns, expansions", ("yes", "no", "variable", "rare")),
    ("neck", "Neck", ("distinct", "gradual", "none or short", "variable")),
    ("aperture_broad", "Aperture, broad",
     ("straight", "linear to slightly curved", "slightly curved", "curved", "strongly curved", "variable")),
    ("aperture_margin", "Aperture margin", ("lip", "collar", "toothed", "variable")),
    ("aperture_narrow", "Aperture, narrow",
     ("oval", "elliptical", "circular", "circular-ovoid", "ovoid", "notched", "variable")),
    ("compression", "Compression", ("compressed", "slightly", "not compressed", "variable")),
    ("fundus_broad", "Fundus", ("rounded", "pointed", "flat")),
)
KEYS = tuple(k for k, _, _ in CHARACTERS)
LABELS = {k: label for k, label, _ in CHARACTERS}
VALUES = {k: values for k, _, values in CHARACTERS}
TAXON = ("genus", "species")                 # names of the taxon rows of the characters table

# The table's note and source columns of each character (shown as help in the window).
NOTES = {"material": ("material_note", "material_ref"), "plate_shape": ("", "plate_ref"),
         "lateral_pores": ("pore_type_position", "pores_ref"), "keel": ("keel_note", "keel_ref"),
         "horns_expansions": ("horns_note", "horns_ref"), "neck": ("neck_note", "neck_ref"),
         "aperture_broad": ("aperture_broad_note", "aperture_ref"),
         "aperture_margin": ("aperture_margin_note", "aperture_ref"),
         "aperture_narrow": ("", "aperture_narrow_ref"), "compression": ("", "compression_ref"),
         "fundus_broad": ("fundus_note", "fundus_ref")}


@cache
def load_genus_table() -> pd.DataFrame:
    """The reference table, indexed by genus (all values as text, blank = not stated)."""
    return pd.read_csv(TABLE, dtype=str, keep_default_na=False).set_index("genus")


def genera() -> list[str]:
    """The genera of the reference table, in alphabetical order."""
    return sorted(load_genus_table().index)


def find_genus(genus: str | None) -> str | None:
    """The table's spelling of ``genus`` (case ignored), or None if it is not in the table."""
    if not genus:
        return None
    match = {g.lower(): g for g in load_genus_table().index}
    return match.get(str(genus).strip().lower())


def defaults(genus: str | None) -> dict[str, str]:
    """The characters of ``genus`` that the table states ({} for a genus not in the table)."""
    g = find_genus(genus)
    if g is None:
        return {}
    row = load_genus_table().loc[g]
    return {k: row[k] for k in KEYS if row.get(k, "")}


def help_text(genus: str | None, key: str) -> str:
    """The table's note and page for one character of ``genus`` ("" if none)."""
    g = find_genus(genus)
    if g is None:
        return ""
    row = load_genus_table().loc[g]
    note, ref = (row.get(c, "") if c else "" for c in NOTES[key])
    return " · ".join(x for x in (note, ref.replace("K25", "Kosakyan et al. 2025,") if ref else "") if x)


def resolve(genus: str | None, by_hand: dict[str, str] | None = None) -> dict[str, tuple[str, str]]:
    """{key: (value, source)} of one specimen: its genus's values, replaced by
    those set by hand. Characters with no value are left out."""
    out = {k: (v, "genus") for k, v in defaults(genus).items()}
    for k, v in (by_hand or {}).items():
        if k in VALUES and v:
            out[k] = (v, "hand")
    return out


def load_characters(path: str | Path | None) -> dict[str, dict[str, str]]:
    """{image: {name: value}} from the characters table (columns image, name,
    value; name = a character key, or genus / species). Empty if the file is
    absent. Raises ValueError on an unknown name or value."""
    if not path or not Path(path).exists():
        return {}
    df = read_table(path, ["image", "name", "value"], unique=("image", "name"), text=True,
                    filled=("image", "name"))
    out: dict[str, dict[str, str]] = {}
    for line, (img, name, value) in enumerate(zip(df["image"], df["name"], df["value"], strict=True), start=2):
        name, value = name.strip(), value.strip()
        if name not in VALUES and name not in TAXON:
            raise ValueError(f"{Path(path).name}, line {line}: unknown character '{name}' "
                             f"(one of {', '.join(TAXON + KEYS)})")
        if name in VALUES and value and value not in VALUES[name]:
            raise ValueError(f"{Path(path).name}, line {line}: '{value}' is not a value of {name} "
                             f"({', '.join(VALUES[name])})")
        out.setdefault(img, {})[name] = value
    return out
