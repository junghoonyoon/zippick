"""Unit tests keep production shared facts separate from test fixtures."""
import os

os.environ.setdefault("ZIPPICK_DATA_MODE", "isolated")
