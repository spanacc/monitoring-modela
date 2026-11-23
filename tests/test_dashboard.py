"""
Provere dashboarda: da li server daje tačne podatke i da li je zaštićen.

Stranica u pregledaču se ovde ne otvara. Proverava se ono što ona dobija
od servera (adrese /api/...), preko "probnog klijenta" iz FastAPI-ja,
koji glumi pregledač bez pravog pokretanja servera.
"""

import random

import pytest
from fastapi.testclient import TestClient

from app.alarmi.evidencija import Evidencija
from app.alarmi.konfiguracija import Konfiguracija
from app.baza import Baza
from app.dashboard import podaci
from app.dashboard.server import napravi_aplikaciju
from app.nadzor import jedan_krug
from app.provere.kalibracija import kalibrisi
from app.provere.osnova import po_serijama
from simulator.modeli import SVI_MODELI
from simulator.pokreni import sacuvaj_csv

IZMENA = {"X-Dashboard": "1"}  # zaglavlje koje šalje stranica dashboarda


@pytest.fixture
def k(tmp_path):
    """Simulirani podaci, provereni jednim krugom nadzora, u privremenom folderu."""
    izvori = []
    for i, (naziv, simuliraj) in enumerate(SVI_MODELI.items()):
        putanja = tmp_path / f"{naziv}.csv"
        sacuvaj_csv(simuliraj(dani=30, seed=i + 1).rezultati, putanja)
        izvori.append({"putanja": str(putanja)})
    konfiguracija = Konfiguracija.model_validate({
        "izvori": izvori,
        "baza": f"sqlite:///{tmp_path}/monitoring.db",
        "provere": {"dana_osnove": 7},
        "kanali": {"dnevnik": {"tip": "dnevnik", "putanja": str(tmp_path / "obavestenja.log")}},
        "slanje": {"info": ["dnevnik"], "upozorenje": ["dnevnik"], "kriticno": ["dnevnik"]},
    })
    jedan_krug(konfiguracija)
    return konfiguracija


@pytest.fixture
def klijent(k):
    return TestClient(napravi_aplikaciju(k, sada_po_podacima=True, hostovi=["testserver"]))


def izvor(pregled, model, ime):
    m = next(m for m in pregled["modeli"] if m["model"] == model)
    return next(i for i in m["izvori"] if i["izvor"] == ime)


# --- pregled ---


def test_pregled_pokazuje_sve_izvore_i_njihovo_stanje(klijent):
    p = klijent.get("/api/pregled?dana=30").json()
    assert [m["model"] for m in p["modeli"]] == ["kvalitet", "potrosnja", "senzori"]
    assert p["ukupno"]["izvora"] == 10
    assert p["ukupno"] == {"info": 1, "upozorenje": 6, "kriticno": 3, "nepotvrdjeno": 10,
                           "izvora": 10, "modela": 3}
    assert izvor(p, "senzori", "M1")["stanje"] == "kriticno"  # greška modela + promašen skok
    assert izvor(p, "senzori", "M3")["stanje"] == "upozorenje"  # pristrasnost
    assert izvor(p, "potrosnja", "L1")["stanje"] == "ok"
    assert izvor(p, "potrosnja", "L3")["stanje"] == "info"  # duplikat
    assert p["najhitniji"]["ozbiljnost"] == "kriticno"


def test_izvori_su_u_prirodnom_redosledu(klijent):
    p = klijent.get("/api/pregled").json()
    senzori = next(m for m in p["modeli"] if m["model"] == "senzori")
    assert [i["izvor"] for i in senzori["izvori"]] == ["M1", "M2", "M3", "M4", "M5"]
    assert podaci.prirodno("M2") < podaci.prirodno("M10")  # a ne "M10" pre "M2"


# --- jedan izvor ---


def test_serija_oznacava_nemoguce_i_prazne_vrednosti(klijent):
    s = klijent.get("/api/serija", params={"model": "senzori", "izvor": "M4"}).json()
    assert s["vrsta"] == "broj" and s["jedinica"] == "°C"
    oznake = [t[3] for t in s["tacke"]]
    assert oznake.count(podaci.VAN_OPSEGA) == 1  # 9999, crta se iznad skale
    assert oznake.count(podaci.PRAZNO) == 6  # šest praznih rezultata
    van = next(t for t in s["tacke"] if t[3] == podaci.VAN_OPSEGA)
    assert van[1] == 9999.0
    assert {a["tip"] for a in s["alarmi"]} == {"nemoguca_vrednost", "prazne_vrednosti"}
    assert s["normalni_period"]["do"] > s["normalni_period"]["od"]


