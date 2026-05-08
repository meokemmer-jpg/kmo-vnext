"""Graphity-Verlag Distributed-Lock Module [CRUX-MK]

Synaptic-Pattern Distributed-Lock fuer Buchprojekt-Section-Edits.

Bio-Pattern-Korrespondenz: Synaptic-Vesikel-Release-Lock
- Pre-Synaptic-Release  -> Lock-Acquire
- Post-Synaptic-Receptor -> Lock-Wait
- Refractory-Period     -> Lock-Cooldown
- Reuptake              -> Lock-Release

Welle-30 W-30-3 (Wild-Code-Blindtest #3): Generalisation-Beweis dass
Bio-Pattern-Lifts auf 3. Domain (Graphity-Verlag) ausserhalb Hotel/Trading
funktionieren.
"""

# Module-level imports deferred to avoid sys.path issues during pytest
# collection. Consumers should import directly:
#   from graphity_lock_manager import GraphityLockManager
# (after adding the module dir to sys.path, like saga-pattern does).
