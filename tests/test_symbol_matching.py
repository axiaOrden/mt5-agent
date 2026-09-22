"""Unit tests for preferred-symbol resolution (conservative matching)."""

from src.models import SymbolInfo
from src.mt5.symbols import SymbolResolver


def _symbols(names: list[str]) -> list[SymbolInfo]:
    return [SymbolInfo(name=n) for n in names]


def test_exact_match():
    resolver = SymbolResolver(_symbols(["XAUUSDm", "EURUSDm", "BTCUSD"]))
    result = resolver.resolve(["BTCUSD"])[0]
    assert result.resolved
    assert result.broker == "BTCUSD"
    assert result.status == "exact"


def test_exact_match_case_insensitive():
    resolver = SymbolResolver(_symbols(["XAUUSDm", "EURUSDm"]))
    result = resolver.resolve(["xauusdm"])[0]
    assert result.resolved
    assert result.broker == "XAUUSDm"


def test_unique_suffix_match():
    resolver = SymbolResolver(_symbols(["XAUUSDm", "EURUSDm", "GBPUSDm"]))
    result = resolver.resolve(["XAUUSD"])[0]
    assert result.resolved
    assert result.broker == "XAUUSDm"
    assert result.status == "suffix"


def test_micro_suffix_match():
    resolver = SymbolResolver(_symbols(["XAUUSDmicro", "EURUSDm"]))
    result = resolver.resolve(["XAUUSD"])[0]
    assert result.resolved
    assert result.broker == "XAUUSDmicro"


def test_dotted_suffix_match():
    resolver = SymbolResolver(_symbols(["XAUUSD.a", "EURUSDm"]))
    result = resolver.resolve(["XAUUSD"])[0]
    assert result.resolved
    assert result.broker == "XAUUSD.a"


def test_ambiguous_requires_explicit_mapping():
    resolver = SymbolResolver(_symbols(["XAUUSDm", "XAUUSD.a", "EURUSDm"]))
    result = resolver.resolve(["XAUUSD"])[0]
    assert not result.resolved
    assert result.status == "ambiguous"
    assert set(result.candidates) == {"XAUUSDm", "XAUUSD.a"}


def test_missing_symbol_reported():
    resolver = SymbolResolver(_symbols(["EURUSDm"]))
    result = resolver.resolve(["XAUUSD"])[0]
    assert not result.resolved
    assert result.status == "missing"
    assert result.candidates == ()


def test_explicit_mapping_overrides():
    resolver = SymbolResolver(_symbols(["XAUUSD", "XAUUSDm", "XAUUSD.a"]))
    result = resolver.resolve(["XAUUSD"], {"XAUUSD": "XAUUSDm"})[0]
    assert result.resolved
    assert result.broker == "XAUUSDm"
    assert result.status == "mapped"


def test_mapping_to_missing_symbol_is_error():
    resolver = SymbolResolver(_symbols(["EURUSDm"]))
    result = resolver.resolve(["XAUUSD"], {"XAUUSD": "XAUUSDm"})[0]
    assert not result.resolved
    assert result.status == "mapping_missing"


def test_semantic_alias_requires_mapping():
    # GOLD is not derivable from XAUUSD by string matching — must be mapped.
    resolver = SymbolResolver(_symbols(["GOLD", "EURUSDm"]))
    result = resolver.resolve(["XAUUSD"])[0]
    assert not result.resolved
    assert result.status == "missing"
    mapped = resolver.resolve(["XAUUSD"], {"XAUUSD": "GOLD"})[0]
    assert mapped.resolved
    assert mapped.broker == "GOLD"


def test_multiple_preferred_resolved_independently():
    resolver = SymbolResolver(_symbols(["XAUUSDm", "XAGUSDm", "EURUSDm", "BTCUSD"]))
    results = resolver.resolve(["XAUUSD", "XAGUSD", "EURUSD", "BTCUSD"])
    assert [r.broker for r in results] == ["XAUUSDm", "XAGUSDm", "EURUSDm", "BTCUSD"]
    assert all(r.resolved for r in results)
