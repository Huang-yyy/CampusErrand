"""CampusErrand entrypoint: `python -m app` runs the server."""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from app.db import init_db
init_db()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)