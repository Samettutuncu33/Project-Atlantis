"""Build the phone dashboard for GitHub Pages: site/index.html + site/live.json.

The page is the Atlantis Live design (dashboard/control_panel.html), read-only: a small shim stands in
for the claude.ai runtime and feeds it live/out/live.json from the same folder. Buttons stay disabled
(controls are not available on this page). SIMULATION ONLY.
"""
import shutil
from pathlib import Path

SHIM = """<script>
/* GitHub Pages shim: read-only. Re-reads ./live.json every minute; the page replays a run when a new one arrives. */
window.claude = { use: async (n) => n !== 'db' ? null : {
  doc: (p) => ({ onSnapshot: (cb) => {
    if (p !== 'status/latest') return;
    const go = () => cb({ exists: true, data: () => ({ live_json: 'live.json?t=' + Date.now() }) });
    go(); setInterval(go, 60 * 1000);
  } }),
  collection: () => { const q = { orderBy: () => q, limit: () => q, onSnapshot: (cb) => cb({ empty: true, docs: [] }) }; return q; },
} };
</script>
"""
NOTE = ('<p class="muted"><b>Phone view (read-only).</b> Updated by GitHub Actions every hour on weekdays; '
        'this page checks for a new run every minute. Controls are not available here.</p>')

src = Path("dashboard/control_panel.html").read_text()
assert "<script>" in src and '<p class="muted" id="runline">' in src
html = ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n' + src)
html = html.replace("<script>", SHIM + "<script>", 1)
html = html.replace("<style>", "<style>\n#ctlbox { display: none; }\n", 1)
html = html.replace('<section class="box">\n      <h2>Controls</h2>', '<section class="box" id="ctlbox">\n      <h2>Controls</h2>', 1)
html = html.replace('<p class="muted" id="runline">', NOTE + '\n    <p class="muted" id="runline">', 1)
out = Path("site")
out.mkdir(exist_ok=True)
(out / "index.html").write_text(html)
shutil.copy("live/out/live.json", out / "live.json")
print("built site/index.html + site/live.json")
