"""Saxo cost model: commissions, overnight financing. Values come from
config/saxo_conditions.yaml; nothing is hard-coded here."""

from __future__ import annotations

from dataclasses import dataclass

from atlantis.instruments.spec import conditions


@dataclass(frozen=True)
class CostModel:
    min_commission_usd: float
    commission_rate: float
    tom_next_markup_pa: float
    unrealised_financing_markup_pa: float
    day_count: float = 360.0          # USD ACT/360 (Saxo benchmark table)
    cost_multiplier: float = 1.0      # for cost-sensitivity sweeps

    @classmethod
    def saxo_classic(cls, cost_multiplier: float = 1.0) -> CostModel:
        fx = conditions()["fx_spot"]
        return cls(
            min_commission_usd=fx["min_commission_usd"]["value"],
            commission_rate=fx["commission_rate"]["value"],
            tom_next_markup_pa=fx["tom_next_markup_pa"]["value"],
            unrealised_financing_markup_pa=fx["unrealised_pnl_financing_markup_pa"]["value"],
            cost_multiplier=cost_multiplier,
        )

    def commission(self, notional_usd: float) -> float:
        # Assumption A1: every $200-account ticket is "small" -> $1 minimum applies.
        return self.cost_multiplier * max(self.commission_rate * abs(notional_usd),
                                          self.min_commission_usd)

    def financing(self, notional_usd: float, unrealised_usd: float, days: float) -> float:
        """Overnight cost for holding a position `days` calendar days.

        Interest-rate differential is UNAVAILABLE (A5) and set to zero; only Saxo's
        published mark-ups are charged, on notional (Tom/Next) and on |unrealised|.
        """
        if days <= 0:
            return 0.0
        rate_cost = (self.tom_next_markup_pa * abs(notional_usd)
                     + self.unrealised_financing_markup_pa * abs(unrealised_usd))
        return self.cost_multiplier * rate_cost * days / self.day_count
