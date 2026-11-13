"""
Provere celog kruga nadzora: učitaj -> proveri -> alarmi -> obaveštenja.
"""

import json

import pytest

from app.alarmi.evidencija import Evidencija
from app.alarmi.konfiguracija import Konfiguracija, ucitaj_konfiguraciju
from app.baza import Baza
from app.nadzor import jedan_krug
from simulator.modeli import SVI_MODELI
from simulator.pokreni import sacuvaj_csv


@pytest.fixture
def podesavanja(tmp_path):
    """Simulirani podaci i konfiguracija sa ekranom i dnevnikom, u privremenom folderu."""
    izvori = []
    for i, (naziv, simuliraj) in enumerate(SVI_MODELI.items()):
        putanja = tmp_path / f"{naziv}.csv"
        sacuvaj_csv(simuliraj(dani=30, seed=i + 1).rezultati, putanja)
        izvori.append({"putanja": str(putanja)})
    return {
        "izvori": izvori,
        "baza": f"sqlite:///{tmp_path}/monitoring.db",
        "kanali": {
            "ekran": {"tip": "ekran"},
            "dnevnik": {"tip": "dnevnik", "putanja": str(tmp_path / "obavestenja.log")},
        },
        "slanje": {"info": ["dnevnik"], "upozorenje": ["dnevnik"], "kriticno": ["ekran", "dnevnik"]},
    }


def test_prvi_krug_javlja_sve_drugi_nista(podesavanja, capsys):
    k = Konfiguracija.model_validate(podesavanja)

    prvi = jedan_krug(k)
    assert prvi.novih_alarma == 10
    assert prvi.poslato == {"dnevnik": 10, "ekran": 3}  # 3 kritična idu i na ekran
    assert prvi.greske == []
    assert "3 alarma iz monitoringa modela" in capsys.readouterr().out  # jedna poruka

    drugi = jedan_krug(k)
    assert drugi.novih_rezultata == 0  # fajlovi se nisu menjali
    assert drugi.novih_alarma == 0
    assert drugi.poslato == {}  # isti problemi, ništa se ne šalje ponovo


def test_posebna_osetljivost_vazi_samo_za_taj_model(podesavanja):
    # Ogromna rezerva samo za senzore: kod senzora nestaju izostanak i drift
    # (njihove granice zavise od rezerve), a potrošnja se ne menja.
    podesavanja["modeli"] = {"senzori": {"rezerva": 1000}}
    k = Konfiguracija.model_validate(podesavanja)
    jedan_krug(k)
    alarmi = Evidencija(baza=Baza(k.baza)).alarmi
    senzori = {a.tip for a in alarmi if a.model == "senzori"}
    potrosnja = {a.tip for a in alarmi if a.model == "potrosnja"}
    assert "izostanak" not in senzori and "drift" not in senzori
    assert potrosnja == {"izostanak", "duplikat"}


def test_kanal_koji_ne_radi_ne_zaustavlja_nadzor(podesavanja, monkeypatch):
    podesavanja["kanali"]["poruka"] = {"tip": "poruka", "adresa_iz": "TEST_WEBHOOK"}
    podesavanja["slanje"]["kriticno"] = ["dnevnik", "poruka"]
    monkeypatch.delenv("TEST_WEBHOOK", raising=False)  # adresa nije postavljena
    k = Konfiguracija.model_validate(podesavanja)

    prvi = jedan_krug(k)
    assert any("TEST_WEBHOOK" in g for g in prvi.greske)  # jasna greška
    assert prvi.poslato["dnevnik"] == 10  # ostalo je ipak poslato
    cekaju = [a for a in Evidencija(baza=Baza(k.baza)).alarmi if a.za_slanje]
    assert len(cekaju) == 3  # kritični čekaju sledeći pokušaj

    # Adresa je u međuvremenu ispravljena, ali na nju niko ne sluša: opet greška,
    # i alarmi i dalje čekaju. Tek kad slanje uspe, prestaju da čekaju.
    monkeypatch.setenv("TEST_WEBHOOK", "http://127.0.0.1:9/")
    drugi = jedan_krug(k)
    assert drugi.greske and len([a for a in Evidencija(baza=Baza(k.baza)).alarmi if a.za_slanje]) == 3


def test_izvor_koji_ne_postoji_ne_zaustavlja_ostale(podesavanja):
    podesavanja["izvori"].append({"putanja": "nema/ovog/fajla.csv"})
    iz = jedan_krug(Konfiguracija.model_validate(podesavanja))
    assert iz.novih_alarma == 10
    assert any("nema/ovog/fajla.csv" in g for g in iz.greske)


def test_greske_u_konfiguraciji_su_jasne(tmp_path, podesavanja):
    podesavanja["slanje"]["kriticno"] = ["telefon"]
    podesavanja["kanali"]["ekran"]["boja"] = "crvena"
    putanja = tmp_path / "k.json"
    putanja.write_text(json.dumps(podesavanja), encoding="utf-8")

    with pytest.raises(ValueError) as greska:
        ucitaj_konfiguraciju(putanja)
    assert "kanali.ekran.boja: nepoznato polje" in str(greska.value)


def test_primer_konfiguracije_je_ispravan():
    k = ucitaj_konfiguraciju("konfiguracija.primer.json")
    assert k.podesavanja_za("potrosnja").rezerva == 3.0
    assert k.podesavanja_za("senzori").rezerva == 2.0


def test_istorija_ostaje_u_bazi_i_kad_fajl_nestane(podesavanja, tmp_path):
    k = Konfiguracija.model_validate(podesavanja)
    prvi = jedan_krug(k)
    (tmp_path / "senzori.csv").unlink()  # model je obrisao svoj fajl

    drugi = jedan_krug(k)
    assert any("senzori.csv" in g for g in drugi.greske)  # javlja da fajla nema
    assert drugi.provereno == prvi.provereno  # ali svi rezultati su i dalje u bazi
    assert drugi.novih_alarma == 0


def test_proverava_se_samo_poslednjih_n_dana(podesavanja):
    # Simulirano je 30 dana. Sa proverom poslednjih 10 dana ostaju samo
    # problemi iz tog perioda, plus pristrasnost, koja traje od početka.
    podesavanja["dana_provere"] = 10
    podesavanja["provere"] = {"dana_osnove": 7}
    k = Konfiguracija.model_validate(podesavanja)
    jedan_krug(k)
    tipovi = {(a.izvor, a.tip) for a in Evidencija(baza=Baza(k.baza)).alarmi}
    assert tipovi == {("M3", "pristrasnost"), ("M4", "prazne_vrednosti"), ("M5", "drift"),
                      ("M1", "promasen_skok"), ("Linija-2", "pad_tacnosti")}