"""Simple, transparent statistical projections (not a policy forecast).

Solar share: log-linear trend fitted on the balanced-panel series, projected to 2030
with a 90% prediction interval. Nigeria demand: linear trend on 2010+ data with interval.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.api as sm


def trend_projection(series: pd.Series, horizon_to: int = 2030, log: bool = False, alpha: float = 0.10) -> pd.DataFrame:
    s = series.dropna()
    y = np.log(s.values) if log else s.values
    X = sm.add_constant(s.index.values.astype(float))
    model = sm.OLS(y, X).fit()
    years = np.arange(s.index.min(), horizon_to + 1)
    pred = model.get_prediction(sm.add_constant(years.astype(float))).summary_frame(alpha=alpha)
    out = pd.DataFrame({"year": years, "fit": pred["mean"], "lo": pred["obs_ci_lower"], "hi": pred["obs_ci_upper"]})
    if log:
        out[["fit", "lo", "hi"]] = np.exp(out[["fit", "lo", "hi"]])
    out["actual"] = out["year"].map(s)
    out.attrs["r2"] = float(model.rsquared)
    out.attrs["annual_growth_pct"] = float((np.exp(model.params[1]) - 1) * 100) if log else float(model.params[1])
    return out
