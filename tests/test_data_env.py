import os
from execution.data.env import load_dotenv


def test_load_dotenv_sets_missing_keys(tmp_path, monkeypatch):
    monkeypatch.delenv("LS_TEST_TOKEN", raising=False)
    (tmp_path / ".env").write_text('LS_TEST_TOKEN=abc123\n# comment\nexport LS_TEST_TWO="xy"\n')
    load_dotenv(tmp_path / ".env")
    assert os.environ["LS_TEST_TOKEN"] == "abc123"
    assert os.environ["LS_TEST_TWO"] == "xy"  # 'export ' prefix + quotes stripped


def test_load_dotenv_does_not_override_existing(tmp_path, monkeypatch):
    monkeypatch.setenv("LS_TEST_TOKEN", "from_shell")
    (tmp_path / ".env").write_text("LS_TEST_TOKEN=from_file\n")
    load_dotenv(tmp_path / ".env")
    assert os.environ["LS_TEST_TOKEN"] == "from_shell"  # existing env wins


def test_load_dotenv_missing_file_is_noop(tmp_path):
    load_dotenv(tmp_path / "nope.env")  # must not raise
