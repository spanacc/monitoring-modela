"""
Provere dodavanja podataka sa dashboarda (korak 7): predlog kolona,
upis u podešavanja, uklanjanje, i ceo put kroz server (adrese /api/izvori).
"""

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import dodavanje
from app.alarmi.konfiguracija import Konfiguracija, ucitaj_ili_prazna
from app.dashboard.server import napravi_aplikaciju

IZMENA = {"X-Dashboard": "1"}


def siroka_tabela(putanja, redova=200, pocetak=None):
    """Svaki senzor u svojoj koloni, merenje na svaki minut, plus redni broj."""
    pocetak = pocetak or datetime(2026, 1, 10, 8, 0, tzinfo=timezone.utc)
    redovi = ["instant;vreme;Pritisak;Protok;Temperatura"]
    for i in range(redova):
        t = pocetak + timedelta(minutes=i)
        redovi.append(f"{i + 1};{t:%Y-%m-%d %H:%M};{4 + (i % 7) / 10:.2f};{120 + (i % 11)};{61 + (i % 5) / 2:.1f}")
    putanja.write_text("\n".join(redovi) + "\n", encoding="utf-8")
    return putanja


def test_predlog_prepoznaje_siroku_tabelu_i_redni_broj(tmp_path):
    p = dodavanje.predlog(siroka_tabela(tmp_path / "senzori.csv"), "Europe/Belgrade")
    assert p["polja"]["vreme"] == "vreme"
    assert p["siroka"] is True
    assert p["brojcane"] == ["Pritisak", "Protok", "Temperatura"]  # bez rednog broja
    assert p["redova"] == 200 and p["od"] and p["do"]
    assert p["istorijski"] is True  # januar 2026. je starije od nedelju dana
    assert next(k for k in p["kolone"] if k["naziv"] == "instant")["vrsta"] == "redni broj"


def test_predlog_bez_vremena_upozorava(tmp_path):
    f = tmp_path / "bez.csv"
    f.write_text("species;bill\nAdelie;39.1\nGentoo;46.1\n", encoding="utf-8")
    p = dodavanje.predlog(f, "Europe/Belgrade")
    assert "vreme" not in p["polja"]
    assert any("vremenom" in u for u in p["upozorenja"])


def test_dodaj_izvor_upisuje_podesavanja_i_proverava_fajl(tmp_path):
    f = siroka_tabela(tmp_path / "senzori.csv")
    k = Konfiguracija(izvori=[], baza=f"sqlite:///{tmp_path}/m.db")
    pod = tmp_path / "podesavanja.json"
    dodavanje.dodaj_izvor(k, f, "pumpa", {"vreme": "vreme"}, ["Pritisak", "Protok"], True, "dm", pod)
    sacuvano = json.loads(pod.read_text(encoding="utf-8"))
    assert sacuvano["izvori"][0]["kolone"] == ["Pritisak", "Protok"]
    assert sacuvano["izvori"][0]["istorijski"] is True
    assert ucitaj_ili_prazna(pod).izvori[0].model == "pumpa"

    with pytest.raises(ValueError, match="već postoji"):
        dodavanje.dodaj_izvor(k, f, "pumpa", {"vreme": "vreme"}, ["Protok"], True, "dm", pod)
    with pytest.raises(ValueError, match="vremenom"):
        dodavanje.dodaj_izvor(k, f, "drugi", {"vrednost": "Protok"}, None, True, "dm", pod)
    with pytest.raises(ValueError, match="nijedan red"):
        dodavanje.dodaj_izvor(k, f, "treci", {"vreme": "Protok", "vrednost": "Pritisak"}, None, True, "dm", pod)

    dodavanje.ukloni_izvor(k, "pumpa", pod)
    assert ucitaj_ili_prazna(pod).izvori == []


def test_ceo_put_kroz_dashboard(tmp_path, monkeypatch):
    # Prazna aplikacija -> ubačen fajl -> predlog -> dodavanje -> podaci i problemi na ekranu -> uklanjanje.
    monkeypatch.chdir(tmp_path)  # ubačeni fajlovi idu u data/ulaz/ u radnom folderu
    k = Konfiguracija(izvori=[], baza=f"sqlite:///{tmp_path}/m.db")
    klijent = TestClient(napravi_aplikaciju(k, hostovi=["testserver"], putanja_podesavanja=tmp_path / "p.json"))
    assert klijent.get("/api/stanje").json()["izvora"] == 0
    assert klijent.get("/api/pregled").json()["modeli"] == []

    sadrzaj = siroka_tabela(tmp_path / "senzori.csv").read_bytes()
    r = klijent.post("/api/izvori/predlog", content=sadrzaj,
                     headers={**IZMENA, "X-Fajl": "senzori.csv", "Content-Type": "application/octet-stream"})
    assert r.status_code == 200, r.text
    predlog = r.json()
    assert predlog["putanja"].startswith("data/ulaz/senzori/")

    r = klijent.post("/api/izvori", json={
        "putanja": predlog["putanja"], "model": "pumpa", "polja": {"vreme": "vreme"},
        "kolone": predlog["brojcane"], "istorijski": True, "redosled_datuma": "dm"}, headers=IZMENA)
    assert r.status_code == 200, r.text
    assert r.json()["izvestaj"]["novih_rezultata"] == 600  # 200 redova x 3 kolone

    p = klijent.get("/api/pregled").json()
    assert [m["model"] for m in p["modeli"]] == ["pumpa"]
    assert p["modeli"][0]["istorijski"] is True
    assert sorted(i["izvor"] for i in p["modeli"][0]["izvori"]) == ["Pritisak", "Protok", "Temperatura"]
    assert p["ukupno"]["kriticno"] == 0  # stari podaci: nema "model ćuti od januara"
    assert klijent.get("/api/izvori").json()[0]["model"] == "pumpa"

    # Isti model ne može dvaput; bez zaglavlja se ništa ne menja.
    assert klijent.post("/api/izvori", json={"putanja": predlog["putanja"], "model": "pumpa",
                                             "polja": {"vreme": "vreme"}, "kolone": ["Protok"]},
                        headers=IZMENA).status_code == 400
    assert klijent.delete("/api/izvori/pumpa").status_code == 403

    assert klijent.delete("/api/izvori/pumpa", headers=IZMENA).status_code == 200
    assert klijent.get("/api/pregled").json()["modeli"] == []
    assert klijent.get("/api/izvori").json() == []


def test_predlog_iz_putanje_na_racunaru(tmp_path):
    folder = tmp_path / "rezultati"
    folder.mkdir()
    siroka_tabela(folder / "a.csv")
    siroka_tabela(folder / "b.csv")
    k = Konfiguracija(izvori=[], baza=f"sqlite:///{tmp_path}/m.db")
    klijent = TestClient(napravi_aplikaciju(k, hostovi=["testserver"], putanja_podesavanja=tmp_path / "p.json"))
    r = klijent.post("/api/izvori/predlog", json={"putanja": str(folder)}, headers=IZMENA)
    assert r.status_code == 200, r.text
    assert r.json()["putanja"].endswith("*.csv")  # folder = svi CSV fajlovi u njemu
    assert r.json()["model"] == "rezultati"
    r = klijent.post("/api/izvori/predlog", json={"putanja": str(tmp_path / "nema.csv")}, headers=IZMENA)
    assert r.status_code == 400 and "Nema fajla" in r.json()["detail"]
