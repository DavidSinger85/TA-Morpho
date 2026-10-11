# TA-Morpho validation: agreement with manual measurement (Fiji) and repeatability, three replicates.
#
# Inputs (data/):
#   fiji_measurements.csv  one blind manual pass per replicate (Fiji, straight lines, scale set on the
#                          printed bar); values in um, or in px of the picture for the 5 drawings without
#                          a scale (only their ratios are used)
#   app_results.csv        TA-Morpho on the same pictures (default settings, no correction; 2_run_app.py)
#   transforms.csv         resize factor, angle and flip of replicates 2 and 3 (1_make_pictures.py)
# Outputs:
#   results/manuscript/    Table_1_repeatability_agreement.csv
#                          (Figure_1_app_output.png is written by 2_run_app.py)
#   results/supplementary/ Figures S1-S3, Tables S1-S4, session_info.txt
#
# Measures: scale bar (px, brought back to the published picture size: px / factor), length, width,
# aperture width (um; the 19 pictures with a scale), W/L and AW/L (all 24 pictures).
#
# Agreement (app - Fiji), per replicate and on the means of the three replicates: bias with its 95 % CI,
# limits of agreement (bias +- 1.96 SD), both in the unit and in % of the mean of the two methods
# (Bland & Altman 1986); Lin's concordance correlation coefficient (CCC).
# Repeatability, per method and measure, over the pictures measured in every replicate: within-picture
# SD s_i and CV_i = 100 s_i / mean_i; Sw = sqrt(mean s_i^2); CVw = sqrt(mean CV_i^2) (root-mean-square CV);
# repeatability coefficient RC = 2.77 Sw (95 % of differences between two replicates are below it);
# ICC(2,1) (two-way random, absolute agreement, single measurement); shift of replicates 2 and 3 from
# replicate 1 in % of the picture mean, with its 95 % CI. Manual vs app: ratio of the CVw with a bootstrap
# 95 % CI over pictures (5000 resamples) and a Wilcoxon signed-rank test on the per-picture CVs.
#
#   Rscript data/validation/scripts/3_analysis.R        (R >= 4.1, package ggplot2)

suppressPackageStartupMessages(library(ggplot2))

validation <- local({   # the folder above scripts/
  f <- sub("^--file=", "", grep("^--file=", commandArgs(FALSE), value = TRUE))
  dirname(dirname(normalizePath(if (length(f)) f else "scripts/3_analysis.R")))
})
data_dir <- file.path(validation, "data")
main_dir <- file.path(validation, "results", "manuscript")
supp_dir <- file.path(validation, "results", "supplementary")
for (d in c(main_dir, supp_dir)) dir.create(d, recursive = TRUE, showWarnings = FALSE)
save_figure <- function(fig, dir, name, width, height) {
  ggsave(file.path(dir, paste0(name, ".png")), fig, width = width, height = height, units = "cm", dpi = 300)
  ggsave(file.path(dir, paste0(name, ".pdf")), fig, width = width, height = height, units = "cm")
}

MEASURES <- data.frame(
  measure = c("Scale bar", "Length", "Width", "Aperture width", "W/L", "AW/L"),
  unit = c("px", "um", "um", "um", "ratio", "ratio"),
  pictures = c("scaled", "scaled", "scaled", "scaled", "all", "all")
)
FIGURE_MEASURES <- c("Scale bar", "Length", "Width", "Aperture width")   # in Table 1 and Figure S1
COLOURS <- c(manual = "#2a78d6", app = "#eb6834")
LABELS <- c(manual = "By hand (Fiji)", app = "TA-Morpho")

# ---- data -------------------------------------------------------------------------------------------
fiji <- read.csv(file.path(data_dir, "fiji_measurements.csv"), check.names = FALSE)
app <- read.csv(file.path(data_dir, "app_results.csv"), check.names = FALSE)
transforms <- read.csv(file.path(data_dir, "transforms.csv"), check.names = FALSE)

factor_of <- function(replicate, image) {
  s <- transforms$scale[match(paste(replicate, image), paste(transforms$replicate, transforms$image))]
  ifelse(replicate == 1, 1, s)
}
app$id <- sub(".*_(P[0-9]{5}|TB[0-9]+[A-Z]).*", "\\1", app$image)

