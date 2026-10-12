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


# --- IGNORE_DIRS: work items ya sincronizados que salieron del board

@pytest.fixture
def pasada(tmp_path, monkeypatch):
    """Corre one_pass(dry_run) con Azure simulado devolviendo los ids dados."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("AZURE_DEVOPS_PAT", "x")
    (tmp_path / "autopilot.env").write_text("REPO_PATH=%s\nBASE_BRANCH=main\n" % tmp_path)

    def correr(ids, extra_env="", con_board=()):
        spec = importlib.util.spec_from_file_location(
            "azure_sync", os.path.join(RAIZ, "integraciones", "azure", "azure-sync.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        conf = tmp_path / "azure-sync.env"
        conf.write_text("AZURE_ORG=o\nAZURE_PROJECT=P\nAZURE_ITERATION=@current\n" + extra_env)
        mod.load_config(str(conf))
        mod.BOARD = mod.wi.Board(mod.wi.cargar_config(str(tmp_path / "autopilot.env")))
        for n in con_board:
            mod.BOARD.crear("task", n, "Medium", "T", "d", "c")
        monkeypatch.setattr(mod, "fetch_new_workitems", lambda f: list(ids))
        monkeypatch.setattr(mod, "fetch_detail", lambda p, wid: {
            "fields": {"System.Title": "t%d" % wid, "System.WorkItemType": "Task"}, "relations": []})
        return mod.one_pass(dry_run=True)
    return correr


def test_ignore_dirs_salta_los_ya_sincronizados(pasada, tmp_path):
    (tmp_path / "archivo" / "sprint1").mkdir(parents=True)
    (tmp_path / "archivo" / "sprint1" / "task-2-viejo.md").write_text("x")
    (tmp_path / "otro").mkdir()
    (tmp_path / "otro" / "bug-4.md").write_text("x")
    r = pasada([1, 2, 3, 4], "IGNORE_DIRS=archivo, otro\n", con_board=("1",))
    assert [a["id"] for a in r["added"]] == [3]
    razones = {s["id"]: s["reason"] for s in r["skipped"]}
    assert "ya en el board" in razones[1]
    assert "IGNORE_DIRS" in razones[2] and "IGNORE_DIRS" in razones[4]


def test_sin_ignore_dirs_importa_todo_lo_que_no_esta_en_el_board(pasada):
    r = pasada([1, 2], con_board=("1",))
    assert [a["id"] for a in r["added"]] == [2]


def test_ignore_dirs_inexistente_no_corre(sync, capsys):
    with pytest.raises(SystemExit):
        sync("IGNORE_DIRS=no-existe\n")
    assert "IGNORE_DIRS" in capsys.readouterr().out
