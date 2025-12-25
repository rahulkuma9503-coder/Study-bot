from http.server import BaseHTTPRequestHandler
from http.server import HTTPServer
import threading

def run_health_check():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Bot is running')
    
    server = HTTPServer(('0.0.0.0', 8080), Handler)
    server.serve_forever()

# Run in a separate thread
threading.Thread(target=run_health_check, daemon=True).start()
