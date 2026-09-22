"""Symbol domain model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class SymbolInfo:
    """Metadata for a single instrument available on the connected account."""

    name: str
    description: str = ""
    path: str = ""
    currency_base: str = ""
    currency_profit: str = ""
    digits: int = 0
    point: float = 0.0
    contract_size: float = 0.0
    volume_min: float = 0.0
    volume_max: float = 0.0
    volume_step: float = 0.0
    trade_mode: int = 0
    visible: bool = True
    spread: Optional[float] = None

    @property
    def category(self) -> str:
        """Best-effort category derived from the symbol path/name."""
        if self.path:
            parts = [p for p in self.path.split("\\") if p]
            if parts:
                return parts[0].upper()
        name = self.name.upper()
        if any(name.startswith(p) for p in ("XAU", "XAG", "GOLD", "SILVER", "PALLADIUM", "PLATINUM")):
            return "METALS"
        if any(name.startswith(p) for p in ("BTC", "ETH", "LTC", "XRP", "DOGE", "SOL", "ADA", "DOT", "BNB", "USDT", "USDC")):
            return "CRYPTO"
        if any(name.startswith(p) for p in ("US30", "NAS100", "SPX", "GER40", "UK100", "JPN225", "US500", "DAX", "FTSE")):
            return "INDICES"
        if any(name.startswith(p) for p in ("WTI", "BRENT", "OIL", "NGAS", "GAS")):
            return "ENERGY"
        return "FOREX"
