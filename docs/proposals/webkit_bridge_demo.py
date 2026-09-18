"""Proof: GTK4 + WebKit6 with JS enabled, agent-style HTML card, choice posted
back into Python. Runs headless under Xvfb; touches nothing in any repo.

Simulates exactly the case you described: the agent renders a card with buttons,
the user clicks one, and the app receives the choice as structured data.
"""
import sys
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('WebKit', '6.0')
from gi.repository import Gtk, WebKit, GLib, Gio  # noqa: E402

received = []

CARD = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
 body{background:#111;color:#ddd;font:14px ui-monospace,monospace;margin:0;padding:16px}
 .card{background:#1a1a1a;border:1px solid #333;border-radius:14px;padding:16px}
 h3{margin:0 0 10px;color:#7cffb2;font-size:15px}
 button{background:#7cffb2;color:#0a0e0a;border:0;border-radius:10px;padding:10px 16px;
        font:inherit;font-weight:600;margin:6px 8px 0 0;cursor:pointer}
 table{border-collapse:collapse;margin-top:12px;font-size:12px}
 td,th{border:1px solid #333;padding:4px 8px}
 canvas{border:1px solid #333;border-radius:8px;margin-top:12px}
</style></head><body>
<div class="card">
  <h3>Two ways to do it — pick one</h3>
  <div>Option A: memoize in the handler (simpler, +1 cache dict).</div>
  <div>Option B: move it to the worker thread (cleaner, touches 3 files).</div>
  <button onclick="pick('A')">Option A</button>
  <button onclick="pick('B')">Option B</button>
  <table><tr><th>option</th><th>files</th><th>risk</th></tr>
  <tr><td>A</td><td>1</td><td>low</td></tr><tr><td>B</td><td>3</td><td>medium</td></tr></table>
  <canvas id="c" width="220" height="60"></canvas>
</div>
<script>
 function pick(v){
   document.querySelectorAll('button').forEach(b=>b.disabled=true);
   window.webkit.messageHandlers.crabcakes.postMessage({type:'choice',card_id:'card-1',value:v});
 }
 (function(){ var x=document.getElementById('c').getContext('2d');
   x.strokeStyle='#7cffb2'; x.beginPath();
   for(var i=0;i<=40;i++){var y=30-Math.sin(i/6)*20; i?x.lineTo(i*5,y):x.moveTo(0,y);} x.stroke(); })();
</script></body></html>"""


def on_message(ucm, result):
    try:
        try:
            payload = result.to_json(0)
        except AttributeError:
            payload = result.get_js_value().to_json(0)
    except Exception as e:
        payload = f"<unreadable: {e}>"
    received.append(payload)
    print("PYTHON RECEIVED:", payload, flush=True)
    GLib.timeout_add(200, app_quit)
    return True


def on_load(webview, event):
    if event == WebKit.LoadEvent.FINISHED:
        print("page loaded, simulating a click on Option B...", flush=True)
        webview.evaluate_javascript("pick('B')", -1, None, None, None, None, None)


def app_quit():
    print("done.", flush=True)
    loop.quit()
    return False


loop = GLib.MainLoop()

ucm = WebKit.UserContentManager()
ucm.register_script_message_handler("crabcakes", None)
ucm.connect("script-message-received::crabcakes", on_message)

win = Gtk.Window()
win.set_default_size(420, 380)
view = WebKit.WebView(user_content_manager=ucm)
view.set_property("settings", WebKit.Settings())
s = view.get_settings()
print("javascript enabled:", s.get_property("enable-javascript"), flush=True)
win.set_child(view)
win.present()
view.connect("load-changed", on_load)
view.load_html(CARD, "about:blank")

GLib.timeout_add_seconds(15, lambda: (print("TIMEOUT", flush=True), loop.quit(), False)[2])
loop.run()
print("RESULT:", received or "no message received", flush=True)
sys.exit(0 if received else 1)
