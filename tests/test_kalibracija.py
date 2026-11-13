"""
Provere kalibracije: da granice zaista zavise od podataka, a ne od
brojeva upisanih u kod.

Najvažniji test je `test_isti_nalazi_bez_obzira_na_jedinice`: ako se sve
vrednosti pomnože sa 1000 (npr. kW umesto W), nalazi moraju biti potpuno
isti. Da su granice fiksni brojevi, to ne bi moglo da važi.
"""

import random
from datetime import datetime, timedelta, timezone

from app.provere import Podesavanja, proveri_sve
from app.provere.kalibracija import kalibrisi, opisi_granice
from app.schema import Rezultat
from simulator.modeli import simuliraj_senzore

T0 = datetime(2026, 11, 1, tzinfo=timezone.utc)


def serija(n=300, korak=timedelta(hours=1), skala=1.0, seed=1):
    rng = random.Random(seed)
    rezultati = []
    for i in range(n):
        stvarno = (50 + rng.gauss(0, 2)) * skala
        rezultati.append(Rezultat(
            vreme=T0 + i * korak, model="m", izvor="A", velicina="x",
            vrednost=stvarno + rng.gauss(0, 1) * skala, stvarna_vrednost=stvarno,
        ))
    return rezultati


def test_granica_za_izostanak_zavisi_od_ucestalosti():
    na_sat = kalibrisi(serija(korak=timedelta(hours=1)), Podesavanja())
    na_dan = kalibrisi(serija(korak=timedelta(days=1)), Podesavanja())
    assert na_sat.max_pauza == timedelta(hours=2)  # rezerva 2 x najduža pauza 1 h
    assert na_dan.max_pauza == timedelta(days=2)


def test_granice_rastu_sa_jedinicama():
    mala = kalibrisi(serija(skala=1), Podesavanja())
    velika = kalibrisi(serija(skala=1000), Podesavanja())
    odnos = velika.max_odskok_vrednosti / mala.max_odskok_vrednosti
    assert abs(odnos - 1000) < 1e-6


def test_isti_nalazi_bez_obzira_na_jedinice():
    # Simulator sa svih 7 ubačenih problema, pa iste vrednosti x 1000.
    rez = simuliraj_senzore(dani=30).rezultati
    puta_1000 = [
        r.model_copy(update={
            "vrednost": None if r.vrednost is None else r.vrednost * 1000,
            "stvarna_vrednost": None if r.stvarna_vrednost is None else r.stvarna_vrednost * 1000,
        })
        for r in rez
    ]

    def sazetak(nalazi):
        return [(n.tip, n.izvor, n.od, n.do) for n in nalazi]

    assert sazetak(proveri_sve(rez)) == sazetak(proveri_sve(puta_1000))
    assert len(proveri_sve(rez)) == 7


def test_rezerva_menja_osetljivost():
    # Nedostaju 2 rezultata: pauza je 3 h, a normalno je 1 h.
    rez = [r for i, r in enumerate(serija()) if i not in (200, 201)]
    osetljivo = proveri_sve(rez, Podesavanja(rezerva=2))
    manje_osetljivo = proveri_sve(rez, Podesavanja(rezerva=5))
    assert [n.tip for n in osetljivo] == ["izostanak"]  # 3 h > 2 x 1 h
    assert manje_osetljivo == []  # 3 h < 5 x 1 h


def test_premalo_podataka_ne_rusi_nista():
    # Sa samo 6 rezultata nema dovoljno za učenje većine granica:
    # te provere se preskaču, ali ništa ne puca.
    g = kalibrisi(serija(n=6), Podesavanja())
    assert g.max_odskok_vrednosti is None
    assert g.drift_dozvoljeno is None
    assert proveri_sve(serija(n=6)) == []


def test_jedan_rezultat_nema_granice():
    assert kalibrisi(serija(n=1), Podesavanja()) is None


def test_granice_se_mogu_opisati_recima():
    rez = serija()
    redovi = opisi_granice(rez, kalibrisi(rez, Podesavanja()))
    assert "rezultati obično stižu na svakih 1 h" in redovi
    assert "izostanak: pauza duža od 2 h" in redovi
    assert any(red.startswith("drift:") for red in redovi)


def test_fiksan_normalni_period_se_ne_pomera():
    # Sa `dana_osnove` normalni period je prvih N dana, ma koliko podataka
    # posle toga stiglo. Sa `udeo_osnove` bi se pomerao kako podaci rastu.
    p = Podesavanja(dana_osnove=5)
    kratko = kalibrisi(serija(n=300), p)
    dugo = kalibrisi(serija(n=900), p)
    assert kratko.kraj_osnove == dugo.kraj_osnove == T0 + timedelta(days=5)

    po_udelu_kratko = kalibrisi(serija(n=300), Podesavanja())
    po_udelu_dugo = kalibrisi(serija(n=900), Podesavanja())
    assert po_udelu_kratko.kraj_osnove < po_udelu_dugo.kraj_osnove
