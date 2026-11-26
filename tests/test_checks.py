import pandas as pd

from pipeline import checks, crosscheck, forecast


def _frame(rows):
    return pd.DataFrame(rows)


def test_zero_vs_missing_flags_zero_run_between_nonzero_years():
    df = _frame([{"iso_code": "AAA", "country": "A", "year": y, "electricity_generation": 10,
                  "net_elec_imports": v} for y, v in [(2000, -1.0), (2001, 0.0), (2002, 0.0), (2003, -2.0)]])
    out = checks.zero_vs_missing(df)
    assert len(out) == 1 and out.iloc[0]["year"] == 2001


def test_zero_vs_missing_ignores_series_that_are_always_zero():
    df = _frame([{"iso_code": "AAA", "country": "A", "year": y, "electricity_generation": 10,
                  "net_elec_imports": 0.0} for y in range(2000, 2005)])
    assert checks.zero_vs_missing(df).empty


def test_carried_forward_detects_repeat():
    df = _frame([{"iso_code": "AAA", "country": "A", "year": y, "electricity_generation": 10,
                  "net_elec_imports": v} for y, v in [(2020, -2.3), (2021, -2.5), (2022, -2.5)]])
    out = checks.carried_forward(df)
    assert out["year"].tolist() == [2022]


def test_sources_vs_total():
    base = {c: 0.0 for c in checks.SRC_COLS}
    ok = {**base, "iso_code": "AAA", "country": "A", "year": 2020, "electricity_generation": 10, "gas_electricity": 10}
    bad = {**base, "iso_code": "BBB", "country": "B", "year": 2020, "electricity_generation": 10, "gas_electricity": 8}
    out = checks.sources_vs_total(_frame([ok, bad]))
    assert out["iso"].tolist() == ["BBB"]


def test_interior_gaps_and_yoy():
    df = _frame([{"iso_code": "AAA", "country": "A", "year": y, "electricity_generation": g}
                 for y, g in [(2000, 2.0), (2001, 2.1), (2003, 3.5)]])
    assert checks.interior_gaps(df)["year"].tolist() == [2002]
    assert checks.yoy_jumps(df)["year"].tolist() == [2003]


def test_owid_vs_ember_flags_zero_when_ember_has_trade():
    owid = _frame([{"iso_code": "AAA", "country": "A", "year": 2010, "electricity_generation": 10.0, "net_elec_imports": 0.0}])
    ember = _frame([
        {"iso": "AAA", "year": 2010, "category": "Electricity generation", "variable": "Total Generation", "unit": "TWh", "value": 10.0},
        {"iso": "AAA", "year": 2010, "category": "Electricity imports", "variable": "Net Imports", "unit": "TWh", "value": -1.5},
    ])
    _, issues = crosscheck.owid_vs_ember(owid, ember)
    assert "owid_zero_but_ember_nonzero_imports" in issues["check"].tolist()


def test_trend_projection_recovers_growth():
    s = pd.Series([1.0 * 1.2 ** i for i in range(10)], index=range(2015, 2025))
    fc = forecast.trend_projection(s, log=True)
    assert abs(fc.attrs["annual_growth_pct"] - 20) < 0.5
    assert fc["year"].max() == 2030
