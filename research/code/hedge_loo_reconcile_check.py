"""Determinism + reconciliation check: regenerate the ledger into a second scratch dir, compare SHA256, run reconcile()."""
import hashlib, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import hedge_loo_generate as G
from atlantis.checks.reconcile import reconcile
import atlantis.adaptive as ad

captured = {}
orig = ad.run_adaptive
def wrap(*a, **k):
    r = orig(*a, **k); captured["r"] = r; return r
G.run_adaptive = wrap
G.main(Path(sys.argv[1]))
r = captured["r"]
from atlantis.engine import BacktestResult
br = r.broker
print("reconcile breaks:", reconcile(BacktestResult(r.equity, None, br, None, br.audit, {}, None, None)))
print("orders:", len(r.broker.orders), "min/max equity:", r.equity.min(), r.equity.max())
print("sha:", hashlib.sha256((Path(sys.argv[1]) / "frozen_ledger.jsonl").read_bytes()).hexdigest())
