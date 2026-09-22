"""The wander drifted halfway across the kingdom and nothing pulled it back.

The operator saw the symptom before any counter did -- "sao tim gem xa the
nhi" -- and asked whether the map was simply barren. It was not. Measured on
kingdom 4096 from 2026-09-20, pairing every deposit with the march time that
followed it:

    0-30 tiles from the city   median  5.3 min
    30-60                      median  5.0 min
    60-100                     median  8.4 min
    100-160                    median 13.0 min
    160-240                    median 13.3 min
    240+                       median 18.1 min

68% of marches were past 60 tiles and 45% past 100, and by evening a round
trip that takes half an hour near home was taking over an hour.

The same evening's log had the fix in it already: "map step: 267 tiles
(844,465 -> 577,582)" straight after a return to the city. The trip resets
the camera; nothing was using that.
"""

import ast
import inspect

from rok_farm import flow_steps
from rok_farm.flow_steps import GemFlowMixin, HOME_RADIUS_TILES


class Fake(GemFlowMixin):
    def __init__(self, home=None, here=None):
        if home:
            self._city_xy = home
        if here:
            self._last_map_xy = here


def test_the_radius_sits_where_the_march_time_doubles():
    assert 60 <= HOME_RADIUS_TILES <= 160, HOME_RADIUS_TILES


def test_distance_is_unknown_until_both_ends_are():
    assert Fake()._tiles_from_home() is None
    assert Fake(home=(577, 617))._tiles_from_home() is None
    assert Fake(here=(577, 617))._tiles_from_home() is None


def test_it_measures_the_drift():
    f = Fake(home=(577, 617), here=(844, 465))
    assert f._tiles_from_home() == 267


def test_near_home_is_not_a_drift():
    f = Fake(home=(577, 617), here=(600, 640))
    assert f._tiles_from_home() == 23
    assert f._tiles_from_home() <= HOME_RADIUS_TILES


def test_the_scan_walks_back_before_searching_not_after_failing():
    src = inspect.getsource(GemFlowMixin._step_scan_and_verify_gem)
    drift = src.find("_tiles_from_home")
    first_scan = src.find("scan_count = 0")
    assert drift != -1, "the scan no longer checks how far out it is"
    assert drift < first_scan, (
        "the drift check happens after the search has started, which spends "
        "the mine before noticing")


def test_every_city_trip_teaches_it_where_home_is():
    """The drift check needs a home and a home is only seen on a city trip.
    Setting the flag only inside the homing path would be a circle that never
    starts."""
    src = inspect.getsource(GemFlowMixin._step_return_city)
    assert "_expect_home_read" in src, (
        "home is only learned when the homing path runs, which cannot run "
        "until home is known")


def test_home_is_only_taken_from_the_home_kingdom():
    """A coordinate read while passing through another kingdom is a different
    coordinate space."""
    # _map_sync is where the accepted coordinate lands and where the home
    # kingdom is decided; the raw OCR reader next door knows nothing about
    # either. Two functions handle positions and picking the wrong one is
    # what this assertion is guarding against in the first place.
    src = inspect.getsource(GemFlowMixin._map_sync)
    idx = src.find("_city_xy")
    assert idx != -1, "home is never recorded"
    assert "_off_home_map" in src[max(0, idx - 300):idx], (
        "home can be learned from another kingdom's coordinates")
