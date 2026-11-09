"""Copy Control Panel presses into live/controls.jsonl (append-only).

Usage: python scripts/sync_controls.py <dir>
<dir> is the out_dir of an ArtifactData `list` of collection `events` on the Control Panel
(https://claude.ai/artifact/SG2VmB7APqkgiKyShrSHTD); it holds <dir>/events/<id>.json files."""
import json
import sys
from pathlib import Path

from atlantis.controls import Controls, sync_from_panel

src = Path(sys.argv[1]) / "events"
docs = []
for p in sorted(src.glob("*.json")) if src.exists() else []:
    d = json.loads(p.read_text())
    docs.append({"id": d.get("id", p.stem), "data": d.get("data", d)})
path = Path("live/controls.jsonl")
new = sync_from_panel(docs, path)
print(f"{len(docs)} panel events read, {len(new)} new appended")
print("current:", Controls.load(path).current())
