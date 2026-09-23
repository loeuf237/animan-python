from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker
from animan.config import settings

Base = declarative_base()

# SQLite connect_args with check_same_thread=False for multi-threaded/async FastAPI usage
engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False
)

@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    Base.metadata.create_all(bind=engine)
    # Migrations de schéma légères pour SQLite
    try:
        with engine.connect() as conn:
            # Vérifier colonnes existantes de download_tasks
            result = conn.exec_driver_sql("PRAGMA table_info(download_tasks)").fetchall()
            existing_cols = {row[1] for row in result}
            new_cols = [
                ("verificationStatus", "VARCHAR DEFAULT 'UNVERIFIED'"),
                ("videoDuration", "FLOAT"),
                ("verifiedAt", "DATETIME"),
                ("verificationError", "VARCHAR"),
                ("selectedServer", "VARCHAR"),
                ("selectedQuality", "VARCHAR"),
            ]
            for col_name, col_type in new_cols:
                if col_name not in existing_cols:
                    conn.exec_driver_sql(f"ALTER TABLE download_tasks ADD COLUMN {col_name} {col_type}")
            conn.commit()
    except Exception:
        pass

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
