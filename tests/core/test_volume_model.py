import pytest

from crypto_simulator.core.volume_model import VolumeModel


def test_volume_is_always_non_negative():
    model = VolumeModel(supply=1_000_000.0, seed=1)
    for _ in range(50):
        assert model.next_volume() >= 0


def test_volume_is_reproducible_given_same_seed():
    a = VolumeModel(supply=1_000_000.0, seed=42)
    b = VolumeModel(supply=1_000_000.0, seed=42)
    assert [a.next_volume() for _ in range(10)] == [b.next_volume() for _ in range(10)]


def test_volume_scales_with_supply():
    small = VolumeModel(supply=1_000.0, seed=1)
    large = VolumeModel(supply=1_000_000.0, seed=1)
    assert large.next_volume() > small.next_volume()


def test_volume_rejects_non_positive_supply():
    with pytest.raises(ValueError):
        VolumeModel(supply=0)


def test_volume_rejects_negative_base_volume_pct():
    with pytest.raises(ValueError):
        VolumeModel(supply=1_000.0, base_volume_pct=-0.1)
