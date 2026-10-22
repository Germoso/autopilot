"""azure-sync: --set KEY=VALUE crea o edita azure-sync.env (no toca el board ni el PAT)."""
import importlib.util
import json
import os
import sys

import pytest

RAIZ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


@pytest.fixture
def sync(tmp_path, monkeypatch):
    def do(*pares):
        spec = importlib.util.spec_from_file_location(
            "azure_sync", os.path.join(RAIZ, "integraciones", "azure", "azure-sync.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        conf = tmp_path / "azure-sync.env"
        # v2: --set es una pareja KEY=VALUE por flag (repetible)
        argv = ["azure-sync.py", "--config", str(conf)] + [a for p in pares for a in ("--set", p)]
        monkeypatch.setattr(sys, "argv", argv)
        return m, conf
    return do


def test_set_crea_desde_el_ejemplo(sync, tmp_path):
    m, conf = sync(
        "AZURE_ORG=codikasrl",
        "AZURE_PROJECT=Konectame_App_Clientes",
        "AZURE_ITERATION=@current",
        "SYNC.Konectame_App_Clientes=Konectame_App_Clientes|@current")
    m.main()
    assert conf.exists()
    txt = conf.read_text()
    assert "AZURE_ORG=codikasrl" in txt
    assert "AZURE_PROJECT=Konectame_App_Clientes" in txt
    # la linea SYNC comentada del ejemplo se activa (sin el #)
    assert "SYNC.Konectame_App_Clientes=Konectame_App_Clientes|@current" in txt
    assert not any(l.startswith("# SYNC.Konectame_App_Clientes") for l in txt.splitlines())


def test_set_pisa_valor_existente(sync, tmp_path):
    m, conf = sync("AZURE_PROJECT=Viejo", "AZURE_PROJECT=Nuevo")
    m.main()
    assert conf.read_text().count("AZURE_PROJECT=Nuevo\n") == 1


def test_set_sin_igual_falla(sync, tmp_path, capsys):
    m, conf = sync("SIN_IGUAL")
    with pytest.raises(SystemExit) as e:
        m.main()
    assert e.value.code == 2
    err = capsys.readouterr().out
    assert json.loads(err)["message"] == "--set necesita KEY=VALUE (recibido: SIN_IGUAL)"


def _cargar(tmp_path, extra=""):
    spec = importlib.util.spec_from_file_location(
        "azure_sync", os.path.join(RAIZ, "integraciones", "azure", "azure-sync.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    conf = tmp_path / "azure-sync.env"
    conf.write_text("AZURE_ORG=o\n" + extra)
    m.load_config(str(conf))
    return m


def test_pat_en_la_config_se_lee(tmp_path):
    assert _cargar(tmp_path, "AZURE_DEVOPS_PAT=pat-de-config\n").CFG["pat"] == "pat-de-config"


def test_pat_de_variable_gana_al_de_config(tmp_path, monkeypatch):
    monkeypatch.setenv("AZURE_DEVOPS_PAT", "pat-global")
    assert _cargar(tmp_path, "AZURE_DEVOPS_PAT=pat-de-config\n").CFG["pat"] == "pat-global"