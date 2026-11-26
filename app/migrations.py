import logging

from sqlalchemy import Engine, inspect, text

from .db import Base, engine
from . import models as _models

logger = logging.getLogger("ctr.migrations")

_MIGRATION_VERSION = "20261126_01_add_server_integration_schema"
_SERVER_COLUMNS = {
    "verification_status": "VARCHAR(32) NOT NULL DEFAULT 'pending_verification'",
    "pairing_token_hash": "VARCHAR(64) NOT NULL DEFAULT ''",
    "registration_id": "VARCHAR(80) NOT NULL DEFAULT ''",
    "owner_id": "INTEGER REFERENCES users(id)",
    "can_issue_global_bans": "BOOLEAN NOT NULL DEFAULT FALSE",
    "last_heartbeat": "TIMESTAMP WITH TIME ZONE",
    "player_count": "INTEGER NOT NULL DEFAULT 0",
    "max_player_count": "INTEGER NOT NULL DEFAULT 0",
    "gmod_version": "VARCHAR(100) NOT NULL DEFAULT ''",
}


def _ensure_registration_ids(connection) -> None:
    rows = connection.execute(
        text("SELECT id, registration_id FROM game_servers ORDER BY id")
    ).all()
    seen: set[str] = set()
    for server_id, registration_id in rows:
        value = (registration_id or "").strip()
        if not value or value in seen:
            base = f"legacy-{server_id}"
            value = base
            suffix = 1
            while value in seen:
                value = f"{base}-{suffix}"
                suffix += 1
            connection.execute(
                text("UPDATE game_servers SET registration_id = :value WHERE id = :server_id"),
                {"value": value, "server_id": server_id},
            )
        seen.add(value)


def _add_missing_server_columns(connection) -> None:
    inspector = inspect(connection)
    if "game_servers" not in inspector.get_table_names():
        raise RuntimeError("Cannot migrate CTR server integration: game_servers table is missing")

    existing = {column["name"] for column in inspector.get_columns("game_servers")}
    is_postgresql = connection.dialect.name == "postgresql"
    add_verification_status = "verification_status" not in existing
    for column, definition in _SERVER_COLUMNS.items():
        if column in existing:
            continue
        if is_postgresql:
            statement = f"ALTER TABLE game_servers ADD COLUMN IF NOT EXISTS {column} {definition}"
        else:
            statement = f"ALTER TABLE game_servers ADD COLUMN {column} {definition}"
        connection.exec_driver_sql(statement)
        logger.info("Added missing game_servers.%s column", column)

    if add_verification_status:
        connection.exec_driver_sql(
            "UPDATE game_servers SET verification_status = "
            "CASE WHEN active = FALSE THEN 'suspended' "
            "WHEN verified = TRUE THEN 'verified' "
            "ELSE 'pending_verification' END"
        )

    _ensure_registration_ids(connection)

    foreign_keys = inspect(connection).get_foreign_keys("game_servers")
    has_owner_fk = any("owner_id" in key.get("constrained_columns", []) for key in foreign_keys)
    if not has_owner_fk and connection.dialect.name == "postgresql":
        connection.exec_driver_sql(
            "ALTER TABLE game_servers ADD CONSTRAINT fk_game_servers_owner_id_users "
            "FOREIGN KEY (owner_id) REFERENCES users (id)"
        )

    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_game_servers_pairing_token_hash "
        "ON game_servers (pairing_token_hash)"
    )
    connection.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_game_servers_registration_id "
        "ON game_servers (registration_id)"
    )


def migrate_database(database_engine: Engine = engine) -> None:
    """Apply the additive CTR schema migration before the application serves traffic."""
    with database_engine.begin() as connection:
        if connection.dialect.name == "postgresql":
            connection.execute(text("SELECT pg_advisory_xact_lock(1146309709, 1)"))

        # create_all only creates missing tables; the versioned migration below
        # handles columns on existing tables without replacing any data.
        Base.metadata.create_all(bind=connection)
        connection.exec_driver_sql(
            "CREATE TABLE IF NOT EXISTS ctr_schema_migrations "
            "(version VARCHAR(100) PRIMARY KEY, applied_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
        applied = connection.execute(
            text("SELECT 1 FROM ctr_schema_migrations WHERE version = :version"),
            {"version": _MIGRATION_VERSION},
        ).scalar_one_or_none()
        _add_missing_server_columns(connection)
        if applied:
            logger.info("Database migration %s is already applied", _MIGRATION_VERSION)
            return

        connection.execute(
            text("INSERT INTO ctr_schema_migrations (version) VALUES (:version)"),
            {"version": _MIGRATION_VERSION},
        )
        logger.info("Applied database migration %s", _MIGRATION_VERSION)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    migrate_database()
