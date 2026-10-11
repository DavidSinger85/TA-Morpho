# Validation of TA-Morpho

Everything needed to check and reproduce the validation of TA-Morpho: agreement with manual
measurement and repeatability. The figures and tables of the article and of its supplementary
material are in [`results/`](results).

## Folder

```
validation/
  README.md                  this file
  SOURCES.md                 source and licence of every picture
  images/                    the pictures measured
    Replicate_1/             as published
    Replicate_2/             resized, turned, mirrored (see data/transforms.csv)
    Replicate_3/             idem, differently
  data/
    fiji_measurements.csv    manual measurements (Fiji), one row per replicate and picture
    app_results.csv          TA-Morpho's results, one row per replicate and picture
    transforms.csv           how Replicate_2 and Replicate_3 were made from Replicate_1
  scripts/                   run in this order
    1_make_pictures.py       Replicate_1 -> Replicate_2, Replicate_3 and data/transforms.csv
    2_run_app.py             the pictures -> data/app_results.csv and Figure 1
    3_analysis.R             data/ -> all statistics, tables and figures
  results/
    manuscript/              figures and table of the article
    supplementary/           figures and tables of the supplementary material
```

## Design

- **24 published pictures** of hyalosphenid tests (13 genera + *Argynnia*; sources and licences in
  [SOURCES.md](SOURCES.md)): 19 with a scale bar (lengths in µm), 5 drawings without one (ratios only).
- **Three replicates** of the same pictures: `Replicate_1` as published; `Replicate_2` and
  `Replicate_3` resized (×0.7–1.6), turned (at least 10° from upright) and mirrored on half,
  differently in each replicate. The scale bar is kept level and resized with the picture, so the bar
  length in the file names stays valid.
- Each replicate was measured **once by hand** in Fiji/ImageJ by one observer, blind to the app's
  values (straight-line tool; scale set on the printed bar), and **once by TA-Morpho** (default
  settings, no correction).

## Results

### Manuscript (`results/manuscript/`)
| File | Content |
|---|---|
| `Figure_1_app_output.png` | TA-Morpho's figure for one specimen (*Padaungiella lageniformis*, Replicate_1), as the program draws it |
| `Table_1_repeatability_agreement.csv` | repeatability of both methods and their agreement: scale bar, length, width, aperture width |

### Supplementary material (`results/supplementary/`)
| File | Content |
|---|---|
| `Figure_S1_repeatability_per_specimen.png/.pdf` | every measurement as a difference from its specimen's average, by hand and with TA-Morpho |
| `Figure_S2_agreement_Bland_Altman.png/.pdf` | TA-Morpho − by hand, against their mean (Bland–Altman), means of the three replicates |
| `Figure_S3_repeatability_CV_per_picture.png/.pdf` | coefficient of variation of each picture over the replicates, both methods |
| `Table_S1_repeatability_full.csv` | all repeatability statistics, including W/L and AW/L |
| `Table_S2_agreement_full.csv` | all agreement statistics, per replicate and on the means of the replicates |
| `Table_S3_values_per_picture.csv` | every value per picture, method and replicate, with its mean and CV |
| `Table_S4_app_status.csv` | TA-Morpho's status (ok / check) per picture and replicate |
| `session_info.txt` | R and package versions of the last run |

## Data files

**`data/fiji_measurements.csv`:** `replicate`, `id` (specimen id in the file name), `image`, `unit`
(`um`, or `px` for the drawings without a scale: their values are in pixels of the picture measured),
`bar_px` (scale bar length measured, px), `aperture`, `length`, `width`, `neck` (replicate 1 only; not
analysed: too few necked specimens, and the neck was not defined in the protocol), `note`. Corrections
made by the observer are given in `note`. Three ids were mistyped in the original sheets and are
given here correctly.

**`data/app_results.csv`:** `replicate`, then the app's own columns (see
[docs/DATA_DICTIONARY.md](../../docs/DATA_DICTIONARY.md)): `image`, `specimen_id`, `software_version`,
`status`, `messages`, `bar_length_um`, `px_per_um`, `length_um`, `width_um`, `aperture_width_um`,
`W/L`, `AW/L`.

**`data/transforms.csv`:** `replicate`, `image`, `scale` (resize factor), `angle_ccw_deg`, `mirrored`,
`bar_px_original`, `bar_px_expected` (= scale × original), `bar_px_detected` (by the app in the new
picture), `size_px`.

## Reproduce

From the repository folder, with TA-Morpho installed (see the main README) and R ≥ 4.1 with ggplot2:

```
python data/validation/scripts/1_make_pictures.py   # optional: rebuilds Replicate_2, Replicate_3, data/transforms.csv (identical files)
python data/validation/scripts/2_run_app.py         # optional: rebuilds data/app_results.csv and Figure 1 (~2 min)
Rscript data/validation/scripts/3_analysis.R        # all statistics, tables and figures -> results/
```

`3_analysis.R` needs only the three files in `data/`; the two Python scripts show where they come from.

## Statistics (in `3_analysis.R`)

- **Repeatability**, per method and measure: coefficient of variation (CV) of each picture over the
  three replicates; CVw = root-mean-square of the CVs ("typical change when the same picture is
  measured again"); repeatability coefficient 2.77 × Sw; ICC(2,1); shift of replicates 2 and 3 from
  replicate 1. By hand vs TA-Morpho: ratio of the CVw (bootstrap 95 % CI, 5000 resamples over
  pictures) and a Wilcoxon signed-rank test on the per-picture CVs.
- **Agreement** (TA-Morpho − by hand), per replicate and on the means of the three replicates: mean
  difference with its 95 % CI and 95 % limits of agreement (mean ± 1.96 SD), in the unit and in % of
  the mean of the two methods (Bland & Altman 1986); Lin's concordance correlation coefficient.
- The scale bar is compared in pixels of the published picture (measured px ÷ resize factor).
