import shutil

import pytest
from fastapi.testclient import TestClient

from app.config import ROOT, Settings
from app.main import create_app
from app.modules.m7_batches.pipeline import run_pipeline
from app.sources import read_sources


@pytest.fixture(scope="session")
def dirty():
    return read_sources(ROOT / "sample_data", "dirty")


@pytest.fixture(scope="session")
def dirty_result(dirty):
    return run_pipeline(dirty)


@pytest.fixture(scope="session")
def clean_result():
    return run_pipeline(read_sources(ROOT / "sample_data", "clean"))


@pytest.fixture
def settings(tmp_path):
    return Settings(tmp_path / "sources", tmp_path / "weigh.sqlite3")


@pytest.fixture
def client(settings):
    shutil.copytree(ROOT / "sample_data", settings.source_dir)
    with TestClient(create_app(settings)) as test_client:
        yield test_client
