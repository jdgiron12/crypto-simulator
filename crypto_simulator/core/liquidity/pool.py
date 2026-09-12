"""``AMMPool``: a constant-product (x * y = k) liquidity pool.

x = coin reserve, y = cash reserve, spot price = y / x (cash per coin).

Swaps are exact-input, with fee rate f charged on the input asset:

- buy:  cash in Δy; fee = Δy·f; net = Δy - fee
        coins out = x - ceil(k / (y + net))
        reserves become (x - out, y + Δy)
- sell: coins in Δx; fee = Δx·f; net = Δx - fee
        cash out  = y - ceil(k / (x + net))
        reserves become (x + Δx, y - out)

The output is priced on the *net* input, so with f = 0 the swap moves
exactly along the x·y = k curve (spot rises to P·(1 + Δy/y)² on a buy and
falls to P/(1 + Δx/x)² on a sell). The fee itself stays inside the reserves
(Uniswap v2 model): it deepens the pool, so ``k`` grows by the fee on every
swap and LP shares appreciate. Fees are never implicit — each
``SwapResult`` reports its fee and the pool keeps cumulative
``fees_collected_cash`` / ``fees_collected_coins`` counters.

Rounding always favors the pool (outputs are computed from a reserve
rounded *up*), so ``k`` can never decrease and reserves can never reach
zero: a buy can approach, but never take, the whole coin reserve.

Liquidity is tracked with LP shares: the initial provider gets √k shares;
later deposits mint ``total · min(Δx/x, Δy/y)`` (rounded down — anything
beyond the pool ratio stays in the pool); withdrawals pay the pro-rata
share of the reserves, fees included (rounded down). Because fees live in
the reserves, a provider joining later pays for them when depositing and
cannot capture fees earned before it joined. The last share cannot be
withdrawn, so a pool always keeps positive reserves and a defined price.

The pool never touches wallets; ``settlement`` moves wallet balances.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from crypto_simulator.core.liquidity.amounts import (
    CEILING,
    EXACT,
    FLOOR,
    NEAREST,
    ONE,
    ZERO,
    to_amount,
    to_rate,
)

BUY = "buy"
SELL = "sell"


class AMMError(ValueError):
    """Base class for pool operations that cannot be carried out."""


class InsufficientLiquidityError(AMMError):
    """The pool (or an LP position) cannot cover the requested operation."""


class InsufficientOutputError(AMMError):
    """The operation is too small to produce any output after rounding."""


class SlippageExceededError(AMMError):
    """The output would fall below the caller's minimum acceptable amount."""


@dataclass(frozen=True)
class SwapResult:
    """Everything about one swap (or quote). Amounts are ``Decimal``.

    ``amount_in`` and ``fee`` are in the input asset (cash for buys, coins
    for sells); ``amount_out`` is in the other asset. Prices are cash per
    coin. ``execution_price`` includes the fee; ``slippage`` excludes it
    (how much worse than ``spot_price_before`` the fee-free price was);
    ``price_impact`` is the relative change in spot price.
    """

    side: str
    amount_in: Decimal
    fee: Decimal
    amount_in_after_fee: Decimal
    amount_out: Decimal
    spot_price_before: Decimal
    spot_price_after: Decimal
    execution_price: Decimal
    price_impact: Decimal
    slippage: Decimal
    fee_rate: Decimal
    coin_reserve_after: Decimal
    cash_reserve_after: Decimal

    @property
    def fee_asset(self) -> str:
        return "cash" if self.side == BUY else "coin"

    @property
    def coins_traded(self) -> Decimal:
        return self.amount_out if self.side == BUY else self.amount_in

    @property
    def cash_traded(self) -> Decimal:
        return self.amount_in if self.side == BUY else self.amount_out


@dataclass(frozen=True)
class LiquidityChange:
    """Result of ``add_liquidity`` / ``remove_liquidity``."""

    kind: str
    provider_id: str
    coins: Decimal
    cash: Decimal
    shares: Decimal


@dataclass(frozen=True)
class PoolState:
    """Point-in-time snapshot of a pool.

    ``fees_collected_*`` are cumulative counters of fees already included
    in the reserves — informational, not extra balances.
    """

    coin_reserve: Decimal
    cash_reserve: Decimal
    invariant: Decimal
    spot_price: Decimal
    fee_rate: Decimal
    fees_collected_coins: Decimal
    fees_collected_cash: Decimal
    total_shares: Decimal
    swap_count: int


def _require_positive(name: str, amount: Decimal) -> None:
    if amount <= 0:
        raise ValueError(f"{name} must be positive (got {amount})")


