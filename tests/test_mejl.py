"""
Provere mejla (korak 8): šifrovana lozinka, bezbedno slanje, sadržaj mejla,
slanje odmah posle provere i dnevni pregled. Pravi mejl server se ne koristi:
umesto njega je "lažni" server koji samo pamti šta mu je poslato.
"""

import os
import smtplib
import stat
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app import tajne
from app.alarmi import mejl
from app.alarmi.evidencija import Alarm, StatusAlarma
from app.alarmi.konfiguracija import Izvor, Konfiguracija, MejlPodesavanja
from app.dashboard.server import napravi_aplikaciju
from app.nadzor import jedan_krug
from app.provere import Ozbiljnost

IZMENA = {"X-Dashboard": "1"}
BG = ZoneInfo("Europe/Belgrade")
T0 = datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc)


class LazniServer:
    """Glumi mejl server. `poslato` je spisak poslatih poruka (za sve primerke)."""
    poslato: list = []
    tls = True  # da li server podržava STARTTLS
    lozinka = "tacna-lozinka"

    def __init__(self, server, port, timeout=None, context=None):
        self.sifrovano = False

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def ehlo(self):
        pass

    def has_extn(self, ime):
        return ime == "starttls" and self.tls

    def starttls(self, context=None):
        self.sifrovano = True

    def login(self, korisnik, lozinka):
        assert self.sifrovano, "lozinka poslata bez šifrovanja!"
        if lozinka != self.lozinka:
            raise smtplib.SMTPAuthenticationError(535, b"pogresno")

    def send_message(self, poruka):
        LazniServer.poslato.append(poruka)


@pytest.fixture(autouse=True)
def lazni_server(monkeypatch, tmp_path):
    LazniServer.poslato = []
    LazniServer.tls = True
    monkeypatch.setattr(mejl.smtplib, "SMTP", LazniServer)
    monkeypatch.setattr(tajne, "FOLDER", tmp_path / "tajne")
    monkeypatch.delenv("MONITORING_MEJL_LOZINKA", raising=False)
    monkeypatch.delenv("MONITORING_KLJUC", raising=False)
    return LazniServer


def alarm(broj=1, tip="izostanak", model="model_a", izvor="glavni", ozbiljnost=Ozbiljnost.UPOZORENJE,
          status=StatusAlarma.OTVOREN, sati=0, opis="Rezultati nisu stizali 3 h."):
    return Alarm(id=broj, tip=tip, model=model, izvor=izvor, od=T0 + timedelta(hours=sati),
                 do=T0 + timedelta(hours=sati + 3), ozbiljnost=ozbiljnost, opis=opis, status=status,
                 prvi_put=T0, poslednji_put=T0 + timedelta(hours=sati + 3))


# --- tajne ---


def test_lozinka_se_cuva_sifrovana_i_zakljucana(tmp_path):
    tajne.sacuvaj("mejl", "abcd efgh ijkl mnop")
    fajl = tajne.FOLDER / "mejl.tajna"
    assert b"abcd" not in fajl.read_bytes()  # nije čitljiva u fajlu
    assert tajne.procitaj("mejl") == "abcd efgh ijkl mnop"
    if os.name == "posix":
        assert stat.S_IMODE(fajl.stat().st_mode) == 0o600
        assert stat.S_IMODE((tajne.FOLDER / "kljuc").stat().st_mode) == 0o600
    tajne.obrisi("mejl")
    assert tajne.procitaj("mejl") is None


def test_lozinka_ne_moze_bez_kljuca(tmp_path):
    tajne.sacuvaj("mejl", "tajna")
    (tajne.FOLDER / "kljuc").unlink()  # neko je kopirao samo šifrovan fajl
    with pytest.raises(ValueError, match="ne može da se pročita"):
        tajne.procitaj("mejl")


# --- slanje ---


def test_slanje_je_uvek_sifrovano():
    mejl.posalji("smtp.x.rs", 587, "a@x.rs", "tacna-lozinka", "a@x.rs", ["b@x.rs"], "N", "t", "<p>h</p>")
    assert len(LazniServer.poslato) == 1
    LazniServer.tls = False
    with pytest.raises(mejl.GreskaSlanja, match="šifrovan"):
        mejl.posalji("smtp.x.rs", 587, "a@x.rs", "tacna-lozinka", "a@x.rs", ["b@x.rs"], "N", "t", "<p>h</p>")
    assert len(LazniServer.poslato) == 1  # ništa nije otišlo


