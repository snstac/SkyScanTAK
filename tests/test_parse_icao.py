"""Tests for ICAO hex extraction from object_id."""

from video.parse import extract_icao_hex


def test_cot_video_uid_not_parsed_as_icao():
    assert extract_icao_hex("cot-skyscan-roof_sf-cam1-video") is None


def test_cot_icao_prefix():
    assert extract_icao_hex("cot-icao-a1c90e") == "A1C90E"


def test_plain_hex():
    assert extract_icao_hex("a506d5") == "A506D5"