class AMMPool:
    """Constant-product pool of a coin against cash."""

    def __init__(
        self,
        coin_reserve: Decimal | float | int | str,
        cash_reserve: Decimal | float | int | str,
        *,
        fee_rate: Decimal | float | int | str = "0.003",
        initial_provider: str = "initial",
    ):
        coins = to_amount(coin_reserve)
        cash = to_amount(cash_reserve)
        _require_positive("coin_reserve", coins)
        _require_positive("cash_reserve", cash)
        rate = to_rate(fee_rate)
        if not ZERO <= rate < ONE:
            raise ValueError(f"fee_rate must be within [0, 1) (got {rate})")
        if not initial_provider:
            raise ValueError("initial_provider must not be empty")

        self._coins = coins
        self._cash = cash
        self.fee_rate = rate
        self.fees_collected_coins = ZERO
        self.fees_collected_cash = ZERO
        self.swap_count = 0
        initial_shares = FLOOR.sqrt(EXACT.multiply(coins, cash))
        if initial_shares <= 0:
            raise InsufficientOutputError("initial reserves too small to mint LP shares")
        self._shares: dict[str, Decimal] = {initial_provider: initial_shares}
        self.total_shares = initial_shares

    # --- state ------------------------------------------------------------

    @property
    def coin_reserve(self) -> Decimal:
        return self._coins

    @property
    def cash_reserve(self) -> Decimal:
        return self._cash

    @property
    def invariant(self) -> Decimal:
        """k = coin_reserve * cash_reserve (exact)."""
        return EXACT.multiply(self._coins, self._cash)

    def spot_price(self) -> Decimal:
        """Marginal price of one coin in cash: cash_reserve / coin_reserve."""
        return NEAREST.divide(self._cash, self._coins)

    def shares_of(self, provider_id: str) -> Decimal:
        return self._shares.get(provider_id, ZERO)

    def state(self) -> PoolState:
        return PoolState(
            coin_reserve=self._coins,
            cash_reserve=self._cash,
            invariant=self.invariant,
            spot_price=self.spot_price(),
            fee_rate=self.fee_rate,
            fees_collected_coins=self.fees_collected_coins,
            fees_collected_cash=self.fees_collected_cash,
            total_shares=self.total_shares,
            swap_count=self.swap_count,
        )

    # --- swaps ------------------------------------------------------------

    def quote_buy(self, cash_in: Decimal | float | int | str) -> SwapResult:
        """What ``buy(cash_in)`` would do, without changing the pool."""
        amount_in, fee, net = self._split_fee(cash_in)
        retained_coins = CEILING.divide(self.invariant, EXACT.add(self._cash, net))
        coins_out = EXACT.subtract(self._coins, retained_coins)
        return self._result(BUY, amount_in, fee, net, coins_out)

    def quote_sell(self, coins_in: Decimal | float | int | str) -> SwapResult:
        """What ``sell(coins_in)`` would do, without changing the pool."""
        amount_in, fee, net = self._split_fee(coins_in)
        retained_cash = CEILING.divide(self.invariant, EXACT.add(self._coins, net))
        cash_out = EXACT.subtract(self._cash, retained_cash)
        return self._result(SELL, amount_in, fee, net, cash_out)

    def buy(
        self,
        cash_in: Decimal | float | int | str,
        *,
        min_coins_out: Decimal | float | int | str = 0,
        coins_out: Decimal | float | int | str | None = None,
    ) -> SwapResult:
        """Swap ``cash_in`` cash for coins.

        ``min_coins_out`` is slippage protection: the swap is refused if it
        would deliver less. ``coins_out`` lets the caller take *less* than
        the quoted output (e.g. the most a float wallet can be credited
        without exceeding the quote); the remainder stays in the pool.
        """
        return self._execute(self.quote_buy(cash_in), min_coins_out, coins_out)

    def sell(
        self,
        coins_in: Decimal | float | int | str,
        *,
        min_cash_out: Decimal | float | int | str = 0,
        cash_out: Decimal | float | int | str | None = None,
    ) -> SwapResult:
        """Swap ``coins_in`` coins for cash. See ``buy`` for the options."""
        return self._execute(self.quote_sell(coins_in), min_cash_out, cash_out)

    def _split_fee(self, amount) -> tuple[Decimal, Decimal, Decimal]:
        amount_in = to_amount(amount)
        _require_positive("swap amount", amount_in)
        fee = EXACT.multiply(amount_in, self.fee_rate)
        return amount_in, fee, EXACT.subtract(amount_in, fee)

    def _result(self, side: str, amount_in, fee, net, amount_out) -> SwapResult:
        if amount_out <= 0:
            raise InsufficientOutputError(f"{side} of {amount_in} is too small to produce any output")
        if side == BUY:
            if amount_out >= self._coins:
                raise InsufficientLiquidityError("buy would exhaust the coin reserve")
            coins_after = EXACT.subtract(self._coins, amount_out)
            cash_after = EXACT.add(self._cash, amount_in)
            execution_price = NEAREST.divide(amount_in, amount_out)
            fee_free_price = NEAREST.divide(net, amount_out)
        else:
            if amount_out >= self._cash:
                raise InsufficientLiquidityError("sell would exhaust the cash reserve")
            coins_after = EXACT.add(self._coins, amount_in)
            cash_after = EXACT.subtract(self._cash, amount_out)
            execution_price = NEAREST.divide(amount_out, amount_in)
            fee_free_price = NEAREST.divide(amount_out, net)

        spot_before = self.spot_price()
        spot_after = NEAREST.divide(cash_after, coins_after)
        relative = NEAREST.divide(fee_free_price, spot_before)
        slippage = NEAREST.subtract(relative, ONE) if side == BUY else NEAREST.subtract(ONE, relative)
        return SwapResult(
            side=side,
            amount_in=amount_in,
            fee=fee,
            amount_in_after_fee=net,
            amount_out=amount_out,
            spot_price_before=spot_before,
            spot_price_after=spot_after,
            execution_price=execution_price,
            price_impact=NEAREST.subtract(NEAREST.divide(spot_after, spot_before), ONE),
            slippage=slippage,
            fee_rate=self.fee_rate,
            coin_reserve_after=coins_after,
            cash_reserve_after=cash_after,
        )

    def _execute(self, quote: SwapResult, minimum, delivered) -> SwapResult:
        result = quote
        if delivered is not None:
            amount_out = to_amount(delivered)
            if not ZERO < amount_out <= quote.amount_out:
                raise ValueError(
                    f"delivered amount must be within (0, {quote.amount_out}] (got {amount_out})"
                )
            if amount_out != quote.amount_out:
                result = self._result(
                    quote.side, quote.amount_in, quote.fee, quote.amount_in_after_fee, amount_out
                )
        if result.amount_out < to_amount(minimum):
            raise SlippageExceededError(
                f"{result.side} output {result.amount_out} is below the minimum {minimum}"
            )

        self._coins = result.coin_reserve_after
        self._cash = result.cash_reserve_after
        if result.side == BUY:
            self.fees_collected_cash = EXACT.add(self.fees_collected_cash, result.fee)
        else:
            self.fees_collected_coins = EXACT.add(self.fees_collected_coins, result.fee)
        self.swap_count += 1
        return result

    # --- liquidity ----------------------------------------------------------

    def optimal_deposit(
        self, max_coins: Decimal | float | int | str, max_cash: Decimal | float | int | str
    ) -> tuple[Decimal, Decimal]:
        """Largest (coins, cash) within the maxima that matches the pool ratio."""
        coins_cap, cash_cap = to_amount(max_coins), to_amount(max_cash)
        _require_positive("max_coins", coins_cap)
        _require_positive("max_cash", cash_cap)
        cash_for_all_coins = CEILING.divide(EXACT.multiply(coins_cap, self._cash), self._coins)
        if cash_for_all_coins <= cash_cap:
            return coins_cap, cash_for_all_coins
        coins_for_all_cash = FLOOR.divide(EXACT.multiply(cash_cap, self._coins), self._cash)
        return coins_for_all_cash, cash_cap

    def add_liquidity(
        self, provider_id: str, coins: Decimal | float | int | str, cash: Decimal | float | int | str
    ) -> LiquidityChange:
        """Deposit both assets and mint LP shares for ``provider_id``.

        Shares are minted for the *smaller* of the two contributions relative
        to the reserves; any excess of the other asset stays in the pool
        (benefiting all LPs). Use ``optimal_deposit`` to avoid that.
        """
        if not provider_id:
            raise ValueError("provider_id must not be empty")
        coins_in, cash_in = to_amount(coins), to_amount(cash)
        _require_positive("coins", coins_in)
        _require_positive("cash", cash_in)
        ratio = min(FLOOR.divide(coins_in, self._coins), FLOOR.divide(cash_in, self._cash))
        minted = FLOOR.multiply(self.total_shares, ratio)
        if minted <= 0:
            raise InsufficientOutputError("deposit too small to mint any LP shares")

        self._coins = EXACT.add(self._coins, coins_in)
        self._cash = EXACT.add(self._cash, cash_in)
        self._shares[provider_id] = EXACT.add(self.shares_of(provider_id), minted)
        self.total_shares = EXACT.add(self.total_shares, minted)
        return LiquidityChange("add", provider_id, coins_in, cash_in, minted)

    def remove_liquidity(self, provider_id: str, shares: Decimal | float | int | str) -> LiquidityChange:
        """Burn ``shares`` and pay their pro-rata share of both reserves."""
        burn = to_amount(shares)
        _require_positive("shares", burn)
        owned = self.shares_of(provider_id)
        if burn > owned:
            raise InsufficientLiquidityError(
                f"{provider_id!r} owns {owned} shares; cannot remove {burn}"
            )
        if burn >= self.total_shares:
            raise InsufficientLiquidityError(
                "cannot remove the pool's last liquidity; reserves must stay positive"
            )

        coins_out = FLOOR.divide(EXACT.multiply(self._coins, burn), self.total_shares)
        cash_out = FLOOR.divide(EXACT.multiply(self._cash, burn), self.total_shares)
        self._coins = EXACT.subtract(self._coins, coins_out)
        self._cash = EXACT.subtract(self._cash, cash_out)
        remaining = EXACT.subtract(owned, burn)
        if remaining == 0:
            del self._shares[provider_id]
        else:
            self._shares[provider_id] = remaining
        self.total_shares = EXACT.subtract(self.total_shares, burn)
        return LiquidityChange("remove", provider_id, coins_out, cash_out, burn)
