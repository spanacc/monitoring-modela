"""
Provere svake provere posebno, na malim ručno napravljenim primerima.

Za svaku proveru testiramo dve stvari:
1. da PRONALAZI problem kad on postoji,
2. da NE diže uzbunu kad problema nema, i da ne prijavljuje tuđe
   probleme (npr. nemoguća vrednost ne sme biti prijavljena i kao skok).
"""

import random
from datetime import datetime, timedelta, timezone

from app.provere import Ozbiljnost, proveri_sve
from app.provere.osnova import trajanje, u_intervale
from app.schema import Rezultat, Status

T0 = datetime(2026, 11, 1, tzinfo=timezone.utc)
SAT = timedelta(hours=1)


def serija(n=300, pomak=0.0, seed=1):
    """
    Pravi `n` mirnih rezultata, jedan na sat: stvarna vrednost oko 50,
    model greši malo i nasumično. `pomak` dodaje stalnu grešku modelu.
    Testovi posle toga ručno pokvare ono što proveravaju.
    """
    rng = random.Random(seed)
    rezultati = []
    for i in range(n):
        stvarno = 50 + rng.gauss(0, 2)
        rezultati.append(Rezultat(
            vreme=T0 + i * SAT, model="m", izvor="A", velicina="x",
            vrednost=stvarno + pomak + rng.gauss(0, 1), stvarna_vrednost=stvarno,
        ))
    return rezultati


def tipovi(nalazi):
    return sorted(n.tip for n in nalazi)


# --- pomoćne funkcije ---

def test_u_intervale_spaja_uzastopna_vremena():
    vremena = [T0, T0 + SAT, T0 + 2 * SAT, T0 + 6 * SAT]
    assert u_intervale(vremena, SAT) == [(T0, T0 + 3 * SAT), (T0 + 6 * SAT, T0 + 7 * SAT)]


def test_trajanje():
    assert trajanje(timedelta(minutes=15)) == "15 min"
    assert trajanje(timedelta(hours=6)) == "6 h"
    assert trajanje(timedelta(days=3)) == "3 dana"
    assert trajanje(timedelta(seconds=2)) == "2 s"  # merenja svake sekunde (korak 6b)
    assert trajanje(timedelta(seconds=2.5)) == "2.5 s"


# --- nema problema -> nema nalaza ---

def test_mirni_podaci_nemaju_nalaza():
    assert proveri_sve(serija()) == []


# --- dostupnost ---

def test_izostanak_u_sredini():
    rez = [r for i, r in enumerate(serija()) if not 100 <= i < 110]
    (nalaz,) = proveri_sve(rez)
    assert nalaz.tip == "izostanak"
    assert (nalaz.od, nalaz.do) == (T0 + 100 * SAT, T0 + 110 * SAT)
    assert nalaz.ozbiljnost == Ozbiljnost.KRITICNO
    assert "10 h" in nalaz.opis


def test_tisina_na_kraju():
    rez = serija()
    sada = rez[-1].vreme + 10 * SAT  # model ćuti već 10 sati
    assert tipovi(proveri_sve(rez, sada=sada)) == ["izostanak"]


def test_duplikat():
    rez = serija()
    rez.append(rez[50].model_copy())
    assert tipovi(proveri_sve(rez)) == ["duplikat"]


def test_greska_modela_nije_prijavljena_i_kao_prazna_vrednost():
    rez = serija()
    rez[80] = rez[80].model_copy(update={"vrednost": None, "status": Status.GRESKA,
                                         "poruka": "timeout"})
    (nalaz,) = proveri_sve(rez)
    assert nalaz.tip == "greska_modela"
    assert "timeout" in nalaz.opis


# --- kvalitet ---

def test_prazne_vrednosti():
    rez = serija()
    for i in range(120, 126):
        rez[i] = rez[i].model_copy(update={"vrednost": None})
    (nalaz,) = proveri_sve(rez)
    assert nalaz.tip == "prazne_vrednosti"
    assert (nalaz.od, nalaz.do) == (T0 + 120 * SAT, T0 + 126 * SAT)


