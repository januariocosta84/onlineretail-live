"""Compile locale/*/LC_MESSAGES/django.po to .mo without needing gettext.

Usage:  python compile_translations.py     (requires: pip install polib)

Django's `manage.py compilemessages` needs the GNU gettext tools, which are
not installed on Windows by default; this script does the same job with polib.
Run it after editing any .po file, then restart the server.
"""

from pathlib import Path

import polib

BASE_DIR = Path(__file__).resolve().parent

for po_path in (BASE_DIR / "locale").glob("*/LC_MESSAGES/django.po"):
    po = polib.pofile(str(po_path))
    mo_path = po_path.with_suffix(".mo")
    po.save_as_mofile(str(mo_path))
    untranslated = len(po.untranslated_entries())
    print(f"{po_path.parent.parent.name}: {len(po)} entries -> {mo_path.name}"
          + (f" ({untranslated} untranslated)" if untranslated else ""))
