"""KMO Wound-Healing Phase-Transitions [CRUX-MK].

State-machine validator. Forward-only transitions per ALLOWED_TRANSITIONS DAG.
Raises PhaseTransitionError on illegal transitions.
"""

from __future__ import annotations

from typing import TypeVar, Mapping, AbstractSet


P = TypeVar("P")


class PhaseTransitionError(RuntimeError):
    """Raised when an illegal phase transition is attempted."""

    def __init__(self, current: object, target: object, allowed: AbstractSet):
        super().__init__(
            f"Illegal phase transition {current!r} -> {target!r}; "
            f"allowed={sorted(map(str, allowed))}"
        )
        self.current = current
        self.target = target
        self.allowed = allowed


def validate_transition(
    current: P, target: P, dag: Mapping[P, AbstractSet[P]]
) -> None:
    """Raise PhaseTransitionError if (current -> target) not in dag.

    Pre:
        - dag is mapping phase -> set of allowed-next-phases
    Post:
        - returns None on legal transition; raises on illegal
    """
    if current not in dag:
        raise PhaseTransitionError(current, target, set())
    allowed = dag[current]
    if target not in allowed:
        raise PhaseTransitionError(current, target, allowed)


# CRUX-MK
