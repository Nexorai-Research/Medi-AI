"""Development server entry point."""
import os
from dotenv import load_dotenv

load_dotenv()

from app import create_app

app = create_app(os.environ.get('FLASK_ENV', 'development'))

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(
        # Werkzeug's debugger allows code execution, so stay on localhost unless HOST is set.
        host=os.environ.get('HOST', '127.0.0.1'),
        port=port,
        debug=app.config.get('DEBUG', False),
    )
