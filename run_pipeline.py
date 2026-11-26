"""Africa Electricity Data Audit: end-to-end pipeline.

1. Fetch OWID energy data (required), Ember yearly data and World Bank WDI (optional, cross-checks)
2. Run data-quality checks in pandas AND in SQL (DuckDB) and assert they agree
3. Cross-validate OWID against Ember and the World Bank
4. Build a balanced panel, statistical projections, static charts and an interactive dashboard

Usage:  python run_pipeline.py
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import duckdb
import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from pipeline import checks, crosscheck, fetch, forecast
from pipeline.dashboard import build_dashboard

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("pipeline")
ROOT = Path(__file__).parent
OUT = ROOT / "outputs"
OUT.mkdir(exist_ok=True)
SSA = fetch.SSA


def main() -> dict:
    # ---------- 1. Load ----------
    owid = fetch.load_owid()
    countries = owid[owid["iso_code"].notna() & ~owid["iso_code"].astype(str).str.startswith("OWID")]
    elec = countries[countries["year"] >= 2000].copy()
    ssa = elec[elec["iso_code"].isin(SSA)].copy()
    ember = fetch.load_ember()
    wb_pop = fetch.load_worldbank("SP.POP.TOTL")
    wb_access = fetch.load_worldbank("EG.ELC.ACCS.ZS")
    sources = {"owid": True, "ember": ember is not None, "worldbank": wb_pop is not None}
    log.info("sources available: %s", sources)

    # ---------- 2. Checks: pandas + SQL ----------
    issues = checks.run_all(elec)

    con = duckdb.connect()
    con.register("elec_df", elec[["iso_code", "country", "year", "electricity_generation", "electricity_demand", "net_elec_imports"]])
    con.execute("CREATE VIEW elec AS SELECT * FROM elec_df")
    con.execute((ROOT / "sql" / "checks.sql").read_text())
    sql_zero = con.execute("SELECT * FROM chk_zero_vs_missing ORDER BY iso_code").df()
    sql_cf = con.execute("SELECT * FROM chk_carried_forward").df()
    sql_yoy = con.execute("SELECT * FROM chk_yoy_jumps").df()
    coverage = con.execute("SELECT * FROM coverage_by_year").df()
    # The two implementations must agree, otherwise one of them has a bug
    agree = {
        "zero_vs_missing": len(sql_zero) == (issues["check"] == "net_imports_zero_then_nonzero").sum(),
        "carried_forward": len(sql_cf) == (issues["check"] == "net_imports_repeated_exactly").sum(),
        "yoy_jumps": len(sql_yoy) == (issues["check"] == "yoy_jump_over_40pct").sum(),
    }
    assert all(agree.values()), f"pandas and SQL checks disagree: {agree}"
    log.info("pandas and SQL checks agree: %s", agree)

    # ---------- 3. Cross-source ----------
    comparison = None
    if ember is not None:
        comparison, x_issues = crosscheck.owid_vs_ember(elec, ember)
        comparison.to_csv(OUT / "owid_vs_ember_comparison.csv", index=False)
        issues = pd.concat([issues, x_issues], ignore_index=True)
    if wb_pop is not None:
        issues = pd.concat([issues, crosscheck.owid_vs_worldbank_population(elec, wb_pop)], ignore_index=True)

    issues.to_csv(OUT / "quality_issues_all_countries.csv", index=False)
    ssa_issues = issues[issues["iso"].isin(SSA)]
    ssa_issues.to_csv(OUT / "quality_issues_sub_saharan_africa.csv", index=False)
    summary = (issues.groupby("check").size().rename("all_countries").to_frame()
               .join(ssa_issues.groupby("check").size().rename("sub_saharan_sample")).fillna(0).astype(int))
    summary.to_csv(OUT / "quality_summary.csv")

    # ---------- 4. Analysis ----------
    ssa_cov = ssa.dropna(subset=["electricity_generation"]).groupby("year")["iso_code"].nunique()
    ssa_cov.rename("countries_reporting").to_csv(OUT / "ssa_reporting_coverage_by_year.csv")
    last_full = int(ssa_cov[ssa_cov == ssa_cov.max()].index.max())
    n_years = last_full - 2015 + 1
    panel = ssa[ssa["year"].between(2015, last_full) & ssa["electricity_generation"].notna()]
    panel_isos = panel.groupby("iso_code")["year"].nunique().loc[lambda s: s == n_years].index
    bal = (ssa[ssa["iso_code"].isin(panel_isos) & ssa["year"].between(2015, last_full)]
           .groupby("year")[["solar_electricity", "electricity_generation"]].sum(min_count=1))
    bal["solar_share_pct"] = bal["solar_electricity"] / bal["electricity_generation"] * 100
    naive = ssa.groupby("year")[["solar_electricity", "electricity_generation"]].sum(min_count=1)
    naive["solar_share_pct"] = naive["solar_electricity"] / naive["electricity_generation"] * 100
    solar = bal[["solar_share_pct"]].rename(columns={"solar_share_pct": "balanced_panel"}).join(
        naive[["solar_share_pct"]].rename(columns={"solar_share_pct": "naive_sum"}), how="outer")
    solar.to_csv(OUT / "ssa_solar_share_balanced_vs_naive.csv")

    solar_fc = forecast.trend_projection(bal["solar_share_pct"], log=True)
    solar_fc.to_csv(OUT / "ssa_solar_share_projection_2030.csv", index=False)

    ng = elec[elec["iso_code"] == "NGA"].set_index("year")
    latest_ng = int(ng["electricity_generation"].dropna().index.max())
    ng_fc = forecast.trend_projection(ng.loc[2010:latest_ng, "electricity_generation"])
    ng_fc.to_csv(OUT / "nigeria_generation_projection_2030.csv", index=False)

    access = None
    if wb_access is not None and wb_pop is not None:
        a = wb_access.rename(columns={"value": "access_pct"}).merge(wb_pop.rename(columns={"value": "pop"}), on=["iso", "year"])
        a = a.merge(ssa[["iso_code", "country", "year", "electricity_generation"]], left_on=["iso", "year"], right_on=["iso_code", "year"])
        a["kwh_per_connected_person"] = a["electricity_generation"] * 1e9 / (a["pop"] * a["access_pct"] / 100)
        a.to_csv(OUT / "ssa_access_and_generation_per_connected_person.csv", index=False)
        access = a

    # ---------- 5. Static charts (README) ----------
    _static_charts(ng, latest_ng, ssa, solar, solar_fc, comparison)

    # ---------- 6. Dashboard ----------
    ng_row = ng.loc[latest_ng]
    facts = {
        "nigeria_latest_year": latest_ng,
        "nigeria_generation_twh": round(float(ng_row["electricity_generation"]), 2),
        "nigeria_gas_share_pct": round(float(ng_row["gas_share_elec"]), 1),
        "nigeria_hydro_share_pct": round(float(ng_row["hydro_share_elec"]), 1),
        "nigeria_kwh_per_person": round(float(ng_row["per_capita_electricity"])),
        "ssa_panel_countries": int(len(panel_isos)),
        "ssa_last_full_year": last_full,
        "ssa_countries_reporting_latest": int(ssa_cov.iloc[-1]),
        "ssa_latest_year": int(ssa_cov.index.max()),
        "ssa_solar_share_2015_pct": round(float(bal.loc[2015, "solar_share_pct"]), 2),
        "ssa_solar_share_last_full_pct": round(float(bal.loc[last_full, "solar_share_pct"]), 2),
        "ssa_solar_naive_latest_pct": round(float(naive["solar_share_pct"].dropna().iloc[-1]), 2),
        "ssa_solar_trend_growth_pct_per_year": round(solar_fc.attrs["annual_growth_pct"], 1),
        "ssa_solar_2030_projection_pct": round(float(solar_fc.loc[solar_fc.year == 2030, "fit"].iloc[0]), 1),
        "ssa_solar_2030_interval_pct": [round(float(solar_fc.loc[solar_fc.year == 2030, "lo"].iloc[0]), 1),
                                        round(float(solar_fc.loc[solar_fc.year == 2030, "hi"].iloc[0]), 1)],
        "issues_total": int(len(issues)),
        "issues_ssa": int(len(ssa_issues)),
        "sources": sources,
        "pandas_sql_agree": {k: bool(v) for k, v in agree.items()},
    }
    (OUT / "key_facts.json").write_text(json.dumps(facts, indent=2))
    build_dashboard(ROOT / "docs" / "index.html", elec=ssa, issues=ssa_issues, solar=solar, solar_fc=solar_fc,
                    ng=ng, ng_fc=ng_fc, comparison=comparison, access=access, facts=facts, coverage=ssa_cov)
    log.info("done: %s", json.dumps(facts))
    return facts


def _static_charts(ng, latest_ng, ssa, solar, solar_fc, comparison):
    mix = ["gas_electricity", "hydro_electricity", "oil_electricity", "solar_electricity", "coal_electricity"]
    fig, ax = plt.subplots(figsize=(9, 4.8))
    ng.loc[2000:latest_ng, mix].fillna(0).rename(columns=lambda c: c.replace("_electricity", "").title()).plot.area(ax=ax, linewidth=0, alpha=0.9)
    ax.set_title(f"Nigeria grid electricity generation by source, 2000-{latest_ng} (TWh)")
    ax.set_xlabel(""); ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); fig.savefig(OUT / "nigeria_generation_mix.png", dpi=150); plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 3.8))
    ni = ng.loc[2000:latest_ng, "net_elec_imports"]
    ax.bar(ni.index, ni.values, color="#1f77b4", label="OWID")
    z = ni[ni == 0]
    ax.scatter(z.index, z.values, marker="x", color="#d62728", zorder=3, label="OWID recorded as exactly 0")
    if comparison is not None:
        e = comparison[comparison["iso_code"] == "NGA"].set_index("year")["ember_net_imports"].dropna()
        if len(e):
            ax.plot(e.index, e.values, "o-", color="#ff7f0e", label="Ember")
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_title("Nigeria net electricity imports (TWh; negative = exports)")
    ax.legend(frameon=False, loc="lower left"); ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); fig.savefig(OUT / "nigeria_net_imports_zero_vs_missing.png", dpi=150); plt.close(fig)

    pc = ssa.dropna(subset=["per_capita_electricity"])
    pc = pc.loc[pc.groupby("iso_code")["year"].idxmax(), ["country", "per_capita_electricity"]].sort_values("per_capita_electricity")
    fig, ax = plt.subplots(figsize=(8, 8))
    ax.barh(pc["country"], pc["per_capita_electricity"], color=["#d62728" if c == "Nigeria" else "#7f7f7f" for c in pc["country"]])
    ax.set_xscale("log"); ax.set_title("Electricity generation per person, latest year (kWh, log scale)")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); fig.savefig(OUT / "ssa_per_capita_generation.png", dpi=150); plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 4.2))
    ax.fill_between(solar_fc["year"], solar_fc["lo"], solar_fc["hi"], color="#2ca02c", alpha=0.15, label="90% prediction interval")
    ax.plot(solar_fc["year"], solar_fc["fit"], "--", color="#2ca02c", label="log-linear trend")
    ax.plot(solar.index, solar["balanced_panel"], "o-", color="#2ca02c", label="balanced panel (actual)")
    ax.plot(solar.index, solar["naive_sum"], "s:", color="#d62728", alpha=0.7, label="naive sum (partial years)")
    ax.set_title("Sub-Saharan solar share of electricity (%): balanced vs naive, trend to 2030")
    ax.legend(frameon=False); ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); fig.savefig(OUT / "ssa_solar_share_trend.png", dpi=150); plt.close(fig)


if __name__ == "__main__":
    main()