def test_dnevni_grafikon_ima_iste_granice_kao_nadzor(k, klijent):
    # Granica na grafikonu mora biti baš ona po kojoj nadzor diže alarm.
    s = klijent.get("/api/serija", params={"model": "senzori", "izvor": "M5"}).json()
    rezultati = Baza(k.baza).citaj_rezultate("senzori")
    serija = next(v for kljuc, v in po_serijama(rezultati).items() if kljuc[1] == "M5")
    g = kalibrisi(serija, k.podesavanja_za("senzori"))
    assert s["dnevno"]["naziv"] == "Tipična greška po danu"
    assert s["dnevno"]["normalno"] == pytest.approx(g.drift_sredina)
    assert s["dnevno"]["gore"] == pytest.approx(g.drift_sredina + g.drift_dozvoljeno)
    # Drift: poslednji dani su iznad granice, a prvi nisu.
    dani = s["dnevno"]["dani"]
    assert dani[-2][2] > s["dnevno"]["gore"]
    assert dani[1][2] < s["dnevno"]["gore"]


def test_serija_za_kategorije(klijent):
    s = klijent.get("/api/serija", params={"model": "kvalitet", "izvor": "Linija-2"}).json()
    assert s["vrsta"] == "kategorija" and "tacke" not in s
    assert set(s["kategorije"]["imena"]) == {"ispravno", "neispravno"}
    dn = s["dnevno"]
    assert dn["naziv"] == "Tačnost po danu" and dn["procenat"]
    assert dn["dole"] < dn["normalno"] <= 1  # granica je ispod normalne tačnosti
    assert [a["tip"] for a in s["alarmi"]] == ["pad_tacnosti"]


def test_pokazatelji_govore_srpski(klijent):
    s = klijent.get("/api/serija", params={"model": "senzori", "izvor": "M3"}).json()
    pok = {p["naziv"]: p for p in s["pokazatelji"]}
    assert pok["Prosečna greška"]["vrednost"].startswith("+5,")  # decimalni zarez
    assert pok["Prosečna greška"]["opis"] == "model uglavnom daje više"
    assert any("normalni period" in red for red in s["naucene_granice"])


def test_nepostojeci_izvor(klijent):
    odgovor = klijent.get("/api/serija", params={"model": "senzori", "izvor": "M99"})
    assert odgovor.status_code == 404


# --- alarmi ---


def test_potvrda_i_resavanje_iz_dashboarda(k, klijent):
    broj = klijent.get("/api/pregled").json()["najhitniji"]["id"]
    verzija_pre = klijent.get("/api/stanje").json()["verzija"]

    a = klijent.post(f"/api/alarmi/{broj}/potvrdi", json={"ko": "Veljko", "napomena": "gledam"},
                     headers=IZMENA).json()
    assert a["status"] == "potvrdjen" and a["potvrdio"] == "Veljko"
    assert klijent.get("/api/stanje").json()["verzija"] != verzija_pre  # stranica će osvežiti

    klijent.post(f"/api/alarmi/{broj}/resi", json={"napomena": "zamenjen senzor"}, headers=IZMENA)
    upisano = Evidencija(baza=Baza(k.baza)).nadji_po_id(broj)
    assert upisano.status.value == "resen" and upisano.napomena == "zamenjen senzor"
    assert broj not in [x["id"] for x in klijent.get("/api/alarmi").json()]  # samo nerešeni
    assert broj in [x["id"] for x in klijent.get("/api/alarmi?svi=true").json()]


def test_ime_je_obavezno_pri_potvrdi(klijent):
    odgovor = klijent.post("/api/alarmi/1/potvrdi", json={"ko": "   "}, headers=IZMENA)
    assert odgovor.status_code == 422


def test_nepostojeci_alarm(klijent):
    odgovor = klijent.post("/api/alarmi/999/resi", json={}, headers=IZMENA)
    assert odgovor.status_code == 404


def test_proveri_sada_ne_pravi_duple_alarme(klijent):
    iz = klijent.post("/api/nadzor", json={}, headers=IZMENA).json()
    assert iz["novih_rezultata"] == 0 and iz["novih_alarma"] == 0


# --- bezbednost ---


def test_izmena_bez_zaglavlja_se_odbija(k, klijent):
    # Ovako bi izgledao napad sa tuđe stranice (CSRF): zahtev bez našeg zaglavlja.
    odgovor = klijent.post("/api/alarmi/1/resi", json={})
    assert odgovor.status_code == 403
    assert Evidencija(baza=Baza(k.baza)).nadji_po_id(1).status.value == "otvoren"


def test_nepoznato_ime_servera_se_odbija(k):
    # Zaštita od "DNS rebinding": prihvataju se samo zahtevi za ovaj računar.
    klijent = TestClient(napravi_aplikaciju(k, hostovi=["127.0.0.1", "localhost"]))
    assert klijent.get("/api/stanje", headers={"Host": "napadac.com"}).status_code == 400
    assert klijent.get("/api/stanje", headers={"Host": "127.0.0.1:8000"}).status_code == 200


