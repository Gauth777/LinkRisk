"""One-time source patch used to integrate the Merchant Protection panel cleanly.

The repository connector updates whole files, so this tiny deterministic patch is
executed by a short-lived GitHub Actions workflow and then can be removed.
"""
from pathlib import Path

path = Path("frontend/src/App.tsx")
text = path.read_text(encoding="utf-8")

import_needle = "import { api } from './api'\n"
import_line = "import { ProtectionPanel } from './ProtectionPanel'\n"
if import_line not in text:
    if import_needle not in text:
        raise SystemExit("App import anchor not found")
    text = text.replace(import_needle, import_needle + import_line, 1)

panel_line = "    <ProtectionPanel record={record} preview={preview} />\n\n"
panel_anchor = "    <section className=\"investigation-grid\">\n"
if panel_line not in text:
    if panel_anchor not in text:
        raise SystemExit("Investigation grid anchor not found")
    text = text.replace(panel_anchor, panel_line + panel_anchor, 1)

path.write_text(text, encoding="utf-8")
print("ProtectionPanel integrated into App.tsx")
