"""
Provere simulatora: da pravi realne podatke i da su problemi zaista ubačeni.
"""

import csv
import json
from datetime import datetime

from simulator.modeli import (
    simuliraj_kvalitet,
    simuliraj_potrosnju,
    simuliraj_senzore,
)
from simulator.pokreni import KOLONE, sacuvaj_csv


def test_isto_seme_daje_iste_podatke():
    a = simuliraj_senzore(dani=5, seed=42).rezultati
    b = simuliraj_senzore(dani=5, seed=42).rezultati
    assert a == b


def test_senzori_imaju_ocekivan_broj_rezultata():
    sim = simuliraj_senzore(dani=30)
    # 5 mašina x 24 sata x 30 dana, minus 6 sati koji nedostaju za M2
    assert len(sim.rezultati) == 5 * 24 * 30 - 6


def test_senzori_sadrze_ubacene_probleme():
    sim = simuliraj_senzore(dani=30)
    r = sim.rezultati
    assert any(x.status.value == "greska" for x in r)
    assert any(x.vrednost == 9999.0 for x in r)
    assert any(x.izvor == "M4" and x.je_prazan and x.status.value == "ok" for x in r)

    # M3 stalno precenjuje: prosečna greška mora biti jasno pozitivna
    m3 = [x for x in r if x.izvor == "M3" and x.stvarna_vrednost is not None]
    prosek = sum(x.vrednost - x.stvarna_vrednost for x in m3) / len(m3)
    assert 4 < prosek < 6

    tipovi = {p.tip for p in sim.problemi}
    assert tipovi == {"greska_modela", "izostanak", "pristrasnost", "nemoguca_vrednost",
                      "prazne_vrednosti", "drift", "promasen_skok"}


def test_potrosnja_ima_duplikat_i_izostanak():
    sim = simuliraj_potrosnju(dani=30)
    kljucevi = [(x.izvor, x.vreme) for x in sim.rezultati]
    assert len(kljucevi) != len(set(kljucevi)), "treba da postoji duplikat"
    l2 = [x for x in sim.rezultati if x.izvor == "L2"]
    assert len(l2) == 30 - 3


def test_kvalitet_tacnost_pada_na_liniji_2():
    sim = simuliraj_kvalitet(dani=30)
    pad_od = datetime.fromisoformat(sim.problemi[0].od)

    def tacnost(rezultati):
        poznati = [x for x in rezultati if x.stvarna_kategorija is not None]
        return sum(x.kategorija == x.stvarna_kategorija for x in poznati) / len(poznati)

    pre = [x for x in sim.rezultati if x.izvor == "Linija-2" and x.vreme < pad_od]
    posle = [x for x in sim.rezultati if x.izvor == "Linija-2" and x.vreme >= pad_od]
    assert tacnost(pre) > 0.92
    assert tacnost(posle) < 0.80


def test_csv_se_cuva_i_cita(tmp_path):
    sim = simuliraj_senzore(dani=2)
    putanja = tmp_path / "senzori.csv"
    sacuvaj_csv(sim.rezultati, putanja)

    with putanja.open(encoding="utf-8") as f:
        redovi = list(csv.DictReader(f))
    assert len(redovi) == len(sim.rezultati)
    assert list(redovi[0].keys()) == KOLONE


def test_spisak_problema_je_ispravan_json():
    sim = simuliraj_senzore(dani=30)
    tekst = json.dumps(sim.problemi_kao_recnik(), ensure_ascii=False)
    assert "pristrasnost" in tekst