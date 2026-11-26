"""
Electricity data audit: West & sub-Saharan Africa
Source: Our World in Data energy dataset (electricity series built on Ember + Energy Institute data)
https://github.com/owid/energy-data

Runs reproducible data-quality checks on the electricity generation series,
then produces a short analysis of Nigeria's and Africa's power mix.
"""
from pathlib import Path
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).parent
DATA = ROOT / "data" / "owid-energy-data.csv"
OUT = ROOT / "outputs"
OUT.mkdir(exist_ok=True)

SOURCES = ["coal", "gas", "oil", "nuclear", "hydro", "wind", "solar", "biofuel", "other_renewable_exc_biofuel"]
SRC_COLS = [f"{s}_electricity" for s in SOURCES]

AFRICA_SSA = ["NGA", "GHA", "CIV", "SEN", "CMR", "KEN", "ETH", "TZA", "UGA", "ZAF", "AGO", "MOZ", "ZMB", "ZWE", "COD", "SDN", "BEN", "TGO", "NER", "MLI", "BFA", "GIN", "SLE", "LBR", "RWA", "MWI", "NAM", "BWA", "GAB", "COG"]

if not DATA.exists():
    DATA.parent.mkdir(exist_ok=True)
    import urllib.request
    urllib.request.urlretrieve("https://raw.githubusercontent.com/owid/energy-data/master/owid-energy-data.csv", DATA)
df = pd.read_csv(DATA)
countries = df[df["iso_code"].notna() & ~df["iso_code"].astype(str).str.startswith("OWID")].copy()
elec = countries[countries["year"] >= 2000].copy()

issues = []

# 1. Sum of sources vs reported total generation
has_all = elec.dropna(subset=["electricity_generation"])
src_sum = has_all[SRC_COLS].sum(axis=1, min_count=1)
gap = (src_sum - has_all["electricity_generation"])
rel = gap / has_all["electricity_generation"].where(has_all["electricity_generation"] > 0)
mask = (rel.abs() > 0.02) & (has_all["electricity_generation"] > 0.5)
for idx in has_all[mask].index:
    r = has_all.loc[idx]
    issues.append({"check": "sources_do_not_sum_to_total", "country": r["country"], "iso": r["iso_code"], "year": int(r["year"]),
                   "detail": f"sum of sources {src_sum[idx]:.2f} TWh vs total {r['electricity_generation']:.2f} TWh ({rel[idx]*100:+.1f}%)"})

# 2. Missing source breakdown where a total exists
missing_src = has_all[has_all[SRC_COLS].isna().all(axis=1)]
for _, r in missing_src.iterrows():
    issues.append({"check": "total_without_source_breakdown", "country": r["country"], "iso": r["iso_code"], "year": int(r["year"]),
                   "detail": f"total {r['electricity_generation']:.2f} TWh but no fuel breakdown"})

# 3. Interior gaps in the generation series
for iso, g in elec.groupby("iso_code"):
    yrs = g.loc[g["electricity_generation"].notna(), "year"].astype(int).sort_values().tolist()
    if len(yrs) < 2:
        continue
    missing = sorted(set(range(yrs[0], yrs[-1] + 1)) - set(yrs))
    if missing:
        issues.append({"check": "interior_year_gaps", "country": g["country"].iloc[0], "iso": iso, "year": missing[0],
                       "detail": f"missing years {missing}"})

# 4. Implausible year-over-year jumps (>40%) for systems above 1 TWh
elec = elec.sort_values(["iso_code", "year"])
elec["gen_prev"] = elec.groupby("iso_code")["electricity_generation"].shift()
elec["yoy"] = elec["electricity_generation"] / elec["gen_prev"] - 1
jumps = elec[(elec["gen_prev"] > 1) & (elec["yoy"].abs() > 0.40)]
for _, r in jumps.iterrows():
    issues.append({"check": "yoy_jump_over_40pct", "country": r["country"], "iso": r["iso_code"], "year": int(r["year"]),
                   "detail": f"{r['gen_prev']:.2f} -> {r['electricity_generation']:.2f} TWh ({r['yoy']*100:+.0f}%)"})

