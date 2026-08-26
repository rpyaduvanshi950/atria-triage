# Extract the ~30 columns Layer 1 needs from the 560,486 x 972 Yale dataframe.
# Run from the repo root:  Rscript data/yale/extract_yale.R   (or: make extract-yale)
#
# The full RData expands to ~3.9 GB, which pyreadr cannot load in 16 GB. R can.

src <- "data/yale/5v_cleandf.RData"
out <- "data/yale/yale_triage_slim.csv"

if (!file.exists(src)) stop("missing ", src, " — see data/README.md")

# load() returns the names of the objects it created. Use that rather than
# guessing: the object in this file happens to be called `df`.
loaded <- load(src)
cat("loaded object(s):", paste(loaded, collapse = ", "), "\n")
d <- get(loaded[1])
cat("dimensions:", nrow(d), "x", ncol(d), "\n")

keep <- c("disposition", "esi", "age", "gender", "race", "ethnicity", "lang",
          "insurance_status", "dep_name", "arrivalmode", "arrivalmonth",
          "arrivalday", "arrivalhour_bin",
          grep("^triage_vital_", names(d), value = TRUE),
          "previousdispo", "n_edvisits", "n_admissions", "n_surgeries")
keep <- intersect(keep, names(d))
missing <- setdiff(c("disposition", "esi", "age"), keep)
if (length(missing)) stop("expected columns absent: ", paste(missing, collapse = ", "))
cat("keeping", length(keep), "columns\n")

write.csv(d[, keep], out, row.names = FALSE)
cat("wrote", out, "\n\n")

# Sanity check. The paper's variable table has the hr / sbp / dbp descriptions
# rotated by one row, so trust the column names only if these ranges look right.
cat("vital sign ranges — check these before building any feature on them:\n")
for (v in grep("^triage_vital_", keep, value = TRUE)) {
  x <- suppressWarnings(as.numeric(d[[v]]))
  if (all(is.na(x))) { cat(sprintf("  %-26s all missing\n", v)); next }
  cat(sprintf("  %-26s median %7.1f   [p1 %6.1f - p99 %6.1f]   missing %4.1f%%\n",
      v, median(x, na.rm = TRUE),
      quantile(x, .01, na.rm = TRUE), quantile(x, .99, na.rm = TRUE),
      100 * mean(is.na(x))))
}

cat("\noutcome:\n")
print(table(d$disposition, useNA = "ifany"))
cat("\nESI distribution:\n")
print(table(d$esi, useNA = "ifany"))
cat("\nhospitals (dep_name):\n")
print(table(d$dep_name, useNA = "ifany"))
