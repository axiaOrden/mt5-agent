"""Symbol discovery and preferred-symbol resolution.

The connected account is the source of truth for what instruments exist.
Preferred logical symbols are resolved against that list conservatively:
exact match first, then a unique prefix+suffix match, otherwise the
resolution is reported as ambiguous or missing — never guessed.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Optional

from ..models import SymbolInfo
from .errors import ProviderError

logger = logging.getLogger(__name__)

# Suffix conventions commonly appended to base instrument names by brokers
# (e.g. XAUUSDm, XAUUSDmicro, XAUUSD.a, XAUUSD.pro). A preferred name may
# resolve to an available symbol whose remainder is one of these.
_KNOWN_SUFFIXES = {
    "M", "MICRO", "MINI", "NANO", "PRO", "I", "C", "D", "E", "F", "G", "H",
    "J", "K", "L", "N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X",
    "Y", "Z", "A", "B",
}
_SUFFIX_RE = re.compile(r"^\.?[A-Z0-9]+$")


def fetch_symbols(mt5: Any) -> list[SymbolInfo]:
    """Retrieve the complete symbol set available to the connected account."""
    names = mt5.symbols_get()
    if names is None:
        raise ProviderError(f"MT5 symbols_get failed: {mt5.last_error()}")
    result = []
    for s in names:
        info = mt5.symbol_info(s.name)
        if info is None:
            logger.warning("symbol_info failed for %s: %s", s.name, mt5.last_error())
            continue
        result.append(
            SymbolInfo(
                name=info.name,
                description=getattr(info, "description", "") or "",
                path=getattr(info, "path", "") or "",
                currency_base=getattr(info, "currency_base", "") or "",
                currency_profit=getattr(info, "currency_profit", "") or "",
                digits=info.digits,
                point=info.point,
                contract_size=info.trade_contract_size,
                volume_min=info.volume_min,
                volume_max=info.volume_max,
                volume_step=info.volume_step,
                trade_mode=info.trade_mode,
                visible=bool(info.visible),
                spread=float(info.spread) if info.spread else None,
            )
        )
    return result


@dataclass(frozen=True)
class ResolutionResult:
    """Outcome of resolving one preferred logical symbol."""

    logical: str
    broker: Optional[str]  # None when unresolved
    status: str  # mapped | exact | suffix | ambiguous | missing | mapping_missing
    candidates: tuple[str, ...] = ()

    @property
    def resolved(self) -> bool:
        return self.broker is not None


class SymbolResolver:
    """Resolve preferred logical symbols against available broker symbols."""

    def __init__(self, available: list[SymbolInfo]) -> None:
        self._available = {s.name: s for s in available}
        self._by_upper = {name.upper(): name for name in self._available}
        self._upper_names = sorted(self._by_upper.keys())

    def resolve(self, preferred: list[str], mappings: Optional[dict[str, str]] = None) -> list[ResolutionResult]:
        mappings = mappings or {}
        results = []
        for logical in preferred:
            results.append(self._resolve_one(logical, mappings.get(logical)))
        return results

    def _resolve_one(self, logical: str, explicit: Optional[str]) -> ResolutionResult:
        logical = logical.strip()
        if explicit:
            if explicit in self._available:
                return ResolutionResult(logical, explicit, "mapped", (explicit,))
            return ResolutionResult(logical, None, "mapping_missing", (explicit,))

        upper = logical.upper()
        if upper in self._by_upper:
            broker = self._by_upper[upper]
            return ResolutionResult(logical, broker, "exact", (broker,))

        candidates = self._suffix_candidates(upper)
        if len(candidates) == 1:
            return ResolutionResult(logical, candidates[0], "suffix", tuple(candidates))
        if len(candidates) > 1:
            return ResolutionResult(logical, None, "ambiguous", tuple(candidates))
        return ResolutionResult(logical, None, "missing", ())

    def _suffix_candidates(self, upper: str) -> list[str]:
        """Available symbols that start with ``upper`` plus a known suffix."""
        candidates = []
        for name_upper in self._upper_names:
            if name_upper == upper or not name_upper.startswith(upper):
                continue
            remainder = name_upper[len(upper):]
            if not _SUFFIX_RE.match(remainder):
                continue
            bare = remainder.lstrip(".")
            if bare in _KNOWN_SUFFIXES or bare.isdigit():
                candidates.append(self._by_upper[name_upper])
        return candidates
