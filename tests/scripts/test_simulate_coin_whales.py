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


# --- --whale-observation (Phase 8, Step 7) -----------------------------------------------------


def test_the_flag_prints_a_whale_summary(monkeypatch, capsys):
    _with_whales(monkeypatch, [WhaleSettings("acc", 0.0, activity_probability=0.6, max_trade_fraction=0.02,
                                             starting_cash=300_000.0, behavior="accumulate",
                                             target_coin_fraction=0.5)])
    output = _run(monkeypatch, capsys, "--ticks", "60", "--whale-observation")
    assert "Whale observations (descriptive; no causal claim):" in output
    assert "ticks with observations: 60 of 60" in output
    assert "whale observation: on (descriptive only)" in output
    assert "tick outcomes:" in output and "acc" in output
    assert "allocation (funded whales, marked at each fill's own price):" in output
    assert "target=0.500" in output and "crossed=no" in output


def test_the_summary_is_absent_without_the_flag(monkeypatch, capsys):
    _with_whales(monkeypatch, [WhaleSettings("acc", 0.0, activity_probability=0.6, max_trade_fraction=0.02,
                                             starting_cash=300_000.0, behavior="accumulate")])
    output = _run(monkeypatch, capsys, "--ticks", "60")
    assert "Whale observations" not in output
    assert "whale observation" not in output


def test_the_flag_does_not_change_the_rest_of_the_output(monkeypatch, capsys):
    _with_whales(monkeypatch, [WhaleSettings("acc", 0.0, activity_probability=0.6, max_trade_fraction=0.02,
                                             starting_cash=300_000.0, behavior="accumulate")])
    plain = _run(monkeypatch, capsys, "--ticks", "30")
    observed = _run(monkeypatch, capsys, "--ticks", "30", "--whale-observation")
    # Everything up to the new section is identical apart from the added
    # configuration line and wall-clock timestamps, which the tick table
    # does not print.
    shared = observed.split("Whale observations")[0]
    for line in plain.splitlines():
        if line.startswith("  whales") or "Accounting" in line or not line.strip():
            continue
        assert line in shared or line in observed


def test_an_unfunded_whale_reports_no_allocation_section(monkeypatch, capsys):
    output = _run(monkeypatch, capsys, "--ticks", "40", "--whale-observation")
    assert "Whale observations (descriptive; no causal claim):" in output
    assert "allocation (funded whales" not in output


def test_the_flag_works_with_no_whales(monkeypatch, capsys):
    output = _run(monkeypatch, capsys, "--ticks", "20", "--no-whales", "--whale-observation")
    assert "no whale observations recorded" in output
