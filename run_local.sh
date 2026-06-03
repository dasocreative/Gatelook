#!/bin/bash
set -e

# Change directory to backend
cd backend

# Create virtual environment if it doesn't exist
if [ ! -d ".venv" ]; then
    echo "[INFO] Creating Python virtual environment..."
    python3 -m venv .venv
fi

# Activate virtual environment
source .venv/bin/activate

# Upgrade pip and install requirements
echo "[INFO] Installing Python dependencies..."
pip install --upgrade pip
# Ensure we use CPU wheel for torch if on Mac
pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt

# Create static directories
echo "[INFO] Preparing directories..."
mkdir -p static/crops

echo "[SUCCESS] Local native setup complete!"
echo ""
echo "To run the application natively on macOS:"
echo "1. Start ONLY PostgreSQL and Redis in Docker (they run perfectly and isolate databases):"
echo "   docker compose up -d db redis"
echo ""
echo "2. Run the FastAPI backend (Terminal 1):"
echo "   source backend/.venv/bin/activate"
echo "   cd backend"
echo "   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"
echo ""
echo "3. Run the Celery worker (Terminal 2):"
echo "   source backend/.venv/bin/activate"
echo "   cd backend"
echo "   celery -A app.workers.celery_app.celery_app worker --loglevel=info --pool=solo"
echo ""
echo "4. Run the React frontend (Terminal 3):"
echo "   cd frontend"
echo "   npm install"
echo "   npm run dev"
echo ""
