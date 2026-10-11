# Diagnostic characters of the hyalospheniid genera and how TA-Morpho uses them

The 14 genera of the family Hyalospheniidae are told apart by a set of characters (Kosakyan
et al. 2025, the monograph, cited "K25 p.N"; the printed page number is the
PDF page number). This file sorts each character into one of three classes:

- **(i) measured** on each specimen (`summary.csv` and the extra tables;
  columns in [DATA_DICTIONARY.md](DATA_DICTIONARY.md));
- **(ii) measurable** from the outline or the picture, but not measured yet;
- **(iii) not measurable** in a single picture in broad view. These come from
  the reference table [`ta_morpho/genus_characters.csv`](../ta_morpho/genus_characters.csv),
  one row per genus.

Every specimen also carries the described characters of its genus, which the
user can check and change (§ 3). The program never detects a genus or a
described character: a value is the genus's (from the monograph) or the
user's, and the identification stays with the user.

*Argynnia* and *Physochila* are not in the table: the monograph excludes them
from the family Hyalospheniidae (K25 p.26).

## 1. The reference table `ta_morpho/genus_characters.csv`

One row per genus (14 genera). Each character has a short value, a free note
(`*_note`, or `pore_type_position` for the pores) and its source (`*_ref`, the
page of the monograph). A blank cell means the monograph says nothing at genus
level; nothing was filled by guessing.

Values used in the table:

- `genus`; `family_status`: the family given by the monograph
  (`Hyalospheniidae` for all 14).
- `material`: `proteinaceous`, `kleptosomic` (recycled euglyphid plates in
  organic cement), `idiosomic` (self-secreted plates), `mixed`, `variable`
  (differs between populations or species), `unresolved` (self-secreted or
  recycled plates: not settled by the monograph, *Mrabella*).
- `plate_shape`: `none`, `round-oval`, `oval`, `square`.
- `lateral_pores`: `yes`, `variable` (some species), or blank.
  `pore_type_position` says whether the pores are small lateral pores or the
  large invaginated pores in depressions of *Certesella* and *Porosia*, and
  where they lie.
- `keel`: `no`, `flat`, `hollow`, `variable`, `rare` (one or two species).
- `horns_expansions`: `yes`, `no`, `variable`, `rare`.
- `neck`: `distinct`, `gradual`, `none or short`, `variable`.
- `aperture_broad`: `linear to slightly curved`, `slightly curved`, `curved`,
  `strongly curved`, `variable`. In the monograph, "curved" means convex,
  arched away from the body.
- `aperture_margin`: `lip` (organic rim or lip), `collar`, `variable`.
- `aperture_narrow`: shape of the aperture in frontal or narrow view (`oval`,
  `elliptical`, `circular-ovoid`, `ovoid`, `notched` = notched in profile,
  `variable`).
- `compression`: `compressed`, `variable`.
- `outline_broad`: the outline in broad view, in the words of the monograph
  (e.g. `piriform`, `elongated-piriform`, `lageniform`, `variable`).
- `fundus_broad`: `rounded`.
- `length_min_um`, `length_max_um`: the extremes of the species ranges given
  in the monograph; `size_note`: the ranges behind them (per species or per author).
- `diagnostic_vs`: the genera it is most often confused with, and the
  character that separates them.

`outline_broad`, the lengths and `diagnostic_vs` are for reading only: they
are not copied to the specimens (the outline and the size are measured).

## 2. Characters and their class