def test_nemoguca_vrednost_nije_prijavljena_i_kao_skok():
    rez = serija()
    rez[200] = rez[200].model_copy(update={"vrednost": 9999.0})
    assert tipovi(proveri_sve(rez)) == ["nemoguca_vrednost"]


# --- tačnost ---

def test_pristrasnost():
    # Model stalno predviđa 5 više. To je pristrasnost, a ne drift ni skok.
    assert tipovi(proveri_sve(serija(pomak=5))) == ["pristrasnost"]


def test_drift_sa_stvarnim_vrednostima():
    rez = serija()
    for i in range(150, 300):  # od polovine greška polako raste do +10
        r = rez[i]
        rez[i] = r.model_copy(update={"vrednost": r.vrednost + (i - 150) / 15})
    nalazi = proveri_sve(rez)
    assert tipovi(nalazi) == ["drift"]
    # Prijavljen je oko početka promene (u prozoru od jednog dana), ne ranije.
    assert nalazi[0].od > T0 + 120 * SAT


def test_drift_bez_stvarnih_vrednosti():
    rez = [r.model_copy(update={"stvarna_vrednost": None}) for r in serija()]
    for i in range(150, 300):
        rez[i] = rez[i].model_copy(update={"vrednost": rez[i].vrednost + 15})
    nalazi = proveri_sve(rez)
    assert tipovi(nalazi) == ["drift"]
    assert "Stvarne vrednosti nisu poznate" in nalazi[0].opis


def test_promasen_skok_nije_prijavljen_kao_drift():
    rez = serija()
    for i in (200, 201, 202):  # stvarnost je skočila za 20, model nije video
        rez[i] = rez[i].model_copy(update={"stvarna_vrednost": rez[i].stvarna_vrednost + 20})
    (nalaz,) = proveri_sve(rez)
    assert nalaz.tip == "promasen_skok"
    assert (nalaz.od, nalaz.do) == (T0 + 200 * SAT, T0 + 203 * SAT)


def test_pad_tacnosti_za_kategorije():
    rng = random.Random(5)
    rez = []
    for i in range(3000):
        stvarno = "ok" if rng.random() > 0.1 else "kvar"
        tacnost = 0.95 if i < 2000 else 0.70  # model se pokvari posle 2000. rezultata
        predvidjeno = stvarno if rng.random() < tacnost else ("kvar" if stvarno == "ok" else "ok")
        rez.append(Rezultat(vreme=T0 + i * timedelta(minutes=15), model="m", izvor="A",
                            velicina="stanje", kategorija=predvidjeno,
                            stvarna_kategorija=stvarno))
    nalazi = proveri_sve(rez)
    assert tipovi(nalazi) == ["pad_tacnosti"]
    assert nalazi[0].opis.startswith("Tačnost je pala")


# --- korak 7: kategorije bez stvarnih vrednosti ---


def kategorije(n=600, seed=3):
    """Model vraća 'ispravno' u 90% i 'kvar' u 10% slučajeva, bez stvarnih odgovora."""
    rng = random.Random(seed)
    return [Rezultat(vreme=T0 + i * SAT, model="m", izvor="L1", velicina="stanje",
                     kategorija="kvar" if rng.random() < 0.1 else "ispravno")
            for i in range(n)]


def test_promena_odgovora_bez_stvarnih_vrednosti():
    rez = kategorije()
    # Poslednjih 5 dana model skoro uvek kaže "kvar".
    for r in rez[-120:]:
        r.kategorija = "kvar"
    nalazi = proveri_sve(rez)
    assert tipovi(nalazi) == ["promena_kategorija"]
    assert "'kvar'" in nalazi[0].opis and "normalnom periodu" in nalazi[0].opis


def test_mirne_kategorije_nemaju_nalaza():
    assert proveri_sve(kategorije()) == []


def test_lep_broj():
    from app.provere.osnova import lep_broj
    assert lep_broj(4940) == "4.940"
    assert lep_broj(63.46) == "63,5"
    assert lep_broj(0.00123) == "0,00123"
    assert lep_broj(22.0) == "22"
    assert lep_broj(-3.25, "°C") == "−3,25 °C"
