"""Research protocol (pre-registered; see docs/RISK_METHOD.md).

  1. Parameters are fixed in advance from the cited literature — no search.
  2. Development period 2012-2019, holdout 2020-2025 (2010-2011 is warm-up).
  3. For each strategy:
       a. scale-free run ($1,000,000) -> the strategy's net edge without
          lot-size distortion; cost sweep 0x/1x/2x/3x + extra spread.
       b. $200 'conservative' run (10% vol target)       <- primary environment
       c. $200 'max_growth' run: leverage = 1/2 Kelly estimated on the
          DEVELOPMENT period of the scale-free run only, then applied to the
          holdout. Capped by ESMA margin inside the sizer.
  4. Every run is recorded in the trial registry; Deflated Sharpe uses the count.
  5. The 2x-per-month target is evaluated by block bootstrap of holdout returns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from atlantis.analytics import metrics as M
from atlantis.checks.reconcile import reconcile
from atlantis.engine import BacktestResult, run_backtest
from atlantis.quant.research.robustness import TrialRegistry, deflated_sharpe, kelly, target_analysis
from atlantis.quant.risk.sizing import MinTicketSizer, VolTargetSizer
from atlantis.gate.sim.costs import CostModel
from atlantis.quant.strategies.library import REGISTRY

DEV = ("2012-01-01", "2019-12-31")
HOLDOUT = ("2020-01-01", "2025-12-31")
SCALE_FREE_CAPITAL = 1_000_000.0
KELLY_FRACTION = 0.5


@dataclass
class RunSummary:
    strategy: str
    profile: str
    period: str
    capital: float
    metrics: dict
    costs: dict
    trades: dict
    sizer: dict
    reconciliation_breaks: list[str]
    audit_counts: dict
    leverage_scale: float = 1.0
    equity: pd.Series = field(default=None, repr=False)

    def as_row(self) -> dict:
        m = self.metrics
        return {"strategy": self.strategy, "profile": self.profile, "period": self.period,
                "capital": self.capital, "leverage": self.leverage_scale,
                "end_equity": m["end_equity"], "net_pnl": m["net_pnl"], "cagr": m["cagr"],
                "sharpe": m["sharpe"], "sortino": m["sortino"], "max_dd": m["max_drawdown"],
                "ann_vol": m["ann_vol"], "trades": self.trades["trades"],
                "win_rate": self.trades["win_rate"], "profit_factor": self.trades["profit_factor"],
                "expectancy_usd": self.trades["expectancy"],
                "costs_usd": self.costs["total_costs"], "costs_pct_capital": self.costs["total_costs"] / self.capital,
                "fills": self.costs["fills"], "rejects": self.costs["rejects"],
                "rounded_to_zero": self.sizer["rounded_to_zero"],
                "rounded_up_to_min": self.sizer["rounded_up_to_min"],
                "recon_ok": not self.reconciliation_breaks}


def summarise(res: BacktestResult, strategy: str, profile: str, period: str, capital: float,
              leverage: float) -> RunSummary:
    led, st = res.ledger, res.broker.stats
    pnl = pd.Series([c.pnl_usd_gross - c.conversion_fee_usd for c in led.closed], dtype=float)
    costs = {"commissions": led.totals["commissions"], "financing": led.totals["financing"],
             "conversion_fees": led.totals["conversion_fees"],
             "spread_cost_est": st["spread_cost_usd"], "slippage_est": st["slippage_usd"],
             "fills": st["fills"], "rejects": st["rejects"], "closeouts": st["closeouts"],
             "traded_notional": st["traded_notional_usd"]}
    costs["total_costs"] = (costs["commissions"] + costs["financing"] + costs["conversion_fees"]
                            + costs["spread_cost_est"] + costs["slippage_est"])
    sev = {k: len(res.audit.by_severity(k)) for k in ("INFO", "WARN", "ERROR")}
    return RunSummary(strategy, profile, period, capital, M.summary(res.equity), costs,
                      M.trade_stats(pnl), dict(res.sizer.adjustments), reconcile(res), sev,
                      leverage, res.equity)


def research(data: dict[str, pd.DataFrame], out_dir: Path, strategies: list[str] | None = None,
             capital: float = 200.0) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    reg = TrialRegistry(out_dir / "trials.jsonl")
    if reg.path.exists():
        reg.path.unlink()
    rows, extra = [], {}
    names = strategies or list(REGISTRY)
    for name in names:
        strat = REGISTRY[name]()
        info: dict = {"citation": strat.citation, "params": strat.params()}
        # (a) scale-free, development + holdout
        sf = {}
        for label, (a, b) in (("dev", DEV), ("holdout", HOLDOUT)):
            r = run_backtest(data, strat, SCALE_FREE_CAPITAL, a, b)
            s = summarise(r, name, "scale_free", label, SCALE_FREE_CAPITAL, 1.0)
            sf[label] = s
            rows.append(s.as_row())
            reg.record(name, strat.params(), M.returns_from_equity(r.equity).mean()
                       / max(M.returns_from_equity(r.equity).std(), 1e-12), label)
        # cost sweep on holdout
        sweep = {}
        for k in (0.0, 1.0, 2.0, 3.0):
            r = run_backtest(data, strat, SCALE_FREE_CAPITAL, *HOLDOUT,
                             costs=CostModel.saxo_classic(k), verify_causality=False)
            sweep[f"cost_x{k:g}"] = M.summary(r.equity)["sharpe"]
        for bps in (1.0, 3.0):
            r = run_backtest(data, strat, SCALE_FREE_CAPITAL, *HOLDOUT, extra_spread_bps=bps,
                             verify_causality=False)
            sweep[f"extra_spread_{bps:g}bps"] = M.summary(r.equity)["sharpe"]
        info["cost_sweep_holdout_sharpe"] = sweep
        # (b) $200 conservative
        for label, (a, b) in (("dev", DEV), ("holdout", HOLDOUT)):
            r = run_backtest(data, strat, capital, a, b, sizer=VolTargetSizer(), verify_causality=False)
            rows.append(summarise(r, name, "conservative_200", label, capital, 1.0).as_row())
        # (b2) $200 min_ticket diagnostic: what the minimum ticket forces on $200
        for label, (a, b) in (("dev", DEV), ("holdout", HOLDOUT)):
            r = run_backtest(data, strat, capital, a, b, sizer=MinTicketSizer(), verify_causality=False)
            rows.append(summarise(r, name, "min_ticket_200", label, capital, float("nan")).as_row())
        # (c) $200 max_growth: half-Kelly from DEV scale-free returns only
        dev_r = M.returns_from_equity(sf["dev"].equity)
        k = kelly(dev_r)
        # Kelly leverage applies to the strategy's own return stream (already at the
        # 10% vol target), so leverage_scale = KELLY_FRACTION x Kelly multiple.
        lev = max(0.0, KELLY_FRACTION * k["kelly_leverage"])
        info["kelly_dev"] = k
        info["max_growth_leverage_scale"] = lev
        if lev > 0:
            r = run_backtest(data, strat, capital, *HOLDOUT,
                             sizer=VolTargetSizer(leverage_scale=lev), verify_causality=False)
            s = summarise(r, name, "max_growth_200", "holdout", capital, lev)
            rows.append(s.as_row())
        # target analysis on holdout scale-free returns at Kelly leverage
        ho_r = M.returns_from_equity(sf["holdout"].equity)
        info["target_at_1x"] = target_analysis(ho_r, 1.0)
        kl = max(k["kelly_leverage"], 0.0)
        info["target_at_full_kelly_from_dev"] = target_analysis(ho_r, kl) if kl > 0 else None
        info["kelly_holdout"] = kelly(ho_r)
        info["_holdout_equity"] = sf["holdout"].equity
        extra[name] = info
    trials = reg.trials()
    srs = pd.Series([t["sr_daily"] for t in trials])
    var_sr = float(srs.var()) if len(srs) > 1 else 0.0
    for name in names:
        eq = extra[name].pop("_holdout_equity")
        extra[name]["deflated_sharpe_holdout"] = deflated_sharpe(
            M.returns_from_equity(eq), len(trials), var_sr)
    return {"rows": rows, "strategies": extra, "n_trials": len(trials)}
