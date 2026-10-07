"""Keysight M8195A AWG driver package."""

__version__ = "0.2.0"

from keysight_awg.m8195a import M8195A
from keysight_awg.multitone import MultiToneGenerator, ToneSpec
from keysight_awg.tools import configure_single_channel, generate_sine, load_and_play

__all__ = [
    "M8195A",
    "MultiToneGenerator",
    "ToneSpec",
    "configure_single_channel",
    "generate_sine",
    "load_and_play",
]
