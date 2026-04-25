"""Common test fixtures.

Adds ``backend/`` to ``sys.path`` so tests can import like the production
app (``from services...``) without needing a package install.
"""

import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Use a temporary SQLite DB so we never touch the dev one.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
