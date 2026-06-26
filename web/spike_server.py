"""Spike 本地服务器：serve web/static + 把 /rpc 代理到 Casper testnet 节点。

浏览器不允许从网页直接 POST 到公共节点（CORS 拦截），所以前端把 RPC 打到本机
同源的 /rpc，由本服务器转发到 node.testnet.casper.network —— 这也是生产架构里
那台小后端要干的活之一（RPC 代理 / faucet / x402）。

纯标准库，零依赖。运行：python3 web/spike_server.py  → http://localhost:8088/spike-wallet.html
"""
import http.server
import os
import socketserver
import urllib.request

NODE = "https://node.testnet.casper.network/rpc"
DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
PORT = int(os.environ.get("PORT", 8088))


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=DIR, **k)

    def end_headers(self):
        # 开发服务器禁用缓存，避免浏览器缓存旧静态文件
        self.send_header("Cache-Control", "no-store, must-revalidate")
        super().end_headers()

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if self.path.rstrip("/") == "/api/vouch-state":
            state_file = os.path.join(os.path.dirname(DIR), "vouch_state.json")
            try:
                data = open(state_file, "rb").read()
            except FileNotFoundError:
                data = b'{"agents":[],"hires":[],"events":[],"treasury":{}}'
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(data)
            return
        return super().do_GET()

    def do_POST(self):
        if self.path.rstrip("/") not in ("/rpc", "/api/rpc"):
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            req = urllib.request.Request(
                NODE, data=body,
                headers={"Content-Type": "application/json"}, method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:  # noqa: BLE001 — 代理层把任何错误回给前端日志
            self.send_response(502)
            self._cors()
            self.end_headers()
            self.wfile.write(str(e).encode())


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True


with Server(("", PORT), Handler) as httpd:
    print(f"spike server on http://localhost:{PORT}  (/rpc -> {NODE})")
    httpd.serve_forever()
