# SecureVote — Deployment Guide

## Project Structure

```
voting_app/
├── app.py                 # Main Flask application (routes, models, SocketIO)
├── requirements.txt       # Python dependencies
├── templates/
│   ├── base.html          # Shared layout (navbar, styles, toasts)
│   ├── index.html         # Home page — voter ID entry
│   ├── vote.html          # Ballot page — candidate selection
│   ├── results.html       # Live results with Chart.js + Socket.IO
│   └── admin.html         # Admin dashboard
└── instance/
    └── votes.db           # SQLite database (auto-created)
```

---

## Quick Start (Local Development)

### 1. Create virtual environment
```bash
cd voting_app
python -m venv venv
source venv/bin/activate       # Linux/macOS
# OR
venv\Scripts\activate          # Windows
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Set environment variables
```bash
export SECRET_KEY="your-very-secret-key-change-this"
export ADMIN_PASSWORD="yourSecureAdminPassword"
# For PostgreSQL (optional):
# export DATABASE_URL="postgresql://user:password@localhost/voting_db"
```

### 4. Run the app
```bash
python app.py
```

Visit: http://localhost:5000

---

## Admin Setup (First Run)

1. Go to http://localhost:5000/admin
2. Login with your ADMIN_PASSWORD (default: `admin1234`)
3. **Add Candidates** → Candidates tab → enter names + optional positions
4. **Generate Voter IDs** → Voters tab → click "Generate IDs" (default 100)
5. **Set Election Timeframe** → Settings tab → set start/end time (UTC), or click "▶ Start Voting Now"
6. **Distribute voter codes** → Export CSV from Voters tab

---

## Production Deployment

### Option A: Heroku / Railway / Render

```bash
# Procfile
web: gunicorn --worker-class eventlet -w 1 app:app
```

Set these environment variables in your hosting dashboard:
- `SECRET_KEY` — long random string
- `ADMIN_PASSWORD` — strong password
- `DATABASE_URL` — PostgreSQL connection string

### Option B: VPS (Ubuntu) with Nginx + Gunicorn

```bash
# Install
pip install gunicorn eventlet

# Run
gunicorn --worker-class eventlet -w 1 --bind 0.0.0.0:5000 app:app
```

Nginx config snippet:
```nginx
server {
    listen 80;
    server_name yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### Option C: Docker

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
ENV SECRET_KEY=changeme
ENV ADMIN_PASSWORD=admin1234
EXPOSE 5000
CMD ["gunicorn", "--worker-class", "eventlet", "-w", "1", "--bind", "0.0.0.0:5000", "app:app"]
```

```bash
docker build -t securevote .
docker run -p 5000:5000 -e SECRET_KEY=xxx -e ADMIN_PASSWORD=yyy securevote
```

### PostgreSQL Setup
```bash
# Create database
createdb voting_db

# Set DATABASE_URL
export DATABASE_URL="postgresql://postgres:password@localhost/voting_db"
```

---

## Security Notes

| Feature | Implementation |
|---|---|
| One vote per ID | `has_voted` flag + DB unique constraint on Vote.voter_id |
| Backend validation | All vote logic server-side; frontend is display only |
| Session security | Flask sessions with SECRET_KEY; HTTPOnly; SameSite=Lax |
| Rate limiting | `/api/validate-voter` → 10/min, `/api/submit-vote` → 5/min |
| Admin auth | Password hash via Werkzeug `generate_password_hash` |
| CSRF | SameSite cookie policy + JSON API (no form submissions) |
| Double-vote race | DB unique constraint on `votes.voter_id` column |

---

## Default Credentials

| | Value |
|---|---|
| Admin password | `admin1234` (change via `ADMIN_PASSWORD` env var) |
| Voter ID format | `VOTE-XXXXXX` (6 alphanumeric chars) |

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | `change-this-in-production-xyz987` | Flask session secret |
| `ADMIN_PASSWORD` | `admin1234` | Admin dashboard password |
| `DATABASE_URL` | `sqlite:///votes.db` | DB connection string |
