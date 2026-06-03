import sys
import os

# Add the parent directory to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.db.session import engine, Base
from app.core.config import settings
import redis

def init_db():
    print("[INFO] Dropping all tables...")
    Base.metadata.drop_all(bind=engine)
    
    print("[INFO] Creating all tables...")
    Base.metadata.create_all(bind=engine)
    
    print("[INFO] Flushing Redis...")
    try:
        r = redis.Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=0)
        r.flushall()
        print("[INFO] Redis flushed successfully.")
    except Exception as e:
        print(f"[WARN] Failed to flush Redis: {e}")
        
    print("[INFO] Database initialization and cleanup complete.")

if __name__ == "__main__":
    init_db()
