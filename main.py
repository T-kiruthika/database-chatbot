import webview
import threading
from server import server_app
import socket
import time

SERVER_PORT = 5879
SERVER_HOST = '127.0.0.1'

class Api:
    def minimize(self): window.minimize()
    def toggle_maximize(self): window.toggle_maximize()
    def close(self): webview.destroy()

def run_server():
    try:
        server_app.run(host=SERVER_HOST, port=SERVER_PORT, debug=False, use_reloader=False)
    except Exception as e:
        print(f"[ERROR] Flask failed: {e}")

def check_server_ready(host, port, timeout=5):
    start_time = time.time()
    while time.time() - start_time < timeout:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex((host, port)) == 0:
                return True
        time.sleep(0.1)
    return False

if __name__ == '__main__':
    api = Api()
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

    if not check_server_ready(SERVER_HOST, SERVER_PORT):
        print("[CRITICAL] Server timeout.")
        exit(1)
        
    window = webview.create_window(
        'Agentic Database Bot',
        f'http://{SERVER_HOST}:{SERVER_PORT}',
        js_api=api,
        width=1200, height=800,
        resizable=True,
        min_size=(800, 600)
    )
    
    webview.start(debug=False)
