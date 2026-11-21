from __future__ import annotations

from advisor.risk.trailing import ratchet_stop, stop_loss_pct


def test_stop_loss_pct():
    assert abs(stop_loss_pct(100, 97) - 0.03) < 1e-9


def test_breakeven_at_one_r():
    entry, initial = 100.0, 97.0  # R=3
    upd = ratchet_stop(
        entry=entry,
        current_stop=initial,
        mark_price=103.0,  # +1R
        initial_stop=initial,
        breakeven_at_r=1.0,
        trail_at_r=2.0,
        cost_buffer_pct=0.001,
    )
    assert upd.event == "breakeven"
    assert upd.stop >= entry


def test_trail_lock_at_two_r():
    entry, initial = 100.0, 97.0
    upd = ratchet_stop(
        entry=entry,
        current_stop=entry,  # already BE
        mark_price=106.0,  # +2R
        initial_stop=initial,
        breakeven_at_r=1.0,
        trail_at_r=2.0,
    )
    assert upd.event == "trail_1R"
    assert abs(upd.stop - (entry + 3.0)) < 1e-6  # +1R locked


def test_never_lowers_stop():
    upd = ratchet_stop(
        entry=100.0,
        current_stop=101.0,
        mark_price=99.0,
        initial_stop=97.0,
    )
    assert upd.stop == 101.0
    assert upd.event is None
