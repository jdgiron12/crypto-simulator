#!/usr/bin/env python
"""Demo CLI: run the single-coin economy simulation and print it.

    python scripts/simulate_coin.py --ticks 20
    python scripts/simulate_coin.py --ticks 20 --no-traders   # whale-only
    python scripts/simulate_coin.py --ticks 20 --pricing-mode amm --no-whales
    python scripts/simulate_coin.py --ticks 40 --pricing-mode amm --no-whales --scenario pump_and_dump
    python scripts/simulate_coin.py --ticks 25 --pricing-mode amm --no-whales --events
    python scripts/simulate_coin.py --ticks 40 --random-events
    python scripts/simulate_coin.py --ticks 40 --events --psychology

Coin economics, whales, traders, manipulators, news events, the market
reserve and the AMM pool all come from the `coin:` section of
`crypto_simulator/config/default.yaml`; `--scenario` swaps in a ready-made
manipulation setup, `--events` a small demo news schedule and
`--random-events` a per-tick chance of random news. `--psychology` turns on
market psychology (off by default, not part of the config) and prints
descriptive psychology observations. `--whale-observation` records what
each whale did on each tick (also off by default, also not part of the
config) and prints a descriptive whale summary.
"""

from __future__ import annotations

import argparse
from dataclasses import replace

from crypto_simulator.analytics import (
    DEFAULT_BASELINE_WINDOW,
    DEFAULT_POST_WINDOW,
    OCCUPANCY_THRESHOLDS,
    analyze_events,
    TICK_OUTCOMES,
    analyze_psychology,
    analyze_whales,
)
from crypto_simulator.config import get_settings
from crypto_simulator.core.coin_simulator import PricingMode
from crypto_simulator.core.traders.base import TradeAction
from crypto_simulator.core.traders.registry import MANIPULATION_STRATEGIES
from crypto_simulator.services.coin_simulation import (
    DEMO_EVENTS,
    DEMO_RANDOM_EVENT_PROBABILITY,
    MANIPULATION_SCENARIOS,
    build_coin_simulator,
)


def _is_manipulator(trader) -> bool:
    return trader.strategy_name in MANIPULATION_STRATEGIES


def _trader_note(tick, manipulator_ids) -> str:
    organic = [t for t in tick.trader_trades if t.trader_id not in manipulator_ids]
    manipulation = [t for t in tick.trader_trades if t.trader_id in manipulator_ids]
    notes = []
    if organic:
        buys = sum(t.quantity for t in organic if t.side is TradeAction.BUY)
        sells = sum(t.quantity for t in organic if t.side is TradeAction.SELL)
        notes.append(f"{len(organic)} fills, net {buys - sells:+,.0f}")
    if tick.wash_volume:
        notes.append(f"wash {tick.wash_volume:,.0f}")
    notes.extend(f"{t.reason} {t.side.value} {t.quantity:,.0f}" for t in manipulation if not t.wash)
    return " | ".join(notes)


