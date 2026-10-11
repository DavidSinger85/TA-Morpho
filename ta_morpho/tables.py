"""Reading the correction tables (CSV files written by the desktop program, or
by hand or by a spreadsheet for the command line).

A table that cannot be used stops the run before any work, with a message
naming the file and the problem (ValueError): a file that is not a CSV, ";"
separators or decimal commas (as a spreadsheet may write them), a missing
column, a value that is not a number, a value that must be positive, or an
image listed twice. Nothing is guessed: a wrong value would silently change
the results.
"""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd


def read_table(path: str | Path, required: list[str], numbers: tuple[str, ...] = (),
               positive: tuple[str, ...] = (), unique: tuple[str, ...] | None = ("image",),
               text: bool = False, filled: tuple[str, ...] = ("image",)) -> pd.DataFrame:
    """Read a correction CSV and check it (see module docstring).

    ``required``: columns that must be there; ``filled``: of these, the ones
    that may not have an empty cell; ``numbers``: columns whose
    non-empty cells must be numbers (read as float); ``positive``: of these,
    the ones that must be above 0; ``unique``: columns whose combination may
    appear only once (None: any number of rows per image). ``text`` reads
    every cell as text, empty cells as "". An empty file gives an empty table."""
    name = Path(path).name
    try:
        df = pd.read_csv(path, dtype=str, keep_default_na=False, skipinitialspace=True)
    except pd.errors.EmptyDataError:
        return pd.DataFrame(columns=required)
    except (pd.errors.ParserError, UnicodeDecodeError) as e:
        raise ValueError(f"{name} cannot be read as a CSV table ({str(e).splitlines()[0]}): save it as "
                         "CSV (comma-separated, UTF-8)") from None
    df.columns = [str(c).strip() for c in df.columns]
    if len(df.columns) == 1 and ";" in df.columns[0]:
        raise ValueError(f"{name} uses ';' between the columns (as some spreadsheets in other languages "
                         "write CSV): save it with commas, and '.' as the decimal mark")
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"{name} has no '{missing[0]}' column (columns needed: {', '.join(required)}; "
                         f"found: {', '.join(df.columns)})")
    df = df.apply(lambda s: s.str.strip())
    for col in filled:
        empty = df.index[df[col] == ""]
        if len(empty):
            raise ValueError(f"{name}, line {empty[0] + 2}: the {col} cell is empty")
    for col in numbers:
        if col not in df.columns:
            continue
        for line, v in zip(range(2, len(df) + 2), df[col], strict=True):
            if v == "":
                continue
            try:
                x = float(v)
            except ValueError:
                hint = " (use '.' as the decimal mark)" if "," in v else ""
                raise ValueError(f"{name}, line {line}: {col} '{v}' is not a number{hint}") from None
            if not math.isfinite(x) or (col in positive and x <= 0):
                raise ValueError(f"{name}, line {line}: {col} must be a number above 0, not '{v}'")
    if unique:
        dupes = df[df.duplicated(list(unique), keep=False)]
        if len(dupes):
            first = dupes.iloc[0]
            what = ", ".join(f"{c} {first[c]}" for c in unique)
            lines = ", ".join(str(i + 2) for i in dupes.index[:4])
            raise ValueError(f"{name}: {what} is listed more than once (lines {lines}): keep one row")
    if not text:
        for col in numbers:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col].replace("", None), errors="coerce").astype(float)
    return df
