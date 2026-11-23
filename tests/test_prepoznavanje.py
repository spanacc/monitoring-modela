"""
Provere automatskog prepoznavanja kolona.
"""

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


# --- korak 7: šta su otkrili pravi fajlovi (pingvini, bicikli) ---


def test_redni_broj_se_prepoznaje_po_sadrzaju_ma_kako_se_zvao():
    # "rowid" i "instant" nisu na spisku reči, ali 1, 2, 3, 4, 5... je očigledno redni broj.
    kolone = ["instant", "dteday", "cnt"]
    m = prepoznaj(kolone, redovi(kolone, *[[str(i), f"2011-01-{i:02d}", str(900 + i * 37)] for i in range(1, 9)]))
    assert m.polja["vrednost"] == "cnt"
    assert "instant" not in m.polja.values()


def test_datum_i_sat_u_dve_kolone():
    # 24 reda sa istim datumom i satom 0-23: bez sata bi sve bilo u istom trenutku.
    kolone = ["dteday", "hr", "cnt"]
    m = prepoznaj(kolone, redovi(kolone, *[["2011-01-01", str(h), str(10 + h * 3)] for h in range(24)]
                                 + [["2011-01-02", str(h), str(12 + h * 3)] for h in range(24)]))
    assert m.polja["vreme"] == "dteday"
    assert m.polja["doba_dana"] == "hr"


def test_sinonimi_za_predvidjeno():
    kolone = ["vreme", "predikcija", "stvarnost"]
    m = prepoznaj(kolone, redovi(kolone, ["2026-11-10 14:00", "Adelie", "Adelie"],
                                 ["2026-11-10 15:00", "Gentoo", "Chinstrap"]))
    assert m.polja["kategorija"] == "predikcija"
    assert m.polja["stvarna_kategorija"] == "stvarnost"


def test_kose_crte_redosled_se_pogadja_iz_kolone():
    # 25/03 može biti samo dan/mesec; 03/25 samo mesec/dan.
    kolone = ["datum", "pred"]
    m = prepoznaj(kolone, redovi(kolone, ["25/03/2026", "10.5"], ["26/03/2026", "11.2"]))
    assert m.redosled_datuma == "dm" and not m.napomene
    m = prepoznaj(kolone, redovi(kolone, ["03/25/2026", "10.5"], ["03/26/2026", "11.2"]))
    assert m.redosled_datuma == "md"
    assert procitaj_vreme("03/25/2026", BEOGRAD, "md").day == 25
    # 01/02 je dvosmisleno: uzima se dan/mesec, uz napomenu da čovek proveri.
    m = prepoznaj(kolone, redovi(kolone, ["01/02/2026", "10.5"], ["02/02/2026", "11.2"]))
    assert m.redosled_datuma == "dm" and m.napomene


def test_samo_mesec_je_vreme():
    assert procitaj_vreme("2026-11", BEOGRAD).month == 11
    assert procitaj_vreme("11.2026", BEOGRAD).year == 2026
