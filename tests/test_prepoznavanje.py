from datetime import timedelta, timezone
from zoneinfo import ZoneInfo

from app.prepoznavanje import (
    normalizuj,
    prepoznaj,
    procitaj_broj,
    procitaj_vreme,
)

BEOGRAD = ZoneInfo("Europe/Belgrade")


def redovi(kolone, *vrednosti):
    """Pravi redove kao da su pročitani iz CSV fajla."""
    return [dict(zip(kolone, red)) for red in vrednosti]


def test_normalizuj_uklanja_kvacice_i_razmake():
    assert normalizuj("Mašina ID") == "masina_id"
    assert normalizuj("  Uređaj ") == "uredjaj"
    assert normalizuj("Predicted-Temp (°C)") == "predicted_temp_c"


def test_procitaj_broj():
    assert procitaj_broj("12,5") == 12.5
    assert procitaj_broj("1.234,5") == 1234.5
    assert procitaj_broj("1,234.5") == 1234.5
    assert procitaj_broj("-3") == -3.0
    assert procitaj_broj("abc") is None
    assert procitaj_broj("nan") is None


def test_procitaj_vreme_u_raznim_oblicima():
    iso = procitaj_vreme("2026-11-10T13:00:00Z", BEOGRAD)
    assert iso.utcoffset() == timedelta(0)  # Z znači UTC, zona se ne menja

    lokalno = procitaj_vreme("10.11.2026 14:00", BEOGRAD)
    assert lokalno.hour == 14
    assert lokalno.utcoffset() == timedelta(hours=1)  # dodeljena je beogradska zona
    assert lokalno == iso  # 14h u Beogradu je 13h po UTC

    assert procitaj_vreme("10.11.2026. 14:00", BEOGRAD) == iso
    assert procitaj_vreme("1794315600", BEOGRAD) == iso  # sekunde od 1970.
    assert procitaj_vreme("1794315600000", BEOGRAD) == iso  # milisekunde
    assert procitaj_vreme("abc", BEOGRAD) is None
    assert procitaj_vreme("20261110", BEOGRAD) is None  # broj, a ne datum


def test_prepoznaje_po_nazivima_na_engleskom():
    kolone = ["Timestamp", "Machine ID", "Predicted Temp", "Measured Temp"]
    m = prepoznaj(kolone, redovi(kolone,
                                 ["10.11.2026 14:00", "M7", "84,5", "81,2"],
                                 ["10.11.2026 15:00", "M7", "85,0", ""]))
    assert m.polja == {
        "vreme": "Timestamp",
        "izvor": "Machine ID",
        "vrednost": "Predicted Temp",
        "stvarna_vrednost": "Measured Temp",
    }
    assert m.nacin["vreme"] == "naziv kolone"
    assert m.velicina == "predicted_temp"
    assert m.neprepoznate == []


def test_prepoznaje_po_sadrzaju_kad_nazivi_ne_govore_nista():
    kolone = ["a", "b", "c"]
    m = prepoznaj(kolone, redovi(kolone,
                                 ["2026-11-10 14:00", "Pumpa 1", "3.2"],
                                 ["2026-11-10 15:00", "Pumpa 2", "3.4"]))
    assert m.polja == {"vreme": "a", "vrednost": "c", "izvor": "b"}
    assert "sadržaj" in m.nacin["vreme"]


def test_isti_naziv_daje_kategoriju_kad_je_sadrzaj_tekst():
    kolone = ["time", "line", "prediction", "actual"]
    m = prepoznaj(kolone, redovi(kolone,
                                 ["2026-11-10T14:00:00Z", "L1", "ok", "ok"],
                                 ["2026-11-10T14:15:00Z", "L1", "kvar", "ok"]))
    assert m.polja["kategorija"] == "prediction"
    assert m.polja["stvarna_kategorija"] == "actual"


def test_redni_broj_se_ne_uzima_kao_vrednost():
    kolone = ["id", "time", "temp"]
    m = prepoznaj(kolone, redovi(kolone,
                                 ["1", "2026-11-10T14:00:00Z", "61.5"],
                                 ["2", "2026-11-10T15:00:00Z", "62.0"]))
    assert m.polja["vrednost"] == "temp"
    assert m.neprepoznate == ["id"]


def test_actual_value_je_stvarna_vrednost_a_ne_prognoza():
    kolone = ["time", "actual_value", "value"]
    m = prepoznaj(kolone, redovi(kolone, ["2026-11-10T14:00:00Z", "1", "2"]))
    assert m.polja["stvarna_vrednost"] == "actual_value"
    assert m.polja["vrednost"] == "value"


def test_epoch_vreme_ostaje_utc():
    v = procitaj_vreme("1794315600", BEOGRAD)
    assert v.tzinfo == timezone.utc