# Pasto Legal

## How to Run

### Local

1. **Install dependencies:**

   ```bash
   pip install -r requirements.txt
   ```

2. **Configure environment variables**

   Create a `.env` file at the project root with the following content:

   ```
   WHATSAPP_ACCESS_TOKEN=<>
   WHATSAPP_VERIFY_TOKEN=<>
   WHATSAPP_WEBHOOK_URL=<>
   WHATSAPP_PHONE_NUMBER_ID=<>
   WHATSAPP_APP_SECRET=<>
   APP_ENV="development"
   GOOGLE_API_KEY=<>

   ```

3. **To run with FastAPI Server (WhatsApp Bot):**

   ```bash
   python run_whatsapp.py
   ```

4. **To run with Streamlit App:**

   ```bash
   python run_streamlit.py
   ```

5. **To (re)build this docker:**

   ```bash
   docker build -t mapbiomas-ai:1.0 docker/
   ```

6. **To Expose the FAST-API service through NGROK:**

   ```bash
   ngrok config add-authtoken <AUTH>
   ngrok http --url=joey-rational-escargot.ngrok-free.app 3000
   ```

### Docker

   ```bash
   docker compose up --build
   ```

