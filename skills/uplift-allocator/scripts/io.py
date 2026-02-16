"""Backward compatibility shim.

Use skill_io.py to avoid conflicts with Python's built-in io module.
"""

from skill_io import read_yaml, read_json, write_json, write_text

__all__ = ["read_yaml", "read_json", "write_json", "write_text"]
