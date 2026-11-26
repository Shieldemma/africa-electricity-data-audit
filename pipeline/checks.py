"""Data-quality checks on a country-year electricity table.

Every check takes a DataFrame with columns iso_code, country, year and the OWID
electricity fields, and returns a DataFrame of issues: check, country, iso, year, detail.
They are pure functions so they can be unit-tested on synthetic data (see tests/).
"""
from __future__ import annotations

import pandas as pd

SOURCES = ["coal", "gas", "oil", "nuclear", "hydro", "wind", "solar", "biofuel", "other_renewable_exc_biofuel"]
SRC_COLS = [f"{s}_electricity" for s in SOURCES]
ISSUE_COLS = ["check", "country", "iso", "year", "detail"]


def _issues(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=ISSUE_COLS)


def sources_vs_total(df: pd.DataFrame, tol: float = 0.02, min_twh: float = 0.5) -> pd.DataFrame:
    d = df.dropna(subset=["electricity_generation"])
    d = d[d["electricity_generation"] > min_twh]
    s = d[[c for c in SRC_COLS if c in d]].sum(axis=1, min_count=1)
    rel = (s - d["electricity_generation"]) / d["electricity_generation"]
    bad = d[rel.abs() > tol]
    return _issues([{"check": "sources_do_not_sum_to_total", "country": r.country, "iso": r.iso_code,
                     "year": int(r.year), "detail": f"sources {s[i]:.2f} vs total {r.electricity_generation:.2f} TWh ({rel[i]*100:+.1f}%)"}
                    for i, r in bad.iterrows()])


def interior_gaps(df: pd.DataFrame, col: str = "electricity_generation") -> pd.DataFrame:
    rows = []
    for iso, g in df.dropna(subset=[col]).groupby("iso_code"):
        yrs = sorted(g["year"].astype(int))
        missing = sorted(set(range(yrs[0], yrs[-1] + 1)) - set(yrs))
        if missing:
            rows.append({"check": "interior_year_gaps", "country": g["country"].iloc[0], "iso": iso,
                         "year": missing[0], "detail": f"missing {col} for {missing}"})
    return _issues(rows)


def yoy_jumps(df: pd.DataFrame, threshold: float = 0.40, min_twh: float = 1.0) -> pd.DataFrame:
    d = df.sort_values(["iso_code", "year"]).copy()
    d["prev"] = d.groupby("iso_code")["electricity_generation"].shift()
    d["yoy"] = d["electricity_generation"] / d["prev"] - 1
    bad = d[(d["prev"] > min_twh) & (d["yoy"].abs() > threshold)]
    return _issues([{"check": "yoy_jump_over_40pct", "country": r.country, "iso": r.iso_code, "year": int(r.year),
                     "detail": f"{r.prev:.2f} -> {r.electricity_generation:.2f} TWh ({r.yoy*100:+.0f}%)"}
                    for r in bad.itertuples()])


def demand_below_generation(df: pd.DataFrame, threshold: float = 0.15, min_twh: float = 1.0) -> pd.DataFrame:
    d = df.dropna(subset=["electricity_demand", "electricity_generation"])
    d = d[d["electricity_generation"] > min_twh]
    gap = (d["electricity_demand"] - d["electricity_generation"]) / d["electricity_generation"]
    bad = d[gap < -threshold]
    return _issues([{"check": "demand_far_below_generation", "country": r.country, "iso": r.iso_code, "year": int(r.year),
                     "detail": f"demand {r.electricity_demand:.2f} vs generation {r.electricity_generation:.2f} TWh"}
                    for r in bad.itertuples()])


def zero_vs_missing(df: pd.DataFrame, col: str = "net_elec_imports", min_twh: float = 1.0) -> pd.DataFrame:
    """Runs of exact zeros in a series that is non-zero in other years: likely missing data stored as 0."""
    rows = []
    d = df.dropna(subset=[col])
    d = d[d["electricity_generation"] > min_twh]
    for iso, g in d.sort_values("year").groupby("iso_code"):
        zeros = g.loc[g[col] == 0, "year"].astype(int).tolist()
        if zeros and (g[col] != 0).any():
            rows.append({"check": "net_imports_zero_then_nonzero", "country": g["country"].iloc[0], "iso": iso,
                         "year": zeros[0], "detail": f"{col} exactly 0 in {len(zeros)} yrs ({zeros[0]}-{zeros[-1]}), non-zero elsewhere"})
    return _issues(rows)


def carried_forward(df: pd.DataFrame, col: str = "net_elec_imports", min_twh: float = 1.0) -> pd.DataFrame:
    rows = []
    d = df.dropna(subset=[col])
    d = d[d["electricity_generation"] > min_twh]
    for iso, g in d.sort_values("year").groupby("iso_code"):
        rep = g[(g[col] != 0) & (g[col].diff() == 0)]
        rows += [{"check": "net_imports_repeated_exactly", "country": r.country, "iso": iso, "year": int(r.year),
                  "detail": f"{col} {getattr(r, col):.2f} identical to previous year"} for r in rep.itertuples()]
    return _issues(rows)


ALL_CHECKS = [sources_vs_total, interior_gaps, yoy_jumps, demand_below_generation, zero_vs_missing, carried_forward]


def run_all(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.concat([chk(df) for chk in ALL_CHECKS], ignore_index=True)
    return out.sort_values(["check", "country", "year"]).reset_index(drop=True)
