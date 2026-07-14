# Forward entry policy v2.0

Apply this only after the monitor first detects a new recurring Hi5 campaign.

1. Define a better price as at least 0.5% below the author's logged execution. Smaller moves are treated as market noise.
2. During D+0 through D+3, send an alert only when a new band is reached:
   - 0.5% cheaper: cumulative target allocation 25%
   - 1.0% cheaper: cumulative target allocation 50%
   - 2.0% cheaper: cumulative target allocation 100%
3. Each symbol/band can alert only once. A lower band may create a later follow-up alert.
4. After D+3, close the episode. Do not issue a delayed buy signal or mechanically chase at D+4.
5. Hard pause: no new risk when data coverage is below 95%, the transaction cannot be independently range-validated, or the disclosure was first seen after D+3.

Report the historical probability of reaching the 0.5% band separately for every ETF. Review thresholds only after at least 30 new independent recurring campaigns; do not tune them from the latest episode.
