# KMO Data-Class Filter [CRUX-MK]

Pre-Routing-Hook for KMO Dark-Factory: enforces 4-stage data-classification
(PUBLIC / INTERNAL / CONFIDENTIAL / SECRET) against provider-compatibility-matrix.

Implements **KMO v0.2.0 Patch P-KMO-A5** (Daten-Klassifikation No-Go-Matrix).

## Use-Case

When KMO routes a prompt to an LLM provider, this filter:

1. Classifies the prompt (frontmatter-tag first, regex pattern-detection fallback for SECRET).
2. Verifies the target provider's `max_data_class` accepts the classified prompt.
3. Returns `RoutingDecision` with ALLOW / BLOCK + reason.
4. Appends every decision to an append-only JSONL audit log.

SECRET-class is **fail-closed by design**: no LLM provider has `max_data_class: SECRET`.

## Setup

```bash
cd /Users/make/Projects/dark-factories/kmo/data-class-filter
pip3 install pyyaml pytest
pytest tests/ -v
```

## Examples

```python
from kmo_data_class_filter import DataClassFilter

f = DataClassFilter()

# Frontmatter-tagged prompt
decision = f.pre_routing_check(
    prompt="Refactor this function...",
    target_provider="codex-gpt5.5",
    frontmatter={"data_class": "PUBLIC"},
)
assert decision.allowed  # PUBLIC -> Codex OK

# Pattern-detected SECRET (no frontmatter)
decision = f.pre_routing_check(
    prompt="API_KEY=sk-abc123",
    target_provider="claude-opus",
)
assert not decision.allowed  # SECRET blocked everywhere
assert "api_key" in decision.detected_patterns

# CONFIDENTIAL stays inside trusted providers
decision = f.pre_routing_check(
    prompt="Family financial detail X",
    target_provider="perplexity-ultimate",
    frontmatter={"data_class": "CONFIDENTIAL"},
)
assert not decision.allowed  # Perplexity max=PUBLIC
```

## CRUX-Bindung

- **K_0 (Kapitalerhaltung):** SECRET-class never routed to flat-LLMs => credential-leak prevention. Pattern-detection auto-quarantines API keys, IBANs, credit-cards, private keys.
- **Q_0 (Qualitaetsinvarianz):** CONFIDENTIAL stays in Claude-Opus + Ollama-Local; family/finance detail never enters flat-LLM training pipelines (even with no-train clauses).

## Provider-Compatibility-Matrix

See `provider_compat.yaml`. Adjust per provider's data-contract change.
Default ranking (max_data_class):
- `claude-opus`, `claude-sonnet`, `ollama-local`: CONFIDENTIAL (3)
- `claude-haiku`, `codex-gpt5.5`, `gemini-2.5-pro`, `grok-4.20`, `copilot-pro`: INTERNAL (2)
- `perplexity-ultimate`: PUBLIC (1)

## Audit-Log

Every `pre_routing_check` appends to:
- Primary: `branch-hub/audit/kmo-routing-decisions.jsonl` (Drive-Sync if mounted)
- Fallback: `~/.kmo/kmo-routing-decisions.jsonl`

Format: one JSON-line per decision with `ts`, `decision`, `data_class`, `target_provider`, `reason`, `detected_patterns`.

## Status

- v0.1 implementation complete.
- Tests: 14 unit tests covering classify_input, is_provider_allowed, pre_routing_check, JSONL audit.
- **Pending:** Cross-LLM-Code-Review (W-Patch-A5-Pentagon: Codex + Gemini + Grok adversarial pass).

[CRUX-MK]
