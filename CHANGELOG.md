# Changelog

Versions follow [semantic versioning](https://semver.org/). Results can change
between minor versions (1.0 → 1.1); every change that can move a result is
listed here. Each `summary.csv` records the version that produced it
(`software_version`), and `.pipeline/config_used.yaml` the exact settings and
package versions.

## 1.0.0 (2026-10-11)

First public version.

- **Calibration:** scale bar found in the picture (dark, light or coloured;
  letters and text rejected), its length read from the file name; or the
  resolution given per picture in a calibration table, or drawn by hand.
- **Outline** of the test wall by colour difference from the background, with
  the background type (light or dark) found per picture, figure frames left
  out, faint walls closed, and smoothing at a fixed physical scale (1 µm).
- **Aperture and start point** found automatically, spines cut before the
  corner search; tests cut by the picture border get no automatic aperture.
- **Measurements:** radial profile (72 rays at 5°); classic measurements along
  the oral–aboral axis (length, width, aperture width and angle, neck, ratios);
  shape descriptors; three genus characters per specimen (`aperture_sag`,
  `neck_jump`, `n_protrusions`); a 250-point outline anchored on the aperture
  corners and the fundus, exported for geometric morphometrics (tpsDig,
  geomorph).
- **Holes and bumps** of the outline, added by hand and measured.
- **Diagnostic characters** per specimen (material, plates, pores, keel, horns,
  neck, aperture, compression, fundus): the genus's values from the monograph,
  editable per specimen with the genus and species; on the cell figure and in
  `summary.csv`.
- **Status** `ok`, `check` or `failed` with the reason; nothing is guessed silently.
- **Desktop program** (installers for Windows and macOS; on Linux it runs
  from source): folders, settings, run, review
  with corrections on the picture (aperture corners, fundus, scale, outline,
  holes and bumps), genus and characters, and Undo; every correction is recorded with the
  results.
- **Command line** `ta-morpho` for batches.
- **Test pictures** (`data/validation`): 24 published pictures of 13
  hyalospheniid genera and *Argynnia* (light microscopy, SEM, drawings), with
  their sources; the tests check that they keep their recorded results.