# 5. Demand lower than generation by >15% (implies large net exports) - worth verifying
d = elec.dropna(subset=["electricity_demand", "electricity_generation"])
d = d[d["electricity_generation"] > 1]
net = (d["electricity_demand"] - d["electricity_generation"]) / d["electricity_generation"]
for idx in d[net < -0.15].index:
    r = d.loc[idx]
    issues.append({"check": "demand_far_below_generation", "country": r["country"], "iso": r["iso_code"], "year": int(r["year"]),
                   "detail": f"demand {r['electricity_demand']:.2f} vs generation {r['electricity_generation']:.2f} TWh"})


# 6. Net imports recorded as exactly zero (often "missing" stored as 0) and values carried forward unchanged
ni = elec.dropna(subset=["net_elec_imports"])
ni = ni[ni["electricity_generation"] > 1]
for iso, g in ni.groupby("iso_code"):
    g = g.sort_values("year")
    zeros = g.loc[g["net_elec_imports"] == 0, "year"].astype(int).tolist()
    nonzero = (g["net_elec_imports"] != 0).any()
    if zeros and nonzero:
        issues.append({"check": "net_imports_zero_then_nonzero", "country": g["country"].iloc[0], "iso": iso, "year": zeros[0],
                       "detail": f"net imports exactly 0 in {zeros[0]}-{zeros[-1]} ({len(zeros)} yrs) but non-zero in other years"})
    rep = g[(g["net_elec_imports"] != 0) & (g["net_elec_imports"].diff() == 0)]
    for _, r in rep.iterrows():
        issues.append({"check": "net_imports_repeated_exactly", "country": r["country"], "iso": iso, "year": int(r["year"]),
                       "detail": f"net imports {r['net_elec_imports']:.2f} TWh identical to previous year (possible carry-forward)"})

iss = pd.DataFrame(issues).sort_values(["check", "country", "year"])
iss.to_csv(OUT / "quality_issues_all_countries.csv", index=False)
ssa_iss = iss[iss["iso"].isin(AFRICA_SSA)]
ssa_iss.to_csv(OUT / "quality_issues_sub_saharan_africa.csv", index=False)
summary = iss.groupby("check").size().rename("all_countries").to_frame().join(
    ssa_iss.groupby("check").size().rename("sub_saharan_sample")).fillna(0).astype(int)
summary.to_csv(OUT / "quality_summary.csv")

# ---------- Analysis: Nigeria mix ----------
ng = elec[elec["iso_code"] == "NGA"].set_index("year")
latest_ng = int(ng["electricity_generation"].dropna().index.max())
mix_cols = ["gas_electricity", "hydro_electricity", "oil_electricity", "solar_electricity", "coal_electricity"]
fig, ax = plt.subplots(figsize=(9, 4.8))
ng.loc[2000:latest_ng, mix_cols].fillna(0).rename(columns=lambda c: c.replace("_electricity", "").title()).plot.area(ax=ax, linewidth=0, alpha=0.9)
ax.set_title(f"Nigeria grid electricity generation by source, 2000-{latest_ng} (TWh)")
ax.set_ylabel("TWh"); ax.set_xlabel("")
ax.spines[["top", "right"]].set_visible(False)
fig.tight_layout(); fig.savefig(OUT / "nigeria_generation_mix.png", dpi=150); plt.close(fig)


