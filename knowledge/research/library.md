# Research library

One entry per effect. Never delete an entry; mark it superseded instead.

## 1. Time series momentum
- Paper: Moskowitz, Ooi, Pedersen (2012), "Time Series Momentum", Journal of Financial Economics 104(2), 228-250. https://econpapers.repec.org/RePEc:eee:jfinec:v:104:y:2012:i:2:p:228-250 (SSRN: https://papers.ssrn.com/abstract=2089463)
- Market: 58 liquid futures and forwards (equity indices, currencies, commodities, sovereign bonds), data from 1985.
- Measured size: an asset's own past 1-12 month return predicts its next-period return with the same sign. The effect partly reverses over longer horizons. Only the persistence and the diversified-portfolio result were checked this run. The per-asset size was not checked, so none is recorded here.
- Known failure cases: reversal at long horizons. The result is a diversified portfolio result and is much weaker for a single asset. Not tested at hourly or daily horizons.
- Applicability: partial. The instruments overlap (FX, indices, commodities, crypto not covered). The signal is monthly, so the 24-hour effect is tiny. Use only as a 0.48/0.52 tilt in the direction of the 1-month trend.
- Status: active
