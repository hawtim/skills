# Forward entry policy v1.0

Apply this only after the monitor first detects a new recurring Hi5 campaign.

1. D+1 open: permit a 25% starter allocation. If price is already more than 1 ATR above the author price, wait.
2. D+1 through D+3: place observation bands at the author price, author price minus 0.5 ATR, and author price minus 1 ATR. A daily low touching a band counts as historically fillable, not as a guaranteed live fill.
3. D+4: if no better price appeared, deploy a fraction of the remaining target:
   - price at/below author: 100%
   - price above author: `max(25%, 1 - gain / (2 * ATR%))`
4. Hard pause: no new risk when data coverage is below 95%, the transaction cannot be independently range-validated, or the disclosure was first seen after D+3.

This policy trades execution improvement against missed-upside risk. Keep the 25% starter, the unfilled cash fraction, and both outcomes in every backtest. Review thresholds only after at least 30 independent recurring campaigns; do not tune them from the latest episode.
