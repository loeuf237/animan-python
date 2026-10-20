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

import logging

logger = logging.getLogger("animan.database")

def init_db():
    import animan.models  # Assure le chargement de tous les modèles pour create_all
    Base.metadata.create_all(bind=engine)
    # Migrations de schéma légères pour SQLite
    try:
        with engine.begin() as conn:
            # Vérifier colonnes existantes de download_tasks
            result = conn.exec_driver_sql("PRAGMA table_info(download_tasks)").fetchall()
            existing_cols = {row[1] for row in result}
            new_cols = [
                ("verificationUrl", "VARCHAR"),
                ("animeUrl", "VARCHAR DEFAULT ''"),
                ("version", "VARCHAR DEFAULT ''"),
                ("verificationStatus", "VARCHAR DEFAULT 'UNVERIFIED'"),
                ("videoDuration", "FLOAT"),
                ("verifiedAt", "DATETIME"),
                ("verificationError", "VARCHAR"),
                ("selectedServer", "VARCHAR"),
                ("selectedQuality", "VARCHAR"),
                ("exportStatus", "VARCHAR NOT NULL DEFAULT 'NOT_REQUESTED'"),
                ("exportUrisJson", "VARCHAR NOT NULL DEFAULT '[]'"),
                ("exportDestination", "VARCHAR"),
                ("exportError", "VARCHAR"),
                ("exportAttempts", "INTEGER NOT NULL DEFAULT 0"),
                ("exportedAt", "DATETIME"),
            ]
            for col_name, col_type in new_cols:
                if col_name not in existing_cols:
                    conn.exec_driver_sql(f"ALTER TABLE download_tasks ADD COLUMN {col_name} {col_type}")
            existing_favorites = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(favorites)")}
            for name, declaration in [
                ("autoDownloadVersion", "VARCHAR DEFAULT ''"),
                ("autoDownloadSubtitles", "BOOLEAN DEFAULT 0"),
                ("autoDownloadServer", "VARCHAR"),
                ("autoDownloadQuality", "VARCHAR"),
                ("autoDownloadInitialized", "BOOLEAN DEFAULT 0"),
                ("autoDownloadError", "VARCHAR"),
            ]:
                if name not in existing_favorites:
                    conn.exec_driver_sql(f'ALTER TABLE favorites ADD COLUMN "{name}" {declaration}')
            # Older Android builds stored export failure in the transfer error.
            # Do not infer EXPORTED for old completed tasks without URI evidence.
            conn.exec_driver_sql("""
                UPDATE download_tasks SET exportStatus='EXPORT_FAILED', exportError=error,
                    exportAttempts=MAX(exportAttempts, 1), error=NULL
                WHERE status='COMPLETED' AND error LIKE 'Android export failed;%'
            """)
    except Exception as e:
        raise RuntimeError("Unable to update the Animan database schema") from e

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
