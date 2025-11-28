from http.server import BaseHTTPRequestHandler, HTTPServer

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def run():
    server = HTTPServer(("0.0.0.0", 8080), HealthHandler)
    print("Health server running on port 8080...")
    server.serve_forever()

if __name__ == "__main__":
    run()