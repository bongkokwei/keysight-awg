import importlib.metadata


def test_package_is_installed():
    meta = importlib.metadata.metadata("keysight_awg")
    assert meta["Name"] == "keysight_awg"


def test_version_is_set():
    meta = importlib.metadata.metadata("keysight_awg")
    assert meta["Version"] == "0.1.0"
