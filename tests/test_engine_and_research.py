import numpy as np
import pandas as pd
import pytest

from atlantis.analytics import metrics as M
from atlantis.checks.reconcile import reconcile
from atlantis.engine import LookAheadError, check_causality, run_backtest
from atlantis.instruments.spec import make_instrument
from atlantis.research.robustness import deflated_sharpe, kelly, target_analysis
from atlantis.risk.sizing import VolTargetSizer
from atlantis.strategies.base import Strategy
from atlantis.strategies.library import REGISTRY


class Cheater(Strategy):
    name = "cheater"

    def signals(self, mid, panels):
        return np.sign(mid.shift(-1) - mid).fillna(0)   # peeks at tomorrow


@pytest.mark.parametrize("name", sorted(REGISTRY))
def test_library_strategies_are_causal(fx_data, name):
    from atlantis.engine import build_panels
    p = build_panels(fx_data)
    check_causality(REGISTRY[name](), p["mid_close"], p, n_checks=6)


def test_lookahead_detector_catches_cheater(fx_data):
    with pytest.raises(LookAheadError):
        run_backtest(fx_data, Cheater())


@pytest.mark.parametrize("name", ["tsmom_12m", "donchian_55_20", "reversal_5d_z"])
def test_backtest_reconciles_independently(fx_data, name):
    res = run_backtest(fx_data, REGISTRY[name](), capital=20_000.0)
    assert reconcile(res) == []
    res.ledger.check_invariants()
    assert res.broker.stats["fills"] > 0


def test_200_usd_conservative_sizing_rounds_fx_to_zero(fx_data):
    """Documented finding: at $200 with a 10% vol target, the vol-targeted size of
    a major FX pair (~100 units) is below half the 1,000-unit minimum -> no trade.
    The sizer must report this, not silently trade an oversized minimum ticket."""
    res = run_backtest(fx_data, REGISTRY["tsmom_12m"](), capital=200.0)
    assert res.broker.stats["fills"] == 0
    assert res.sizer.adjustments["rounded_to_zero"] > 0
    assert res.equity.iloc[-1] == 200.0


def test_backtest_is_reproducible(fx_data):
    a = run_backtest(fx_data, REGISTRY["donchian_55_20"](), capital=200.0)
    b = run_backtest(fx_data, REGISTRY["donchian_55_20"](), capital=200.0)
    pd.testing.assert_series_equal(a.equity, b.equity)
    assert a.manifest["data_sha256"] == b.manifest["data_sha256"]


def test_higher_costs_never_increase_final_equity(fx_data):
    from atlantis.sim.costs import CostModel
    eq = [run_backtest(fx_data, REGISTRY["donchian_55_20"](), costs=CostModel.saxo_classic(k),
                       verify_causality=False).equity.iloc[-1] for k in (0.0, 1.0, 3.0)]
    assert eq[0] >= eq[1] >= eq[2]


def test_sizer_rounding_rules():
    inst = make_instrument("EURUSD")
    s = VolTargetSizer()
    assert s.round_qty(499, inst) == 0
    assert s.round_qty(500, inst) == 1000
    assert s.round_qty(-1234.4, inst) == -1234
    assert s.adjustments["rounded_to_zero"] == 1 and s.adjustments["rounded_up_to_min"] == 1


def test_metrics_match_quantstats():
    qs = pytest.importorskip("quantstats")
    rng = np.random.default_rng(3)
    idx = pd.bdate_range("2018-01-01", periods=800)
    r = pd.Series(rng.normal(0.0004, 0.01, len(idx)), index=idx)
    eq = 200 * (1 + r).cumprod()
    r2 = M.returns_from_equity(eq)
    assert M.sharpe(r2) == pytest.approx(qs.stats.sharpe(r2, periods=252), rel=1e-6)
    assert M.sortino(r2) == pytest.approx(qs.stats.sortino(r2, periods=252), rel=1e-6)
    assert M.max_drawdown(eq) == pytest.approx(qs.stats.max_drawdown(eq), rel=1e-6)


def test_metrics_edge_cases():
    eq = pd.Series([200.0, 200.0, 200.0], index=pd.bdate_range("2020-01-01", periods=3))
    s = M.summary(eq)
    assert s["sharpe"] == 0.0 and s["max_drawdown"] == 0.0
    assert np.isnan(M.trade_stats(pd.Series([], dtype=float))["win_rate"])
    assert M.trade_stats(pd.Series([1.0, -0.5]))["profit_factor"] == 2.0


def test_kelly_and_target_math():
    k = kelly(pd.Series([0.01, -0.005] * 200))
    assert k["sharpe_needed_for_2x_month"] == pytest.approx(4.0784, rel=1e-3)
    rng = np.random.default_rng(0)
    r = pd.Series(rng.normal(0.0002, 0.005, 1000))
    t = target_analysis(r, n_paths=500)
    assert 0 <= t["p_double_in_a_month"] <= 0.01
    assert t["p_lose_half_within_12m"] < 0.05


def test_deflated_sharpe_penalises_many_trials():
    rng = np.random.default_rng(1)
    r = pd.Series(rng.normal(0.0005, 0.01, 1500))
    one = deflated_sharpe(r, 1, 0.0005)["dsr"]
    many = deflated_sharpe(r, 500, 0.0005)["dsr"]
    assert many < one