def _news_note(tick) -> str:
    """Live events this tick — simulator ground truth, shown for teaching."""
    return "; ".join(f"{s.event_id} {s.phase.value} {s.intensity:.2f}" for s in tick.event_state.events)


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
    parser.add_argument(
        "--scenario",
        choices=sorted(MANIPULATION_SCENARIOS),
        help="Run a ready-made manipulation scenario (replaces coin.manipulators)",
    )
    parser.add_argument(
        "--events",
        action="store_true",
        help="Run a small demo news schedule (replaces coin.events.scheduled)",
    )
    parser.add_argument(
        "--random-events",
        action="store_true",
        help=f"Start random news events with probability {DEMO_RANDOM_EVENT_PROBABILITY} per tick "
        "(sets coin.events.random.probability)",
    )
    parser.add_argument(
        "--psychology",
        action="store_true",
        help="Turn on market psychology (off by default; uncalibrated) and print psychology observations",
    )
    parser.add_argument(
        "--whale-observation",
        action="store_true",
        help="Record what each whale did each tick (off by default) and print a whale summary",
    )
    args = parser.parse_args()

    settings = get_settings()
    events = settings.coin.events
    if args.events:
        events = replace(events, scheduled=list(DEMO_EVENTS))
    if args.random_events:
        events = replace(events, random=replace(events.random, probability=DEMO_RANDOM_EVENT_PROBABILITY))
    if events is not settings.coin.events:
        settings = replace(settings, coin=replace(settings.coin, events=events))
    try:
        sim = build_coin_simulator(
            settings,
            include_traders=not args.no_traders,
            include_whales=not args.no_whales,
            pricing_mode=args.pricing_mode,
            scenario=args.scenario,
            psychology=args.psychology,
            whale_observation=args.whale_observation,
        )
    except ValueError as exc:
        parser.error(str(exc))
    manipulator_ids = {t.trader_id for t in sim.traders if _is_manipulator(t)}
    start_price = sim.coin.starting_price
    start_equity = {t.trader_id: t.wallet.equity(start_price) for t in sim.traders}
    # Funded whales settle against the reserve too; unfunded ones are outside.
    funded_whales = [w.wallet for w in sim.whales if w.funded]
    total_coins_before = sim.reserve.coins + sum(t.wallet.coins for t in sim.traders) + sum(w.coins for w in funded_whales)
    total_cash_before = sim.reserve.cash + sum(t.wallet.cash for t in sim.traders) + sum(w.cash for w in funded_whales)
    exact_before = sim.accounting_totals()
    k_before = sim.pool.invariant if sim.pool else None

    print(f"Simulating {sim.coin.name} ({sim.coin.symbol})")
    print(f"  initial supply : {sim.coin.initial_supply:,.0f} {sim.coin.symbol}")
    print(f"  starting price : {start_price:,.4f}")
    print(f"  starting mcap  : {sim.market_cap():,.2f}")
    print(f"  whales         : {len(sim.whales)}")
    print(f"  traders        : {len(sim.traders) - len(manipulator_ids)}")
    print(f"  manipulators   : {len(manipulator_ids)}")
    if args.scenario:
        print(f"  scenario       : {args.scenario} — {MANIPULATION_SCENARIOS[args.scenario].description}")
    print(f"  pricing mode   : {sim.pricing_mode.value}")
    if sim.events is not None:
        random_note = f", random {sim.event_generator.probability:g}/tick" if sim.event_generator else ""
        print(
            f"  news events    : {len(sim.events.events)} scheduled{random_note} "
            f"(drift_per_sentiment {sim.drift_per_sentiment})"
        )
    if sim.psychology_enabled:
        print("  psychology     : on (calibration deferred)")
    if sim.whale_observation_enabled:
        print("  whale observation: on (descriptive only)")
    if sim.pool:
        print(
            f"  amm pool       : {sim.pool.coin_reserve:,.2f} {sim.coin.symbol} / "
            f"{sim.pool.cash_reserve:,.2f} cash, fee {sim.pool.fee_rate:%}"
        )
    print()

    show_news = sim.events is not None
    news_header = f"{'news (ground truth)':<28}  " if show_news else ""
    header = (
        f"{'tick':>4}  {'price':>9}  {'market_cap':>14}  {'volume':>10}  "
        f"{news_header}{'whale activity':<32}  trader activity"
    )
    print(header)
    print("-" * len(header))

    ticks = sim.run(args.ticks)
    for t in ticks:
        whale_note = "; ".join(
            f"{wt.whale_id} {wt.side} {wt.quantity:,.0f} (x{wt.price_impact:.3f})"
            for wt in t.whale_trades
        )
        news = f"{_news_note(t):<28}  " if show_news else ""
        print(
            f"{t.tick:>4}  {t.price:>9,.4f}  {t.market_cap:>14,.2f}  {t.volume:>10,.0f}  "
            f"{news}{whale_note:<32}  {_trader_note(t, manipulator_ids)}"
        )

    last = ticks[-1]
    pct_change = (last.price - start_price) / start_price * 100
    print()
    print(f"Final price     : {last.price:,.4f} ({pct_change:+.2f}% vs. starting price)")
    print(f"Final market cap: {last.market_cap:,.2f}")
    print(f"Average volume  : {sum(t.volume for t in ticks) / len(ticks):,.2f} {sim.coin.symbol}/tick")
    print(f"Whale trades    : {sum(len(t.whale_trades) for t in ticks)} across {len(ticks)} ticks")
    print(f"Trader fills    : {sum(len(t.trader_trades) for t in ticks)} across {len(ticks)} ticks")
    if show_news:
        _print_news_schedule(sim)
        _print_event_analysis(sim, ticks)
    if sim.whale_observation_enabled:
        _print_whale_observations(ticks)
    if sim.psychology_enabled:
        _print_psychology_observations(sim, ticks)

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

    if manipulator_ids:
        _print_manipulation_summary(sim, ticks, start_equity, manipulator_ids)

    if sim.pool:
        _print_amm_summary(sim, ticks, k_before, exact_before)
        return

    total_coins_after = sim.reserve.coins + sum(t.wallet.coins for t in sim.traders) + sum(w.coins for w in funded_whales)
    total_cash_after = sim.reserve.cash + sum(t.wallet.cash for t in sim.traders) + sum(w.cash for w in funded_whales)
    print()
    print(f"Accounting (traders{' + funded whales' if funded_whales else ''} + market reserve):")
    print(f"  coins before/after: {total_coins_before:,.4f} / {total_coins_after:,.4f}")
    print(f"  cash  before/after: {total_cash_before:,.4f} / {total_cash_after:,.4f}")


