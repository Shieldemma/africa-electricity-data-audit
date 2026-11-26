"""Cross-source validation: OWID vs Ember (generation, net imports) and OWID vs World Bank (population)."""
from __future__ import annotations

import pandas as pd


def ember_wide(ember: pd.DataFrame) -> pd.DataFrame:
    """Pull the TWh totals we need out of Ember's long format, one row per iso-year."""
    e = ember[ember["unit"].astype(str).str.upper() == "TWH"].copy()
    var = e["variable"].astype(str).str.lower()
    cat = e["category"].astype(str).str.lower()
    pick = {
        "ember_generation": (cat.str.contains("generation")) & (var.isin(["total generation"])),
        "ember_demand": (cat.str.contains("demand")) & (var.isin(["demand"])),
        "ember_net_imports": var.isin(["net imports"]),
    }
    frames = []
    for name, mask in pick.items():
        f = e[mask].groupby(["iso", "year"])["value"].sum(min_count=1).rename(name)
        frames.append(f)
    return pd.concat(frames, axis=1).reset_index()


def owid_vs_ember(owid: pd.DataFrame, ember: pd.DataFrame, tol: float = 0.02) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (merged comparison table, issues)."""
    w = ember_wide(ember)
    m = owid.merge(w, left_on=["iso_code", "year"], right_on=["iso", "year"], how="inner")
    m["gen_diff_pct"] = (m["electricity_generation"] / m["ember_generation"] - 1) * 100
    rows = []
    for r in m.itertuples():
        if pd.notna(r.gen_diff_pct) and abs(r.gen_diff_pct) > tol * 100 and r.ember_generation > 0.5:
            rows.append({"check": "owid_vs_ember_generation", "country": r.country, "iso": r.iso_code, "year": int(r.year),
                         "detail": f"OWID {r.electricity_generation:.2f} vs Ember {r.ember_generation:.2f} TWh ({r.gen_diff_pct:+.1f}%)"})
        if pd.notna(r.net_elec_imports) and pd.notna(r.ember_net_imports) and r.net_elec_imports == 0 and abs(r.ember_net_imports) >= 0.05:
            rows.append({"check": "owid_zero_but_ember_nonzero_imports", "country": r.country, "iso": r.iso_code, "year": int(r.year),
                         "detail": f"OWID net imports 0 vs Ember {r.ember_net_imports:.2f} TWh"})
    cols = ["iso_code", "country", "year", "electricity_generation", "ember_generation", "gen_diff_pct",
            "net_elec_imports", "ember_net_imports"]
    return m[cols], pd.DataFrame(rows, columns=["check", "country", "iso", "year", "detail"])


def owid_vs_worldbank_population(owid: pd.DataFrame, wb_pop: pd.DataFrame, tol: float = 0.03) -> pd.DataFrame:
    m = owid.merge(wb_pop.rename(columns={"value": "wb_population"}), left_on=["iso_code", "year"], right_on=["iso", "year"])
    m["pop_diff_pct"] = (m["population"] / m["wb_population"] - 1) * 100
    bad = m[m["pop_diff_pct"].abs() > tol * 100]
    return pd.DataFrame([{"check": "owid_vs_worldbank_population", "country": r.country, "iso": r.iso_code, "year": int(r.year),
                          "detail": f"OWID {r.population/1e6:.1f}m vs World Bank {r.wb_population/1e6:.1f}m ({r.pop_diff_pct:+.1f}%)"}
                         for r in bad.itertuples()], columns=["check", "country", "iso", "year", "detail"])
