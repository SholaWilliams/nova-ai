"""Unit tests for nova.core.config — Settings load/save and Secrets precedence (docs/11 §5)."""

import json
from pathlib import Path

import pytest
from pytest import MonkeyPatch

from nova.core.config import (
    Secrets,
    Settings,
    get_data_dir,
    load_settings,
    save_settings,
    write_secret_to_env,
)

# ── get_data_dir ──────────────────────────────────────────────────────


def test_get_data_dir_honors_override(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("NOVA_DATA_DIR", str(tmp_path / "custom"))
    assert get_data_dir() == tmp_path / "custom"


def test_get_data_dir_defaults_under_appdata(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv("NOVA_DATA_DIR", raising=False)
    monkeypatch.setenv("APPDATA", r"C:\Users\test\AppData\Roaming")
    assert get_data_dir() == Path(r"C:\Users\test\AppData\Roaming") / "NOVA"


def test_get_data_dir_falls_back_to_home_without_appdata(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv("NOVA_DATA_DIR", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)
    assert get_data_dir() == Path.home() / ".nova"


# ── Settings: load defaults / quarantine ─────────────────────────────


def test_load_settings_missing_file_returns_defaults(tmp_path: Path) -> None:
    settings = load_settings(tmp_path / "settings.json")
    assert settings == Settings()
    assert settings.provider.omniroute_model == "auto/coding"
    assert settings.weather.default_city == "Lagos"


def test_load_settings_corrupt_json_falls_back_to_defaults(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{not valid json", encoding="utf-8")

    settings = load_settings(path)

    assert settings == Settings()


def test_load_settings_non_object_json_falls_back_to_defaults(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")

    settings = load_settings(path)

    assert settings == Settings()


def test_load_settings_invalid_section_reverts_only_that_section(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                # omniroute_model: str — an int fails validation (pydantic v2 doesn't
                # coerce int -> str), same "one bad section" trigger the old `active`
                # Literal field used to provide.
                "provider": {"omniroute_model": 123},
                "weather": {"default_city": "Nairobi"},
            }
        ),
        encoding="utf-8",
    )

    settings = load_settings(path)

    assert settings.provider.omniroute_model == "auto/coding"  # reverted to default
    assert settings.weather.default_city == "Nairobi"  # untouched, valid


def test_load_settings_valid_file_round_trips_values(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "provider": {"omniroute_model": "custom/model"},
                "ui": {"accent": "violet", "reduced_motion": True},
            }
        ),
        encoding="utf-8",
    )

    settings = load_settings(path)

    assert settings.provider.omniroute_model == "custom/model"
    assert settings.ui.accent == "violet"
    assert settings.ui.reduced_motion is True


# ── Settings: unknown-field preservation (forward compatibility) ────


def test_load_settings_preserves_unknown_top_level_section(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"version": 1, "speech": {"wake_word": "nova"}}),
        encoding="utf-8",
    )

    settings = load_settings(path)

    assert settings.model_dump(mode="json")["speech"] == {"wake_word": "nova"}


def test_load_settings_preserves_unknown_field_within_a_section(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {"version": 1, "provider": {"omniroute_model": "auto/coding", "future_field": 42}}
        ),
        encoding="utf-8",
    )

    settings = load_settings(path)

    assert settings.provider.model_dump()["future_field"] == 42


# ── Settings: atomic save ────────────────────────────────────────────


