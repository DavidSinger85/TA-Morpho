# Contributing

Questions, problems and ideas are welcome on the
[Issues](https://github.com/DavidSinger85/TA-Morpho/issues) page. Everyone
taking part follows the [code of conduct](CODE_OF_CONDUCT.md).

## Reporting a problem with a picture

Open an issue with:
- the picture (or a link to it) and its file name exactly as used, if you can
  share it;
- its cell figure (`cells/<picture>.png` in the output folder) and its row of
  `summary.csv` (the `status` and `messages` columns say what the program
  noticed);
- what you expected (e.g. "the aperture is on the left, not on the right");
- `.pipeline/config_used.yaml` if you changed a setting, and
  `.pipeline/batch.log` if the program stopped with an error.

Most problems can also be corrected by hand in the desktop program (Review);
the corrections are recorded and listed in the `corrections` column.

## Working on the code

```bash
conda env create -f environment.yml && conda activate ta-morpho   # or: pip install -e ".[gui,test]"
python -m pytest tests            # about a minute; the window tests run offscreen
pip install ruff                  # once: ruff is not installed with the program
ruff check ta_morpho tests        # errors and likely bugs only
```

- One function per step in `ta_morpho/`, with a docstring. Nothing is guessed
  silently: a value that cannot be measured stays empty, a default is used
  only with the picture flagged, and the reason is given.
- Every setting lives in `ta_morpho/config.yaml` with a comment that says what it
  does and why; every output column is described in `ta_morpho/dictionary.py`. After
  changing either, regenerate the two reference pages:
  `python -m ta_morpho.dictionary docs`.
- A change that moves a result makes `tests/test_validation_pictures.py` fail.
  If the change is intended, record the new values with
  `python -m tests.test_validation_pictures --update`: it lists the pictures
  and columns that changed and keeps the run in `validation_update/`. Check its
  cell figures (`validation_update/cells/`), update `docs/METHODS.md` if the
  method changed, and add a line to `CHANGELOG.md`.
- Pull requests: one change per request, with the tests passing.
