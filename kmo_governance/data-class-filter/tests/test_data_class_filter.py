"""Tests for KMO Data-Class Filter [CRUX-MK].

Coverage:
- classify_input via frontmatter (all 4 classes)
- classify_input via SECRET-pattern detection
- pre_routing_check ALLOW for compatible class+provider
- pre_routing_check BLOCK for class > provider-max
- pre_routing_check BLOCK for unknown provider (fail-closed)
- JSONL audit-log append (format + content)
- YAML provider_compat load
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kmo_data_class_filter import (
    DataClass,
    DataClassFilter,
    RoutingDecision,
    SECRET_PATTERNS,
)


@pytest.fixture
def tmp_filter(tmp_path: Path) -> DataClassFilter:
    """Filter with isolated audit-log + real provider_compat.yaml."""
    config = Path(__file__).parent.parent / "provider_compat.yaml"
    audit = tmp_path / "audit.jsonl"
    return DataClassFilter(config_path=config, audit_log_path=audit)


# ----- DataClass.from_tag -----

@pytest.mark.parametrize(
    "tag,expected",
    [
        ("PUBLIC", DataClass.PUBLIC),
        ("public", DataClass.PUBLIC),
        ("INTERNAL", DataClass.INTERNAL),
        ("CONFIDENTIAL", DataClass.CONFIDENTIAL),
        ("SECRET", DataClass.SECRET),
        ("CLASS-1", DataClass.PUBLIC),
        ("class_2", DataClass.INTERNAL),
        ("3", DataClass.CONFIDENTIAL),
        ("nonsense", None),
        ("", None),
    ],
)
def test_dataclass_from_tag(tag, expected):
    """from_tag accepts canonical names + class-N + integer-string."""
    assert DataClass.from_tag(tag) == expected


# ----- classify_input via frontmatter -----

def test_classify_via_frontmatter_all_4_classes(tmp_filter: DataClassFilter):
    """Frontmatter-tag wins over content; all 4 DataClasses parseable."""
    prompt = "harmless content"
    cases = {
        "PUBLIC": DataClass.PUBLIC,
        "INTERNAL": DataClass.INTERNAL,
        "CONFIDENTIAL": DataClass.CONFIDENTIAL,
        "SECRET": DataClass.SECRET,
    }
    for tag, expected in cases.items():
        actual = tmp_filter.classify_input(prompt, frontmatter={"data_class": tag})
        assert actual == expected, f"Tag '{tag}' should yield {expected.name}"


def test_classify_via_frontmatter_alt_key(tmp_filter: DataClassFilter):
    """Both `data_class` and `data-class` keys accepted."""
    actual = tmp_filter.classify_input("x", frontmatter={"data-class": "INTERNAL"})
    assert actual == DataClass.INTERNAL


# ----- classify_input via pattern detection -----

@pytest.mark.parametrize(
    "prompt",
    [
        "API_KEY=sk-abc123def456",
        "Bearer eyJhbGciOiJIUzI1NiIsInR",
        "PASSWORD: hunter2",
        "Authorization: Bearer xoxp-secret-token-here",
        "AKIAIOSFODNN7EXAMPLE in config",
        "IBAN DE89 3704 0044 0532 0130 00",
        "card 4532-1234-5678-9010 expires 12/27",
        "-----BEGIN PRIVATE KEY-----\nMIIE...",
    ],
)
def test_classify_secret_patterns(tmp_filter: DataClassFilter, prompt: str):
    """SECRET_PATTERNS triggers SECRET-class without frontmatter."""
    actual = tmp_filter.classify_input(prompt)
    assert actual == DataClass.SECRET, f"Pattern in '{prompt[:30]}...' should -> SECRET"


def test_classify_default_public(tmp_filter: DataClassFilter):
    """No frontmatter + no SECRET-pattern -> PUBLIC default."""
    actual = tmp_filter.classify_input("Generate a hello-world Python script.")
    assert actual == DataClass.PUBLIC


def test_secret_pattern_count():
    """Sanity-check: at least 8 SECRET-patterns active."""
    assert len(SECRET_PATTERNS) >= 8


# ----- is_provider_allowed -----

def test_provider_compat_matrix(tmp_filter: DataClassFilter):
    """Compat-matrix loads correctly."""
    assert tmp_filter.is_provider_allowed(DataClass.PUBLIC, "perplexity-ultimate")
    assert tmp_filter.is_provider_allowed(DataClass.CONFIDENTIAL, "claude-opus")
    assert tmp_filter.is_provider_allowed(DataClass.CONFIDENTIAL, "ollama-local")
    # CONFIDENTIAL must NOT be allowed on flat-LLMs:
    assert not tmp_filter.is_provider_allowed(DataClass.CONFIDENTIAL, "codex-gpt5.5")
    assert not tmp_filter.is_provider_allowed(DataClass.CONFIDENTIAL, "perplexity-ultimate")


def test_unknown_provider_fail_closed(tmp_filter: DataClassFilter):
    """Unknown provider -> always denied."""
    assert not tmp_filter.is_provider_allowed(DataClass.PUBLIC, "unknown-xyz")


# ----- pre_routing_check ALLOW/BLOCK -----

def test_pre_routing_allow_public_to_perplexity(tmp_filter: DataClassFilter):
    decision = tmp_filter.pre_routing_check(
        prompt="What is 2+2?",
        target_provider="perplexity-ultimate",
        frontmatter={"data_class": "PUBLIC"},
    )
    assert decision.allowed is True
    assert decision.data_class == DataClass.PUBLIC


def test_pre_routing_block_secret_anywhere(tmp_filter: DataClassFilter):
    """SECRET must be blocked on every configured LLM provider."""
    secret_prompt = "API_KEY=sk-leaked-key-12345"
    for provider in [
        "claude-opus",
        "claude-sonnet",
        "codex-gpt5.5",
        "gemini-2.5-pro",
        "grok-4.20",
        "copilot-pro",
        "perplexity-ultimate",
        "ollama-local",
    ]:
        decision = tmp_filter.pre_routing_check(secret_prompt, provider)
        assert decision.allowed is False, f"SECRET MUST block on {provider}"
        assert decision.data_class == DataClass.SECRET
        assert "api_key" in decision.detected_patterns


def test_pre_routing_block_confidential_to_flat_llm(tmp_filter: DataClassFilter):
    """CONFIDENTIAL blocked on all flat-LLMs (codex/gemini/grok/copilot/perplexity)."""
    decision = tmp_filter.pre_routing_check(
        prompt="Family-financial-detail XYZ",
        target_provider="codex-gpt5.5",
        frontmatter={"data_class": "CONFIDENTIAL"},
    )
    assert decision.allowed is False
    assert "Mismatch" in decision.reason


def test_pre_routing_allow_confidential_to_opus(tmp_filter: DataClassFilter):
    """CONFIDENTIAL routes to Claude-Opus + Ollama only."""
    decision = tmp_filter.pre_routing_check(
        prompt="Q_0 family decision context",
        target_provider="claude-opus",
        frontmatter={"data_class": "CONFIDENTIAL"},
    )
    assert decision.allowed is True


def test_pre_routing_unknown_provider_blocks(tmp_filter: DataClassFilter):
    decision = tmp_filter.pre_routing_check(
        prompt="hello",
        target_provider="invalid-llm-name",
        frontmatter={"data_class": "PUBLIC"},
    )
    assert decision.allowed is False
    assert "Unbekannt" in decision.reason


# ----- audit-log JSONL append -----

def test_audit_log_appends_jsonl(tmp_filter: DataClassFilter):
    """Each pre_routing_check writes exactly one JSONL line."""
    log = tmp_filter.audit_log_path
    n_before = log.read_text(encoding="utf-8").count("\n") if log.exists() else 0

    tmp_filter.pre_routing_check("hi", "claude-opus", frontmatter={"data_class": "PUBLIC"})
    tmp_filter.pre_routing_check("hi", "perplexity-ultimate", frontmatter={"data_class": "INTERNAL"})

    n_after = log.read_text(encoding="utf-8").count("\n")
    assert n_after - n_before == 2

    # Validate JSON-format of last line
    last_line = log.read_text(encoding="utf-8").splitlines()[-1]
    parsed = json.loads(last_line)
    assert parsed["decision"] in {"ALLOW", "BLOCK"}
    assert "ts" in parsed
    assert "data_class" in parsed
    assert parsed["target_provider"] == "perplexity-ultimate"


def test_yaml_load_smoke(tmp_filter: DataClassFilter):
    """YAML loaded: at least 5 providers, all values mapped to DataClass int."""
    assert len(tmp_filter._compat) >= 5
    for prov, cls_int in tmp_filter._compat.items():
        assert 1 <= cls_int <= 4, f"Provider {prov} has invalid class {cls_int}"


def test_routing_decision_log_entry_shape(tmp_filter: DataClassFilter):
    decision = tmp_filter.pre_routing_check(
        "API_KEY=test",
        "claude-opus",
    )
    entry = decision.to_log_entry()
    required = {"ts", "ts_iso", "decision", "data_class", "target_provider", "reason"}
    assert required.issubset(entry.keys())
    assert entry["decision"] == "BLOCK"
    assert entry["data_class"] == "SECRET"
