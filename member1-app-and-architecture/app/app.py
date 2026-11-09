"""CoWIN scaled-down component: Vaccine Center Lookup microservice.

Pure Python standard library (no pip install needed).
Each instance reports which Availability Zone it runs in (env ZONE),
so the load balancer's traffic distribution and failover are visible.

Endpoints:
  GET /                            -> web page (search + live failover monitor)
  GET /health                      -> 200 {"status": "healthy", "zone": ...}
  GET /centers                     -> all centers
  GET /centers?state=Gujarat       -> filter by state
  GET /centers?pincode=380001      -> filter by pincode
"""
import json
import os
import socket
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

ZONE = os.environ.get("ZONE", "local-zone")
PORT = int(os.environ.get("PORT", "8080"))
STARTED = time.time()

# Static data (stands in for the CoWIN centre database)
CENTERS = [
    {"id": 1, "name": "Civil Hospital Ahmedabad", "state": "Gujarat", "district": "Ahmedabad", "pincode": "380016", "vaccine": "Covishield", "slots": 120},
    {"id": 2, "name": "SSG Hospital Vadodara", "state": "Gujarat", "district": "Vadodara", "pincode": "390001", "vaccine": "Covaxin", "slots": 80},
    {"id": 3, "name": "KEM Hospital Mumbai", "state": "Maharashtra", "district": "Mumbai", "pincode": "400012", "vaccine": "Covishield", "slots": 200},
    {"id": 4, "name": "AIIMS Delhi", "state": "Delhi", "district": "New Delhi", "pincode": "110029", "vaccine": "Covaxin", "slots": 300},
    {"id": 5, "name": "Nizam's Institute Hyderabad", "state": "Telangana", "district": "Hyderabad", "pincode": "500082", "vaccine": "Covishield", "slots": 150},
    {"id": 6, "name": "Victoria Hospital Bengaluru", "state": "Karnataka", "district": "Bengaluru Urban", "pincode": "560002", "vaccine": "Sputnik V", "slots": 90},
]


