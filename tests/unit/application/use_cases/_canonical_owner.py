"""Shared assertion for Ledger-mapped Application owner tests."""

from importlib import import_module


def assert_owner(module_name: str, symbols: tuple[str, ...], handler: str) -> None:
    module = import_module(module_name)
    assert all(hasattr(module, symbol) for symbol in symbols)
    assert getattr(module, handler).__module__ == module.__name__
