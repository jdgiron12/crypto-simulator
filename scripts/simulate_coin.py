#!/usr/bin/env python
"""Demo CLI: run the single-coin economy simulation and print it.

    python scripts/simulate_coin.py --ticks 20
    python scripts/simulate_coin.py --ticks 20 --no-traders   # whale-only
    python scripts/simulate_coin.py --ticks 20 --pricing-mode amm --no-whales

Coin economics, whales, traders, the market reserve and the AMM pool all
come from the `coin:` section of `crypto_simulator/config/default.yaml`.
"""

from __future__ import annotations

import argparse

from crypto_simulator.config import get_settings
from crypto_simulator.core.coin_simulator import PricingMode
from crypto_simulator.core.traders.base import TradeAction
from crypto_simulator.services.coin_simulation import build_coin_simulator


def _trader_note(tick) -> str:
    if not tick.trader_trades:
        return ""
    buys = sum(t.quantity for t in tick.trader_trades if t.side is TradeAction.BUY)
    sells = sum(t.quantity for t in tick.trader_trades if t.side is TradeAction.SELL)
    return f"{len(tick.trader_trades)} fills, net {buys - sells:+,.0f}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticks", type=int, default=20, help="Number of ticks to simulate")
    parser.add_argument("--no-traders", action="store_true", help="Disable trader agents")
    parser.add_argument("--no-whales", action="store_true", help="Disable whales")
    parser.add_argument(
        "--pricing-mode",
        choices=[mode.value for mode in PricingMode],
        help="Override coin.pricing_mode from config",
    )
    args = parser.parse_args()

    try:
        sim = build_coin_simulator(
            get_settings(),
            include_traders=not args.no_traders,
            include_whales=not args.no_whales,
            pricing_mode=args.pricing_mode,
        )
    except ValueError as exc:
        parser.error(str(exc))
    start_price = sim.coin.starting_price
    start_equity = {t.trader_id: t.wallet.equity(start_price) for t in sim.traders}
    total_coins_before = sim.reserve.coins + sum(t.wallet.coins for t in sim.traders)
    total_cash_before = sim.reserve.cash + sum(t.wallet.cash for t in sim.traders)
    exact_before = sim.accounting_totals()
    k_before = sim.pool.invariant if sim.pool else None

    print(f"Simulating {sim.coin.name} ({sim.coin.symbol})")
    print(f"  initial supply : {sim.coin.initial_supply:,.0f} {sim.coin.symbol}")
    print(f"  starting price : {start_price:,.4f}")
    print(f"  starting mcap  : {sim.market_cap():,.2f}")
    print(f"  whales         : {len(sim.whales)}")
    print(f"  traders        : {len(sim.traders)}")
    print(f"  pricing mode   : {sim.pricing_mode.value}")
    if sim.pool:
        print(
            f"  amm pool       : {sim.pool.coin_reserve:,.2f} {sim.coin.symbol} / "
            f"{sim.pool.cash_reserve:,.2f} cash, fee {sim.pool.fee_rate:%}"
        )
    print()

    header = (
        f"{'tick':>4}  {'price':>9}  {'market_cap':>14}  {'volume':>10}  "
        f"{'whale activity':<32}  trader activity"
    )
    print(header)
    print("-" * len(header))

    ticks = sim.run(args.ticks)
    for t in ticks:
        whale_note = "; ".join(
            f"{wt.whale_id} {wt.side} {wt.quantity:,.0f} (x{wt.price_impact:.3f})"
            for wt in t.whale_trades
        )
        print(
            f"{t.tick:>4}  {t.price:>9,.4f}  {t.market_cap:>14,.2f}  {t.volume:>10,.0f}  "
            f"{whale_note:<32}  {_trader_note(t)}"
        )

    last = ticks[-1]
    pct_change = (last.price - start_price) / start_price * 100
    print()
    print(f"Final price     : {last.price:,.4f} ({pct_change:+.2f}% vs. starting price)")
    print(f"Final market cap: {last.market_cap:,.2f}")
    print(f"Average volume  : {sum(t.volume for t in ticks) / len(ticks):,.2f} {sim.coin.symbol}/tick")
    print(f"Whale trades    : {sum(len(t.whale_trades) for t in ticks)} across {len(ticks)} ticks")
    print(f"Trader fills    : {sum(len(t.trader_trades) for t in ticks)} across {len(ticks)} ticks")

    if not sim.traders:
        return

    print()
    print(f"{'trader':<20} {'strategy':<17} {'cash':>11} {'coins':>11} {'avg cost':>9} {'P&L':>11}")
    for trader in sim.traders:
        w = trader.wallet
        pnl = w.equity(last.price) - start_equity[trader.trader_id]
        print(
            f"{trader.trader_id:<20} {trader.strategy_name:<17} {w.cash:>11,.2f} "
            f"{w.coins:>11,.2f} {w.average_cost:>9.4f} {pnl:>+11,.2f}"
        )

    if sim.pool:
        _print_amm_summary(sim, ticks, k_before, exact_before)
        return

    total_coins_after = sim.reserve.coins + sum(t.wallet.coins for t in sim.traders)
    total_cash_after = sim.reserve.cash + sum(t.wallet.cash for t in sim.traders)
    print()
    print("Accounting (traders + market reserve):")
    print(f"  coins before/after: {total_coins_before:,.4f} / {total_coins_after:,.4f}")
    print(f"  cash  before/after: {total_cash_before:,.4f} / {total_cash_after:,.4f}")


def _print_amm_summary(sim, ticks, k_before, exact_before) -> None:
    pool = sim.pool
    swaps = [f.swap for t in ticks for f in t.trader_trades]
    print()
    print("AMM pool:")
    print(f"  reserves        : {pool.coin_reserve:,.4f} {sim.coin.symbol} / {pool.cash_reserve:,.4f} cash")
    print(f"  spot price      : {pool.spot_price():,.6f}")
    print(f"  k before/after  : {k_before:,.4f} / {pool.invariant:,.4f} (grows only by fees)")
    print(
        f"  fees collected  : {pool.fees_collected_coins:,.4f} {sim.coin.symbol} + "
        f"{pool.fees_collected_cash:,.4f} cash (held in reserves, owed to LPs)"
    )
    print(f"  swaps           : {pool.swap_count}")
    if swaps:
        worst = max(swaps, key=lambda s: s.slippage)
        print(
            f"  worst slippage  : {worst.slippage:.4%} on a {worst.side} of "
            f"{worst.amount_in:,.2f} (price impact {worst.price_impact:+.4%})"
        )
    exact_after = sim.accounting_totals()
    print()
    print("Accounting (traders + market reserve + pool reserves), exact Decimal:")
    print(f"  coins before/after: {exact_before[0]:,.4f} / {exact_after[0]:,.4f}")
    print(f"  cash  before/after: {exact_before[1]:,.4f} / {exact_after[1]:,.4f}")
    print(f"  conserved exactly : {exact_before == exact_after}")


if __name__ == "__main__":
    main()
