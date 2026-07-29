import runpy
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text


def test_active_profile_version_migration_uses_the_current_version(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.sqlite'}")
    migration_path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "0014_profile_active_version.py"
    )
    migration = runpy.run_path(str(migration_path))

    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE agent_profiles (
                id VARCHAR(32) NOT NULL PRIMARY KEY,
                version INTEGER NOT NULL
            )
            """
        )
        connection.execute(
            text(
                "INSERT INTO agent_profiles (id, version) "
                "VALUES ('profile-one', 1), ('profile-three', 3)"
            )
        )
        context = MigrationContext.configure(
            connection,
            opts={"render_as_batch": True},
        )
        with Operations.context(context):
            migration["upgrade"]()

        rows = connection.execute(
            text(
                "SELECT id, version, active_version "
                "FROM agent_profiles ORDER BY id"
            )
        ).mappings()
        assert [dict(row) for row in rows] == [
            {"id": "profile-one", "version": 1, "active_version": 1},
            {"id": "profile-three", "version": 3, "active_version": 3},
        ]
