"""Tests must not see the developer's real data directory (settings, skin, database).

PET_DATA_DIR is pointed at an empty temporary directory before curiosity_pet.config is imported,
so the persona, settings and store defaults are the built-in ones.
"""

import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="pet-test-data-")
os.environ["PET_DATA_DIR"] = _tmp
os.environ.setdefault("PET_WIKI_CONTACT", "")
os.environ.setdefault("PET_ONLINE_LOOKUP", "0")
