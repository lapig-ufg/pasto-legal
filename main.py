"""Pasto Legal entry point — assembles the app from the Semente framework.

Run with:  python main.py   (WhatsApp webhook on port 3000)
"""

from semente.build import build_app

app = build_app("semente.yaml")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=3000, reload=True)