def _print_news_schedule(sim) -> None:
    """The configured events as the simulator knows them. This is ground
    truth for teaching, not something a market observer could see, and it
    makes no claim about what any event did to the price."""
    print()
    kind = "News events, scheduled and random" if sim.event_generator else "News schedule"
    print(f"{kind} (simulator ground truth, not observable market data):")
    for event in sim.events.events:
        fade = f"fading ticks {event.last_active_tick + 1}-{event.expires_at - 1}" if event.decay_ticks else "no fade"
        print(
            f"  {event.event_id:<16} {event.category:<24} severity {event.severity:.2f}  "
            f"sentiment {event.sentiment:+.2f}  vol boost {event.volatility_boost:.2f}  "
            f"attention {event.attention:.2f}"
        )
        print(f"  {'':<16} \"{event.headline}\" — active ticks {event.start_tick}-{event.last_active_tick}, {fade}")


def _pct(value) -> str:
    return "n/a" if value is None else f"{value:+.2%}"


def _num(value, spec: str) -> str:
    return "n/a" if value is None else format(value, spec)


def _print_event_analysis(sim, ticks) -> None:
    """Descriptive market observations over each event's window. Windows
    come from ground-truth timing; every number below is computed from
    prices, volumes, fills and pool snapshots only, and none is a claim
    about what an event did."""
    generated = sim.event_generator.generated_events if sim.event_generator else ()
    observations = analyze_events(
        ticks, sim.events.events, initial_price=sim.coin.starting_price, trader_count=len(sim.traders) or None,
        random_event_ids=[event.event_id for event in generated],
    )
    print()
    print("Event analysis (observed market data over each event's ground-truth window; descriptive, not causal):")
    if not observations:
        print("  no events started during the run")
    symbol, base, post = sim.coin.symbol, DEFAULT_BASELINE_WINDOW, DEFAULT_POST_WINDOW
    for obs in observations:
        truth, market, trading = obs.ground_truth, obs.market, obs.trading
        window = f"ticks {truth.start_tick}-{truth.last_active_tick}"
        if not obs.event_window_complete:
            window += f" (run ended after {obs.event_ticks_observed} of {truth.duration})"
        print(f"  {truth.event_id} ({truth.category}), event window {window}")
        source = "random" if truth.randomly_generated else "scheduled"
        print(f"    ground truth : severity {truth.severity:.2f}, sentiment {truth.sentiment:+.2f}, {source} event")
        print(
            f"    observed     : first-tick return {_pct(market.immediate_return)}, "
            f"event-window return {_pct(market.event_return)}, next {post} ticks {_pct(market.post_event_return)}"
        )
        print(
            f"                   realized volatility {_num(market.volatility, '.4f')} "
            f"(prior {base} ticks: {_num(market.baseline_volatility, '.4f')}); "
            f"volume/tick {_num(market.volume_ratio, '.2f')}x prior {base} ticks"
        )
        participation = "" if trading.participation_rate is None else f", {trading.participation_rate:.0%} of traders active"
        print(
            f"                   trader fills {trading.trade_count}: buy {trading.buy_volume:,.0f} / "
            f"sell {trading.sell_volume:,.0f} {symbol} (net {trading.net_flow:+,.0f}){participation}"
        )
        if obs.pool is not None:
            pool = obs.pool
            reserves = "n/a" if pool.coin_reserve_change is None else (
                f"{pool.coin_reserve_change:+,.0f} {symbol} / {pool.cash_reserve_change:+,.2f} cash"
            )
            fees = "n/a" if pool.fees_cash is None else f"{pool.fees_cash:,.2f} cash + {pool.fees_coins:,.2f} {symbol}"
            print(f"                   pool: {pool.swap_count} swaps, reserves {reserves}, fees {fees}")
        others = ", ".join(obs.overlapping_event_ids)
        print(f"    overlapping  : {others + ' (window metrics mix these events)' if others else 'none'}")


def _ticks(count: int) -> str:
    return f"{count} tick" if count == 1 else f"{count} ticks"


