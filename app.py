# built-in modules 
import asyncio  # allows me to scan multiple ports  at the same time
import socket   # used under the hood by asyncio to open TCP connections
from datetime import datetime #to timestamp when the scan starts/finishes

# Flask web framework 
from flask import Flask, render_template, request, jsonify

app = Flask(__name__) # this creates the Flask app object, I'll attach the routs like /scan and /

# ---------- ROUTES ----------

@app.route("/")  
def index():
    return render_template("index.html")  # 👈 Looks for templates/index.html

@app.route("/scan", methods=["POST"])  
def scan(): 
    data = request.get_json(silent=True) or {}
    host = (data.get("host") or "").strip()
    port_str = data.get("ports", "")
    # runs the async scan, summarizes it, and returns the JSON with results
    if not host: 
        return jsonify({"error": "Host is required"}), 400
      
    ports = parse_ports(port_str)
    started = datetime.utcnow().isoformat() + "Z"
    
    # asyncio.run() creates and runs an event loop once. 
    # In some dev servers an event loop may already exist, so we fall back
    try: 
        results = asyncio.run(run_scan(host, ports))
    except RuntimeError: 
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        results = loop.run_until_complete(run_scan(host, ports))
        loop.close()
        
    # builds a tiny summary for charts 
    open_count = sum(1 for r in results if r["status"] == "open")
    closed_count = len(results) - open_count

    return jsonify({
      "host": host, 
      "started": started, 
      "finished": datetime.utcnow().isoformat() + "Z",
      "summary": {
          "total": len(results), 
          "open": open_count,
          "closed": closed_count
        }, 
        "results": results 
    }) 

# ---------- HELPERS ----------

# Default ports and a helper to parse user input
DEFAULT_PORTS = [
    21,22,23,25,53,80,110,123,135,139,143,161,389,443,445,465,
    587,993,995,1433,1521,1723,2049,3306,3389,5432,5900,6379,8080
]

def parse_ports(port_str: str):
  """
  turns text like "22,80,443" or "20-25,80" into a clean list of integers.
  if empty, return DEFAULT_PORTS.
  We also clamp values to 1..65535 and remove duplicates. 
  """
  ports = set()
  if not port_str:
    return DEFAULT_PORTS
  
  for part in port_str.split(","):
      part = part.strip()
      if not part: 
          continue
      if "-" in part:
          start, end = part.split("-",1)
          try: 
              start, end = int(start), int(end)
              # range is inclusive
              for p in range(min(start, end), max(start, end) + 1):
                  if 1 <= p <= 65535:
                      ports.add(p)
          except ValueError: 
              # if the user typed something weird, just skip it
              continue
      else: 
          try: 
              p = int(part)
              if 1 <= p <= 65535:
                  ports.add(p)
          except ValueError:
              continue
          
  return sorted(ports)

# The actual port checker (async)
async def scan_port(host: str, port: int, timeout: float = 1.0):
  """
  Try to open a TCP connection to (host,port). 
  If we connect within 'timeout' seconds, we call it 'open'.
  Otherwise, it's closed (or filtered by a firewall)
  """
  try: 
        # Attempt the connection
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), 
            timeout=timeout
        )
        
        # if it worked, immediately close nicely
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return {"port": port, "status": "open"}
  except Exception: 
      # any exception (timeout, refused, network error) counts as closed for our purposes
      return {"port": port, "status": "closed"}
    
# why? A TCP port is "open" if a program is listening and accepts a connection. 
# if the attempt times out or is refused, we mark it "closed"
# async def lets us run a lot of these in parallel.

# Run many scans together
async def run_scan(host: str, ports: list[int]):
  """
  Launch one async task per port and wait for all to finish. 
  This is the 'parallel' part that makes it fast.
  """
  tasks = [scan_port(host, p) for p in ports]
  return await asyncio.gather(*tasks) 

# This creates a list of coroutines (one per port) and gather waits for all results. 
# This is MUCH faster than checking one port at a time. 

# ---------- ENTRY POINT ----------

if __name__ == "__main__": 
    # debug=True auto-reloads on code changes and shows helpful error pages during development
    app.run(host="0.0.0.0", port=5000, debug=True)

    