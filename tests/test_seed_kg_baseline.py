import pytest
from unittest.mock import patch, MagicMock
import sys, os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))


def _load_mod():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "seed_kg_baseline",
        os.path.join(os.path.dirname(__file__), '..', 'scripts', 'seed_kg_baseline.py')
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_driver():
    driver = MagicMock()
    session = MagicMock()
    driver.session.return_value.__enter__.return_value = session
    driver.session.return_value.__exit__.return_value = False
    return driver, session


@patch('ai_engine.engine.engine.generate_embedding', return_value=[0.1] * 768)
def test_seed_tier2_creates_document_types(mock_embed):
    mod = _load_mod()
    driver, session = _make_driver()
    counts = mod.seed_tier2(driver, embed=False)
    assert counts["document_types"] == 10
    assert counts["workflow_steps"] > 0
    assert session.run.call_count > 0


@patch('ai_engine.engine.engine.generate_embedding', return_value=[0.1] * 768)
def test_seed_tier4_creates_csi_and_aia(mock_embed):
    mod = _load_mod()
    driver, session = _make_driver()
    counts = mod.seed_tier4(driver, embed=False)
    assert counts["spec_sections"] == len(mod.CSI_DIVISIONS)
    assert counts["contract_clauses"] == 3


@patch('ai_engine.engine.engine.generate_embedding', return_value=[0.1] * 768)
def test_seed_tier1_creates_agents_and_rules(mock_embed):
    mod = _load_mod()
    driver, session = _make_driver()
    counts = mod.seed_tier1(driver, embed=False)
    assert counts["agents"] == 2
    assert counts["rules"] == len(mod.DISPATCHER_RULES) + len(mod.RFI_RULES)
    assert counts["escalation_criteria"] == 2