| Character | Definition | Genera with it (K25) | Class | Columns |
|---|---|---|---|---|
| Size | Aperture to fundus in broad view (K25 Fig. 1) | all; ranges in the table | (i) per specimen | `length_um`, `width_um`, `W/L`, `area_um2` |
| Outline in broad view | circular, piriform, ovoid, drop-shaped, elongated-piriform, lageniform (K25 Fig. 2) | all | (i) | rays `r…`, outline profile `d…`, `W/L`, `widest_position`, `h1`–`h5`, `circularity` |
| Neck | Narrow part ending at the aperture | *Apodera*, *Alocodera*, *Padaungiella*, *Certesella*, *Cornutheca*; some *Hyalosphenia*, *Quadrulella* | (i) | `neck_length_um`, `neck_width_um`, `NL/L`, … |
| Neck distinctness | Abrupt neck–body junction or gradual taper (key steps 8–9) | distinct: *Apodera*, *Alocodera*, *Padaungiella*; gradual: *Longinebela*, *Planocarina*, *Gibbocarina*, *Mrabella*, *Alabasta* | (i) | `neck_jump` |
| Constriction or lateral indentations at the neck base | Deep groove round the neck base (*Apodera*) or two lateral notches (*Alocodera*) | *Apodera*, *Alocodera* | (i) partly | `neck_jump`; holes added by hand at the junction (`n_holes_junction`) |
| Aperture curvature in broad view | Linear, curved, or strongly curved and flared rim | strongly curved: *Alabasta*; linear to slightly curved: *Longinebela*, *Planocarina*, *Mrabella*; varies by species in *Nebela*, *Hyalosphenia*, *Quadrulella*, *Padaungiella* | (i) | `aperture_sag` |
| Aperture width and obliqueness | Width of the opening; bent neck | all; oblique in *Alabasta kivuense*, *Apodera crenata* | (i) | `aperture_width_um`, `AW/W`, `aperture_angle_deg` |
| Horns and lateral expansions | Hollow protrusions: two lateral horns (*Cornutheca*) | *Cornutheca*; small triangular expansions in some *Certesella* | (i) | `n_protrusions`, `protrusion_levels` |
| Lip flare | Rim wider than the neck just behind it | *Alabasta* (flare) | (ii) | — |
| Keel | Flat or hollow flange along the margin and round the fundus | flat: *Planocarina*, *Porosia paracarinata*, *Quadrulella alata*; hollow: *Gibbocarina*, *Mrabella*, *Apodera angatakere*, *Nebela aliciae*, *N. orbicularis*, *Certesella australis* | (ii) presence in broad view; (iii) flat or hollow | — |
| Serrated or tuberous keel, wavy margins | Wavy outline of the keel or of the sides | *Gibbocarina* (tuberous), *Planocarina maxima* (serrated), *Longinebela meisterfeldi* | (i) by hand | bumps added by hand (`n_bumps`) |
| Fundus shape | Rounded or pointed aboral end in broad view | mostly rounded; pointed: *Quadrulella acuminata*, one *Hyalosphenia* | (ii), a species character | — |
| Symmetry and curvature of the test | Left–right asymmetry; bent body | *Alabasta kivuense* (laterally curved) | (i) | `symmetry_index`, `aperture_angle_deg`, `h3` |
| Small lateral pores | Pores 1–3 µm wide at the margin of the broad side, "often difficult to observe" | *Alabasta*, *Alocodera*, *Gibbocarina*, *Mrabella*, *Planocarina*; some *Nebela*, *Longinebela*, *Hyalosphenia*, *Quadrulella* | (i) by hand | holes added by hand (`n_holes`, `outline_features.csv`) |
| Large invaginated pores in depressions | Two large pores (2–5 µm) joined by internal tubes, about 2/3 of the way from the fundus to the aperture | *Certesella*, *Porosia* | (iii) | on the broad face, inside the outline |
| Internal neck teeth | Conical teeth inside the neck, seen as rows of dots in light microscopy | *Certesella* | (iii) | — |
| Shell material | Organic, recycled plates, self-secreted plates | table | (iii) | — |
| Plate shape | Square, round or oval, none | square: *Quadrulella*, *Mrabella*; none: *Hyalosphenia* | (iii) | — |
| Organic rim and its thickness | Lip at the aperture; thickened inwards in some *Hyalosphenia* | most genera | (iii) | — |
| Crenate aperture margin | Aperture bordered by plates | *Apodera crenata* | (iii) mostly | bumps added by hand at the aperture (`n_bumps_aperture`) |
| Compression | Thickness ÷ breadth | almost all compressed; circular section in *H. savoiei*, *L. golemanskyi*, *P. nebeloides*, *P. pulcherrima* | (iii) | needs a lateral view |
| Aperture in narrow or frontal view | Oval, elliptical, circular; notched in profile | notched: *Alabasta* (key character), several *Hyalosphenia* | (iii) | needs a lateral or apertural view |

