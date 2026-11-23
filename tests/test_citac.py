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
    assert m.polja["vrednost"] == "kol2"  # pogodio je poslednju, a to nije tačno

    # Čovek ispravi mapiranje u JSON fajlu...
    m.polja["vrednost"] = "kol1"
    m.polja["stvarna_vrednost"] = "kol2"
    json_putanja = tmp_path / "mapiranje.json"
    m.sacuvaj(json_putanja)

    # ...i aplikacija ga od tada koristi.
    r = ucitaj_csv(putanja, mapiranje=Mapiranje.ucitaj(json_putanja)).rezultati[0]
    assert r.vrednost == 10
    assert r.stvarna_vrednost == 11


# --- široka tabela: svaka kolona je poseban izvor (korak 6b) ---


def test_siroka_tabela_svaka_kolona_je_izvor(tmp_path):
    putanja = napisi(tmp_path, "pumpa.csv",
                     "datetime;Pritisak;Protok;Temperatura\n"
                     "2026-11-10 14:00:00;1,2;32,0;70,1\n"
                     "2026-11-10 14:00:01;1,3;31,9;70,2\n")
    ucitano = ucitaj_csv(putanja, kolone=["Pritisak", "Protok"])
    assert len(ucitano.rezultati) == 4  # 2 reda x 2 kolone
    assert {r.izvor for r in ucitano.rezultati} == {"Pritisak", "Protok"}
    assert [r.vrednost for r in ucitano.rezultati if r.izvor == "Protok"] == [32.0, 31.9]


def test_siroka_tabela_sve_brojcane_kolone(tmp_path):
    putanja = napisi(tmp_path, "pumpa.csv",
                     "vreme,A,B,napomena\n2026-11-10 14:00,1,2,ok\n2026-11-10 14:01,3,4,ok\n")
    izvori = {r.izvor for r in ucitaj_csv(putanja, kolone=["sve"]).rezultati}
    assert izvori == {"A", "B"}  # "napomena" nije broj, a vreme se ne računa


def test_siroka_tabela_sa_pogresnom_kolonom(tmp_path):
    putanja = napisi(tmp_path, "pumpa.csv", "vreme,A\n2026-11-10 14:00,1\n")
    with pytest.raises(ValueError, match="nema kolona: Protok"):
        ucitaj_csv(putanja, kolone=["Protok"])


# --- korak 7 ---


def test_datum_i_sat_se_spajaju(tmp_path):
    putanja = napisi(tmp_path, "sati.csv",
                     "dteday,hr,cnt\n" + "".join(f"2011-01-01,{h},{10 + h}\n" for h in range(24))
                     + "".join(f"2011-01-02,{h},{20 + h}\n" for h in range(24)))
    u = ucitaj_csv(putanja)
    assert u.mapiranje.polja["doba_dana"] == "hr"
    assert len({r.vreme for r in u.rezultati}) == 48  # svaki sat je svoj trenutak
    assert u.rezultati[13].vreme.hour == 13


def test_samo_godina_kao_vreme_kad_je_kolona_rucno_izabrana(tmp_path):
    putanja = napisi(tmp_path, "g.csv", "year,pred\n2007,1.5\n2008,1.7\n2009,1.9\n")
    m = Mapiranje(polja={"vreme": "year", "vrednost": "pred"})
    u = ucitaj_csv(putanja, mapiranje=m)
    assert [r.vreme.year for r in u.rezultati] == [2007, 2008, 2009] and not u.greske
