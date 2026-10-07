"""
High-level helper functions for the Keysight M8195A AWG.

These are convenience wrappers around the low-level M8195A driver that
combine multiple SCPI calls into common workflows (quick channel setup,
waveform load-and-play, sine generation, etc.).

Usage:
    from keysight_awg.m8195a import M8195A

#: Waveform length granularity in [SINGle]-channel mode (samples).
SINGLE_CHANNEL_GRANULARITY = 256
#: Minimum segment length, in units of the granularity (1280 samples SINGle).
MIN_SEGMENT_VECTORS = 5
#: Default waveform buffer length (samples).
DEFAULT_LENGTH = 2**16
    from keysight_awg.tools import configure_single_channel, generate_sine

    with M8195A("169.254.x.x") as awg:
        configure_single_channel(awg)
        generate_sine(awg, channel=1, frequency=10e9)
"""

from __future__ import annotations

import numpy as np

from keysight_awg.m8195a import M8195A

#: Waveform length granularity in [SINGle]-channel mode (samples).
SINGLE_CHANNEL_GRANULARITY = 256
#: Minimum segment length, in units of the granularity (1280 samples SINGle).
MIN_SEGMENT_VECTORS = 5
#: Default waveform buffer length (samples).
DEFAULT_LENGTH = 2**16


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


def check_waveform_length(length: int, granularity: int = SINGLE_CHANNEL_GRANULARITY) -> None:
    """Raise ``ValueError`` unless *length* is a valid M8195A segment length.

    A segment must be a whole number of *granularity* samples (256 in
    [SINGle]-channel mode) and at least ``MIN_SEGMENT_VECTORS`` (5) of them,
    i.e. at least 1280 samples in [SINGle]-channel mode.
    """
    if length < MIN_SEGMENT_VECTORS * granularity or length % granularity != 0:
        raise ValueError(
            f"length must be a multiple of {granularity} and at least "
            f"{MIN_SEGMENT_VECTORS * granularity} samples, got {length}"
        )


def quantise_frequency(frequency: float, sample_rate: float, length: int) -> int:
    """Return the integer cycle count *n* whose tone is closest to *frequency*.

    A buffer of *length* samples looped at *sample_rate* can only hold tones
    at :math:`f = n f_s / L`, so the request is rounded to

    .. math::

        n = \\operatorname{round}\\!\\left(\\frac{f L}{f_s}\\right)

    Raises
    ------
    ValueError
        If *frequency* is not strictly positive, or *n* falls outside
        ``1 <= n < length / 2`` (i.e. the tone rounds to DC or to Nyquist).
    """
    if frequency <= 0:
        raise ValueError(f"frequency must be positive, got {frequency}")
    n = round(frequency * length / sample_rate)
    resolution = sample_rate / length
    if n < 1:
        raise ValueError(
            f"frequency {frequency} Hz is below the resolution {resolution} Hz "
            f"of a {length}-sample buffer; increase length"
        )
    if 2 * n >= length:
        raise ValueError(
            f"frequency {frequency} Hz exceeds Nyquist limit {sample_rate / 2} Hz"
        )
    return n


def generate_sine(
    awg: M8195A,
    channel: int = 1,
    frequency: float = 1e9,
    length: int = DEFAULT_LENGTH,
    segment_id: int = 1,
) -> float:
    """Generate and play a sine wave on *channel*.

    The buffer has a fixed *length* and holds an integer number of cycles
    *n*, so the looped output is phase-continuous.  The tone actually played
    is

    .. math::

        f_{\\text{out}} = \\frac{n f_s}{L}, \\qquad
        n = \\operatorname{round}\\!\\left(\\frac{f L}{f_s}\\right)

    so :math:`|f_{\\text{out}} - f| \\le f_s / 2L` (about 488 kHz at
    64 GSa/s with the default :math:`L = 2^{16}`).  Increase *length* for
    finer resolution, e.g. for MHz-scale tones.

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
        Requested sine frequency in Hz (default 1 GHz).
    length : int
        Waveform length in samples (default :math:`2^{16}`).  Must be a
        multiple of 256 and at least 1280 ([SINGle]-channel granularity).
    segment_id : int
        Segment identifier to use (default 1).

    Returns
    -------
    float
        The frequency actually played, :math:`n f_s / L`, in Hz.

    Raises
    ------
    ValueError
        If *length* is not a valid segment length, or *frequency* rounds to
        DC or to/above the Nyquist frequency.

    Examples
    --------
    >>> with M8195A("WINDOWS-QNNRGV2") as awg:
    ...     configure_single_channel(awg, sample_rate=64e9)
    ...     f_out = generate_sine(awg, channel=1, frequency=10e9)
    """
    check_waveform_length(length)
    sample_rate = awg.sample_rate
    n = quantise_frequency(frequency, sample_rate, length)

    t = np.arange(length)
    load_and_play(awg, channel, np.sin(2 * np.pi * n * t / length), segment_id)
    return n * sample_rate / length

if __name__ == "__main__":
    with M8195A(host="WINDOWS-QNNRGV2") as awg:
        configure_single_channel(awg, amplitude=1.0)
        generate_sine(awg, channel=1, frequency=1e9)
