# Extract the ~30 columns Layer 1 needs from the 560,486 x 972 Yale dataframe.
# Run once:  Rscript data/yale/extract_yale.R
# The full RData expands to ~3.9 GB; pyreadr cannot load it in 11 GB.

load("data/yale/5v_cleandf.RData")
df <- get(ls()[!ls() %in% c("df")][1])
cat("loaded:", nrow(df), "x", ncol(df), "\n")

keep <- c("disposition", "esi", "age", "gender", "race", "ethnicity", "lang",
          "insurance_status", "dep_name", "arrivalmode", "arrivalmonth",
          "arrivalday", "arrivalhour_bin",
          grep("^triage_vital_", names(df), value = TRUE),
          "previousdispo", "n_edvisits", "n_admissions", "n_surgeries")
keep <- intersect(keep, names(df))
cat("keeping", length(keep), "columns\n")

out <- df[, keep]
write.csv(out, "data/yale/yale_triage_slim.csv", row.names = FALSE)
cat("wrote data/yale/yale_triage_slim.csv\n")

# Sanity-check the vitals: the paper's variable table has the hr/sbp/dbp
# descriptions rotated by one row. Trust names only if these ranges look right.
for (v in grep("^triage_vital_", keep, value = TRUE)) {
  x <- suppressWarnings(as.numeric(out[[v]]))
  cat(sprintf("%-28s median %8.1f  [%.0f - %.0f]\n", v,
      median(x, na.rm = TRUE),
      quantile(x, .01, na.rm = TRUE), quantile(x, .99, na.rm = TRUE)))
}
