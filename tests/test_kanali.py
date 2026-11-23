"""
Provere kanala za slanje obaveštenja.

Pravi mejl server i pravi Slack/Teams ne možemo da koristimo u testovima,
pa ih zamenjujemo:
- za mejl: lažnom klasom koja samo zapamti šta bi bilo poslato,
- za poruku: malim web serverom na ovom računaru koji primi poruku.
"""

import json
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from zoneinfo import ZoneInfo

from app.alarmi import kanali
from app.alarmi.evidencija import Alarm
from app.provere import Ozbiljnost

BEOGRAD = ZoneInfo("Europe/Belgrade")
T0 = datetime(2026, 11, 10, 13, 0, tzinfo=timezone.utc)


def alarm(id_=1, ozbiljnost=Ozbiljnost.KRITICNO):
    return Alarm(id=id_, tip="izostanak", model="senzori", izvor="M2", od=T0,
                 do=T0 + timedelta(hours=6), ozbiljnost=ozbiljnost,
                 opis="Rezultati nisu stizali 6 h.", prvi_put=T0, poslednji_put=T0)


def test_tekst_jednog_alarma():
    naslov, telo = kanali.tekst_poruke([alarm()], BEOGRAD)
    assert naslov == "[KRITIČNO] izostanak: senzori / M2"
    assert "od 10.11.2026 14:00" in telo  # 13h UTC = 14h u Beogradu
    assert "Rezultati nisu stizali 6 h." in telo


def test_vise_alarma_u_jednoj_poruci():
    naslov, telo = kanali.tekst_poruke(
        [alarm(1, Ozbiljnost.UPOZORENJE), alarm(2, Ozbiljnost.KRITICNO)], BEOGRAD)
    assert naslov == "[KRITIČNO] 2 alarma iz monitoringa modela"  # najgori u naslovu
    assert "#1" in telo and "#2" in telo


def test_dnevnik_dopisuje_u_fajl(tmp_path):
    putanja = tmp_path / "obavestenja.log"
    dnevnik = kanali.DnevnikKanal(putanja, BEOGRAD)
    dnevnik.posalji([alarm(1)])
    dnevnik.posalji([alarm(2)])
    tekst = putanja.read_text(encoding="utf-8")
    assert "#1" in tekst and "#2" in tekst


def test_mejl(monkeypatch):
    poslato = {}

    class LazniSMTP:
        def __init__(self, server, port, timeout):
            poslato["server"] = (server, port)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def ehlo(self):
            pass

        def has_extn(self, ime):
            return ime == "starttls"

        def starttls(self, context=None):
            poslato["tls"] = context is not None  # šifrovano, uz proveru sertifikata

        def login(self, korisnik, lozinka):
            poslato["prijava"] = (korisnik, lozinka)

        def send_message(self, poruka):
            poslato["poruka"] = poruka

    from app.alarmi import mejl as mejl_modul
    monkeypatch.setattr(mejl_modul.smtplib, "SMTP", LazniSMTP)
    mejl = kanali.MejlKanal("smtp.firma.rs", 587, "mon", "tajna", "mon@firma.rs",
                            ["a@firma.rs", "b@firma.rs"], BEOGRAD)
    mejl.posalji([alarm()])

    assert poslato["server"] == ("smtp.firma.rs", 587)
    assert poslato["tls"]  # veza je šifrovana
    assert poslato["prijava"] == ("mon", "tajna")
    assert poslato["poruka"]["To"] == "a@firma.rs, b@firma.rs"
    assert poslato["poruka"]["Subject"] == "[Monitoring] Hitno: Podaci ne stižu (senzori)"


def test_poruka_preko_webhook_a():
    primljeno = []

    class Prijem(BaseHTTPRequestHandler):
        def do_POST(self):
            duzina = int(self.headers["Content-Length"])
            primljeno.append(json.loads(self.rfile.read(duzina)))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass  # bez ispisa u testovima

    server = HTTPServer(("127.0.0.1", 0), Prijem)  # 0 = bilo koji slobodan port
    nit = threading.Thread(target=server.handle_request)
    nit.start()

    adresa = f"http://127.0.0.1:{server.server_port}/"
    kanali.WebhookKanal(adresa, BEOGRAD).posalji([alarm()])
    nit.join(timeout=5)
    server.server_close()

    assert len(primljeno) == 1
    assert primljeno[0]["text"].startswith("[KRITIČNO] izostanak: senzori / M2")