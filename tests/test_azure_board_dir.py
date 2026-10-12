"""azure-sync: BOARD_DIR (azure-sync.env) y --board eligen la carpeta del board donde se importa."""
import importlib.util
import os
import sys

import pytest

RAIZ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(RAIZ, "lib"))


@pytest.fixture
def sync(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("AZURE_DEVOPS_PAT", "x")
    (tmp_path / "autopilot.env").write_text("REPO_PATH=%s\nBASE_BRANCH=main\n" % tmp_path)

    def correr(extra_env="", *flags):
        spec = importlib.util.spec_from_file_location(
            "azure_sync", os.path.join(RAIZ, "integraciones", "azure", "azure-sync.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        conf = tmp_path / "azure-sync.env"
        conf.write_text("AZURE_ORG=o\nAZURE_PROJECT=P\nAZURE_ITERATION=@current\n" + extra_env)
        visto = {}
        monkeypatch.setattr(mod, "do_status", lambda: visto.setdefault("dir", mod.BOARD.dir) and 0)
        monkeypatch.setattr(sys, "argv", ["azure-sync.py", "--config", str(conf), "--status", *flags])
        mod.main()
        return visto["dir"]
    return correr


def test_sin_board_dir_usa_el_de_autopilot_env(sync, tmp_path):
    assert sync() == str(tmp_path / ".workitems")


def test_board_dir_relativo_al_config(sync, tmp_path):
    assert sync("BOARD_DIR=otro/board\n") == str(tmp_path / "otro" / "board")


def test_flag_board_gana_sobre_board_dir(sync, tmp_path):
    destino = tmp_path / "flag"
    assert sync("BOARD_DIR=otro\n", "--board", str(destino)) == str(destino)
