import os
import unittest
from unittest.mock import MagicMock, patch

from deploy import init_database


class DeploySchemaTest(unittest.TestCase):
    def test_schema_initializer_executes_every_statement(self):
        connection = MagicMock()

        with (
            patch.dict(os.environ, {"DATABASE_URL": "mssql+pyodbc://example"}, clear=False),
            patch.object(init_database, "create_engine") as create_engine,
        ):
            create_engine.return_value.begin.return_value.__enter__.return_value = connection
            init_database.main()

        self.assertEqual(
            create_engine.return_value.begin.return_value.__enter__.return_value.execute.call_count,
            len(init_database.SCHEMA_STATEMENTS),
        )

    def test_schema_initializer_requires_database_url(self):
        with patch.dict(os.environ, {"DATABASE_URL": ""}, clear=False):
            with self.assertRaisesRegex(RuntimeError, "DATABASE_URL"):
                init_database.main()

    def test_schema_contains_current_audit_log_fields(self):
        schema = "\n".join(init_database.SCHEMA_STATEMENTS)
        self.assertIn("CREATE TABLE dbo.Audit_logs", schema)
        self.assertIn("Detail_json varchar(max)", schema)
        self.assertIn("IX_Audit_logs_User_id_CreatedAt", schema)


if __name__ == "__main__":
    unittest.main()
