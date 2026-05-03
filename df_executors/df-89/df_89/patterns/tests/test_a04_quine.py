"""CRUX-MK tests for A-04 Quine/Kleene self-description pattern."""

from pathlib import Path

import pytest

from df_89.config import DFConfig
from df_89.patterns.a04_quine import BootstrapRegistry, DFConfigDescriptor


def _descriptor(dependencies: list[str] | None = None) -> DFConfigDescriptor:
    return DFConfigDescriptor(
        config=DFConfig(topic="fixpoints", state_dir=Path("state/df-89")),
        dependencies=dependencies or [],
    )


def test_describe_returns_dict_with_required_keys() -> None:
    desc = _descriptor().describe()

    assert isinstance(desc, dict)
    assert desc["version"] == "0.1.0-skeleton"
    assert desc["type"] == "DFConfigDescriptor"
    assert desc["config"]["df_id"] == "DF-89"


def test_from_description_reconstructs_module() -> None:
    original = _descriptor()

    reconstructed = DFConfigDescriptor.from_description(original.describe())

    assert isinstance(reconstructed, DFConfigDescriptor)
    assert reconstructed.config == original.config
    assert reconstructed.dependencies == original.dependencies


def test_verify_fixpoint_idempotent() -> None:
    module = _descriptor()
    desc = module.describe()

    assert module.verify_fixpoint() is True
    assert DFConfigDescriptor.from_description(desc).describe() == desc


def test_bootstrap_registry_serializes() -> None:
    registry = BootstrapRegistry()
    registry.register(_descriptor())

    restored = BootstrapRegistry.from_json(registry.to_json())

    assert restored.describe() == registry.describe()
    assert restored.modules["DF-89"].verify_fixpoint() is True


def test_bootstrap_from_seed_recreates_state(tmp_path: Path) -> None:
    registry = BootstrapRegistry()
    registry.register(_descriptor())
    seed = tmp_path / "seed.json"
    seed.write_text(registry.to_json(), encoding="utf-8")

    restored = BootstrapRegistry.bootstrap_from_seed(seed)

    assert restored.describe() == registry.describe()


def test_dependency_cycle_detected() -> None:
    registry = BootstrapRegistry()
    registry.register(_descriptor(dependencies=["DF-89"]))

    with pytest.raises(ValueError, match="dependency cycle detected"):
        registry.to_json()


def test_external_seed_required() -> None:
    with pytest.raises(ValueError, match="external seed required"):
        BootstrapRegistry.bootstrap_from_seed(None)