def test_pogresna_lozinka_daje_jasnu_poruku_bez_lozinke():
    with pytest.raises(mejl.GreskaSlanja) as e:
        mejl.posalji("smtp.gmail.com", 587, "a@x.rs", "pogresna-123", "a@x.rs", ["b@x.rs"], "N", "t", "h")
    assert "lozinka za aplikaciju" in str(e.value)
    assert "pogresna-123" not in str(e.value)


def test_naslov_ne_moze_da_ubaci_zaglavlje():
    a = alarm(model="zli\r\nBcc: svi@svet.com")
    naslov, _, html_ = mejl.mejl_odmah([a], BG, None)
    assert "\n" not in naslov and "\r" not in naslov
    mejl.posalji("s.x.rs", 587, None, None, "a@x.rs", ["b@x.rs"], naslov, "t", html_)
    assert LazniServer.poslato[0]["Bcc"] is None


def test_html_mejla_je_ociscen():
    a = alarm(model="<script>alert(1)</script>", opis="<img src=x onerror=alert(1)>")
    _, tekst, html_ = mejl.mejl_odmah([a], BG, None)
    assert "<script>" not in html_ and "<img" not in html_
    assert "&lt;script&gt;" in html_
    assert "<script>alert(1)</script>" in tekst  # običan tekst se ne izvršava, može da ostane


# --- sadržaj ---


def test_mejl_za_nove_probleme_grupise_i_pise_nazive():
    alarmi = [alarm(1, izvor="S1"), alarm(2, izvor="S2"),  # isti problem na dva izvora
              alarm(3, tip="nemoguca_vrednost", ozbiljnost=Ozbiljnost.KRITICNO, sati=5)]
    naslov, tekst, html_ = mejl.mejl_odmah(alarmi, BG, "http://monitoring.firma.rs")
    assert naslov == "[Monitoring] Hitno: 2 nova problema (model_a)"
    assert "Podaci ne stižu (model_a · 2 izvora" in tekst
    assert "Neobična vrednost" in tekst
    assert "http://monitoring.firma.rs" in html_ and "Otvori monitoring" in html_


def test_dnevni_pregled_sve_u_redu_i_sa_problemima():
    naslov, tekst, _ = mejl.mejl_pregled([], BG, T0, None, 3)
    assert "Sve u redu" in naslov and "Nema otvorenih problema" in tekst
    prosao = alarm(2, status=StatusAlarma.RESEN)
    naslov, tekst, _ = mejl.mejl_pregled([alarm(1), prosao], BG, T0 + timedelta(hours=4), None, 3)
    assert "1 otvoren problem" in naslov
    assert "Prošlo u poslednja 24 h" in tekst


def test_vreme_za_dnevni_pregled():
    m = MejlPodesavanja(ukljuceno=True, server="s.x.rs", za=["a@x.rs"], dnevni_sat="07:30")
    rano = datetime(2026, 11, 20, 6, 0, tzinfo=timezone.utc)  # 07:00 u Beogradu
    kasnije = datetime(2026, 11, 20, 7, 0, tzinfo=timezone.utc)  # 08:00
    assert not mejl.vreme_za_dnevni(m, rano, BG, None)
    assert mejl.vreme_za_dnevni(m, kasnije, BG, None)
    # Stari zapis (samo datum): uzima se ponoć, pa novo vreme istog dana stiže.
    assert mejl.vreme_za_dnevni(m, kasnije, BG, "2026-11-20")
    assert not mejl.vreme_za_dnevni(m, kasnije, BG, "2026-11-20T07:30:10+01:00")  # danas već poslat
    assert not mejl.vreme_za_dnevni(m.model_copy(update={"dnevni": False}), kasnije, BG, None)
    # Poslat danas u 07:31: ne opet. Vreme pomereno na 13:19: stiže i tad.
    assert not mejl.vreme_za_dnevni(m, kasnije, BG, "2026-11-20T07:31:00+01:00")
    m2 = m.model_copy(update={"dnevni_sat": "13:19"})
    u_1319 = datetime(2026, 11, 20, 12, 19, tzinfo=timezone.utc)
    assert not mejl.vreme_za_dnevni(m2, u_1319.replace(minute=18), BG, "2026-11-20T07:31:00+01:00")
    assert mejl.vreme_za_dnevni(m2, u_1319, BG, "2026-11-20T07:31:00+01:00")
    assert not mejl.vreme_za_dnevni(m2, u_1319, BG, "2026-11-20T13:19:05+01:00")
    assert mejl.vreme_za_dnevni(m2, u_1319.replace(day=21), BG, "2026-11-20T13:19:05+01:00")


