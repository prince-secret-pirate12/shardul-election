<<<<<<< HEAD
# Shardul vs Sattu vs Aash — No-login live voting

Visitors can vote directly without creating an account. The original Shardul and Aash image bytes are unchanged; Sattu has the grey default avatar. Flask-SocketIO broadcasts results to all connected clients and the central database persists counts.

## Local run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
eventlet>=0.40.3```

Open `http://127.0.0.1:5000` (or set `PORT=5001` if 5000 is occupied). Set `SECRET_KEY` to a long random value in production.

## Important: voting limits

No login means **one vote per browser session/cookie**, NOT one vote per person. Clearing cookies, switching browsers/devices, or private browsing can allow additional votes. This is suitable for a casual poll, not a verified election. Existing registered-account votes (if any) remain included in totals.

## Admin

The public site has no login. The separate `/admin` page has a protected admin sign-in. Set `ADMIN_USERNAME` and `ADMIN_PASSWORD` (8+ characters) in environment variables **before first startup**. Do not publish credentials. Admin can pause, open, or close voting.

## Render deployment

Use a Render web service with PostgreSQL. Set `DATABASE_URL`, `SECRET_KEY`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `COOKIE_SECURE=1`. Build: `pip install -r requirements.txt`. Start: `gunicorn --worker-class gthread --threads 8 --workers 1 --bind 0.0.0.0:$PORT app:app`. Use one worker; multi-instance deployments require Redis for Socket.IO broadcasts and suitable load-balancing. Do not use ephemeral SQLite in production. After deploying, test two devices and verify both see the same count without refreshing.
=======
# shardul-election
>>>>>>> 1ea2ab01ffbfb83927c41e7c1c13766cc66f64f5
