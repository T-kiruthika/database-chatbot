import webview
import threading
from server import server_app

# This class contains the functions that control the window, exposed to JavaScript.
class Api:
    def minimize(self):
        window.minimize()

    def toggle_maximize(self):
        window.toggle_maximize()

    def close(self):
        window.destroy()

def run_server():
    # --- THIS LINE IS NOW CORRECT ---
    # The server now correctly listens on the same port the window connects to.
    server_app.run(host='127.0.0.1', port=5879, debug=False)

if __name__ == '__main__':
    # Create an instance of the Api class to pass to the window
    api = Api()
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

    # Create the final application window with all features enabled
    window = webview.create_window(
        'Database Bot',
        'http://127.0.0.1:5879', # This port now matches the server's port.
        js_api=api,
        width=1200,
        height=800,
        resizable=True,
        min_size=(800, 600),
        text_select=True,
        frameless=False
    )
    webview.start(debug=False)