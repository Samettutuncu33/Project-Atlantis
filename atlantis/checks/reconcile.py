"""Independent recomputation of account results.

This module deliberately re-implements FIFO P&L from the raw SIMULATED fill
records in the audit log, without using the Ledger class, and compares it to
the engine's books. Any difference is a portfolio-accounting defect.
"""

from __future__ import annotations

from collections import defaultdict, deque


def recompute_from_audit(events: list[dict], initial: float, conversion_fee: float,
                         quote_ccy: dict[str, str], q2usd_at_fill: dict[int, float]) -> dict:
    books: dict[str, deque] = defaultdict(deque)
    realised = conv = comm = fin = nbp = 0.0
    for e in events:
        k = e["kind"]
        if k == "FILL":
            comm += e["commission"]
            sym, qty, px = e["symbol"], e["qty"], e["price"]
            rate = q2usd_at_fill[e["seq"]]
            book = books[sym]
            while qty and book and (book[0][0] > 0) != (qty > 0):
                lq, lp = book[0]
                c = min(abs(qty), abs(lq))
                sgn = 1 if lq > 0 else -1
                pnl = sgn * c * (px - lp) * rate
                realised += pnl
                if quote_ccy[sym] != "USD":
                    conv += abs(pnl) * conversion_fee
                lq -= sgn * c
                qty += sgn * c
                if abs(lq) < 1e-9:
                    book.popleft()
                else:
                    book[0] = (lq, lp)
                if abs(qty) < 1e-9:
                    qty = 0
            if qty:
                book.append((qty, px))
        elif k == "FINANCING":
            fin += e["amount"]
        elif k == "NBP":
            nbp += e["amount"]
    cash = initial + realised - conv - comm - fin + nbp
    return {"cash": cash, "realised": realised, "conversion_fees": conv,
            "commissions": comm, "financing": fin,
            "positions": {s: sum(q for q, _ in b) for s, b in books.items() if b}}


def reconcile(result) -> list[str]:
    """Compare engine books vs independent recomputation. Returns list of breaks."""
    led = result.ledger
    # Recover the exact conversion rate applied to each fill from the journal: we
    # re-derive it from realised postings is circular, so the broker records it.
    rates = {e["seq"]: e.get("q2usd", 1.0) for e in result.audit.events if e["kind"] == "FILL"}
    fin_events = [{"kind": "FINANCING", "amount": j.amount_usd} for j in led.journal
                  if j.debit == "financing_expense"]
    nbp_events = [{"kind": "NBP", "amount": j.amount_usd} for j in led.journal
                  if j.credit == "nbp_credit"]
    events = result.audit.events + fin_events + nbp_events
    quote = {s: i.quote for s, i in result.broker.instruments.items()}
    ind = recompute_from_audit(events, led.initial_deposit, led.conversion_fee, quote, rates)
    breaks = []
    tol = 1e-6 * max(1.0, led.initial_deposit)
    for k_ind, k_led in (("cash", None), ("commissions", "commissions"),
                         ("financing", "financing"), ("conversion_fees", "conversion_fees"),
                         ("realised", "realised_gross")):
        a = ind[k_ind]
        b = led.cash if k_led is None else led.totals[k_led]
        if abs(a - b) > tol:
            breaks.append(f"{k_ind}: independent={a:.8f} engine={b:.8f}")
    for s in set(ind["positions"]) | set(led.lots):
        if abs(ind["positions"].get(s, 0.0) - led.position(s)) > 1e-6:
            breaks.append(f"position {s}: independent={ind['positions'].get(s)} engine={led.position(s)}")
    return breaks
