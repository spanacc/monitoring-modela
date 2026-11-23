"""
Provere evidencije alarma: jedan problem = jedan alarm, bez ponavljanja.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.alarmi.evidencija import Evidencija, StatusAlarma
from app.provere import Nalaz, Ozbiljnost

T0 = datetime(2026, 11, 1, tzinfo=timezone.utc)
SAT = timedelta(hours=1)


def nalaz(od=0, do=6, tip="izostanak", izvor="A", ozbiljnost=Ozbiljnost.UPOZORENJE):
    return Nalaz(tip, "m", izvor, T0 + od * SAT, T0 + do * SAT, ozbiljnost, "opis")


@pytest.fixture
def ev(tmp_path):
    return Evidencija(tmp_path / "alarmi.json")


def test_nov_nalaz_postaje_alarm(ev):
    novi = ev.uskladi([nalaz()], T0)
    assert len(novi) == 1
    assert novi[0].id == 1
    assert novi[0].status == StatusAlarma.OTVOREN
    assert novi[0].za_slanje


def test_isti_nalaz_ponovo_ne_pravi_nov_alarm(ev):
    ev.uskladi([nalaz()], T0)
    assert ev.uskladi([nalaz()], T0 + SAT) == []
    assert len(ev.alarmi) == 1


def test_problem_koji_traje_produzava_isti_alarm(ev):
    ev.uskladi([nalaz(0, 6)], T0)
    assert ev.uskladi([nalaz(0, 9)], T0 + SAT) == []  # ne javlja se ponovo
    assert ev.alarmi[0].do == T0 + 9 * SAT


def test_razliciti_problemi_su_razliciti_alarmi(ev):
    novi = ev.uskladi([nalaz(izvor="A"), nalaz(izvor="B"), nalaz(tip="drift"),
                       nalaz(20, 22)], T0)
    assert [a.id for a in novi] == [1, 2, 3, 4]


def test_pogorsanje_se_javlja_ponovo(ev):
    ev.uskladi([nalaz()], T0)
    ev.alarmi[0].za_slanje = False  # obaveštenje je poslato
    novi = ev.uskladi([nalaz(ozbiljnost=Ozbiljnost.KRITICNO)], T0 + SAT)
    assert len(novi) == 1
    assert novi[0].ozbiljnost == Ozbiljnost.KRITICNO
    assert novi[0].za_slanje


def test_potvrdjen_alarm_se_ne_javlja_dok_traje(ev):
    ev.uskladi([nalaz(0, 6)], T0)
    ev.potvrdi(1, "Veljko", "proveravam")
    assert ev.uskladi([nalaz(0, 9)], T0 + SAT) == []
    assert ev.alarmi[0].status == StatusAlarma.POTVRDJEN


def test_resen_alarm_se_otvara_ako_se_problem_nastavi(ev):
    ev.uskladi([nalaz(0, 6)], T0)
    ev.resi(1)
    # Stari, isti nalaz: ostaje rešen.
    assert ev.uskladi([nalaz(0, 6)], T0 + SAT) == []
    # Problem se nastavio posle rešavanja: otvara se ponovo.
    (a,) = ev.uskladi([nalaz(0, 9)], T0 + 2 * SAT)
    assert a.status == StatusAlarma.OTVOREN
    assert a.za_slanje


def test_otvoreni_su_poredjani_po_ozbiljnosti(ev):
    ev.uskladi([nalaz(izvor="A"), nalaz(izvor="B", ozbiljnost=Ozbiljnost.KRITICNO)], T0)
    ev.resi(1)
    assert [a.izvor for a in ev.otvoreni()] == ["B"]


def test_cuvanje_i_ucitavanje(tmp_path):
    putanja = tmp_path / "alarmi.json"
    ev = Evidencija(putanja)
    ev.uskladi([nalaz()], T0)
    ev.potvrdi(1, "Veljko")
    ev.sacuvaj()

    ponovo = Evidencija(putanja)
    assert ponovo.alarmi == ev.alarmi


def test_nepostojeci_alarm(ev):
    with pytest.raises(KeyError):
        ev.potvrdi(42, "Veljko")


# --- korak 7: problem koji prođe sam se zatvara ---


def test_problem_koji_provere_vise_ne_nalaze_se_sam_zatvara(ev):
    ev.uskladi([nalaz(izvor="A"), nalaz(izvor="B")], T0, zatvori_nestale=True)
    assert all(a.status == StatusAlarma.OTVOREN for a in ev.alarmi)  # novi se ne zatvaraju odmah
    ev.uskladi([nalaz(izvor="A", do=8)], T0 + 2 * SAT, zatvori_nestale=True)
    a, b = ev.alarmi
    assert a.status == StatusAlarma.OTVOREN and a.do == T0 + 8 * SAT
    assert b.status == StatusAlarma.RESEN and b.napomena == Evidencija.PRESTALO


def test_bez_zatvori_nestale_nista_se_ne_zatvara(ev):
    ev.uskladi([nalaz(izvor="A")], T0)
    ev.uskladi([], T0 + SAT)  # npr. krug sa greškom: ne sme da "reši" alarm
    assert ev.alarmi[0].status == StatusAlarma.OTVOREN