manual <- with(fiji, data.frame(
  method = "manual", replicate, id,
  "Scale bar" = bar_px / factor_of(replicate, image), "Length" = length, "Width" = width,
  "Aperture width" = aperture, "W/L" = width / length, "AW/L" = aperture / length, check.names = FALSE))
automatic <- with(app, data.frame(
  method = "app", replicate, id,
  "Scale bar" = px_per_um * bar_length_um / factor_of(replicate, image), "Length" = length_um,
  "Width" = width_um, "Aperture width" = aperture_width_um, "W/L" = `W/L`, "AW/L" = `AW/L`,
  check.names = FALSE))
scaled_ids <- unique(fiji$id[fiji$unit == "um"])

# pictures x replicates, for one method and measure (pictures with a value in every replicate)
values <- function(d, measure, pictures) {
  x <- tapply(d[[measure]], list(d$id, d$replicate), function(v) v[1])
  if (pictures == "scaled") x <- x[rownames(x) %in% scaled_ids, , drop = FALSE]
  x[complete.cases(x), , drop = FALSE]
}
both <- function(measure, pictures) {  # the same pictures for both methods
  m <- values(manual, measure, pictures)
  a <- values(automatic, measure, pictures)
  ids <- intersect(rownames(m), rownames(a))
  list(manual = m[ids, , drop = FALSE], app = a[ids, , drop = FALSE])
}

# ---- statistics -------------------------------------------------------------------------------------
ccc <- function(x, y) 2 * cov(x, y) / (var(x) + var(y) + (mean(x) - mean(y))^2)

icc_2_1 <- function(x) {
  n <- nrow(x); k <- ncol(x); g <- mean(x)
  msr <- k * sum((rowMeans(x) - g)^2) / (n - 1)
  msc <- n * sum((colMeans(x) - g)^2) / (k - 1)
  res <- x - outer(rowMeans(x), rep(1, k)) - outer(rep(1, n), colMeans(x)) + g
  mse <- sum(res^2) / ((n - 1) * (k - 1))
  (msr - mse) / (msr + (k - 1) * mse + k * (msc - mse) / n)
}

agreement_row <- function(a, f) {
  d <- a - f
  p <- 100 * d / ((a + f) / 2)
  n <- length(d)
  half <- qt(0.975, n - 1) * sd(d) / sqrt(n)
  data.frame(n = n, bias = mean(d), bias_ci_low = mean(d) - half, bias_ci_high = mean(d) + half,
             loa_low = mean(d) - 1.96 * sd(d), loa_high = mean(d) + 1.96 * sd(d),
             bias_pct = mean(p), loa_low_pct = mean(p) - 1.96 * sd(p), loa_high_pct = mean(p) + 1.96 * sd(p),
             median_abs_pct = median(abs(p)), within_5pct = sum(abs(p) <= 5),
             largest_pct = names(p)[which.max(abs(p))], ccc = ccc(a, f))
}

agreement <- do.call(rbind, lapply(seq_len(nrow(MEASURES)), function(i) {
  x <- both(MEASURES$measure[i], MEASURES$pictures[i])
  reps <- colnames(x$manual)
  rows <- lapply(c(reps, "mean"), function(r) {
    pick <- function(m) if (r == "mean") rowMeans(m) else m[, r]
    cbind(data.frame(measure = MEASURES$measure[i], unit = MEASURES$unit[i], replicate = r),
          agreement_row(pick(x$app), pick(x$manual)))
  })
  do.call(rbind, rows)
}))

