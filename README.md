# Pasto Legal

## How to Run

1. **Install dependencies:**

   ```bash
   pip install -r requirements.txt
   ```

2. **Configure environment variables**

   Create a `.env` file at the project root with the following content:

   ```
   POSTGRES_HOST=your_host
   POSTGRES_PORT=5432
   POSTGRES_DBNAME=your_db
   POSTGRES_USER=your_user
   POSTGRES_PASSWORD=your_password
   export WHATSAPP_ACCESS_TOKEN=<>
   export WHATSAPP_VERIFY_TOKEN=<>
   export WHATSAPP_WEBHOOK_URL=<>
   export WHATSAPP_PHONE_NUMBER_ID=<>
   export WHATSAPP_APP_SECRET=<>
   export APP_ENV="development"
   export GOOGLE_API_KEY=<>

   ```

4. **To run with FastAPI Server:**

   ```bash
   python -m src.app.fastapi_server
   ```

5. **To run with Streamlit App :**

   ```bash
   python -m streamlit run ./app/streamlit_webapp.py
   ```

6. **To (re)build this docker:**
   ```bash
   docker build -t mapbiomas-ai:1.0 docker/
   ```

7. **To Expose the FAST-API service through NGROK:**
   ```bash
   ngrok config add-authtoken <AUTH>
   ngrok http --url=joey-rational-escargot.ngrok-free.app 3000 
   ```
