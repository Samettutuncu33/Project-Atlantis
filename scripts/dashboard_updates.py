"""Write the JSON payloads a scheduled run sends to the dashboard after uploading
live/out/live.json. Usage: python scripts/dashboard_updates.py /_blob/<id> <outdir>
Prints the dataset ids; each <outdir>/<id>.json is an `update` for datasets/<id>."""
import json, sys, datetime
from pathlib import Path
blob, out = sys.argv[1], Path(sys.argv[2])
assert blob.startswith("/_blob/") and len(blob) == 39, "expected /_blob/<32 hex>"
out.mkdir(parents=True, exist_ok=True)
now = datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
for k in ["run", "accounts", "equity", "plan", "positions", "fills", "projection", "prices", "checks",
          "predictions", "knowhow", "lessons", "calibration"]:
    (out / f"{k}.json").write_text(json.dumps({
        "source": {"url": blob}, "updated": {"at": now, "by": "Atlantis scheduled run"},
        "edit": {"via": "claude", "at": now}}))
    print(k)
