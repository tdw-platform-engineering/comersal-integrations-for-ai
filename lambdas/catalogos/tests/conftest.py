"""Test configuration — mock pymssql before any import touches it."""

import sys
from unittest.mock import MagicMock

# pymssql can't be installed on Windows (needs C libs) — mock it for unit tests
sys.modules["pymssql"] = MagicMock()