## 3. Described characters per specimen

The eleven described characters of the table (material, plate shape, lateral
pores, keel, horns and expansions, neck, aperture in broad view, aperture
margin, aperture in narrow view, compression, fundus) are given for every
specimen, in the columns `ch_material` … `ch_fundus_broad` of `summary.csv`
and on the cell figure:

- a specimen whose genus (read from the file name, or set by hand) is in the
  table starts with its genus's values; a blank in the table stays blank;
- any value, and the genus and species themselves, can be set by hand for one
  specimen: in the desktop program, Review > **Characters** (the genus's value
  is shown in brackets, a value set by hand in bold; Undo, and **Back to the
  genus values**); on the command line, in `characters.csv` (columns image,
  name, value). The values allowed:
  - material: proteinaceous, kleptosomic, idiosomic, mixed, variable, unresolved;
  - plate shape: none, round-oval, oval, square, variable;
  - lateral pores: yes, no, variable;
  - keel: no, flat, hollow, variable, rare;
  - horns, expansions: yes, no, variable, rare;
  - neck: distinct, gradual, none or short, variable;
  - aperture in broad view: straight, linear to slightly curved, slightly
    curved, curved, strongly curved, variable;
  - aperture margin: lip, collar, toothed, variable;
  - aperture in narrow view: oval, elliptical, circular, circular-ovoid, ovoid,
    notched, variable;
  - compression: compressed, slightly, not compressed, variable;
  - fundus: rounded, pointed, flat;
- `characters_by_hand` lists the characters set by hand, and `corrections`
  shows `characters` (and `taxon` when the genus or species was set by hand).

"variable" and "rare" are answers at genus level; for a specimen, set the value
seen on it when it can be seen.

## 4. The three genus characters measured per specimen

Each is one number per specimen, computed the same way for every test, with no
label ([METHODS.md](METHODS.md) § 7). Each is empty when the aperture it needs
is missing, and follows the aperture corners and fundus when they are
corrected by hand.

- **`aperture_sag`, curvature of the rim.** The largest signed distance of the
  outline between the two aperture corners from the line joining them, ÷
  aperture width. About 0 for a straight rim, positive for a convex (curved)
  rim, highest for the strongly curved, flared rim of *Alabasta*; negative
  when the rim is sunk between the lips.
- **`neck_jump`, distinctness of the neck.** The largest steepening of the
  width profile between the aperture and the widest section (the neck
  criterion of METHODS § 6), given for every test, also below the 0.5 threshold
  that marks a neck: about 0.5 or less for a gradual taper or no neck
  (negative when the sides never steepen), 1.3–2 for a clear neck–body
  junction, above 2 for a deep constriction or lateral indentations.
- **`n_protrusions` and `protrusion_levels`, horns and spines.** The pieces
  cut off by the opening of the aperture search (a disk of 0.06 × the test's
  minor axis, METHODS § 4) that are longer than twice its radius, with the
  level of each along the oral–aboral axis (0 = aperture plane, 1 = fundus).
  Pieces reaching below 0.1 belong to the aperture end (lips, teeth) and are
  left out. Smooth tests give 0; the lateral horns of *Cornutheca* lie at mid
  length. Horns joined to the body by a keel are not free protrusions in a
  2D outline and are not counted; spines broken off the specimen lower the
  count.

## 5. Caveats

- The size ranges are the extremes of the species ranges in the monograph,
  including outlying literature values (e.g. *Apodera vas* reported at
  90–234 µm). They are not population statistics.
- *Cornutheca* keel: the description says "hollow keel" and the key says
  "flat extension similar to the keel of *Planocarina*" (K25 p.37 and p.68).
  Both are given in the note.
- Every value cites its page; check a value against the page before relying
  on it.

## Reference

- Kosakyan A., Meisterfeld R., Lara E., Duckert C., Mitchell E.A.D. (2025). A
  taxonomic monograph of hyalospheniid testate amoebae (Amoebozoa: Arcellinida:
  Hyalospheniformes). Mémoires de la Société neuchâteloise des sciences
  naturelles, tome XIV. Alphil-Presses universitaires suisses, Neuchâtel.
  https://doi.org/10.33055/alphil.00614
