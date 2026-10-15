import numpy as np
import pytest

from app.simulation.cn import (
    HSG_A, HSG_B, HSG_C, HSG_D, TEXTURE_CODES, adjust_amc, curve_number, hsg_from_texture,
    most_restrictive_hsg, usda_texture_class,
)


@pytest.mark.parametrize("sand,clay,expected", [
    (92, 3, "sand"), (80, 5, "loamy sand"), (65, 10, "sandy loam"), (40, 20, "loam"),
    (20, 15, "silt loam"), (5, 5, "silt"), (60, 25, "sandy clay loam"), (35, 33, "clay loam"),
    (10, 33, "silty clay loam"), (50, 40, "sandy clay"), (5, 45, "silty clay"), (20, 55, "clay"),
])
def test_usda_texture_triangle(sand, clay, expected):
    assert usda_texture_class(np.array([sand]), np.array([clay]))[0] == TEXTURE_CODES[expected]


def test_every_valid_composition_gets_a_class():
    sand, clay = np.meshgrid(np.arange(0, 101, 1.0), np.arange(0, 101, 1.0))
    ok = sand + clay <= 100
    assert (usda_texture_class(sand[ok], clay[ok]) > 0).all()


def test_texture_to_hsg_follows_ross_2018():
    codes = np.array([TEXTURE_CODES[t] for t in ("sand", "sandy loam", "clay loam", "clay")])
    assert hsg_from_texture(codes).tolist() == [HSG_A, HSG_B, HSG_C, HSG_D]


def test_most_restrictive_layer_wins():
    assert most_restrictive_hsg(np.array([HSG_A]), np.array([HSG_C]))[0] == HSG_C


def test_tr55_lookup_and_missing_soil():
    landcover = np.array([10, 10, 50, 40, 80])
    hsg = np.array([HSG_B, HSG_D, 0, 0, 0])
    cn, report = curve_number(landcover, hsg)
    assert cn[:3].tolist() == [55, 77, 98]       # woods B, woods D, built-up (soil-independent)
    assert np.isnan(cn[3])                       # cropland needs soil data
    assert cn[4] == 100                          # open water
    assert report["soil_missing_pixels"] == 1


def test_antecedent_moisture_ordering():
    cn = np.array([60.0, 80.0])
    assert np.all(adjust_amc(cn, "I") < cn) and np.all(adjust_amc(cn, "III") > cn)
    assert adjust_amc(np.array([98.0]), "III")[0] <= 100
    with pytest.raises(ValueError):
        adjust_amc(cn, "IV")
