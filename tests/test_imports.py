def test_import_m8195a_class():
    from keysight_awg.m8195a import M8195A
    assert callable(M8195A)


def test_import_tools():
    from keysight_awg.tools import configure_single_channel, load_and_play, generate_sine
    assert callable(configure_single_channel)
    assert callable(load_and_play)
    assert callable(generate_sine)


def test_import_multitone():
    from keysight_awg.multitone import MultiToneGenerator, ToneSpec
    assert callable(MultiToneGenerator)
    assert callable(ToneSpec)