# --- ceo put: nadzor šalje odmah ---


def test_nadzor_salje_mejl_za_nove_probleme_jednom(tmp_path):
    csv = tmp_path / "model_a.csv"
    redovi = ["vreme,vrednost"]
    for i in range(400):
        if 300 <= i < 330:
            continue  # 30 sati bez rezultata: problem
        redovi.append(f"{(T0 + timedelta(hours=i)).isoformat()},{50 + (i % 7)}")
    csv.write_text("\n".join(redovi), encoding="utf-8")
    tajne.sacuvaj("mejl", "tacna-lozinka")
    k = Konfiguracija(izvori=[Izvor(putanja=csv, istorijski=True)], baza=f"sqlite:///{tmp_path}/m.db",
                      dana_provere=None,
                      mejl=MejlPodesavanja(ukljuceno=True, server="smtp.x.rs", korisnik="mon@x.rs", za=["dezurni@x.rs"]))
    iz = jedan_krug(k, None)
    assert iz.novih_alarma >= 1
    assert len(LazniServer.poslato) == 1
    poruka = LazniServer.poslato[0]
    assert poruka["To"] == "dezurni@x.rs" and "Podaci ne stižu" in poruka["Subject"]
    jedan_krug(k, None)
    assert len(LazniServer.poslato) == 1  # isti problem se ne šalje ponovo


# --- stranica: lozinka se nikad ne vraća ---


def test_stranica_cuva_podesavanja_a_lozinku_nikad_ne_vraca(tmp_path):
    k = Konfiguracija(izvori=[], baza=f"sqlite:///{tmp_path}/m.db")
    klijent = TestClient(napravi_aplikaciju(k, hostovi=["testserver"], putanja_podesavanja=tmp_path / "p.json"))
    telo = {"ukljuceno": True, "server": "smtp.gmail.com", "port": 587, "korisnik": "mon@gmail.com",
            "za": ["a@firma.rs", "b@firma.rs"], "dnevni_sat": "08:00", "lozinka": "tacna-lozinka"}
    assert klijent.post("/api/mejl", json=telo).status_code == 403  # bez zaglavlja: odbijeno
    r = klijent.post("/api/mejl", json=telo, headers=IZMENA)
    assert r.status_code == 200, r.text
    assert "tacna-lozinka" not in r.text and r.json()["lozinka_sacuvana"] is True
    assert "tacna-lozinka" not in klijent.get("/api/mejl").text
    assert "tacna-lozinka" not in (tmp_path / "p.json").read_text(encoding="utf-8")
    assert tajne.procitaj("mejl") == "tacna-lozinka"

    # Bez nove lozinke ostaje stara.
    klijent.post("/api/mejl", json={**telo, "lozinka": None}, headers=IZMENA)
    assert tajne.procitaj("mejl") == "tacna-lozinka"

    # Probni mejl, pa odmah drugi: drugi se odbija (najviše jedan na 10 s).
    r = klijent.post("/api/mejl/proba", json={}, headers=IZMENA)
    assert r.status_code == 200, r.text
    assert "Probni mejl" in LazniServer.poslato[-1]["Subject"]
    assert klijent.post("/api/mejl/proba", json={}, headers=IZMENA).status_code == 429

    # Loši podaci se odbijaju.
    for lose in [{"za": ["nije-adresa"]}, {"server": "smtp gmail com"}, {"dnevni_sat": "7h"},
                 {"adresa_aplikacije": "javascript:alert(1)"}, {"nepoznato": 1}]:
        assert klijent.post("/api/mejl", json={**telo, **lose}, headers=IZMENA).status_code == 422, lose

    assert klijent.delete("/api/mejl/lozinka", headers=IZMENA).json()["lozinka_sacuvana"] is False


def test_kontekst_proverava_sertifikat():
    import ssl
    from app.alarmi.mejl import bezbedan_kontekst
    k = bezbedan_kontekst()
    assert k.verify_mode == ssl.CERT_REQUIRED and k.check_hostname
    assert k.cert_store_stats()["x509_ca"] > 0
