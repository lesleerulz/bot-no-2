# keep_alive.py
from flask import Flask
from threading import Thread
import logging
import os

# Use a specific logger for keep_alive or reuse main app's logger if configured early
ka_logger = logging.getLogger("keep_alive_server") # Specific name
if not ka_logger.handlers: # Basic config if not already set by main app
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

app = Flask(__name__) # Use __name__ for Flask app

@app.route('/')
def home():
    ka_logger.info("Keep-alive endpoint '/' was pinged.")
    return "File Share Bot is active and alive!"

def run_flask_app():
  try:
    # Render and some other platforms set a PORT environment variable
    port = int(os.environ.get("PORT", 8080)) # Default to 8080 if PORT not set
    ka_logger.info(f"Starting Flask keep-alive server on host 0.0.0.0, port {port}...")
    # Use a production-grade WSGI server if this were a more complex web app,
    # but for a simple keep-alive ping, Flask's dev server is often sufficient
    # and simpler on platforms like Replit/Render that manage the external interface.
    app.run(host='0.0.0.0', port=port)
    ka_logger.info("Flask keep-alive server has stopped.") # Should not typically be reached
  except Exception as e:
    ka_logger.error(f"Flask keep-alive server encountered an error: {e}", exc_info=True)

def keep_alive():
    """Starts the Flask app in a separate daemon thread."""
    ka_logger.info("Initializing keep_alive thread...")
    flask_thread = Thread(target=run_flask_app)
    flask_thread.daemon = True  # Ensure thread doesn't block program exit
    flask_thread.start()
    ka_logger.info("Keep_alive thread started.")
