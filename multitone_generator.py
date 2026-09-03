from __future__ import annotations

import math
import numpy as np
from dataclasses import dataclass, field
from typing import Sequence


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

    The buffer length is chosen to contain an integer number of cycles of
    *every* tone, avoiding loop-boundary discontinuities.  The fundamental
    period is determined by the GCD of all tone frequencies:

    .. math::

        f_{\\text{fund}} = \\gcd(f_1, f_2, \\ldots, f_k)

        N_{\\text{raw}} = \\frac{f_s}{f_{\\text{fund}}} \\times n_{\\text{cycles}}

        N = \\lceil N_{\\text{raw}} / G \\rceil \\times G

    where :math:`G` is the waveform granularity (256 for [SINGle]-channel
    mode, 128 for dual, 64 for four-channel).

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
    granularity : int
        Waveform length granularity in samples.  Defaults to 256
        ([SINGle]-channel mode).
    num_cycles : int
        Number of fundamental periods in the buffer.  Default is 1.
        Increasing this improves frequency resolution at the cost of
        waveform memory.
    use_schroeder_phases : bool
        If ``True``, override ``phase_deg`` on all tones with Schroeder
        phases to minimise PAPR.  Default is ``False``.

    Examples
    --------
    >>> gen = MultiToneGenerator(sample_rate=65e9)
    >>> tones = [
    ...     ToneSpec(frequency=1e6, amplitude=0.3),
    ...     ToneSpec(frequency=2e6, amplitude=0.3),
    ...     ToneSpec(frequency=3e6, amplitude=0.3),
    ... ]
    >>> waveform = gen.generate(tones)
    >>> waveform.shape
    (65000,)
    """

    def __init__(
        self,
        sample_rate: float = 65e9,
        granularity: int = 256,
        num_cycles: int = 1,
        use_schroeder_phases: bool = False,
    ) -> None:
        if sample_rate <= 0:
            raise ValueError(f"sample_rate must be positive, got {sample_rate}")
        if granularity <= 0 or (granularity & (granularity - 1)) != 0:
            raise ValueError(
                f"granularity must be a positive power of 2, got {granularity}"
            )
        if num_cycles < 1:
            raise ValueError(f"num_cycles must be >= 1, got {num_cycles}")

        self.sample_rate = sample_rate
        self.granularity = granularity
        self.num_cycles = num_cycles
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
            Floating-point waveform samples normalised to [-1, 1].  Length
            is a multiple of ``self.granularity``.

        Raises
        ------
        ValueError
            If *tones* is empty, any frequency is non-positive or exceeds
            the Nyquist limit, or any amplitude is outside (0, 1].
        """
        if not tones:
            raise ValueError("tones must contain at least one ToneSpec")

        self._validate_tones(tones)

        num_samples = self._compute_num_samples(tones)
        phases = self._compute_phases(tones)

        t = np.arange(num_samples) / self.sample_rate
        waveform = np.zeros(num_samples, dtype=np.float64)

        for spec, phase_rad in zip(tones, phases):
            waveform += spec.amplitude * np.sin(
                2.0 * np.pi * spec.frequency * t + phase_rad
            )

        peak = np.max(np.abs(waveform))
        if peak > 1.0:
            import warnings
            warnings.warn(
                f"Waveform peak amplitude {peak:.3f} exceeds 1.0; "
                "normalising to prevent DAC clipping.  "
                "Reduce individual tone amplitudes or enable Schroeder phases.",
                UserWarning,
                stacklevel=2,
            )
            waveform /= peak

        return waveform

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
        nyquist = self.sample_rate / 2.0
        for i, spec in enumerate(tones):
            if spec.frequency <= 0:
                raise ValueError(
                    f"tones[{i}].frequency must be positive, got {spec.frequency}"
                )
            if spec.frequency >= nyquist:
                raise ValueError(
                    f"tones[{i}].frequency {spec.frequency} Hz exceeds "
                    f"Nyquist limit {nyquist} Hz"
                )
            if not (0.0 < spec.amplitude <= 1.0):
                raise ValueError(
                    f"tones[{i}].amplitude must be in (0, 1], got {spec.amplitude}"
                )

    def _compute_num_samples(self, tones: Sequence[ToneSpec]) -> int:
        """Return the smallest valid buffer length covering all tones.

        Uses integer arithmetic on Hz values (rounded to the nearest
        millihertz) to avoid floating-point GCD errors.
        """
        # Scale to mHz integers for robust GCD computation.
        scale = 1000
        int_freqs = [round(spec.frequency * scale) for spec in tones]
        fund_mhz = math.gcd(*int_freqs)
        fund_hz = fund_mhz / scale

        raw = round(self.sample_rate / fund_hz * self.num_cycles)
        return int(math.ceil(raw / self.granularity) * self.granularity)

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