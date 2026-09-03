def test_top_level_import_m8195a():
    from keysight_awg import M8195A
    assert M8195A.SCPI_PORT == 5025

def test_top_level_import_multitone():
    from keysight_awg import MultiToneGenerator, ToneSpec
    import numpy as np
    gen = MultiToneGenerator(sample_rate=1e9, granularity=256)
    tones = [ToneSpec(frequency=1e6, amplitude=0.5)]
    waveform = gen.generate(tones)
    assert isinstance(waveform, np.ndarray)
    assert len(waveform) % 256 == 0

def test_top_level_import_tools():
    from keysight_awg import configure_single_channel, load_and_play, generate_sine
    assert callable(configure_single_channel)

def test_version():
    import keysight_awg
    assert keysight_awg.__version__ == "0.1.0"
