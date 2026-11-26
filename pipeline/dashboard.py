"""Interactive Plotly dashboard written to docs/index.html (served by GitHub Pages)."""
from __future__ import annotations

import html
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

FUELS = {"gas": "#4C78A8", "hydro": "#72B7B2", "oil": "#9D755D", "coal": "#545454", "solar": "#F2B701",
         "wind": "#54A24B", "nuclear": "#B279A2", "biofuel": "#8CD17D", "other_renewable_exc_biofuel": "#BAB0AC"}
LAYOUT = dict(template="plotly_white", margin=dict(l=50, r=20, t=60, b=40), font=dict(family="Inter, Arial", size=13),
              legend=dict(orientation="h", y=-0.15))


def _mix_with_dropdown(elec: pd.DataFrame) -> go.Figure:
    countries = sorted(elec["country"].unique(), key=lambda c: (c != "Nigeria", c))
    fig = go.Figure()
    for ci, c in enumerate(countries):
        d = elec[elec["country"] == c].sort_values("year")
        for f, col in FUELS.items():
            y = d.get(f"{f}_electricity")
            if y is None or y.fillna(0).sum() == 0:
                y = pd.Series([None] * len(d))
            fig.add_trace(go.Scatter(x=d["year"], y=y, name=f.replace("_exc_biofuel", "").replace("_", " ").title(),
                                     stackgroup="one", line=dict(width=0, color=col), visible=(ci == 0),
                                     legendgroup=f, showlegend=True,
                                     hovertemplate="%{x}: %{y:.2f} TWh<extra>" + f + "</extra>"))
    n = len(FUELS)
    buttons = [dict(label=c, method="update",
                    args=[{"visible": [i // n == ci for i in range(n * len(countries))]},
                          {"title": f"{c}: electricity generation by source (TWh)"}])
               for ci, c in enumerate(countries)]
    fig.update_layout(**LAYOUT, title=f"{countries[0]}: electricity generation by source (TWh)",
                      updatemenus=[dict(buttons=buttons, x=1, xanchor="right", y=1.18, showactive=True)])
    return fig


def _net_imports(ng: pd.DataFrame, comparison: pd.DataFrame | None) -> go.Figure:
    ni = ng["net_elec_imports"].dropna()
    fig = go.Figure(go.Bar(x=ni.index, y=ni.values, name="OWID", marker_color=["#d62728" if v == 0 else "#4C78A8" for v in ni.values],
                           hovertemplate="%{x}: %{y:.2f} TWh<extra>OWID</extra>"))
    z = ni[ni == 0]
    fig.add_trace(go.Scatter(x=z.index, y=z.values, mode="markers", name="Recorded as exactly 0",
                             marker=dict(symbol="x", size=11, color="#d62728")))
    if comparison is not None:
        e = comparison[comparison["iso_code"] == "NGA"].set_index("year")["ember_net_imports"].dropna()
        if len(e):
            fig.add_trace(go.Scatter(x=e.index, y=e.values, mode="lines+markers", name="Ember", line=dict(color="#F58518")))
    fig.update_layout(**LAYOUT, title="Nigeria net imports (TWh, negative = exports). Red x = recorded as exactly 0")
    return fig


def _solar(solar: pd.DataFrame, fc: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=list(fc["year"]) + list(fc["year"][::-1]), y=list(fc["hi"]) + list(fc["lo"][::-1]),
                             fill="toself", fillcolor="rgba(84,162,75,0.15)", line=dict(width=0), name="90% prediction interval", hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=fc["year"], y=fc["fit"], name="Log-linear trend", line=dict(dash="dash", color="#54A24B")))
    fig.add_trace(go.Scatter(x=solar.index, y=solar["balanced_panel"], name="Balanced panel (actual)", mode="lines+markers", line=dict(color="#54A24B")))
    fig.add_trace(go.Scatter(x=solar.index, y=solar["naive_sum"], name="Naive sum (partial years)", mode="markers", marker=dict(symbol="x", color="#d62728")))
    fig.update_layout(**LAYOUT, title="Sub-Saharan solar share of generation (%), with trend to 2030", yaxis_ticksuffix="%")
    return fig


def _issues_heatmap(issues: pd.DataFrame) -> go.Figure:
    p = issues.pivot_table(index="country", columns="check", values="year", aggfunc="count", fill_value=0)
    p = p.loc[p.sum(axis=1).sort_values().index]
    fig = go.Figure(go.Heatmap(z=p.values, x=[c.replace("_", " ") for c in p.columns], y=p.index, colorscale="Oranges",
                               hovertemplate="%{y}<br>%{x}: %{z}<extra></extra>"))
    fig.update_layout(**{**LAYOUT, "margin": dict(l=170, r=20, t=60, b=140)}, title="Flagged country-years by check", height=700)
    return fig


def _per_capita(elec: pd.DataFrame, access: pd.DataFrame | None) -> go.Figure:
    pc = elec.dropna(subset=["per_capita_electricity"])
    pc = pc.loc[pc.groupby("iso_code")["year"].idxmax()].sort_values("per_capita_electricity")
    fig = go.Figure(go.Bar(y=pc["country"], x=pc["per_capita_electricity"], orientation="h", name="kWh per person",
                           marker_color=["#d62728" if c == "Nigeria" else "#9D9D9D" for c in pc["country"]]))
    if access is not None:
        a = access.dropna(subset=["kwh_per_connected_person"])
        a = a.loc[a.groupby("iso")["year"].idxmax()].set_index("country").reindex(pc["country"])
        fig.add_trace(go.Bar(y=a.index, x=a["kwh_per_connected_person"], orientation="h", name="kWh per person with access (World Bank)",
                             marker_color="rgba(76,120,168,0.6)"))
    fig.update_layout(**{**LAYOUT, "margin": dict(l=170, r=20, t=60, b=40)}, barmode="group", xaxis_type="log", height=750,
                      title="Grid generation per person, latest year (kWh, log scale)")
    return fig


def build_dashboard(path: Path, *, elec, issues, solar, solar_fc, ng, ng_fc, comparison, access, facts, coverage) -> None:
    path.parent.mkdir(exist_ok=True)
    figs = [_mix_with_dropdown(elec), _net_imports(ng, comparison), _solar(solar, solar_fc),
            _issues_heatmap(issues), _per_capita(elec, access)]
    parts = [f.to_html(full_html=False, include_plotlyjs=False, config={"displaylogo": False})
             for i, f in enumerate(figs)]
    src = facts["sources"]
    kpis = [
        ("Countries audited", "30"),
        ("Flagged country-years", f"{facts['issues_ssa']:,}"),
        (f"Nigeria grid output {facts['nigeria_latest_year']}", f"{facts['nigeria_generation_twh']} TWh"),
        ("Nigeria gas share", f"{facts['nigeria_gas_share_pct']}%"),
        (f"Solar share {facts['ssa_last_full_year']} (balanced)", f"{facts['ssa_solar_share_last_full_pct']}%"),
        ("2030 trend (90% PI)", f"{facts['ssa_solar_2030_projection_pct']}% ({facts['ssa_solar_2030_interval_pct'][0]}–{facts['ssa_solar_2030_interval_pct'][1]})"),
    ]
    kpi_html = "".join(f'<div class="kpi"><div class="v">{html.escape(v)}</div><div class="l">{html.escape(l)}</div></div>' for l, v in kpis)
    top = issues.sort_values(["check", "country", "year"]).head(400)
    rows = "".join(f"<tr><td>{html.escape(r.check.replace('_', ' '))}</td><td>{html.escape(r.country)}</td><td>{r.year}</td><td>{html.escape(r.detail)}</td></tr>"
                   for r in top.itertuples())
    srcs = ", ".join(k for k, v in src.items() if v)
    page = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Africa Electricity Data Audit</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js" charset="utf-8"></script>
<style>
body{{font-family:Inter,Arial,sans-serif;margin:0;background:#f6f7f9;color:#1d2433}}
header{{background:#0f2b3d;color:#fff;padding:28px 24px}} header h1{{margin:0 0 6px;font-size:26px}} header p{{margin:0;opacity:.85}}
main{{max-width:1150px;margin:0 auto;padding:20px 16px 60px}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin:-36px 0 20px}}
.kpi{{background:#fff;border-radius:10px;padding:14px 16px;box-shadow:0 1px 4px rgba(0,0,0,.08)}} .kpi .v{{font-size:22px;font-weight:700}} .kpi .l{{font-size:12px;color:#5b6475;margin-top:4px}}
.card{{background:#fff;border-radius:10px;padding:12px;margin:16px 0;box-shadow:0 1px 4px rgba(0,0,0,.08)}}
.note{{font-size:14px;color:#3b4456;margin:6px 8px 0}}
table{{border-collapse:collapse;width:100%;font-size:13px}} td,th{{border-bottom:1px solid #eceef1;padding:6px 8px;text-align:left;vertical-align:top}}
.scroll{{max-height:420px;overflow:auto}} a{{color:#0b6e99}}
</style></head><body>
<header><h1>Africa Electricity Data Audit</h1>
<p>Automated quality checks on national electricity statistics for 30 sub-Saharan countries, 2000–{facts['ssa_latest_year']}. Sources used in this build: {html.escape(srcs)}.</p></header>
<main>
<div class="kpis">{kpi_html}</div>
<div class="card">{parts[1]}<p class="note">Exact zeros sitting between years of exports are almost certainly missing data. Treating them as real understates trade and overstates implied demand.</p></div>
<div class="card">{parts[2]}<p class="note">Only {facts['ssa_countries_reporting_latest']} of 30 countries report {facts['ssa_latest_year']} so far, so naive regional sums are biased. The balanced panel keeps only countries that report every year from 2015 to {facts['ssa_last_full_year']}. Trend growth is {facts['ssa_solar_trend_growth_pct_per_year']}% a year (log-linear OLS); this is a statistical projection, not a policy forecast.</p></div>
<div class="card">{parts[0]}<p class="note">Use the menu to switch country.</p></div>
<div class="card">{parts[3]}</div>
<div class="card">{parts[4]}</div>
<div class="card"><h3 style="margin:6px 8px">Flagged issues (first 400)</h3><div class="scroll"><table><tr><th>Check</th><th>Country</th><th>Year</th><th>Detail</th></tr>{rows}</table></div></div>
<p class="note">Built by Otuekong "Shield" Udo · code: <a href="https://github.com/Shieldemma/africa-electricity-data-audit">github.com/Shieldemma/africa-electricity-data-audit</a> · data: Our World in Data (Ember / Energy Institute), Ember, World Bank WDI.</p>
</main></body></html>"""
    path.write_text(page, encoding="utf-8")
