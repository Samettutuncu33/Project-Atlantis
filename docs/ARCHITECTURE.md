# ATLANTIS architecture

```
AI RESEARCH & DEVELOPMENT LAYER     .claude/agents/  researcher → planner → tester → executor
                                     analytics/ (reports), research notes/plans/results
MARKET INTELLIGENCE LAYER            atlantis/intel/   Dukascopy bid/ask (live + history), Saxo public
                                     conditions snapshots, validation, provenance store; Saxo SIM adapter
                                     (read-only, disabled). News, fundamentals, calendar: not yet sourced.
QUANT STRATEGY ENGINE                atlantis/quant/   strategies (rules), predict (chart features,
                                     rule + ML predictors), learn (prediction ledger, Hedge weights,
                                     calibration, lessons), decide (half Kelly, edge > cost), research
                                     (DSR, bootstrap, trial registry), risk/sizing
   ── emits OrderIntent only (architecture test forbids importing the broker) ──
CENTRAL RISK & EXECUTION ENGINE      atlantis/gate/    risk_gate.py (mandatory pre-trade checks,
                                     capital allocation), sim/ (order state machine, fills, Saxo costs,
                                     SimBroker = the only router), portfolio/ (double-entry FIFO ledger)
                                     Limits: config/risk_policy.yaml (policy) + saxo_conditions.yaml (ESMA)
ORCHESTRATION                        engine.py (rule backtests), adaptive.py (self-learning account),
                                     live.py (scheduled paper step), checks/reconcile.py (independent books)
```

## Agents
| Agent | Writes | Never does |
|---|---|---|
| atlantis-researcher | research/notes | edit code, run stateful jobs |
| atlantis-planner | research/plans (pre-registered) | write code or look at results first |
| atlantis-tester | quant code, tests, research/results | touch the gate, risk policy or live journal |
| atlantis-executor | live/ outputs, dashboard | edit code, strategies or past journal entries |

## Safety invariants (all tested)
- SimBroker is the only router, and no live router class exists (`tests/test_gate.py`).
- The Saxo adapter can send only GET requests to `/sim/openapi/{ref,chart}` (`tests/test_safety.py`).
- Order states can only move along legal transitions (property test).
- The fills journal and the prediction ledger are append-only across runs: every run re-checks them, and any earlier record that changed raises a CRITICAL failure.
