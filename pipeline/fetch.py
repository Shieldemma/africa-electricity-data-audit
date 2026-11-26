"""Download raw sources. Each source is optional except OWID: if a download fails,
the pipeline logs it and the dependent checks are skipped instead of crashing."""
from __future__ import annotations

import json
import logging
import urllib.request
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)
DATA = Path(__file__).resolve().parents[1] / "data"
DATA.mkdir(exist_ok=True)

OWID_URL = "https://raw.githubusercontent.com/owid/energy-data/master/owid-energy-data.csv"
EMBER_URL = "https://storage.googleapis.com/emb-prod-bkt-publicdata/public-downloads/yearly_full_release_long_format.csv"
WB_URL = ("https://api.worldbank.org/v2/country/{isos}/indicator/{ind}"
          "?format=json&date=2000:2025&per_page=20000")

# 30-country sub-Saharan sample used throughout the project
SSA = ["NGA", "GHA", "CIV", "SEN", "CMR", "KEN", "ETH", "TZA", "UGA", "ZAF", "AGO", "MOZ", "ZMB",
       "ZWE", "COD", "SDN", "BEN", "TGO", "NER", "MLI", "BFA", "GIN", "SLE", "LBR", "RWA", "MWI",
       "NAM", "BWA", "GAB", "COG"]


def _download(url: str, dest: Path, timeout: int = 120) -> Path | None:
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "africa-electricity-data-audit"})
        with urllib.request.urlopen(req, timeout=timeout) as r, open(dest, "wb") as f:
            f.write(r.read())
        log.info("downloaded %s", dest.name)
        return dest
    except Exception as e:  # network blocked, host down, etc.
        log.warning("could not download %s: %s", url, e)
        if dest.exists():
            dest.unlink()
        return None


def load_owid() -> pd.DataFrame:
    path = _download(OWID_URL, DATA / "owid-energy-data.csv")
    if path is None:
        raise RuntimeError("OWID dataset is required and could not be downloaded")
    return pd.read_csv(path)


def load_ember() -> pd.DataFrame | None:
    """Ember yearly electricity data (long format). Returns tidy columns:
    iso, year, variable, category, unit, value."""
    path = _download(EMBER_URL, DATA / "ember_yearly_long.csv", timeout=300)
    if path is None:
        return None
    df = pd.read_csv(path)
    cols = {c.lower().strip(): c for c in df.columns}
    need = ["iso 3 code", "year", "category", "variable", "unit", "value"]
    if not all(k in cols for k in need):
        log.warning("Ember schema changed; columns are %s", list(df.columns))
        return None
    out = df.rename(columns={cols["iso 3 code"]: "iso", cols["year"]: "year", cols["category"]: "category",
                             cols["variable"]: "variable", cols["unit"]: "unit", cols["value"]: "value"})
    return out[["iso", "year", "category", "variable", "unit", "value"]]


def load_worldbank(indicator: str) -> pd.DataFrame | None:
    """World Bank WDI indicator for the SSA sample -> iso, year, value."""
    dest = DATA / f"wb_{indicator}.json"
    path = _download(WB_URL.format(isos=";".join(SSA), ind=indicator), dest)
    if path is None:
        return None
    try:
        payload = json.loads(path.read_text())
        rows = [{"iso": r["countryiso3code"], "year": int(r["date"]), "value": r["value"]}
                for r in payload[1] if r.get("value") is not None]
        return pd.DataFrame(rows)
    except Exception as e:
        log.warning("World Bank parse failed for %s: %s", indicator, e)
        return None