# Nigeria net imports: zero-vs-missing illustration
fig, ax = plt.subplots(figsize=(9, 3.8))
ni_ng = ng.loc[2000:latest_ng, "net_elec_imports"]
ax.bar(ni_ng.index, ni_ng.values, color=["#bbbbbb" if v == 0 else "#1f77b4" for v in ni_ng.values])
ax.axhline(0, color="black", linewidth=0.8)
z = ni_ng[ni_ng == 0]
ax.scatter(z.index, z.values, marker="x", color="#d62728", zorder=3, label="recorded as exactly 0")
ax.legend(frameon=False, loc="lower left")
ax.set_title("Nigeria net electricity imports in the dataset (TWh; negative = exports)")
ax.spines[["top", "right"]].set_visible(False)
fig.tight_layout(); fig.savefig(OUT / "nigeria_net_imports_zero_vs_missing.png", dpi=150); plt.close(fig)

# Per-capita comparison, latest common year
pc = elec[elec["iso_code"].isin(AFRICA_SSA)].dropna(subset=["per_capita_electricity"])
pc_latest = pc.loc[pc.groupby("iso_code")["year"].idxmax(), ["country", "year", "per_capita_electricity"]].sort_values("per_capita_electricity")
fig, ax = plt.subplots(figsize=(8, 8))
colors = ["#d62728" if c == "Nigeria" else "#7f7f7f" for c in pc_latest["country"]]
ax.barh(pc_latest["country"], pc_latest["per_capita_electricity"], color=colors)
ax.set_title("Electricity generation per person, sub-Saharan sample (kWh, latest year)")
ax.set_xscale("log"); ax.spines[["top", "right"]].set_visible(False)
fig.tight_layout(); fig.savefig(OUT / "ssa_per_capita_generation.png", dpi=150); plt.close(fig)

# Solar growth in SSA sample
ssa = elec[elec["iso_code"].isin(AFRICA_SSA)]
coverage = ssa.dropna(subset=["electricity_generation"]).groupby("year")["iso_code"].nunique().rename("countries_reporting")
coverage.to_csv(OUT / "ssa_reporting_coverage_by_year.csv")
# Balanced panel: only countries that report in every year 2015..last year with full coverage,
# so a partial latest year does not distort the aggregate share.
full_years = coverage[coverage == coverage.max()].index
last_full = int(full_years.max())
panel_isos = ssa[(ssa["year"].between(2015, last_full)) & ssa["electricity_generation"].notna()].groupby("iso_code")["year"].nunique()
panel_isos = panel_isos[panel_isos == (last_full - 2015 + 1)].index
sol = ssa[ssa["iso_code"].isin(panel_isos) & ssa["year"].between(2015, last_full)].groupby("year")[["solar_electricity", "electricity_generation"]].sum(min_count=1)
sol["solar_share_pct"] = sol["solar_electricity"] / sol["electricity_generation"] * 100
sol.to_csv(OUT / "ssa_solar_share_by_year.csv")

ng_latest = ng.loc[latest_ng]
facts = {
    "nigeria_latest_year": latest_ng,
    "nigeria_generation_twh": round(float(ng_latest["electricity_generation"]), 2),
    "nigeria_gas_share_pct": round(float(ng_latest["gas_share_elec"]), 1),
    "nigeria_hydro_share_pct": round(float(ng_latest["hydro_share_elec"]), 1),
    "nigeria_solar_share_pct": round(float(ng_latest["solar_share_elec"]), 2) if pd.notna(ng_latest["solar_share_elec"]) else None,
    "nigeria_kwh_per_person": round(float(ng_latest["per_capita_electricity"]), 0),
    "ssa_solar_share_2015_pct": round(float(sol.loc[2015, "solar_share_pct"]), 2),
    "ssa_solar_share_latest_pct": round(float(sol["solar_share_pct"].dropna().iloc[-1]), 2),
    "ssa_solar_latest_year": int(sol["solar_share_pct"].dropna().index[-1]),
    "ssa_panel_countries": int(len(panel_isos)),
    "ssa_countries_reporting_2025": int(coverage.get(2025, 0)),
    "ssa_countries_reporting_max": int(coverage.max()),
}
pd.Series(facts).to_csv(OUT / "key_facts.csv", header=["value"])
print(summary)
print(pd.Series(facts))
print(ssa_iss.head(25).to_string())
