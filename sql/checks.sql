-- Data-quality checks written in SQL (DuckDB). Same logic as pipeline/checks.py,
-- so the two implementations cross-validate each other (see run_pipeline.py).
-- Input view: elec(iso_code, country, year, electricity_generation, electricity_demand, net_elec_imports)

-- 1. Net imports exactly zero in some years but non-zero in others (zero-vs-missing)
CREATE OR REPLACE VIEW chk_zero_vs_missing AS
WITH base AS (
    SELECT * FROM elec WHERE net_elec_imports IS NOT NULL AND electricity_generation > 1
)
SELECT iso_code,
       any_value(country)                                   AS country,
       count(*) FILTER (WHERE net_elec_imports = 0)         AS zero_years,
       min(year) FILTER (WHERE net_elec_imports = 0)        AS first_zero_year,
       max(year) FILTER (WHERE net_elec_imports = 0)        AS last_zero_year
FROM base
GROUP BY iso_code
HAVING count(*) FILTER (WHERE net_elec_imports = 0) > 0
   AND count(*) FILTER (WHERE net_elec_imports <> 0) > 0;

-- 2. Values carried forward unchanged from the previous year
CREATE OR REPLACE VIEW chk_carried_forward AS
SELECT iso_code, country, year, net_elec_imports
FROM (
    SELECT *, lag(net_elec_imports) OVER (PARTITION BY iso_code ORDER BY year) AS prev
    FROM elec
    WHERE net_elec_imports IS NOT NULL AND electricity_generation > 1
)
WHERE net_elec_imports <> 0 AND net_elec_imports = prev;

-- 3. Year-on-year generation jumps above 40% for systems above 1 TWh
CREATE OR REPLACE VIEW chk_yoy_jumps AS
SELECT iso_code, country, year, prev AS prev_twh, electricity_generation AS twh,
       round(100 * (electricity_generation / prev - 1), 1) AS pct_change
FROM (
    SELECT *, lag(electricity_generation) OVER (PARTITION BY iso_code ORDER BY year) AS prev
    FROM elec WHERE electricity_generation IS NOT NULL
)
WHERE prev > 1 AND abs(electricity_generation / prev - 1) > 0.40;

-- 4. Reporting coverage by year (how many countries have data)
CREATE OR REPLACE VIEW coverage_by_year AS
SELECT year, count(DISTINCT iso_code) AS countries_reporting
FROM elec WHERE electricity_generation IS NOT NULL
GROUP BY year ORDER BY year;
