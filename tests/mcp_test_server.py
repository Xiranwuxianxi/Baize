"""最小的 MCP 服务，只用于自检：按 MCP 协议（JSON-RPC 2.0）实现 initialize / tools/list / tools/call。

  python tests/mcp_test_server.py            # stdio 方式
  python tests/mcp_test_server.py --http 18780   # Streamable HTTP 方式（只回 JSON）

提供两个真实工具：word_count（统计文本字数）、list_dir（列出目录里的文件）。
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

TOOLS = [
    {"name": "word_count", "description": "统计一段文本的字符数和行数",
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
    {"name": "list_dir", "description": "列出某个目录下的文件名",
     "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
]


def handle(msg):
    method, rid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if rid is None:
        return None  # 通知，不回复
    if method == "initialize":
        result = {"protocolVersion": params.get("protocolVersion", "2025-03-26"), "capabilities": {"tools": {}},
                  "serverInfo": {"name": "mac-test", "version": "1"}}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        name, args = params.get("name"), params.get("arguments") or {}
        if name == "word_count":
            text = str(args.get("text", ""))
            result = {"content": [{"type": "text", "text": "字符数 %d，行数 %d" % (len(text), text.count("\n") + 1)}]}
        elif name == "list_dir":
            try:
                result = {"content": [{"type": "text", "text": "\n".join(sorted(os.listdir(args.get("path", "."))))}]}
            except OSError as e:
                result = {"content": [{"type": "text", "text": str(e)}], "isError": True}
        else:
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "unknown tool " + str(name)}}
    else:
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "unknown method"}}
    return {"jsonrpc": "2.0", "id": rid, "result": result}


class Http(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        out = handle(body)
        self.send_response(200 if out else 202)
        self.send_header("Content-Type", "application/json")
        self.send_header("Mcp-Session-Id", "test-session")
        self.end_headers()
        if out:
            self.wfile.write(json.dumps(out, ensure_ascii=False).encode("utf-8"))

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    if "--http" in sys.argv:
        HTTPServer(("127.0.0.1", int(sys.argv[sys.argv.index("--http") + 1])), Http).serve_forever()
    else:
        for line in sys.stdin.buffer:
            try:
                out = handle(json.loads(line))
            except ValueError:
                continue
            if out:
                sys.stdout.buffer.write((json.dumps(out, ensure_ascii=False) + "\n").encode("utf-8"))
                sys.stdout.buffer.flush()
