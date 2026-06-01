"""Tests for CoT air/surface selection helpers."""

from lib.cot_select import cot_event_type_selectable, ledger_row_selectable


def test_adsb_rows_always_selectable():
    assert ledger_row_selectable("aircraft", None) is True
    assert ledger_row_selectable("aircraft", "") is True


def test_cot_air_and_surface():
    assert cot_event_type_selectable("a-f-A-M-H-Q") is True
    assert cot_event_type_selectable("a-h-S-C-F") is True


def test_cot_ground_and_bridge_types_rejected():
    assert cot_event_type_selectable("a-f-G-E-S-E") is False
    assert cot_event_type_selectable("b-i-v") is False
    assert cot_event_type_selectable("b-m-p-s-p-e") is False


def test_cot_row_requires_air_or_surface():
    assert ledger_row_selectable("cot", "a-f-A-M-H-Q") is True
    assert ledger_row_selectable("cot", "b-i-v") is False
    assert ledger_row_selectable("cot", "") is False
