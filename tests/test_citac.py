"""
Provere učitavanja CSV fajlova.
"""

from datetime import timedelta

import pytest

from app.citac import ucitaj_csv
from app.prepoznavanje import Mapiranje
from app.schema import Status
from simulator.modeli import SVI_MODELI
from simulator.pokreni import sacuvaj_csv


def napisi(tmp_path, ime, tekst, kodiranje="utf-8"):
    putanja = tmp_path / ime
    putanja.write_text(tekst, encoding=kodiranje)
    return putanja


@pytest.mark.parametrize("naziv", list(SVI_MODELI))
def test_fajlovi_iz_simulatora_se_ucitavaju_bez_gubitka(tmp_path, naziv):
    # Najvažnija provera: šta simulator zapiše, čitač mora da pročita isto.
    sim = SVI_MODELI[naziv](dani=5)
    putanja = tmp_path / f"{naziv}.csv"
    sacuvaj_csv(sim.rezultati, putanja)

    ucitano = ucitaj_csv(putanja)

    assert ucitano.greske == []
    assert ucitano.rezultati == sim.rezultati


def test_fajl_iz_excela_sa_tackom_zarezom_i_decimalnim_zarezom(tmp_path):
    putanja = napisi(tmp_path, "pec_3.csv",
                     "Timestamp;Machine ID;Predicted Temp;Measured Temp\n"
                     "10.11.2026 14:00;Mašina 7;84,5;81,2\n"
                     "10.11.2026 15:00;Mašina 7;85,0;\n")

    ucitano = ucitaj_csv(putanja)
    prvi, drugi = ucitano.rezultati

    assert ucitano.greske == []
    assert prvi.model == "pec_3"  # ime fajla, jer model nije zadat
    assert prvi.izvor == "Mašina 7"
    assert prvi.velicina == "predicted_temp"
    assert prvi.vrednost == 84.5
    assert prvi.stvarna_vrednost == 81.2
    assert prvi.vreme.utcoffset() == timedelta(hours=1)  # beogradsko vreme
    assert drugi.stvarna_vrednost is None  # stvarna još nije poznata


def test_fajl_u_kodnoj_strani_1250(tmp_path):
    putanja = napisi(tmp_path, "stari.csv",
                     "vreme;mašina;vrednost\n10.11.2026 14:00;Čačak-2;12,5\n",
                     kodiranje="cp1250")
    ucitano = ucitaj_csv(putanja)
    assert ucitano.rezultati[0].izvor == "Čačak-2"


def test_neispravni_redovi_ne_ruse_ucitavanje(tmp_path):
    putanja = napisi(tmp_path, "m.csv",
                     "time,source,value\n"
                     "2026-11-10T14:00:00Z,A,1.5\n"
                     "juče,A,2.5\n"
                     "2026-11-10T16:00:00Z,A,mnogo\n"
                     "2026-11-10T17:00:00Z,A,\n")
    ucitano = ucitaj_csv(putanja)

    assert len(ucitano.rezultati) == 2  # prvi red i red sa praznom vrednošću
    assert ucitano.rezultati[1].je_prazan  # prazno nije greška
    assert [red for red, _ in ucitano.greske] == [3, 4]  # brojevi redova u fajlu
    assert "vreme" in ucitano.greske[0][1]


def test_bez_kolone_izvor_svi_dobijaju_isti_izvor(tmp_path):
    putanja = napisi(tmp_path, "m.csv", "time,value\n2026-11-10T14:00:00Z,1\n")
    assert ucitaj_csv(putanja).rezultati[0].izvor == "glavni"


def test_status_greske_se_prepoznaje(tmp_path):
    putanja = napisi(tmp_path, "m.csv",
                     "time,value,status\n"
                     "2026-11-10T14:00:00Z,12,ok\n"
                     "2026-11-10T15:00:00Z,,timeout\n")
    ok, greska = ucitaj_csv(putanja).rezultati
    assert ok.status == Status.OK
    assert greska.status == Status.GRESKA
    assert greska.poruka == "timeout"


def test_bez_kolone_vremena_javlja_jasnu_gresku(tmp_path):
    putanja = napisi(tmp_path, "m.csv", "source,value\nA,1\n")
    with pytest.raises(ValueError, match="vremenom"):
        ucitaj_csv(putanja)


def test_rucno_mapiranje_se_cuva_i_koristi(tmp_path):
    # Nazivi koje prepoznavanje ne zna: "kol1" i "kol2" su obe brojevi,
    # pa ne može da zna koja je prognoza a koja stvarna vrednost.
    putanja = napisi(tmp_path, "m.csv",
                     "t,kol1,kol2\n2026-11-10T14:00:00Z,10,11\n")
    m = ucitaj_csv(putanja).mapiranje
    assert m.polja["vrednost"] == "kol1"  # pogodio je prvu, a to nije tačno

    # Čovek ispravi mapiranje u JSON fajlu...
    m.polja["vrednost"] = "kol2"
    m.polja["stvarna_vrednost"] = "kol1"
    json_putanja = tmp_path / "mapiranje.json"
    m.sacuvaj(json_putanja)

    # ...i aplikacija ga od tada koristi.
    r = ucitaj_csv(putanja, mapiranje=Mapiranje.ucitaj(json_putanja)).rezultati[0]
    assert r.vrednost == 11
    assert r.stvarna_vrednost == 10