# Benchmark data

Place reviewer-curated evaluation segments here as CSV (see `example.csv` for the schema).

* `example.csv` contains three **illustrative placeholder sentences only**. It is not evaluation data and has no reference translations.
* Real sets (spec §14): about 100-500 representative segments per language direction at the start, growing to 1,000-5,000.
  Include different domains, registers, lengths and scripts. Human reference translations come from TNI translators.
* Do **not** commit client content, customer documents or production datasets. Keep real sets in controlled storage
  and mount or copy them in when running `scripts/benchmark.py`.