set.seed(1)
per_picture <- list()
repeatability <- do.call(rbind, lapply(seq_len(nrow(MEASURES)), function(i) {
  name <- MEASURES$measure[i]
  x <- both(name, MEASURES$pictures[i])
  cv <- lapply(x, function(m) 100 * apply(m, 1, sd) / rowMeans(m))
  boot <- replicate(5000, {
    j <- sample(length(cv$manual), replace = TRUE)
    sqrt(mean(cv$manual[j]^2)) / sqrt(mean(cv$app[j]^2))
  })
  wilcox_p <- suppressWarnings(wilcox.test(cv$manual, cv$app, paired = TRUE)$p.value)
  rows <- lapply(names(x), function(method) {
    m <- x[[method]]
    s <- apply(m, 1, sd)
    mean_i <- rowMeans(m)
    per_picture[[paste(name, method)]] <<- data.frame(
      measure = name, method = method, id = rownames(m), m, mean = mean_i, cv_pct = cv[[method]],
      check.names = FALSE)
    shifts <- do.call(cbind, lapply(colnames(m)[-1], function(r) {
      d <- 100 * (m[, r] - m[, 1]) / mean_i
      half <- qt(0.975, length(d) - 1) * sd(d) / sqrt(length(d))
      setNames(data.frame(mean(d), half), paste0(c("shift_r", "shift_ci_r"), r, "_pct"))
    }))
    sw <- sqrt(mean(s^2))
    cvw <- sqrt(mean(cv[[method]]^2))
    cbind(data.frame(measure = name, unit = MEASURES$unit[i], method = method, n = nrow(m),
                     replicates = ncol(m), Sw = sw, CVw_pct = cvw, median_cv_pct = median(cv[[method]]),
                     max_cv_pct = max(cv[[method]]), largest = names(which.max(cv[[method]])),
                     RC = 2.77 * sw, RC_pct = 2.77 * cvw, ICC = icc_2_1(m)),
          shifts,
          data.frame(cv_ratio_manual_app = sqrt(mean(cv$manual^2)) / sqrt(mean(cv$app^2)),
                     ratio_ci_low = unname(quantile(boot, 0.025)), ratio_ci_high = unname(quantile(boot, 0.975)),
                     wilcoxon_p = wilcox_p, pictures_manual_more_variable = sum(cv$manual > cv$app)))
  })
  do.call(rbind, rows)
}))
per_picture <- do.call(rbind, per_picture)

status <- reshape(app[, c("id", "image", "replicate", "status")], idvar = c("id", "image"),
                  timevar = "replicate", direction = "wide")
names(status) <- sub("^status\\.", "status_replicate_", names(status))

# ---- tables ------------------------------------------------------------------------------------------
round_df <- function(d) { num <- vapply(d, is.numeric, TRUE); d[num] <- lapply(d[num], signif, 5); d }

# Table 1 (manuscript): repeatability and agreement of the four measures, in words a reader can quote
signed <- function(v) sprintf("%+.1f", v)
table1 <- do.call(rbind, lapply(FIGURE_MEASURES, function(name) {
  r <- repeatability[repeatability$measure == name, ]
  h <- r[r$method == "manual", ]; a <- r[r$method == "app", ]
  g <- agreement[agreement$measure == name & agreement$replicate == "mean", ]
  data.frame(
    "Measure" = name, "Unit" = h$unit, "Pictures" = h$n,
    "By hand: CVw (%)" = sprintf("%.2g", h$CVw_pct), "TA-Morpho: CVw (%)" = sprintf("%.2g", a$CVw_pct),
    "Ratio by hand / TA-Morpho (95% CI)" = sprintf("%.1f (%.1f-%.1f)", h$cv_ratio_manual_app, h$ratio_ci_low,
                                                   h$ratio_ci_high),
    "Wilcoxon p" = ifelse(h$wilcoxon_p < 0.001, "< 0.001", sprintf("%.2f", h$wilcoxon_p)),
    "TA-Morpho - by hand: mean difference (%)" = signed(g$bias_pct),
    "95% limits of agreement (%)" = paste(signed(g$loa_low_pct), "to", signed(g$loa_high_pct)),
    check.names = FALSE)
}))
write.csv(table1, file.path(main_dir, "Table_1_repeatability_agreement.csv"), row.names = FALSE)
write.csv(round_df(repeatability), file.path(supp_dir, "Table_S1_repeatability_full.csv"), row.names = FALSE)
write.csv(round_df(agreement), file.path(supp_dir, "Table_S2_agreement_full.csv"), row.names = FALSE)
write.csv(round_df(per_picture), file.path(supp_dir, "Table_S3_values_per_picture.csv"), row.names = FALSE)
write.csv(status[order(status$image), ], file.path(supp_dir, "Table_S4_app_status.csv"), row.names = FALSE)