def _print_whale_observations(ticks) -> None:
    """Descriptive summary of what each whale did. Post-processing only:
    it reads the recorded observations and changes nothing."""
    report = analyze_whales(ticks)
    print()
    print("Whale observations (descriptive; no causal claim):")
    if not report.whales:
        print("  no whale observations recorded")
        return
    print(f"  ticks with observations: {report.observed_ticks} of {report.ticks}")
    header = (f"  {'whale':<16} {'trades':>7} {'buy/sell':>11} {'volume':>12} "
              f"{'vwap':>9} {'net coins':>13} {'net cash':>13}")
    print(header)
    print("  " + "-" * (len(header) - 2))
    for whale in report.whales:
        vwap = f"{whale.vwap:,.4f}" if whale.vwap is not None else "-"
        print(f"  {whale.whale_id:<16} {whale.trade_count:>7} "
              f"{whale.buy_count:>5}/{whale.sell_count:<5} {whale.total_volume:>12,.0f} "
              f"{vwap:>9} {whale.net_coin_flow:>13,.0f} {whale.net_cash_flow:>13,.2f}")
    print("  tick outcomes:")
    for whale in report.whales:
        counts = "  ".join(f"{name}={whale.outcome_ticks[name]}"
                           for name in TICK_OUTCOMES if whale.outcome_ticks[name])
        print(f"    {whale.whale_id:<16} {counts}")
    paths = [(w.whale_id, w.allocation) for w in report.whales if w.allocation is not None]
    if paths:
        print("  allocation (funded whales, marked at each fill's own price):")
        for whale_id, path in paths:
            target = "none" if path.target_coin_fraction is None else f"{path.target_coin_fraction:.3f}"
            at_target = "-" if path.ticks_at_target is None else str(path.ticks_at_target)
            crossed = "-" if path.crossed_target is None else ("yes" if path.crossed_target else "no")
            print(f"    {whale_id:<16} final={path.last_coin_fraction:.4f}  target={target}  "
                  f"ticks at target={at_target}  crossed={crossed}")


def _print_psychology_observations(sim, ticks) -> None:
    """Descriptive statistics of the recorded market-wide psychology, and
    side-by-side comparisons over the same ticks. Nothing here says why a
    number is what it is."""
    report = analyze_psychology(ticks, trader_count=len(sim.traders) or None)
    print()
    print("Psychology observations (recorded market-wide state; descriptive only, calibration deferred):")
    print(f"  ticks with psychology: {report.ticks_with_psychology} of {report.ticks}")
    if not report.components:
        return
    levels = "  ".join(f">={level:.2f}" for level in OCCUPANCY_THRESHOLDS)
    print(
        f"  {'component':<12} {'mean':>6} {'median':>6} {'p90':>6} {'p95':>6} {'min':>6} {'max':>6}  {levels}"
        f"  longest run >={report.persistence_threshold:.2f}"
    )
    for c in report.components:
        shares = "  ".join(f"{o.share:>6.0%}" for o in c.occupancy)
        run = c.persistence
        run_note = f"{_ticks(run.longest_run)} from tick {run.longest_run_start}" if run.longest_run else "none"
        print(
            f"  {c.component:<12} {c.mean:>6.3f} {c.median:>6.3f} {c.p90:>6.3f} {c.p95:>6.3f} "
            f"{c.minimum:>6.3f} {c.maximum:>6.3f}  {shares}  {run_note}"
        )
    print("  Descriptive comparison — dominant component vs. trader fills on the same ticks:")
    for group in report.dominant:
        if not group.ticks:
            continue
        activity = group.activity
        participation = "" if activity.participation_rate is None else (
            f", {activity.participation_rate:.0%} of traders with fills"
        )
        print(
            f"    {group.dominant:<12} {_ticks(group.ticks):>9} ({group.share:>4.0%}): "
            f"{activity.fills_per_tick:.2f} fills/tick, "
            f"{activity.active_traders_per_tick:.2f} traders with fills/tick{participation}"
        )
    periods = report.event_periods
    if periods is not None:
        print(
            f"  Event-period comparison — {periods.event_period_ticks} ticks with a live event vs. "
            f"{periods.other_period_ticks} other ticks (ground-truth timing), mean per component:"
        )
        for means in periods.components:
            print(
                f"    {means.component:<12} {_num(means.event_period_mean, '.3f')} vs. "
                f"{_num(means.other_period_mean, '.3f')} (difference {_num(means.difference, '+.3f')})"
            )


def _print_manipulation_summary(sim, ticks, start_equity, manipulator_ids) -> None:
    last = ticks[-1].price
    pnl = {t.trader_id: t.wallet.equity(last) - start_equity[t.trader_id] for t in sim.traders}
    peak = max(ticks, key=lambda t: t.price)
    wash = sum(t.wash_volume for t in ticks)
    volume = sum(t.volume for t in ticks)
    print()
    print("Manipulation:")
    print(f"  peak price      : {peak.price:,.4f} at tick {peak.tick} (final {last:,.4f})")
    for trader_id in sorted(manipulator_ids):
        print(f"  {trader_id:<16}: P&L {pnl[trader_id]:+,.2f}")
    organic = sum(v for k, v in pnl.items() if k not in manipulator_ids)
    print(f"  organic traders : combined P&L {organic:+,.2f} (marked at the final price)")
    if wash:
        print(f"  wash volume     : {wash:,.0f} {sim.coin.symbol} = {wash / volume:.1%} of reported volume")


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
