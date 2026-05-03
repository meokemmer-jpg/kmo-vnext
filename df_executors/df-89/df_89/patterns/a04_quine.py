"""CRUX-MK A-04 Quine/Kleene fixpoint self-description pattern."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

from df_89.config import DFConfig


class ModuleDescription(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str
    type: str
    module_id: str
    config: dict[str, Any]
    dependencies: list[str] = Field(default_factory=list)

    @field_validator("version", "type", "module_id")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        """Pre: value is parsed as a string. Post: value is non-empty."""
        stripped = value.strip()
        if not stripped:
            raise ValueError("description identity fields must not be blank")
        return stripped


class SelfDescribingModule(ABC):
    """Base for modules that can reconstruct their own description."""

    _types: ClassVar[dict[str, type["SelfDescribingModule"]]] = {}
    type_name: ClassVar[str]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        type_name = getattr(cls, "type_name", None)
        if type_name:
            SelfDescribingModule._types[type_name] = cls

    @abstractmethod
    def describe(self) -> dict[str, Any]:
        """Pre: initialized module. Post: deterministic JSON-safe description."""

    @classmethod
    def from_description(cls, desc: dict[str, Any]) -> "SelfDescribingModule":
        """Pre: registered desc type. Post: described module instance."""
        parsed = ModuleDescription.model_validate(desc)
        if cls is SelfDescribingModule:
            target = cls._types.get(parsed.type)
            if target is None:
                raise ValueError(f"unknown module type: {parsed.type}")
            return target._from_description(parsed)
        return cls._from_description(parsed)

    @classmethod
    @abstractmethod
    def _from_description(cls, desc: ModuleDescription) -> "SelfDescribingModule":
        """Pre: validated desc. Post: module instance."""

    def verify_fixpoint(self) -> bool:
        """Pre: deterministic round-trip. Post: fixpoint truth value."""
        desc = self.describe()
        return self.from_description(desc).describe() == desc


class DFConfigDescriptor(BaseModel, SelfDescribingModule):
    """Self-describing DF-89 configuration module."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    type_name: ClassVar[str] = "DFConfigDescriptor"
    config: DFConfig
    dependencies: list[str] = Field(default_factory=list)

    @property
    def module_id(self) -> str:
        """Pre: valid config. Post: stable registry key."""
        return self.config.df_id

    def describe(self) -> dict[str, Any]:
        """Pre: valid config. Post: canonical description."""
        return ModuleDescription(
            version=self.config.version,
            type=self.type_name,
            module_id=self.module_id,
            config=self.config.model_dump(mode="json"),
            dependencies=list(self.dependencies),
        ).model_dump(mode="json")

    @classmethod
    def _from_description(cls, desc: ModuleDescription) -> "DFConfigDescriptor":
        """Pre: matching desc.type. Post: recreated descriptor."""
        if desc.type != cls.type_name:
            raise ValueError(f"cannot build {cls.type_name} from {desc.type}")
        return cls(
            config=DFConfig.model_validate(desc.config),
            dependencies=list(desc.dependencies),
        )


class BootstrapRegistry:
    """Registry for self-describing modules and seed-based bootstrapping."""

    def __init__(self) -> None:
        self._modules: dict[str, SelfDescribingModule] = {}

    @property
    def modules(self) -> dict[str, SelfDescribingModule]:
        """Pre: registry exists. Post: module mapping copy."""
        return dict(self._modules)

    def register(self, module: SelfDescribingModule) -> None:
        """Pre: module self-describes. Post: registered by module_id."""
        desc = ModuleDescription.model_validate(module.describe())
        self._modules[desc.module_id] = module

    def describe(self) -> list[dict[str, Any]]:
        """Pre: acyclic graph. Post: topologically ordered descriptions."""
        return [self._modules[module_id].describe() for module_id in self._topological_ids()]

    def to_json(self) -> str:
        """Pre: acyclic graph. Post: deterministic JSON snapshot."""
        modules = [ModuleDescription.model_validate(item).model_dump() for item in self.describe()]
        return json.dumps(
            {"modules": modules}, sort_keys=True, separators=(",", ":")
        )

    @classmethod
    def from_json(cls, payload: str) -> "BootstrapRegistry":
        """Pre: valid snapshot. Post: recreated registry state."""
        data = json.loads(payload)
        registry = cls()
        for item in data["modules"]:
            desc = ModuleDescription.model_validate(item)
            registry.register(SelfDescribingModule.from_description(desc.model_dump()))
        registry._topological_ids()
        return registry

    @classmethod
    def bootstrap_from_seed(cls, seed_path: Path | None) -> "BootstrapRegistry":
        """Pre: external seed path. Post: cold-booted registry."""
        if seed_path is None:
            raise ValueError("external seed required for bootstrap")
        if not seed_path.exists():
            raise FileNotFoundError(seed_path)
        return cls.from_json(seed_path.read_text(encoding="utf-8"))

    def _topological_ids(self) -> list[str]:
        descriptions = {
            module_id: ModuleDescription.model_validate(module.describe())
            for module_id, module in self._modules.items()
        }
        visiting: set[str] = set()
        visited: set[str] = set()
        ordered: list[str] = []

        def visit(module_id: str) -> None:
            if module_id in visited:
                return
            if module_id in visiting:
                raise ValueError("dependency cycle detected")
            desc = descriptions.get(module_id)
            if desc is None:
                raise ValueError(f"unknown dependency: {module_id}")
            visiting.add(module_id)
            for dependency in desc.dependencies:
                visit(dependency)
            visiting.remove(module_id)
            visited.add(module_id)
            ordered.append(module_id)

        for module_id in descriptions:
            visit(module_id)
        return ordered