# ---- figures -----------------------------------------------------------------------------------------
facet_order <- function(d) { d$measure <- factor(d$measure, levels = MEASURES$measure); d }
theme_set(theme_classic(base_size = 9) +
            theme(strip.background = element_blank(), strip.text = element_text(hjust = 0, size = 9),
                  panel.grid.major.y = element_line(colour = "#e6e6e6", linewidth = 0.3),
                  plot.title = element_text(size = 9.5)))

# Figure S2 (supplementary): Bland-Altman, means of the three replicates
ba <-facet_order(do.call(rbind, lapply(seq_len(nrow(MEASURES)), function(i) {
  x <- both(MEASURES$measure[i], MEASURES$pictures[i])
  a <- rowMeans(x$app); f <- rowMeans(x$manual)
  data.frame(measure = MEASURES$measure[i], id = names(a), mean = (a + f) / 2, pct = 100 * (a - f) / ((a + f) / 2))
})))
lines <- facet_order(agreement[agreement$replicate == "mean", c("measure", "n", "bias_pct", "loa_low_pct", "loa_high_pct")])
titles <- setNames(sprintf("%s (n = %d)\nbias %+.1f %%, LoA %+.1f to %+.1f %%", lines$measure, lines$n,
                           lines$bias_pct, lines$loa_low_pct, lines$loa_high_pct), lines$measure)
outside <- merge(ba, lines)
outside <- outside[outside$pct < outside$loa_low_pct | outside$pct > outside$loa_high_pct, ]
fig_s2 <- ggplot(ba, aes(mean, pct)) +
  geom_hline(yintercept = 0, colour = "#bbbbbb", linewidth = 0.4) +
  geom_hline(data = lines, aes(yintercept = bias_pct), colour = "#c0392b", linewidth = 0.5) +
  geom_hline(data = lines, aes(yintercept = loa_low_pct), colour = "#c0392b", linewidth = 0.4, linetype = "dashed") +
  geom_hline(data = lines, aes(yintercept = loa_high_pct), colour = "#c0392b", linewidth = 0.4, linetype = "dashed") +
  geom_point(colour = "#0b7d79", size = 1.6) +
  geom_text(data = outside, aes(label = id), size = 2.3, hjust = 1.2, vjust = 0.4) +
  scale_y_continuous(expand = expansion(mult = 0.1)) +
  scale_x_continuous(expand = expansion(mult = 0.08)) +
  facet_wrap(~measure, scales = "free", labeller = as_labeller(titles)) +
  labs(x = "mean of app and Fiji (px, um or ratio)", y = "app - Fiji (% of mean)",
       title = "TA-Morpho vs manual measurement in Fiji (Bland-Altman, means of three replicates)")
save_figure(fig_s2, supp_dir, "Figure_S2_agreement_Bland_Altman", 18, 11.5)

# Figure S3 (supplementary): per-picture CV over the replicates, Fiji vs app
set.seed(2)
cvs <- facet_order(per_picture[, c("measure", "method", "id", "cv_pct")])
jitter <- setNames(runif(length(unique(cvs$id)), -0.12, 0.12), unique(cvs$id))
cvs$x <- ifelse(cvs$method == "manual", 1, 2) + jitter[cvs$id]
medians <- facet_order(aggregate(cv_pct ~ measure + method, cvs, median))
medians$x <- ifelse(medians$method == "manual", 1, 2)
cvw <- facet_order(repeatability[, c("measure", "method", "CVw_pct", "n")])
cvw$x <- ifelse(cvw$method == "manual", 1, 2)
cvw$label <- sprintf("CVw %.2g %%", cvw$CVw_pct)
fig_s3 <- ggplot(cvs, aes(x, cv_pct)) +
  geom_line(aes(group = id), colour = "#c9c9c9", linewidth = 0.3) +
  geom_point(aes(colour = method, shape = method), size = 1.8) +
  geom_segment(data = medians, aes(x = x - 0.3, xend = x + 0.3, y = cv_pct, yend = cv_pct),
               colour = "#333333", linewidth = 0.7) +
  geom_text(data = cvw, aes(x = x, y = 40, label = label), size = 2.5) +
  scale_colour_manual(values = COLOURS, labels = LABELS) +
  scale_shape_manual(values = c(manual = 16, app = 17), labels = LABELS) +
  scale_x_continuous(breaks = 1:2, labels = LABELS[c("manual", "app")], limits = c(0.5, 2.5)) +
  scale_y_log10(breaks = c(0.001, 0.01, 0.1, 1, 10), labels = c("0.001", "0.01", "0.1", "1", "10"),
                limits = c(0.001, 60)) +
  facet_wrap(~measure) +
  labs(x = NULL, y = "CV over the replicates (%)",
       title = "Repeatability: one dot per picture, grey lines join the same picture, black bars = median") +
  theme(legend.position = "none")
