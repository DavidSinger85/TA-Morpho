"""The documentation is up to date and its links work.

docs/DATA_DICTIONARY.md and docs/PARAMETERS.md are generated from the code
(``python -m ta_morpho.dictionary``); every relative link of README.md and
docs/*.md points to a file of the repository.
"""

import re
from pathlib import Path

import pytest

from ta_morpho.dictionary import markdown, parameters_markdown
from ta_morpho.export import DEFAULT_CONFIG

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]
LINK = re.compile(r"!?\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
FENCE = re.compile(r"^```.*?^```", re.MULTILINE | re.DOTALL)
HINT = "run: python -m ta_morpho.dictionary"


def test_data_dictionary_is_up_to_date():
    assert (ROOT / "docs" / "DATA_DICTIONARY.md").read_text(encoding="utf-8") == markdown() + "\n", HINT


def test_parameter_table_is_up_to_date():
    config = DEFAULT_CONFIG.read_text(encoding="utf-8")
    assert (ROOT / "docs" / "PARAMETERS.md").read_text(encoding="utf-8") == parameters_markdown(config) + "\n", HINT


def relative_links(document: Path) -> list[str]:
    text = FENCE.sub("", document.read_text(encoding="utf-8"))        # no links in code blocks
    targets = [m.group(1) for m in LINK.finditer(text)]
    return [t for t in targets if not re.match(r"[a-z][a-z0-9+.-]*:", t, re.IGNORECASE) and not t.startswith("#")]


@pytest.mark.parametrize("document", DOCUMENTS, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_relative_links_resolve(document):
    missing = [t for t in relative_links(document)
               if not (document.parent / t.split("#")[0]).exists()]
    assert not missing, f"links to missing files in {document.name}: {missing}"
