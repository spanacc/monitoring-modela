"""Probni podaci uživo (python -m app --demo) i dugme "Rešio sam"."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from app.alarmi.konfiguracija import Izvor, Konfiguracija
from app.baza import Baza
from app.dashboard.server import napravi_aplikaciju
from app.dodavanje import napusteni_modeli
from app.nadzor import jedan_krug
from app.schema import Rezultat
from simulator import uzivo

BG = ZoneInfo("Europe/Belgrade")


def test_dopuni_nastavlja_gde_je_stao(tmp_path):
    prvo = uzivo.dopuni(tmp_path, datetime(2026, 11, 2, 0, 0, tzinfo=BG))
    ceo = (tmp_path / "temperatura_peci.csv").read_text(encoding="utf-8")
    drugo = uzivo.dopuni(tmp_path, datetime(2026, 11, 2, 1, 0, tzinfo=BG))
    assert prvo > 0 and drugo == 6 * 3 + 1 + 4 * 2  # 6 temp. x 3 peći, 1 sat struje, 4 x 2 linije
    assert uzivo.dopuni(tmp_path, datetime(2026, 11, 2, 1, 0, tzinfo=BG)) == 0
    # Isto vreme uvek daje iste brojeve.
    uzivo.dopuni(tmp_path / "b", datetime(2026, 11, 2, 1, 0, tzinfo=BG))
    assert (tmp_path / "b" / "temperatura_peci.csv").read_text(encoding="utf-8").startswith(ceo)


def test_demo_nalazi_sve_ubacene_probleme(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    k = Konfiguracija(baza=f"sqlite:///{tmp_path / 'b.db'}", izvori=[])
    sada = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
    assert set(uzivo.ukljuci(k, tmp_path / "p.json", sada=sada)) == set(uzivo.MODELI)
    assert k.demo and len(k.izvori) == 3
    assert uzivo.dopuni(uzivo.FOLDER, sada) == 0  # sve je već dopisano
    jedan_krug(k, sada)
    from app.alarmi.evidencija import Evidencija
    nadjeno = {(a.tip, a.izvor) for a in Evidencija(baza=Baza(k.baza)).otvoreni()}
    assert {("izostanak", "Peć 2"), ("nemoguca_vrednost", "Peć 1"), ("drift", "Peć 3"),
            ("greska_modela", "glavni"), ("promasen_skok", "glavni"),
            ("pad_tacnosti", "Linija 2")} <= nadjeno

    uzivo.iskljuci(k, tmp_path / "p.json", Baza(k.baza))
    assert not k.izvori and not k.demo and not Baza(k.baza).modeli()


def test_napusteni_modeli(tmp_path):
    k = Konfiguracija(baza=f"sqlite:///{tmp_path / 'b.db'}",
                      izvori=[Izvor(putanja=tmp_path / "ulaz", model="novi")])
    b = Baza(k.baza)
    r = dict(vreme=datetime(2026, 11, 1, tzinfo=timezone.utc), izvor="x", velicina="v", vrednost=1)
    b.upisi_rezultate(str(tmp_path / "ulaz" / "a.csv"), [Rezultat(model="novi", **r)])
    b.upisi_rezultate(str(tmp_path / "staro" / "s.csv"), [Rezultat(model="stari", **r)])
    assert napusteni_modeli(k, b) == ["stari"]


def test_resio_sam_pamti_ko_i_sta(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    k = Konfiguracija(baza=f"sqlite:///{tmp_path / 'b.db'}", izvori=[])
    sada = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
    uzivo.ukljuci(k, tmp_path / "p.json", sada=sada)
    jedan_krug(k, sada)
    klijent = TestClient(napravi_aplikaciju(k, putanja_podesavanja=tmp_path / "p.json",
                                            hostovi=["testserver"]))
    zaglavlje = {"X-Dashboard": "1"}
    alarmi = klijent.get("/api/alarmi").json()
    prvi = next(a for a in alarmi if a["tip"] == "izostanak")
    odg = klijent.post(f"/api/alarmi/{prvi['id']}/resi", headers=zaglavlje,
                       json={"ko": "Veljko", "napomena": "Ponovo pokrenut prenos."})
    assert odg.status_code == 200
    a = odg.json()
    assert (a["status"], a["potvrdio"], a["napomena"]) == ("resen", "Veljko", "Ponovo pokrenut prenos.")
    # Bez zaglavlja (druga stranica na internetu) ne može.
    assert klijent.post(f"/api/alarmi/{prvi['id']}/resi", json={}).status_code == 403
    # Prošao problem ostaje zatvoren i u sledećem krugu.
    jedan_krug(k, sada)
    from app.alarmi.evidencija import Evidencija
    assert Evidencija(baza=Baza(k.baza)).nadji_po_id(prvi["id"]).status.value == "resen"


def test_problem_na_dugme(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    k = Konfiguracija(baza=f"sqlite:///{tmp_path / 'b.db'}", izvori=[])
    sada = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
    uzivo.ukljuci(k, tmp_path / "p.json", sada=sada)
    jedan_krug(k, sada)
    klijent = TestClient(napravi_aplikaciju(k, putanja_podesavanja=tmp_path / "p.json",
                                            hostovi=["testserver"], sada_po_podacima=True,
                                            izazovi_problem=lambda v: uzivo.izazovi(v, sada=sada)))
    zaglavlje = {"X-Dashboard": "1"}
    assert klijent.get("/api/stanje").json()["demo"] is True
    r = klijent.post("/api/demo/problem", headers=zaglavlje, json={"vrsta": "neobicna"}).json()
    assert r["izvestaj"]["novih_alarma"] == 1 and "9.999" in r["opis"]
    r = klijent.post("/api/demo/problem", headers=zaglavlje, json={"vrsta": "greska"}).json()
    assert r["izvestaj"]["novih_alarma"] == 1
    assert klijent.post("/api/demo/problem", headers=zaglavlje, json={"vrsta": "rm -rf"}).status_code == 422
    assert klijent.post("/api/demo/problem", json={"vrsta": "greska"}).status_code == 403


def test_bez_demoa_nema_dugmeta(tmp_path):
    k = Konfiguracija(baza=f"sqlite:///{tmp_path / 'b.db'}", izvori=[])
    klijent = TestClient(napravi_aplikaciju(k, hostovi=["testserver"]))
    assert klijent.get("/api/stanje").json()["demo"] is False
    assert klijent.post("/api/demo/problem", headers={"X-Dashboard": "1"},
                        json={"vrsta": "greska"}).status_code == 404


def test_bez_problema_od(tmp_path, monkeypatch):
    """Pregled kaže od kad nema problema, a dok je neki otvoren, ne kaže."""
    monkeypatch.chdir(tmp_path)
    k = Konfiguracija(baza=f"sqlite:///{tmp_path / 'b.db'}", izvori=[])
    sada = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
    uzivo.ukljuci(k, tmp_path / "p.json", sada=sada)
    klijent = TestClient(napravi_aplikaciju(k, putanja_podesavanja=tmp_path / "p.json",
                                            hostovi=["testserver"]))
    jedan_krug(k, sada)
    assert klijent.get("/api/pregled?dana=30").json()["mirno_od"] is None
    # Svi problemi rešeni: "bez problema" od kraja poslednjeg.
    for a in klijent.get("/api/alarmi").json():
        klijent.post(f"/api/alarmi/{a['id']}/resi", headers={"X-Dashboard": "1"}, json={"ko": "Test"})
    p = klijent.get("/api/pregled?dana=30").json()
    assert p["mirno_od"] is not None and p["mirno_od"] <= p["sada"]