save_figure(fig_s3, supp_dir, "Figure_S3_repeatability_CV_per_picture", 18, 11.5)

# Figure S1 (supplementary): each measurement as a difference from the specimen's average
reps <- intersect(c("1", "2", "3"), names(per_picture))
dots <- do.call(rbind, lapply(reps, function(r)
  data.frame(per_picture[c("measure", "method", "id")], pct = 100 * (per_picture[[r]] / per_picture$mean - 1))))
dots <- dots[dots$measure %in% FIGURE_MEASURES, ]
dots$measure <- factor(dots$measure, levels = FIGURE_MEASURES)
size <- with(per_picture[per_picture$measure == "Length" & per_picture$method == "manual", ], setNames(mean, id))
size_order <- names(sort(size))
dots$x <- match(dots$id, size_order) + ifelse(dots$method == "manual", -0.18, 0.18)
spans <- aggregate(pct ~ measure + method + id + x, dots, function(v) c(lo = min(v), hi = max(v)))
spans <- data.frame(spans[1:4], lo = spans$pct[, "lo"], hi = spans$pct[, "hi"])
fig_s1 <- ggplot(dots, aes(x, pct, colour = method)) +
  geom_hline(yintercept = 0, colour = "#999999", linewidth = 0.3) +
  geom_segment(data = spans, aes(x = x, xend = x, y = lo, yend = hi), linewidth = 0.5, alpha = 0.5) +
  geom_point(aes(shape = method), size = 1.5) +
  scale_colour_manual(values = COLOURS, labels = LABELS, breaks = c("manual", "app")) +
  scale_shape_manual(values = c(manual = 16, app = 17), labels = LABELS, breaks = c("manual", "app")) +
  scale_x_continuous(breaks = seq_along(size_order), labels = size_order, expand = expansion(add = 0.6)) +
  facet_wrap(~measure, ncol = 1) +
  labs(x = "specimen (pictures with a scale bar, from the smallest to the largest test)",
       y = "difference from the specimen's average (%)") +
  theme(legend.position = "top", legend.title = element_blank(),
        axis.text.x = element_text(angle = 90, vjust = 0.5, hjust = 1, size = 7),
        strip.text = element_text(face = "bold"))
save_figure(fig_s1, supp_dir, "Figure_S1_repeatability_per_specimen", 17, 20)

session <- capture.output(sessionInfo())
session <- gsub("(/|[A-Za-z]:\\\\)[^ ;]*[/\\\\]", "", session)   # library file names only, no local folders
writeLines(session, file.path(supp_dir, "session_info.txt"))

# ---- summary -----------------------------------------------------------------------------------------
options(width = 200)
cat("\nRepeatability\n")
print(round_df(repeatability[, c("measure", "method", "n", "CVw_pct", "median_cv_pct", "RC_pct", "ICC",
                                  "cv_ratio_manual_app", "ratio_ci_low", "ratio_ci_high", "wilcoxon_p")]),
      row.names = FALSE, digits = 3)
cat("\nAgreement app - Fiji (%)\n")
print(round_df(agreement[, c("measure", "replicate", "n", "bias_pct", "loa_low_pct", "loa_high_pct",
                             "within_5pct", "ccc")]), row.names = FALSE, digits = 3)
cat("\nTable 1\n")
print(table1, row.names = FALSE)
cat("\nResults in", file.path(validation, "results"), "\n")