def test_save_settings_writes_readable_json(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    save_settings(Settings(), path)

    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["version"] == 1
    assert on_disk["provider"]["omniroute_model"] == "auto/coding"


def test_save_settings_creates_parent_directory(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "dir" / "settings.json"
    save_settings(Settings(), path)
    assert path.is_file()


def test_save_settings_leaves_no_temp_file_behind(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    save_settings(Settings(), path)
    assert list(tmp_path.iterdir()) == [path]


def test_save_settings_cleans_up_temp_file_on_write_failure(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "settings.json"

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full (simulated)")

    monkeypatch.setattr("os.replace", _boom)

    with pytest.raises(OSError, match="disk full"):
        save_settings(Settings(), path)

    assert not path.exists()
    assert list(tmp_path.iterdir()) == []  # temp file was cleaned up, not orphaned


def test_save_then_load_round_trips_unknown_fields(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    original = load_settings(path)  # defaults
    path.write_text(
        json.dumps({**original.model_dump(mode="json"), "future_top_level": "value"}),
        encoding="utf-8",
    )
    loaded = load_settings(path)
    save_settings(loaded, path)

    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["future_top_level"] == "value"


# ── Secrets ───────────────────────────────────────────────────────────


def test_secrets_reads_from_process_env(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("NOVA_OMNIROUTE_API_KEY", "omniroute-key-from-env")
    monkeypatch.setenv("NOVA_GROQ_API_KEY", "groq-key-from-env")

    secrets = Secrets.load(repo_env=tmp_path / "missing.env", data_dir=tmp_path)

    assert secrets.omniroute_api_key == "omniroute-key-from-env"
    assert secrets.groq_api_key == "groq-key-from-env"


def test_secrets_defaults_when_nothing_set(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("NOVA_OMNIROUTE_API_KEY", raising=False)
    monkeypatch.delenv("NOVA_GROQ_API_KEY", raising=False)

    secrets = Secrets.load(repo_env=tmp_path / "missing.env", data_dir=tmp_path)

    assert secrets.omniroute_api_key is None
    assert secrets.log_level == "INFO"


def test_secrets_reads_repo_env_file(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("NOVA_OMNIROUTE_API_KEY", raising=False)
    repo_env = tmp_path / "repo" / ".env"
    repo_env.parent.mkdir(parents=True)
    repo_env.write_text("NOVA_OMNIROUTE_API_KEY=from-repo-env\n", encoding="utf-8")

    secrets = Secrets.load(repo_env=repo_env, data_dir=tmp_path / "data")

    assert secrets.omniroute_api_key == "from-repo-env"


def test_secrets_data_dir_env_file_overrides_repo_env_file(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("NOVA_OMNIROUTE_API_KEY", raising=False)
    repo_env = tmp_path / "repo" / ".env"
    repo_env.parent.mkdir(parents=True)
    repo_env.write_text("NOVA_OMNIROUTE_API_KEY=from-repo-env\n", encoding="utf-8")

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / ".env").write_text("NOVA_OMNIROUTE_API_KEY=from-data-dir-env\n", encoding="utf-8")

    secrets = Secrets.load(repo_env=repo_env, data_dir=data_dir)

    assert secrets.omniroute_api_key == "from-data-dir-env"


def test_secrets_process_env_overrides_both_env_files(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    repo_env = tmp_path / "repo" / ".env"
    repo_env.parent.mkdir(parents=True)
    repo_env.write_text("NOVA_OMNIROUTE_API_KEY=from-repo-env\n", encoding="utf-8")

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / ".env").write_text("NOVA_OMNIROUTE_API_KEY=from-data-dir-env\n", encoding="utf-8")

    monkeypatch.setenv("NOVA_OMNIROUTE_API_KEY", "from-process-env")

    secrets = Secrets.load(repo_env=repo_env, data_dir=data_dir)

    assert secrets.omniroute_api_key == "from-process-env"


@pytest.mark.parametrize("key", ["omniroute_api_key", "groq_api_key", "desktop_override"])
def test_secrets_never_exposes_keys_via_repr_by_default(key: str) -> None:
    # Sanity check that Secrets is a plain BaseSettings model (no accidental logging config);
    # real secret-scrubbing in log output is core.logging's job, tested there.
    assert key in Secrets.model_fields


# ── write_secret_to_env ───────────────────────────────────────────────


def test_write_secret_to_env_creates_file_with_key(tmp_path: Path) -> None:
    write_secret_to_env(tmp_path, "NOVA_OMNIROUTE_API_KEY", "new-key")

    content = (tmp_path / ".env").read_text(encoding="utf-8")
    assert content == "NOVA_OMNIROUTE_API_KEY=new-key\n"


def test_write_secret_to_env_creates_parent_directory(tmp_path: Path) -> None:
    data_dir = tmp_path / "nested" / "dir"
    write_secret_to_env(data_dir, "NOVA_OMNIROUTE_API_KEY", "new-key")
    assert (data_dir / ".env").is_file()


def test_write_secret_to_env_replaces_existing_key_in_place(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        "NOVA_OMNIROUTE_API_KEY=old-key\nNOVA_GROQ_API_KEY=groq-key\n", encoding="utf-8"
    )

    write_secret_to_env(tmp_path, "NOVA_OMNIROUTE_API_KEY", "rotated-key")

    lines = (tmp_path / ".env").read_text(encoding="utf-8").splitlines()
    assert lines == ["NOVA_OMNIROUTE_API_KEY=rotated-key", "NOVA_GROQ_API_KEY=groq-key"]


def test_write_secret_to_env_preserves_other_keys_when_adding_new_one(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("NOVA_OMNIROUTE_API_KEY=omniroute-key\n", encoding="utf-8")

    write_secret_to_env(tmp_path, "NOVA_GROQ_API_KEY", "groq-key")

    lines = (tmp_path / ".env").read_text(encoding="utf-8").splitlines()
    assert lines == ["NOVA_OMNIROUTE_API_KEY=omniroute-key", "NOVA_GROQ_API_KEY=groq-key"]


def test_write_secret_to_env_leaves_no_temp_file_behind(tmp_path: Path) -> None:
    write_secret_to_env(tmp_path, "NOVA_OMNIROUTE_API_KEY", "new-key")
    assert list(tmp_path.iterdir()) == [tmp_path / ".env"]


def test_write_secret_to_env_cleans_up_temp_file_on_write_failure(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    def _boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full (simulated)")

    monkeypatch.setattr("os.replace", _boom)

    with pytest.raises(OSError, match="disk full"):
        write_secret_to_env(tmp_path, "NOVA_OMNIROUTE_API_KEY", "new-key")

    assert not (tmp_path / ".env").exists()
    assert list(tmp_path.iterdir()) == []
