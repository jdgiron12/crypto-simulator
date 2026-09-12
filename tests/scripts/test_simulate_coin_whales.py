"""The demo CLI with funded whales configured."""

import dataclasses

import crypto_simulator.config
from crypto_simulator.config import WhaleSettings, get_settings
from tests.scripts.test_simulate_coin import _run


def _with_whales(monkeypatch, whales):
    settings = get_settings()
    patched = dataclasses.replace(settings, coin=dataclasses.replace(settings.coin, whales=whales))
    monkeypatch.setattr(crypto_simulator.config, "get_settings", lambda *args, **kwargs: patched)


def _accounting(output):
    lines = output.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("Accounting ("))
    return lines[start:start + 3]


def test_funded_whales_are_included_in_the_accounting_check(monkeypatch, capsys):
    _with_whales(monkeypatch, [WhaleSettings("acc", 0.0, activity_probability=0.5, max_trade_fraction=0.02,
                                             starting_cash=300_000.0, behavior="accumulate")])
    header, coins, cash = _accounting(_run(monkeypatch, capsys, "--ticks", "40"))
    assert header == "Accounting (traders + funded whales + market reserve):"
    for line in (coins, cash):
        before, after = line.split(":", 1)[1].split(" / ")
        assert before.strip() == after.strip()


def test_the_default_unfunded_whale_keeps_the_original_accounting_label(monkeypatch, capsys):
    header, _, _ = _accounting(_run(monkeypatch, capsys, "--ticks", "10"))
    assert header == "Accounting (traders + market reserve):"
