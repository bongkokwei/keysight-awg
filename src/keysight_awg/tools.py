"""
High-level helper functions for the Keysight M8195A AWG.

These are convenience wrappers around the low-level M8195A driver that
combine multiple SCPI calls into common workflows (quick channel setup,
waveform load-and-play, sine generation, etc.).

Usage:
    from keysight_awg.m8195a import M8195A
    from keysight_awg.tools import configure_single_channel, generate_sine

    with M8195A("169.254.x.x") as awg:
        configure_single_channel(awg)
        generate_sine(awg, channel=1, frequency=10e6)
"""

from __future__ import annotations

import numpy as np

from keysight_awg.m8195a import M8195A


def configure_single_channel(
    awg: M8195A,
    sample_rate: float = 64e9,
    amplitude: float = 0.5,
    offset: float = 0.0,
) -> None:
    """Quick setup: single-channel arbitrary mode.

    Resets the instrument, sets DAC mode to SINGle, configures sample
    rate, amplitude, offset, arm mode, and continuous triggering.

    Parameters
    ----------
    awg : M8195A
        Connected driver instance.
    sample_rate : float
        DAC sample rate in Hz (default 64 GSa/s).
    amplitude : float
        Peak-to-peak output amplitude in V (default 0.5).
    offset : float
        DC offset in V (default 0.0).
    """
    awg.reset()
    awg.dac_mode = "SING"
    awg.sample_rate = sample_rate
    awg.function_mode = "ARB"
    awg.set_amplitude(1, amplitude)
    awg.set_offset(1, offset)
    awg.arm_mode = "SELF"
    awg.continuous = True


def load_and_play(
    awg: M8195A,
    channel: int,
    waveform: np.ndarray,
    segment_id: int = 1,
) -> None:
    """Delete existing segments, define a new one, load data, and start.

    Parameters
    ----------
    awg : M8195A
        Connected driver instance.
    channel : int
        Target channel (1–4).
    waveform : np.ndarray
        Float array in [-1, +1] or int8 array.
    segment_id : int
        Segment identifier to use (default 1).
    """
    awg.abort(channel)
    awg.delete_all_segments(channel)

    length = len(waveform)
    awg.define_segment(channel, segment_id, length, init_value=0)

    if waveform.dtype == np.int8:
        awg.load_waveform(channel, segment_id, waveform)
    else:
        awg.load_waveform_float(channel, segment_id, waveform)

    awg.select_segment(channel, segment_id)
    awg.set_output(channel, True)
    awg.start(channel)


def generate_sine(
    awg: M8195A,
    channel: int = 1,
    frequency: float = 1e6,
    num_cycles: int = 1,
    segment_id: int = 1,
) -> None:
    """Generate and play a sine wave on *channel*.

    Computes the waveform length automatically from the instrument's current
    sample rate and the requested frequency, ensuring:

    - an integer number of complete cycles (no looping discontinuity), and
    - a length that is a multiple of 256 (single-channel granularity).

    The effective waveform sample rate is ``awg.sample_rate``, so
    ``configure_single_channel`` (or equivalent) must be called first to set
    the DAC sample rate before invoking this function.

    Parameters
    ----------
    awg : M8195A
        Connected driver instance.
    channel : int
        Target channel (default 1).
    frequency : float
        Sine frequency in Hz (default 1 MHz).  Must satisfy
        ``frequency < awg.sample_rate / 2`` (Nyquist limit).
    num_cycles : int
        Number of complete sine cycles in the waveform buffer (default 1).
        Increasing this value improves frequency resolution at the cost of
        more waveform memory.
    segment_id : int
        Segment identifier to use (default 1).

    Raises
    ------
    ValueError
        If *frequency* is not strictly positive, or exceeds the Nyquist
        frequency (``awg.sample_rate / 2``).

    Notes
    -----
    The minimum samples-per-cycle at 65 GSa/s for a 1 MHz sine is:

        N_cycle = f_s / f = 65e9 / 1e6 = 65 000 samples/cycle

    The raw count is rounded up to the next multiple of 256 (granularity
    for [SINGle]-channel mode) before the waveform array is allocated.
    Using fewer samples than one full period produces a sawtooth-like
    artefact because the DAC loops a tiny linear ramp of the sine rather
    than a complete oscillation.

    Examples
    --------
    >>> with M8195A("WINDOWS-QNNRGV2") as awg:
    ...     configure_single_channel(awg, sample_rate=65e9)
    ...     generate_sine(awg, channel=1, frequency=1e6, num_cycles=1)
    """
    sr = awg.sample_rate
    if frequency <= 0:
        raise ValueError(f"frequency must be positive, got {frequency}")
    if frequency >= sr / 2:
        raise ValueError(f"frequency {frequency} Hz exceeds Nyquist limit {sr / 2} Hz")

    granularity = 256
    raw = round(sr / frequency * num_cycles)
    num_samples = int(np.ceil(raw / granularity) * granularity)

    t = np.arange(num_samples) / sr
    waveform = np.sin(2 * np.pi * frequency * t)
    load_and_play(awg, channel, waveform, segment_id)


if __name__ == "__main__":
    with M8195A(host="WINDOWS-QNNRGV2") as awg:
        configure_single_channel(awg, amplitude=1.0)
        generate_sine(awg, channel=1, frequency=1e6)
