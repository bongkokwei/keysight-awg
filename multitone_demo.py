"""
multitone_demo.py
=================
Generate a 3-tone waveform (1 MHz, 2 MHz, 3 MHz), plot it, and send it to
the M8195A AWG.
"""

from __future__ import annotations

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import time

from m8195a import M8195A
from m8195a_tools import configure_single_channel, load_and_play
from multitone_generator import MultiToneGenerator, ToneSpec
from rigol_dho4204 import DHO4204

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

HOST = "WINDOWS-QNNRGV2"
CHANNEL = 1
SEGMENT_ID = 1

SAMPLE_RATE = 65e9  # Sa/s  — single-channel mode maximum
GRANULARITY = 256  # samples — single-channel mode
NUM_CYCLES = 1  # buffer covers 1 fundamental period

TONES = [
    ToneSpec(frequency=1e6, amplitude=1 / 3, phase_deg=0),
    ToneSpec(frequency=2e6, amplitude=1 / 3, phase_deg=0),
    ToneSpec(frequency=3e6, amplitude=1 / 3, phase_deg=0),
]

# ---------------------------------------------------------------------------
# 1.  Generate waveform
# ---------------------------------------------------------------------------

gen = MultiToneGenerator(
    sample_rate=SAMPLE_RATE,
    granularity=GRANULARITY,
    num_cycles=NUM_CYCLES,
    use_schroeder_phases=True,
)

waveform = gen.generate(TONES)
papr = gen.papr_db(waveform)

print(f"Waveform length : {len(waveform):,} samples")
print(f"Duration        : {len(waveform) / SAMPLE_RATE * 1e6:.3f} µs")
print(f"PAPR            : {papr:.2f} dB")

# ---------------------------------------------------------------------------
# 2.  Plot — time-domain excerpt + power spectrum
# ---------------------------------------------------------------------------

t_us = np.arange(len(waveform)) / SAMPLE_RATE * 1e6  # µs
mask = t_us <= 3

fig = plt.figure(figsize=(12, 7))
fig.suptitle(
    f"Multitone waveform: {', '.join(f'{t.frequency/1e6:.0f} MHz' for t in TONES)}\n"
    f"Sample rate: {SAMPLE_RATE/1e9:.0f} GSa/s   |   "
    f"Buffer: {len(waveform):,} samples   |   "
    f"PAPR: {papr:.1f} dB",
    fontsize=11,
)

gs = gridspec.GridSpec(2, 1, hspace=0.45)

# --- Time domain ---
ax_time = fig.add_subplot(gs[0])
ax_time.plot(t_us[mask], waveform[mask], linewidth=0.8, color="#2563eb")
ax_time.set_xlabel("Time (µs)")
ax_time.set_ylabel("Normalised amplitude")
ax_time.set_title("Time domain (first 3 µs)")
ax_time.set_ylim(-1.1, 1.1)
ax_time.axhline(0, color="grey", linewidth=0.5, linestyle="--")
ax_time.grid(True, alpha=0.3)

# --- Power spectrum ---
ax_fft = fig.add_subplot(gs[1])

N = len(waveform)
spectrum = np.fft.rfft(waveform)
freqs_mhz = np.fft.rfftfreq(N, d=1.0 / SAMPLE_RATE) / 1e6
power_db = 20 * np.log10(np.abs(spectrum) / N + 1e-12)  # dBFS, avoid log(0)

# Limit x-axis to a sensible window around the tones
max_freq_mhz = max(t.frequency for t in TONES) / 1e6
ax_fft.plot(freqs_mhz, power_db, linewidth=0.7, color="#16a34a")
ax_fft.set_xlim(0, max_freq_mhz * 1.5)
ax_fft.set_ylim(bottom=-80)
ax_fft.set_xlabel("Frequency (MHz)")
ax_fft.set_ylabel("Power (dBFS)")
ax_fft.set_title("Power spectrum")
ax_fft.grid(True, alpha=0.3)

# Annotate the tone peaks
for tone in TONES:
    f_mhz = tone.frequency / 1e6
    # Find the nearest FFT bin
    bin_idx = np.argmin(np.abs(freqs_mhz - f_mhz))
    peak_db = power_db[bin_idx]
    ax_fft.annotate(
        f"{f_mhz:.0f} MHz",
        xy=(freqs_mhz[bin_idx], peak_db),
        xytext=(freqs_mhz[bin_idx] + 0.05, peak_db + 3),
        fontsize=8,
        arrowprops=dict(arrowstyle="->", lw=0.8),
    )
fig_path = "figures/multitone_plot_target.png"
fig_path = None  # set to None to skip saving

if fig_path is not None:
    plt.savefig(fig_path, dpi=150, bbox_inches="tight")
    print(f"Plot saved to {fig_path}")

# ---------------------------------------------------------------------------
# 3.  Send to AWG
# ---------------------------------------------------------------------------

print(f"\nConnecting to AWG at {HOST} ...")

with M8195A(HOST) as awg:
    configure_single_channel(awg, sample_rate=SAMPLE_RATE, amplitude=1.0)
    load_and_play(awg, CHANNEL, waveform, SEGMENT_ID)
    print(f"Waveform playing on channel {CHANNEL}.")

# # ---------------------------------------------------------------------------
# # 4. Measure with oscilloscope
# # ---------------------------------------------------------------------------

# with DHO4204() as scope:
#     # Basic setup
#     scope.channel_enable(1, True)
#     scope.channel_coupling(1, "DC")
#     scope.channel_scale(1, 0.5)
#     scope.channel_offset(1, 0.0)
#     scope.timebase_scale(500e-9)
#     scope.trigger_edge(ch=1, level=1.0, slope="POS")

#     # Let it trigger
#     scope.run()
#     time.sleep(2)
#     scope.stop()

#     # Read measurements
#     measurements = scope.measure_all(1)
#     print("\n── Measurements (CH1) ──")
#     for k, v in measurements.items():
#         print(f"  {k:>6s}: {v:.4g}")

#     # Download and plot waveform
#     scope.plot_waveform(1, save_path="figures/awg_multitone_3tones_python.png")
#     print("\nWaveform screenshot saved to figures/awg_multitone_3tones_python.png")

#     scope.system_restart()

#     print("\nDone.")

# # ---------------------------------------------------------------------------
# # Stop AWG output
# # ---------------------------------------------------------------------------

# with M8195A(host="WINDOWS-QNNRGV2") as awg:
#     awg.abort()
#     awg.set_output(1, False)  # pulls the output amp off
#     print("AWG output stopped.")
