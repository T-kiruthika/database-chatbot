import webview
import threading
from server import server_app

class Api:
    def minimize(self):
        window.minimize()

    def toggle_maximize(self):
        window.toggle_maximize()

    def close(self):
        window.destroy()

def run_server():
    server_app.run(host='127.0.0.1', port=5879, debug=False)

if __name__ == '__main__':
    api = Api()
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

    window = webview.create_window(
        'Database Bot',
        'http://127.0.0.1:5879',
        js_api=api,
        width=1200,
        height=800,
        resizable=True,
        min_size=(800, 600),
        text_select=True,
        frameless=False
    )
    webview.start(debug=False)
