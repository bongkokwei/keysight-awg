from __future__ import annotations

import math
import warnings
import numpy as np
from dataclasses import dataclass
from typing import Sequence

from keysight_awg.tools import (
    DEFAULT_LENGTH,
    SINGLE_CHANNEL_GRANULARITY,
    check_waveform_length,
    quantise_frequency,
)


@dataclass
class ToneSpec:
    """Specification for a single tone in a multitone waveform.

    Parameters
    ----------
    frequency : float
        Tone frequency in Hz.  Must be positive and below the Nyquist limit.
    amplitude : float
        Normalised amplitude in the range (0, 1].  Default is 1.0.
        The sum of all amplitudes should not exceed 1.0 to avoid clipping.
    phase_deg : float
        Initial phase in degrees.  Default is 0.0.
        Use Schroeder phases (see ``MultiToneGenerator``) to minimise PAPR
        instead of setting this manually.
    """

    frequency: float
    amplitude: float = 1.0
    phase_deg: float = 0.0


class MultiToneGenerator:
    """Generate a multitone waveform buffer for the Keysight M8195A AWG.

    The class is intentionally decoupled from the ``M8195A`` driver: it
    accepts raw AWG parameters (sample rate, granularity) rather than a
    connected instrument instance, so waveforms can be designed and
    inspected offline.

    The buffer has a fixed length :math:`L` and every tone is snapped to an
    integer number of cycles in it, so the looped waveform is
    phase-continuous at the loop boundary:

    .. math::

        n_k = \\operatorname{round}\\!\\left(\\frac{f_k L}{f_s}\\right),
        \\qquad f_{k,\\text{out}} = \\frac{n_k f_s}{L}

    Each tone is therefore played within :math:`f_s / 2L` of its request;
    use :meth:`actual_frequencies` to see the values.  :math:`L` must be a
    multiple of the waveform granularity :math:`G` (256 for [SINGle]-channel
    mode, 128 for dual, 64 for four-channel) and at least :math:`5G`.

    Peak-to-average power ratio (PAPR) can be reduced by applying
    Schroeder phases instead of zero phases:

    .. math::

        \\phi_k = -\\frac{k(k-1)\\pi}{K}

    where :math:`k` is the 1-based tone index and :math:`K` is the total
    number of tones.

    Parameters
    ----------
    sample_rate : float
        AWG waveform sample rate in Sa/s (e.g. 65e9 for [SINGle]-channel
        mode at maximum rate).
    length : int
        Buffer length in samples.  Default is :math:`2^{16}`.  The frequency
        resolution is :math:`f_s / L`; increase it for closely spaced or
        low-frequency tones.
    granularity : int
        Waveform length granularity in samples.  Defaults to 256
        ([SINGle]-channel mode).
    use_schroeder_phases : bool
        If ``True``, override ``phase_deg`` on all tones with Schroeder
        phases to minimise PAPR.  Default is ``False``.

    Examples
    --------
    >>> gen = MultiToneGenerator(sample_rate=64e9)
    >>> tones = [
    ...     ToneSpec(frequency=1e9, amplitude=0.3),
    ...     ToneSpec(frequency=2e9, amplitude=0.3),
    ...     ToneSpec(frequency=3e9, amplitude=0.3),
    ... ]
    >>> waveform = gen.generate(tones)
    >>> waveform.shape
    (65536,)
    """

    def __init__(
        self,
        sample_rate: float = 64e9,
        length: int = DEFAULT_LENGTH,
        granularity: int = SINGLE_CHANNEL_GRANULARITY,
        use_schroeder_phases: bool = False,
    ) -> None:
        if sample_rate <= 0:
            raise ValueError(f"sample_rate must be positive, got {sample_rate}")
        if granularity <= 0 or (granularity & (granularity - 1)) != 0:
            raise ValueError(
                f"granularity must be a positive power of 2, got {granularity}"
            )
        check_waveform_length(length, granularity)

        self.sample_rate = sample_rate
        self.length = length
        self.granularity = granularity
        self.use_schroeder_phases = use_schroeder_phases

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(self, tones: Sequence[ToneSpec]) -> np.ndarray:
        """Compute the multitone waveform buffer.

        Parameters
        ----------
        tones : sequence of ToneSpec
            List of tone specifications.  At least one tone is required.
            The sum of ``amplitude`` values should be <= 1.0 to avoid
            clipping; a ``UserWarning`` is raised if this is exceeded.

        Returns
        -------
        numpy.ndarray
            Floating-point waveform samples normalised to [-1, 1], of
            length ``self.length``.  Tones play at
            :meth:`actual_frequencies`.

        Raises
        ------
        ValueError
            If *tones* is empty, any frequency rounds to DC or to/above the
            Nyquist limit, or any amplitude is outside (0, 1].
        """
        if not tones:
            raise ValueError("tones must contain at least one ToneSpec")

        self._validate_tones(tones)

        cycles = self._compute_cycles(tones)
        if len(set(cycles)) < len(cycles):
            warnings.warn(
                "Two or more tones round to the same frequency bin "
                f"(resolution {self.sample_rate / self.length} Hz); "
                "increase length to separate them.",
                UserWarning,
                stacklevel=2,
            )
        phases = self._compute_phases(tones)

        t = np.arange(self.length)
        waveform = np.zeros(self.length, dtype=np.float64)

        for spec, n, phase_rad in zip(tones, cycles, phases):
            waveform += spec.amplitude * np.sin(
                2.0 * np.pi * n * t / self.length + phase_rad
            )

        peak = np.max(np.abs(waveform))
        if peak > 1.0:
            warnings.warn(
                f"Waveform peak amplitude {peak:.3f} exceeds 1.0; "
                "normalising to prevent DAC clipping.  "
                "Reduce individual tone amplitudes or enable Schroeder phases.",
                UserWarning,
                stacklevel=2,
            )
            waveform /= peak

        return waveform

    def actual_frequencies(self, tones: Sequence[ToneSpec]) -> list[float]:
        """Return the frequency, in Hz, at which each tone is actually played.

        Each is :math:`n_k f_s / L` with
        :math:`n_k = \\operatorname{round}(f_k L / f_s)`.
        """
        return [n * self.sample_rate / self.length for n in self._compute_cycles(tones)]

    def papr_db(self, waveform: np.ndarray) -> float:
        """Return the peak-to-average power ratio of *waveform* in dB.

        .. math::

            \\text{PAPR} = 10 \\log_{10}\\!\\left(
                \\frac{\\max(|x|^2)}{\\overline{|x|^2}}
            \\right)
        """
        power = waveform ** 2
        return 10.0 * np.log10(np.max(power) / np.mean(power))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _validate_tones(self, tones: Sequence[ToneSpec]) -> None:
        for i, spec in enumerate(tones):
            try:
                quantise_frequency(spec.frequency, self.sample_rate, self.length)
            except ValueError as exc:
                raise ValueError(f"tones[{i}]: {exc}") from None
            if not (0.0 < spec.amplitude <= 1.0):
                raise ValueError(
                    f"tones[{i}].amplitude must be in (0, 1], got {spec.amplitude}"
                )

    def _compute_cycles(self, tones: Sequence[ToneSpec]) -> list[int]:
        """Return the integer cycle count of each tone in the buffer."""
        return [
            quantise_frequency(spec.frequency, self.sample_rate, self.length)
            for spec in tones
        ]

    def _compute_phases(self, tones: Sequence[ToneSpec]) -> list[float]:
        """Return per-tone initial phases in radians."""
        k_total = len(tones)
        phases = []
        for k, spec in enumerate(tones, start=1):
            if self.use_schroeder_phases:
                # Schroeder phase: phi_k = -k(k-1)*pi / K
                phase_rad = -k * (k - 1) * math.pi / k_total
            else:
                phase_rad = math.radians(spec.phase_deg)
            phases.append(phase_rad)
        return phases