def test_bezbednosna_zaglavlja(klijent):
    for adresa in ["/", "/api/pregled"]:
        z = klijent.get(adresa).headers
        assert "default-src 'self'" in z["content-security-policy"]
        assert z["x-content-type-options"] == "nosniff"
        assert z["x-frame-options"] == "DENY"
    assert klijent.get("/api/pregled").headers["cache-control"] == "no-store"


def test_stranica_se_ucitava_bez_interneta(klijent):
    html = klijent.get("/").text
    assert "Monitoring modela" in html
    assert "http" not in html.replace('content="width', "")  # nijedna spoljna adresa
    assert klijent.get("/pregled.js").status_code == 200
    assert klijent.get("/podesavanja.html").status_code == 200
    assert klijent.get("/stil.css").status_code == 200


# --- prazna baza i brzina ---


def test_prazna_baza(tmp_path):
    k = Konfiguracija.model_validate({"izvori": [], "baza": f"sqlite:///{tmp_path}/prazna.db"})
    klijent = TestClient(napravi_aplikaciju(k, sada_po_podacima=True, hostovi=["testserver"]))
    p = klijent.get("/api/pregled").json()
    assert p["modeli"] == [] and p["najhitniji"] is None
    assert klijent.get("/api/alarmi").json() == []


def test_proredjivanje_cuva_skokove():
    # 100.000 tačaka postane najviše 1500, ali skok i nemoguća vrednost ostaju.
    tacke = [[i, float(i % 50), None, podaci.OBICNA] for i in range(100_000)]
    tacke[54_321][1] = 500.0  # nagli skok
    tacke[77_777] = [77_777, 9999.0, None, podaci.VAN_OPSEGA]
    proredjene, grupa = podaci.proredi(tacke, 1500)
    assert len(proredjene) <= 1500 and grupa > 1
    assert max(t[1] for t in proredjene) == 9999.0
    assert any(t[1] == 500.0 for t in proredjene)
    assert [t[0] for t in proredjene] == sorted(t[0] for t in proredjene)


def test_srpski_brojevi():
    assert podaci.sr_broj(1234.6) == "1.235"
    assert podaci.sr_broj(63.46) == "63,5"
    assert podaci.sr_broj(-12.94) == "\u221212,9"
    assert podaci.sr_broj(-0.01, znak=True, kao=2.0) == "0,0"  # bez "-0,0"
    assert podaci.ceo_broj(2880) == "2.880"


# --- česta merenja i široke tabele (korak 6b) ---


def merenja_svake_sekunde(tmp_path, rupa=None):
    """Sat vremena merenja svake sekunde, dva senzora u kolonama. `rupa`: sekunde bez podataka."""
    rng = random.Random(5)
    redovi = ["vreme;A;B"]
    for i in range(3600):
        if rupa and rupa[0] <= i < rupa[1]:
            continue
        redovi.append(f"2026-11-10 10:{i // 60:02d}:{i % 60:02d};{50 + rng.gauss(0, 1):.3f};"
                      f"{20 + rng.gauss(0, 1):.3f}")
    putanja = tmp_path / "pumpa.csv"
    putanja.write_text("\n".join(redovi), encoding="utf-8")
    k = Konfiguracija.model_validate({
        "izvori": [{"putanja": str(putanja), "model": "pumpa", "kolone": ["A", "B"]}],
        "baza": f"sqlite:///{tmp_path}/m.db",
        "slanje": {"info": [], "upozorenje": [], "kriticno": []},
    })
    jedan_krug(k)
    return TestClient(napravi_aplikaciju(k, sada_po_podacima=True, hostovi=["testserver"]))


def test_kratki_podaci_se_prikazuju_ceo_period(tmp_path):
    # Sat vremena podataka: prikaz počinje od prvog rezultata, a ne 30 dana
    # unazad, a "dnevni" grafikon ide po prozorima, jer bi dan bio besmislen.
    klijent = merenja_svake_sekunde(tmp_path)
    p = klijent.get("/api/pregled?dana=30").json()
    assert p["od"] == izvor(p, "pumpa", "A")["prvo"]
    s = klijent.get("/api/serija", params={"model": "pumpa", "izvor": "A"}).json()
    assert s["korak_s"] == 1
    assert s["dnevno"]["po_prozoru"] and "po prozoru od" in s["dnevno"]["naziv"]
    assert len(s["tacke"]) <= podaci.NAJVISE_TACAKA


def test_isti_problem_na_vise_izvora_se_broji_jednom(tmp_path):
    # Oba senzora su ućutala isti minut: to je jedan problem, a ne dva.
    klijent = merenja_svake_sekunde(tmp_path, rupa=(1800, 1860))
    p = klijent.get("/api/pregled").json()
    assert p["ukupno"]["kriticno"] == 1
    assert p["najhitniji"]["tip"] == "izostanak" and p["najhitniji_izvora"] == 2
    izostanci = [a for a in klijent.get("/api/alarmi").json() if a["tip"] == "izostanak"]
    assert len(izostanci) == 2  # alarm i dalje postoji za svaki izvor
