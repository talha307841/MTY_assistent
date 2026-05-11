# FOCUS

FOCUS is a local-first productivity agent for Linux that tracks activity, manages task state, and resurfaces blocked work so tasks do not get lost.

## Stack

- Python + FastAPI daemon
- SQLite + SQLAlchemy storage
- ActivityWatch integration
- NVIDIA NIM (Llama 3.1 70B instruct) for reasoning
- PyQt6 tray app
- Chrome extension (Manifest v3)
- Local voice loop (faster-whisper + Piper)

## Run locally

```bash
cd /workspaces/MTY_assistent/focus
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python focus_daemon.py
```

Daemon URL: http://127.0.0.1:7799

## Important paths

- Config: `~/.focus/config.yaml`
- DB: `~/.focus/focus.db`
- Logs: `~/.focus/logs/focus.log`
- Reports: `~/.focus/reports/YYYY-MM-DD.html`

## Key API endpoints

- `POST /task/create`
- `POST /task/block`
- `POST /task/complete`
- `GET /tasks/pending`
- `GET /tasks/active`
- `POST /chat`
- `GET /report/today`
- `POST /context/browser`

## Install as service

```bash
cd /workspaces/MTY_assistent/focus
chmod +x install.sh
./install.sh
```

## Tests

```bash
cd /workspaces/MTY_assistent/focus
pytest -q
```