INDEX_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CoWIN - Vaccine Center Lookup</title>
<style>
  :root{--bg:#f4f7fb;--card:#fff;--ink:#14213d;--mut:#5b6b85;--line:#dde4ef;--acc:#1b6ef3;--ok:#12a150;--bad:#d92d20}
  *{box-sizing:border-box}
  body{margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--ink)}
  header{background:var(--ink);color:#fff;padding:18px 20px}
  header h1{margin:0;font-size:1.25rem}
  header p{margin:4px 0 0;color:#b8c4dc;font-size:.9rem}
  main{max-width:980px;margin:0 auto;padding:16px;display:grid;gap:16px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px}
  h2{margin:0 0 12px;font-size:1rem}
  .row{display:flex;gap:8px;flex-wrap:wrap}
  input,select,button{font:inherit;padding:9px 12px;border:1px solid var(--line);border-radius:8px;background:#fff;color:var(--ink)}
  input{flex:1;min-width:150px}
  button{background:var(--acc);color:#fff;border-color:var(--acc);cursor:pointer}
  button.alt{background:#fff;color:var(--ink);border-color:var(--line)}
  table{width:100%;border-collapse:collapse;font-size:.92rem}
  th,td{text-align:left;padding:9px 8px;border-bottom:1px solid var(--line)}
  th{color:var(--mut);font-weight:600;font-size:.8rem;text-transform:uppercase;letter-spacing:.04em}
  .wrap{overflow-x:auto}
  .badge{display:inline-block;padding:4px 10px;border-radius:999px;font-size:.8rem;font-weight:600;background:#e8f0fe;color:var(--acc)}
  .zoneA{background:#e6f6ec;color:var(--ok)} .zoneB{background:#fff4e0;color:#b25e00}
  .down{background:#fde8e6;color:var(--bad)}
  .stat{display:flex;gap:16px;flex-wrap:wrap;align-items:center}
  .stat b{font-size:1.4rem}
  .muted{color:var(--mut);font-size:.85rem}
  #log{font-family:ui-monospace,Consolas,monospace;font-size:.8rem;background:#0f1b33;color:#cfe0ff;border-radius:8px;padding:10px;height:150px;overflow:auto;white-space:pre-wrap}
</style></head><body>
<header><h1>CoWIN &middot; Vaccine Center Lookup</h1>
<p>Scaled-down multi-Availability-Zone proof of concept</p></header>
<main>
  <section class="card">
    <h2>Find a vaccination center</h2>
    <div class="row">
      <select id="state"><option value="">All states</option></select>
      <input id="pin" placeholder="Pincode (e.g. 380016)" inputmode="numeric" maxlength="6">
      <button id="go">Search</button>
      <button class="alt" id="reset">Reset</button>
    </div>
    <p class="muted" id="meta"></p>
    <div class="wrap"><table><thead><tr>
      <th>Center</th><th>District</th><th>State</th><th>Pincode</th><th>Vaccine</th><th>Slots</th>
    </tr></thead><tbody id="rows"></tbody></table></div>
  </section>

  <section class="card">
    <h2>Live failover monitor</h2>
    <p class="muted">Pings the load balancer every second and shows which zone answered.
      Stop one zone and watch traffic move to the other.</p>
    <div class="stat">
      <div>Served by <span class="badge" id="zone">-</span></div>
      <div>Requests <b id="total">0</b></div>
      <div>Failed <b id="failed">0</b></div>
      <div>Status <span class="badge" id="status">idle</span></div>
      <button id="toggle">Start</button>
    </div>
    <p></p>
    <div id="log"></div>
  </section>
</main>
<script>
var STATES = ["Delhi","Gujarat","Karnataka","Maharashtra","Telangana"];
var $ = function(id){return document.getElementById(id)};
STATES.forEach(function(s){var o=document.createElement("option");o.value=s;o.textContent=s;$("state").appendChild(o)});

function zoneClass(z){return z.indexOf("1a")>-1?"zoneA":(z.indexOf("1b")>-1?"zoneB":"")}
function setZone(z){var e=$("zone");e.textContent=z;e.className="badge "+zoneClass(z)}

function search(){
  var q=[];
  if($("state").value) q.push("state="+encodeURIComponent($("state").value));
  if($("pin").value.trim()) q.push("pincode="+encodeURIComponent($("pin").value.trim()));
  fetch("/centers"+(q.length?"?"+q.join("&"):"")).then(function(r){return r.json()}).then(function(d){
    $("meta").textContent=d.count+" center(s) found - answered by "+d.zone+" ("+d.host+")";
    setZone(d.zone);
    var tb=$("rows");tb.innerHTML="";
    d.centers.forEach(function(c){
      var tr=document.createElement("tr");
      [c.name,c.district,c.state,c.pincode,c.vaccine,c.slots].forEach(function(v){
        var td=document.createElement("td");td.textContent=v;tr.appendChild(td)});
      tb.appendChild(tr)});
    if(!d.centers.length){tb.innerHTML='<tr><td colspan="6" class="muted">No centers match.</td></tr>'}
  }).catch(function(){$("meta").textContent="Request failed - service unreachable."});
}
$("go").onclick=search;
$("reset").onclick=function(){$("state").value="";$("pin").value="";search()};
$("pin").addEventListener("keydown",function(e){if(e.key==="Enter")search()});
search();

var timer=null,total=0,failed=0,t0=0;
function logLine(t){var l=$("log");l.textContent+=t+"\\n";l.scrollTop=l.scrollHeight}
function ping(){
  total++;$("total").textContent=total;
  var s=Date.now();
  fetch("/health",{cache:"no-store"}).then(function(r){
    var z=r.headers.get("X-Served-By-Zone")||"?";
    if(!r.ok)throw new Error("HTTP "+r.status);
    setZone(z);$("status").textContent="healthy";$("status").className="badge zoneA";
    logLine(((Date.now()-t0)/1000).toFixed(1)+"s  200  "+z+"  "+(Date.now()-s)+" ms");
  }).catch(function(e){
    failed++;$("failed").textContent=failed;
    $("status").textContent="failing";$("status").className="badge down";
    logLine(((Date.now()-t0)/1000).toFixed(1)+"s  ERROR  "+e.message);
  });
}
$("toggle").onclick=function(){
  if(timer){clearInterval(timer);timer=null;$("toggle").textContent="Start";$("status").textContent="idle";$("status").className="badge"}
  else{t0=Date.now();ping();timer=setInterval(ping,1000);$("toggle").textContent="Stop"}
};
</script></body></html>
"""


class Handler(BaseHTTPRequestHandler):
    def _html(self, html):
        body = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Served-By-Zone", ZONE)
        self.end_headers()
        self.wfile.write(body)

    def _send(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Served-By-Zone", ZONE)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        qs = parse_qs(url.query)
        if url.path == "/health":
            return self._send(200, {"status": "healthy", "zone": ZONE,
                                    "host": socket.gethostname(),
                                    "uptime_s": round(time.time() - STARTED, 1)})
        if url.path == "/":
            return self._html(INDEX_HTML)
        if url.path == "/centers":
            result = CENTERS
            if "state" in qs:
                result = [c for c in result if c["state"].lower() == qs["state"][0].lower()]
            if "pincode" in qs:
                result = [c for c in result if c["pincode"] == qs["pincode"][0]]
            return self._send(200, {"zone": ZONE, "host": socket.gethostname(),
                                    "count": len(result), "centers": result})
        self._send(404, {"error": "not found"})

    def log_message(self, fmt, *args):
        print(f"[{ZONE}] {self.address_string()} {fmt % args}", flush=True)


if __name__ == "__main__":
    print(f"CoWIN center-lookup starting in zone={ZONE} on port {PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
