"""
Provere baze: šta se upiše, to se i pročita; upisuju se samo novi redovi;
vremena ostaju tačna; alarmi se čuvaju.
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.alarmi.evidencija import Evidencija, StatusAlarma
from app.baza import Baza
from app.provere import Nalaz, Ozbiljnost
from app.schema import Rezultat
from simulator.modeli import SVI_MODELI

T0 = datetime(2026, 11, 1, tzinfo=timezone.utc)
SAT = timedelta(hours=1)


@pytest.fixture
def baza(tmp_path):
    return Baza(f"sqlite:///{tmp_path}/test.db")


@pytest.mark.parametrize("naziv", list(SVI_MODELI))
def test_sta_se_upise_to_se_procita(baza, naziv):
    rez = SVI_MODELI[naziv](dani=5).rezultati
    assert baza.upisi_rezultate("fajl.csv", rez) == len(rez)
    assert baza.citaj_rezultate(naziv) == sorted(rez, key=lambda r: r.vreme)


def test_vreme_sa_zonom_ostaje_tacno(baza):
    # 14:00 po beogradskom vremenu je 13:00 UTC. SQLite sam po sebi bi to
    # pogrešno upisao kao 14:00 bez zone, zato baza sve pretvara u UTC.
    beograd = datetime(2026, 11, 10, 14, 0, tzinfo=ZoneInfo("Europe/Belgrade"))
    r = Rezultat(vreme=beograd, model="m", izvor="A", velicina="x", vrednost=1.0)
    baza.upisi_rezultate("f.csv", [r])
    (procitan,) = baza.citaj_rezultate("m")
    assert procitan.vreme == beograd  # isti trenutak
    assert procitan.vreme.hour == 13  # zapisan u UTC


def test_upisuju_se_samo_novi_redovi(baza):
    rez = SVI_MODELI["senzori"](dani=2).rezultati
    assert baza.upisi_rezultate("s.csv", rez[:100]) == 100
    assert baza.upisi_rezultate("s.csv", rez[:100]) == 0  # isti fajl ponovo: ništa novo
    assert baza.upisi_rezultate("s.csv", rez) == len(rez) - 100  # fajl je dopisan
    assert len(baza.citaj_rezultate("senzori")) == len(rez)


def test_duplikati_iz_fajla_se_cuvaju(baza):
    # Dva ista reda u fajlu su dva rezultata: provera duplikata mora da ih vidi.
    r = Rezultat(vreme=T0, model="m", izvor="A", velicina="x", vrednost=1.0)
    baza.upisi_rezultate("f.csv", [r, r.model_copy()])
    assert len(baza.citaj_rezultate("m")) == 2


def test_citanje_samo_normalnog_perioda_i_poslednjih_dana(baza):
    rez = [Rezultat(vreme=T0 + i * SAT, model="m", izvor="A", velicina="x", vrednost=float(i))
           for i in range(24 * 30)]  # 30 dana, na sat
    baza.upisi_rezultate("f.csv", rez)

    procitano = baza.citaj_rezultate("m", kraj_osnove=T0 + timedelta(days=7),
                                     pocetak=T0 + timedelta(days=20))
    # prvih 7 dana + poslednjih 10 dana, ono između se ne čita
    assert len(procitano) == 24 * 7 + 24 * 10
    assert baza.prvo_i_poslednje("m") == (T0, T0 + (24 * 30 - 1) * SAT)


def test_alarmi_se_cuvaju_u_bazi(baza):
    ev = Evidencija(baza=baza)
    ev.uskladi([Nalaz("izostanak", "m", "A", T0, T0 + 6 * SAT, Ozbiljnost.KRITICNO, "opis")], T0)
    ev.potvrdi(1, "Veljko", "proveravam")
    ev.sacuvaj()

    ponovo = Evidencija(baza=baza)
    assert ponovo.alarmi == ev.alarmi
    assert ponovo.alarmi[0].status == StatusAlarma.POTVRDJEN