"""Regras que decidem se um preço parece uma falha."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Alert:
    product: object
    reasons: list[str]
    reference: float | None  # preço de referência usado
    drop_pct: float | None
    score: float             # quanto maior, mais suspeito


def check(p, median: float | None, n_hist: int, rules: dict) -> Alert | None:
    reasons: list[str] = []
    ref = None
    drop = None

    # Regra 1: queda face ao histórico do produto
    if median and n_hist >= rules["min_history_points"]:
        d = (1 - p.price / median) * 100
        if d >= rules["drop_vs_history_pct"] and median >= rules["min_reference_price"]:
            reasons.append(f"−{d:.0f}% face à mediana ({median:.2f} €, {n_hist} leituras)")
            ref, drop = median, d

    # Regra 2: desconto anunciado face ao preço antigo
    if p.old_price and p.old_price >= rules["min_reference_price"]:
        d = (1 - p.price / p.old_price) * 100
        if d >= rules["drop_vs_old_price_pct"]:
            reasons.append(f"−{d:.0f}% face ao preço riscado ({p.old_price:.2f} €)")
            if drop is None or d > drop:
                ref, drop = p.old_price, d

    # Regra 3: preço absurdo
    base = max(filter(None, [median, p.old_price]), default=None)
    if base and base >= rules["absurd_if_median_above"] and p.price < rules["absurd_price_below"]:
        reasons.append(f"preço absurdo: {p.price:.2f} € num produto de ~{base:.0f} €")
        ref = ref or base
        drop = drop or (1 - p.price / base) * 100

    if not reasons:
        return None
    score = (drop or 0) + 15 * (len(reasons) - 1)
    return Alert(product=p, reasons=reasons, reference=ref, drop_pct=drop, score=score)
