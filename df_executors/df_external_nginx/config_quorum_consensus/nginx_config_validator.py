"""NGINX Config Validator -- Parser + Syntax-Validator fuer nginx.conf [CRUX-MK].

Externe Domain: NGINX Reverse-Proxy Config-Format (http/server/location Bloecke).
Pure Domain-Logic: KEINE Kemmer-Dependencies.

Pre-Conditions:
    - Config-Source ist String (UTF-8) oder Path
    - Max-Size 1 MiB (anti-DoS)
Post-Conditions:
    - parse() liefert NginxConfigBlock-Tree oder ConfigParseError
    - validate() liefert Liste ValidationFinding (empty = valid)
    - normalize() liefert kanonisierten String (whitespace-stripped, kommentar-frei)
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# Constants with units.
MAX_CONFIG_SIZE_BYTES: int = 1 * 1024 * 1024  # 1 MiB DoS-Limit
MAX_BLOCK_NESTING_DEPTH: int = 10              # nginx.conf praktisches Maximum
ALLOWED_BLOCK_NAMES: frozenset[str] = frozenset({
    "http", "server", "location", "upstream", "events",
    "stream", "mail", "if", "limit_except", "types", "map",
})
REQUIRED_TOP_LEVEL: frozenset[str] = frozenset({"events"})  # NGINX-Pflicht-Block


class FindingSeverity(str, Enum):
    """Validation-Severity (Borrowed from RFC-style severities)."""
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class ValidationFinding:
    """Einzelner Validation-Befund (immutable nach Erstellung)."""
    severity: FindingSeverity
    message: str
    line: int = 0
    block_name: str = ""

    def is_blocking(self) -> bool:
        """Errors blockieren Quorum-Approve. Warnings/Info nicht."""
        return self.severity == FindingSeverity.ERROR


class ConfigParseError(ValueError):
    """Raised wenn nginx.conf nicht parsebar (Syntax-Error)."""


@dataclass
class NginxConfigBlock:
    """AST-Node fuer nginx.conf Block (http/server/location/...).

    Beispiel:
        http {
            server {
                listen 80;
                location / { proxy_pass http://upstream; }
            }
        }
    """
    name: str
    args: list[str] = field(default_factory=list)
    directives: list[tuple[str, list[str]]] = field(default_factory=list)
    children: list["NginxConfigBlock"] = field(default_factory=list)
    line_start: int = 0
    line_end: int = 0


class NginxConfigValidator:
    """Parser + Syntax-Validator fuer nginx.conf-Format.

    Reentranter Validator (kein Mutable-State zwischen Calls).
    Thread-safe by design: stateless API.
    """

    _COMMENT_RE = re.compile(r"#[^\n]*")
    _WHITESPACE_RE = re.compile(r"\s+")

    def __init__(
        self,
        max_size_bytes: int = MAX_CONFIG_SIZE_BYTES,
        max_nesting: int = MAX_BLOCK_NESTING_DEPTH,
    ) -> None:
        if max_size_bytes <= 0:
            raise ValueError("max_size_bytes must be > 0")
        if max_nesting <= 0:
            raise ValueError("max_nesting must be > 0")
        self.max_size_bytes = max_size_bytes
        self.max_nesting = max_nesting

    # ---------------- Public API ----------------

    def parse(self, source: str) -> NginxConfigBlock:
        """Parse nginx.conf-String in AST. Raises ConfigParseError on syntax issues."""
        if not isinstance(source, str):
            raise ConfigParseError("source must be str")
        encoded = source.encode("utf-8")
        if len(encoded) > self.max_size_bytes:
            raise ConfigParseError(
                f"config too large: {len(encoded)} > {self.max_size_bytes}"
            )
        # Tokenize: strip comments, split on { } ;
        clean = self._strip_comments(source)
        tokens = self._tokenize(clean)
        # Build AST (synthetic root)
        root = NginxConfigBlock(name="__root__", line_start=1)
        idx = self._parse_block_body(tokens, 0, root, depth=0)
        if idx != len(tokens):
            raise ConfigParseError(f"unexpected token at position {idx}")
        return root

    def validate(self, source: str) -> list[ValidationFinding]:
        """Parse + Syntax-Check + Semantic-Pruefungen. Empty Liste = valid."""
        findings: list[ValidationFinding] = []
        try:
            ast = self.parse(source)
        except ConfigParseError as exc:
            findings.append(
                ValidationFinding(
                    severity=FindingSeverity.ERROR,
                    message=f"parse-error: {exc}",
                    line=0,
                )
            )
            return findings
        # Semantic-Checks
        findings.extend(self._check_required_blocks(ast))
        findings.extend(self._check_unknown_blocks(ast))
        findings.extend(self._check_listen_conflicts(ast))
        findings.extend(self._check_proxy_pass_targets(ast))
        return findings

    def normalize(self, source: str) -> str:
        """Liefert kanonisierte Form (kommentarfrei, whitespace-normalisiert).

        Verwendung: Config-Hash fuer Quorum-Vergleich.
        """
        clean = self._strip_comments(source)
        # Collapse whitespace, strip per-line, drop empty lines
        lines = [self._WHITESPACE_RE.sub(" ", ln).strip() for ln in clean.splitlines()]
        return "\n".join(ln for ln in lines if ln)

    def config_hash(self, source: str) -> str:
        """SHA256-Hash der normalisierten Config (Auto-Inducer-Molecule-Aequivalent)."""
        normalized = self.normalize(source)
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    # ---------------- Internals ----------------

    def _strip_comments(self, source: str) -> str:
        return self._COMMENT_RE.sub("", source)

    def _tokenize(self, source: str) -> list[tuple[str, int]]:
        """Liefert (token, line_no)-Tupel. Trennt auf { } ; Whitespace."""
        tokens: list[tuple[str, int]] = []
        buf: list[str] = []
        line = 1
        for ch in source:
            if ch == "\n":
                line += 1
            if ch in "{};":
                if buf:
                    tokens.append(("".join(buf).strip(), line))
                    buf = []
                tokens.append((ch, line))
            elif ch.isspace():
                if buf:
                    tokens.append(("".join(buf).strip(), line))
                    buf = []
            else:
                buf.append(ch)
        if buf and "".join(buf).strip():
            tokens.append(("".join(buf).strip(), line))
        return [(t, ln) for t, ln in tokens if t]

    def _parse_block_body(
        self,
        tokens: list[tuple[str, int]],
        start_idx: int,
        block: NginxConfigBlock,
        depth: int,
    ) -> int:
        """Parse direktiven + sub-bloecke bis '}' oder Ende. Returns naechster Index."""
        if depth > self.max_nesting:
            raise ConfigParseError(f"max nesting depth {self.max_nesting} exceeded")
        idx = start_idx
        current_args: list[str] = []
        while idx < len(tokens):
            tok, line = tokens[idx]
            if tok == "}":
                if current_args:
                    raise ConfigParseError(
                        f"unterminated directive at line {line}: {current_args}"
                    )
                block.line_end = line
                return idx + 1
            if tok == ";":
                if not current_args:
                    raise ConfigParseError(f"empty directive at line {line}")
                name = current_args[0]
                args = current_args[1:]
                block.directives.append((name, args))
                current_args = []
                idx += 1
                continue
            if tok == "{":
                if not current_args:
                    raise ConfigParseError(f"unnamed block at line {line}")
                child = NginxConfigBlock(
                    name=current_args[0],
                    args=current_args[1:],
                    line_start=line,
                )
                block.children.append(child)
                current_args = []
                idx = self._parse_block_body(tokens, idx + 1, child, depth + 1)
                continue
            current_args.append(tok)
            idx += 1
        if current_args:
            raise ConfigParseError(f"unterminated directive at end: {current_args}")
        if block.name != "__root__":
            raise ConfigParseError(f"unclosed block {block.name!r}")
        return idx

    def _check_required_blocks(self, ast: NginxConfigBlock) -> list[ValidationFinding]:
        findings = []
        present_names = {b.name for b in ast.children}
        for required in REQUIRED_TOP_LEVEL:
            if required not in present_names:
                findings.append(
                    ValidationFinding(
                        severity=FindingSeverity.ERROR,
                        message=f"missing required top-level block: {required}",
                    )
                )
        return findings

    def _check_unknown_blocks(self, ast: NginxConfigBlock) -> list[ValidationFinding]:
        findings: list[ValidationFinding] = []

        def walk(block: NginxConfigBlock) -> None:
            for child in block.children:
                if child.name not in ALLOWED_BLOCK_NAMES:
                    findings.append(
                        ValidationFinding(
                            severity=FindingSeverity.WARNING,
                            message=f"unknown block name: {child.name}",
                            line=child.line_start,
                            block_name=child.name,
                        )
                    )
                walk(child)

        walk(ast)
        return findings

    def _check_listen_conflicts(self, ast: NginxConfigBlock) -> list[ValidationFinding]:
        """Erkennt doppelte listen-Direktiven auf gleichem Port (Conflict-Marker)."""
        findings: list[ValidationFinding] = []
        listen_ports: dict[str, int] = {}

        def walk(block: NginxConfigBlock) -> None:
            for child in block.children:
                if child.name == "server":
                    for d_name, d_args in child.directives:
                        if d_name == "listen" and d_args:
                            port = d_args[0]
                            listen_ports[port] = listen_ports.get(port, 0) + 1
                walk(child)

        walk(ast)
        for port, count in listen_ports.items():
            if count > 1:
                findings.append(
                    ValidationFinding(
                        severity=FindingSeverity.WARNING,
                        message=f"multiple servers listen on port {port} (count={count})",
                        block_name="server",
                    )
                )
        return findings

    def _check_proxy_pass_targets(self, ast: NginxConfigBlock) -> list[ValidationFinding]:
        """Validiert proxy_pass-Targets (URL-Format)."""
        findings: list[ValidationFinding] = []
        url_re = re.compile(r"^https?://[\w.\-:/]+")

        def walk(block: NginxConfigBlock) -> None:
            for d_name, d_args in block.directives:
                if d_name == "proxy_pass" and d_args:
                    target = d_args[0]
                    if not url_re.match(target):
                        findings.append(
                            ValidationFinding(
                                severity=FindingSeverity.ERROR,
                                message=f"invalid proxy_pass target: {target!r}",
                                block_name=block.name,
                            )
                        )
            for child in block.children:
                walk(child)

        walk(ast)
        return findings


# CRUX-MK
