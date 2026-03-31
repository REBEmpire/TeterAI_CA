import pytest
from unittest.mock import patch, MagicMock
import sys, os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))


def test_setup_schema_runs_all_statements():
    """setup_kg_schema must execute both constraint and vector index statements."""
    with patch('neo4j.GraphDatabase.driver') as mock_gdb:
        driver = MagicMock()
        mock_gdb.return_value = driver
        session = MagicMock()
        driver.session.return_value.__enter__.return_value = session
        driver.session.return_value.__exit__.return_value = False

        with patch.dict('os.environ', {
            'NEO4J_URI': 'neo4j+s://test',
            'NEO4J_USERNAME': 'neo4j',
            'NEO4J_PASSWORD': 'password',
        }):
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "setup_kg_schema",
                os.path.join(os.path.dirname(__file__), '..', 'scripts', 'setup_kg_schema.py')
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            mod.apply_schema(driver)

        # Should have called session.run many times (constraints + indexes)
        assert session.run.call_count >= 12, (
            f"Expected >=12 Cypher statements, got {session.run.call_count}"
        )
