from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
import html
import threading
import webbrowser
from custom_qa_store import list_custom_qa, save_custom_qa, delete_custom_qa

HTML_TEMPLATE = '''<!doctype html><html><head><meta charset="utf-8"><title>Career Agent - Custom Q&A</title>
<style>body{font-family:Segoe UI,Arial;margin:40px;background:#f5f6f8;color:#222}main{max-width:1000px;margin:auto;background:#fff;padding:28px;border-radius:14px;box-shadow:0 4px 18px #0001}textarea{width:100%;padding:10px;margin:6px 0 14px;border:1px solid #ccd1d8;border-radius:8px;box-sizing:border-box}button{padding:10px 16px;border:0;border-radius:8px;cursor:pointer;background:#1667d9;color:white}.row{border:1px solid #e2e5e9;border-radius:10px;padding:16px;margin:12px 0}.muted{color:#6b7280}</style></head><body><main>
<h1>Custom Q&amp;A</h1><p class="muted">Save an application question once. The agent will reuse the verified answer on future forms.</p>
<form method="post" action="/save"><label>Question</label><textarea name="question" rows="3" required></textarea><label>Answer</label><textarea name="answer" rows="3" required></textarea><button type="submit">Save answer</button></form>
<h2>Saved questions</h2>{rows}</main></body></html>'''


def render():
    rows = []
    for row in list_custom_qa():
        rows.append(
            '<div class="row"><b>Q:</b> ' + html.escape(row['question']) +
            '<br><b>A:</b> ' + html.escape(row['answer']) +
            '<br><span class="muted">Updated: ' + html.escape(str(row['updated_at'])) +
            '</span><form method="post" action="/delete"><input type="hidden" name="id" value="' + str(row['id']) +
            '"><button type="submit" style="background:#b91c1c;margin-top:10px">Delete</button></form></div>'
        )
    return HTML_TEMPLATE.replace('{rows}', ''.join(rows) or '<p class="muted">No saved answers yet.</p>')


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(render().encode('utf-8'))

    def do_POST(self):
        length = int(self.headers.get('Content-Length', '0'))
        data = parse_qs(self.rfile.read(length).decode('utf-8'))
        path = urlparse(self.path).path
        if path == '/save':
            save_custom_qa(data.get('question', [''])[0], data.get('answer', [''])[0])
        elif path == '/delete':
            delete_custom_qa(data.get('id', [''])[0])
        self.send_response(303)
        self.send_header('Location', '/')
        self.end_headers()

    def log_message(self, *_args):
        return


if __name__ == '__main__':
    host, port = '127.0.0.1', 8765
    server = ThreadingHTTPServer((host, port), Handler)
    url = f'http://{host}:{port}/'
    threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    print(f'Custom Q&A GUI: {url}')
    server.serve_forever()
