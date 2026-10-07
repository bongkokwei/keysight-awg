"""Hardware-free tests for fixed-length, integer-cycle tone generation."""

from __future__ import annotations

import numpy as np
import pytest

from keysight_awg import MultiToneGenerator, ToneSpec, generate_sine

SAMPLE_RATE = 64e9
LENGTH = 2**16
FREQS_GHZ = range(1, 31)


class FakeAWG:
    """Stand-in for ``M8195A`` that records the loaded waveform."""

    def __init__(self, sample_rate: float = SAMPLE_RATE) -> None:
        self.sample_rate = sample_rate
        self.waveform: np.ndarray | None = None
        self.segment_length: int | None = None
        self.started = False

    def abort(self, channel): pass
    def delete_all_segments(self, channel): pass
    def select_segment(self, channel, segment_id): pass
    def set_output(self, channel, on): pass

    def define_segment(self, channel, segment_id, length, init_value=0):
        self.segment_length = length

    def load_waveform_float(self, channel, segment_id, waveform):
        self.waveform = np.asarray(waveform)

    def start(self, channel):
        self.started = True


def assert_loops_continuously(w: np.ndarray) -> None:
    """The step from the last sample back to the first is an ordinary step."""
    wrap_step = w[0] - w[-1]
    assert abs(wrap_step) <= np.max(np.abs(np.diff(w))) + 1e-12


# ---------------------------------------------------------------------------
# generate_sine
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("f_ghz", FREQS_GHZ)
def test_generate_sine_returns_frequency_within_resolution(f_ghz):
    awg = FakeAWG()
    requested = f_ghz * 1e9
    played = generate_sine(awg, channel=1, frequency=requested)

    assert abs(played - requested) <= SAMPLE_RATE / LENGTH
    # Played frequency is an exact integer number of cycles in the buffer.
    n = played * LENGTH / SAMPLE_RATE
    assert n == pytest.approx(round(n), abs=1e-9)
    assert awg.started
    assert awg.segment_length == LENGTH == len(awg.waveform)


@pytest.mark.parametrize("f_ghz", FREQS_GHZ)
def test_generate_sine_loops_continuously(f_ghz):
    awg = FakeAWG()
    generate_sine(awg, channel=1, frequency=f_ghz * 1e9)
    w = awg.waveform

    assert_loops_continuously(w)
    # For a pure sine the wrap-around step equals the first step exactly.
    assert w[0] - w[-1] == pytest.approx(w[1] - w[0], abs=1e-9)


def test_generate_sine_waveform_is_at_returned_frequency():
    awg = FakeAWG()
    played = generate_sine(awg, channel=1, frequency=12.345e9)
    spectrum = np.abs(np.fft.rfft(awg.waveform))
    peak_bin = int(np.argmax(spectrum))

    assert peak_bin * SAMPLE_RATE / LENGTH == played
    # No spectral leakage: everything outside the tone bin is numerical noise.
    off_peak = np.delete(spectrum, peak_bin)
    assert np.max(off_peak) < 1e-6 * spectrum[peak_bin]


def test_generate_sine_custom_length():
    awg = FakeAWG()
    played = generate_sine(awg, channel=1, frequency=1e6, length=64_000)
    assert played == 1e6
    assert len(awg.waveform) == 64_000


@pytest.mark.parametrize("length", [1000, 1024, 2**16 + 128])
def test_generate_sine_rejects_bad_length(length):
    with pytest.raises(ValueError, match="length"):
        generate_sine(FakeAWG(), frequency=1e9, length=length)


@pytest.mark.parametrize("frequency", [0.0, -1e9, 100e3, 32e9, 40e9])
def test_generate_sine_rejects_out_of_range_frequency(frequency):
    with pytest.raises(ValueError):
        generate_sine(FakeAWG(), frequency=frequency)


# ---------------------------------------------------------------------------
# MultiToneGenerator
# ---------------------------------------------------------------------------


def test_multitone_actual_frequencies_within_resolution():
    gen = MultiToneGenerator(sample_rate=SAMPLE_RATE)
    tones = [ToneSpec(frequency=f * 1e9, amplitude=1 / 30) for f in FREQS_GHZ]
    played = gen.actual_frequencies(tones)

    for spec, f_out in zip(tones, played):
        assert abs(f_out - spec.frequency) <= SAMPLE_RATE / LENGTH


@pytest.mark.parametrize("schroeder", [False, True])
def test_multitone_loops_continuously(schroeder):
    gen = MultiToneGenerator(sample_rate=SAMPLE_RATE, use_schroeder_phases=schroeder)
    tones = [
        ToneSpec(frequency=1.1e9, amplitude=0.3),
        ToneSpec(frequency=7.77e9, amplitude=0.3, phase_deg=45),
        ToneSpec(frequency=29.9e9, amplitude=0.3),
    ]
    w = gen.generate(tones)

    assert len(w) == LENGTH
    assert_loops_continuously(w)

    # All energy sits in the integer bins of the played frequencies.
    spectrum = np.abs(np.fft.rfft(w))
    bins = [round(f * LENGTH / SAMPLE_RATE) for f in gen.actual_frequencies(tones)]
    off_tone = np.delete(spectrum, bins)
    assert np.max(off_tone) < 1e-6 * np.max(spectrum)


def test_multitone_warns_when_tones_share_a_bin():
    gen = MultiToneGenerator(sample_rate=SAMPLE_RATE)
    tones = [ToneSpec(frequency=10e9, amplitude=0.4), ToneSpec(frequency=10.0001e9, amplitude=0.4)]
    with pytest.warns(UserWarning, match="same frequency bin"):
        gen.generate(tones)


def test_multitone_rejects_bad_length():
    with pytest.raises(ValueError, match="length"):
        MultiToneGenerator(sample_rate=SAMPLE_RATE, length=65_000)
