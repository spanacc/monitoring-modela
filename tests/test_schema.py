"""
Provere univerzalnog formata rezultata.

Testovi su mali programi koji automatski proveravaju da li kod radi kako
treba. Pokreću se komandom `pytest`. Ako neko kasnije nešto pokvari,
testovi će to odmah otkriti.
"""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.schema import Rezultat, Status

SADA = datetime(2026, 11, 10, 14, 0, tzinfo=timezone.utc)


def osnovno(**izmene):
    """Ispravan rezultat, uz mogućnost da se promeni neko polje."""
    podaci = dict(vreme=SADA, model="m", izvor="Mašina 7", velicina="temperatura")
    podaci.update(izmene)
    return podaci


def test_ispravan_rezultat_sa_brojem():
    r = Rezultat(**osnovno(vrednost=84.0, jedinica="°C"))
    assert r.vrednost == 84.0
    assert r.status == Status.OK
    assert not r.je_prazan


def test_ispravan_rezultat_sa_kategorijom():
    r = Rezultat(**osnovno(kategorija="ispravno"))
    assert r.kategorija == "ispravno"


def test_prazan_rezultat_je_dozvoljen_ali_oznacen():
    # Prazan rezultat ne odbacujemo: monitoring treba da ga vidi i prijavi.
    r = Rezultat(**osnovno())
    assert r.je_prazan


def test_vreme_bez_zone_se_odbija():
    with pytest.raises(ValidationError, match="vremensku zonu"):
        Rezultat(**osnovno(vreme=datetime(2026, 11, 10, 14, 0)))


def test_broj_i_kategorija_zajedno_se_odbijaju():
    with pytest.raises(ValidationError, match="istovremeno"):
        Rezultat(**osnovno(vrednost=1.0, kategorija="ispravno"))


def test_obavezna_polja_ne_smeju_biti_prazna():
    with pytest.raises(ValidationError):
        Rezultat(**osnovno(izvor=""))


def test_negativan_horizont_se_odbija():
    with pytest.raises(ValidationError):
        Rezultat(**osnovno(vrednost=1.0, horizont_min=-5))


def test_vreme_kao_tekst_se_prevodi():
    # Podaci iz CSV fajla stižu kao tekst; pydantic ih sam prevodi u vreme.
    r = Rezultat(**osnovno(vreme="2026-11-10T14:00:00+01:00", vrednost="12.5"))
    assert r.vreme.utcoffset().total_seconds() == 3600
    assert r.vrednost == 12.5