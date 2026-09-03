# keysight-awg

Python driver for the Keysight M8195A 65 GSa/s Arbitrary Waveform Generator.

Communicates via SCPI commands over a raw TCP socket (port 5025) — no VISA or pyvisa required.

## Installation

```bash
pip install -e .
```

With optional dependencies:

```bash
pip install -e ".[plot]"   # adds matplotlib for example scripts
pip install -e ".[dev]"    # adds pytest
```

## Quick start

```python
from keysight_awg import M8195A

with M8195A("192.168.1.10") as awg:
    print(awg.idn)
    awg.reset()
    awg.dac_mode = "SING"
    awg.sample_rate = 65e9
```

## High-level helpers

```python
from keysight_awg import M8195A, configure_single_channel, generate_sine

with M8195A("192.168.1.10") as awg:
    configure_single_channel(awg, sample_rate=65e9, amplitude=0.5)
    generate_sine(awg, channel=1, frequency=1e6)
```

## Multitone generation

```python
from keysight_awg import M8195A, MultiToneGenerator, ToneSpec, load_and_play

tones = [
    ToneSpec(frequency=1e6, amplitude=1/3),
    ToneSpec(frequency=2e6, amplitude=1/3),
    ToneSpec(frequency=3e6, amplitude=1/3),
]

gen = MultiToneGenerator(sample_rate=65e9, use_schroeder_phases=True)
waveform = gen.generate(tones)
print(f"PAPR: {gen.papr_db(waveform):.1f} dB")

with M8195A("192.168.1.10") as awg:
    configure_single_channel(awg, sample_rate=65e9, amplitude=1.0)
    load_and_play(awg, channel=1, waveform=waveform)
```

## Package structure

```
src/keysight_awg/
    m8195a.py      # M8195A driver class (SCPI over TCP)
    tools.py       # configure_single_channel, load_and_play, generate_sine
    multitone.py   # MultiToneGenerator, ToneSpec
examples/
    multitone_demo.py    # 3-tone waveform generation + plotting
    stop_output.py       # quick stop-output script
    test_connection.py   # connection test
```

## Requirements

- Python >= 3.10
- numpy >= 1.24
