"""A return to the city that is already in the city must not toggle out of it.

The loop runs the full cycle whenever it finds the queue full, including right
after a wait that came back too early -- still in the city. The corner button
is a toggle, so that return took the view OUT of the city: over every return in
the log, 62 of the 114 that followed a "TOO EARLY" wait landed on the world
map, and live 2026-09-14 13:25 the harvest then ran there.

The toggle is skipped only when the flow's flag and a fresh glyph read both
say city. After a march the flag says world, so the old failure -- the glyph
misreading the post-march map as the city and the return never happening --
cannot come back through this.
"""

from rok_farm.flow_steps import GemFlowMixin


class Fake(GemFlowMixin):
    def __init__(self, flag_world, reads_world):
        self._view_is_world = flag_world
        self.reads_world = reads_world
        self.toggles = 0

    def _on_world_map(self, frame=None):
        return self.reads_world

    def _toggle_view(self, label):
        self.toggles += 1

    def _wait(self, seconds):
        pass

    def _grab(self):
        return None

    def _record(self, *args, **kwargs):
        pass


def test_after_a_wait_in_the_city_it_does_not_toggle_out():
    f = Fake(flag_world=False, reads_world=False)
    f._step_return_city("city_idle")
    assert f.toggles == 0
    assert f._view_is_world is False


def test_after_a_march_it_toggles_even_when_the_glyph_reads_city():
    """The post-march map reads ambiguously; the flag decides."""
    f = Fake(flag_world=True, reads_world=False)
    f._step_return_city("city_idle")
    assert f.toggles == 1
    assert f._view_is_world is False


def test_a_flag_that_says_city_is_overruled_by_a_world_reading():
    """The flag can be wrong -- a return whose toggle did not take still sets
    it to city. A clear world reading means toggle."""
    f = Fake(flag_world=False, reads_world=True)
    f._step_return_city("city_idle")
    assert f.toggles == 1


def test_an_unknown_flag_toggles_as_before():
    f = Fake(flag_world=True, reads_world=True)
    del f._view_is_world
    f._step_return_city("city_idle")
    assert f.toggles == 1
