import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def load_deploy():
    spec = importlib.util.spec_from_file_location(
        "deploy_to_space", REPO_ROOT / "scripts" / "deploy_to_space.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["deploy_to_space"] = module
    spec.loader.exec_module(module)
    return module


deploy = load_deploy()


def test_a_missing_token_stops_before_anything_is_uploaded(monkeypatch):
    from copilot import settings as settings_module

    monkeypatch.setattr(
        settings_module,
        "get_settings",
        lambda: settings_module.Settings(hf_token="", _env_file=None),
    )
    monkeypatch.setattr(deploy, "get_settings", settings_module.get_settings)
    with pytest.raises(SystemExit, match="HF_TOKEN is not set"):
        deploy.require_token()


def test_a_present_token_is_returned(monkeypatch):
    from copilot import settings as settings_module

    monkeypatch.setattr(
        deploy, "get_settings", lambda: settings_module.Settings(hf_token="hf_x", _env_file=None)
    )
    assert deploy.require_token() == "hf_x"


def test_the_space_readme_declares_the_docker_sdk_and_port():
    assert "sdk: docker" in deploy.SPACE_README
    assert "app_port: 7860" in deploy.SPACE_README


def test_the_space_readme_says_it_is_a_limited_demo():
    assert "rate limited" in deploy.SPACE_README
    assert "daily token budget" in deploy.SPACE_README


def test_only_what_the_space_needs_is_uploaded():
    assert "Dockerfile" in deploy.INCLUDED
    assert "src" in deploy.INCLUDED
    assert "api" in deploy.INCLUDED
    assert "app" in deploy.INCLUDED


def test_the_data_and_the_environment_are_never_uploaded_as_source():
    for excluded in ("data", ".venv", ".chroma", ".env", "mlruns"):
        assert excluded not in deploy.INCLUDED


def test_every_included_path_exists_in_the_repository():
    for name in deploy.INCLUDED:
        assert (REPO_ROOT / name).exists(), name


def test_the_index_travels_as_a_dataset_not_inside_the_image():
    assert deploy.INDEX_FILE.endswith(".tar.gz")
    assert "index" in deploy.INDEX_FILE


def test_a_free_account_is_told_it_cannot_create_a_docker_space():
    # The failure used to arrive partway through the upload, which read like a bug.
    deploy = load_deploy()
    with pytest.raises(deploy.PaidPlanNeededError) as raised:
        deploy.require_docker_spaces(is_pro=False)
    assert "paid Hugging Face plan" in str(raised.value)
    assert "make api" in str(raised.value)


def test_a_paid_account_is_allowed_through():
    deploy = load_deploy()
    assert deploy.require_docker_spaces(is_pro=True) is None
