"""
Mejlovi iz aplikacije (korak 8): problemi odmah i dnevni pregled ujutru.

ŠTA SE ŠALJE
------------
    odmah          čim provera nađe nov problem (ili se problem pogorša).
                   Napomene (sitnice) se ne šalju. Svi novi problemi iz
                   jednog kruga idu u JEDAN mejl.
    dnevni pregled jednom dnevno, u zadato vreme: šta je otvoreno, šta je
                   prošlo za poslednja 24 h, ili "Sve u redu".
    probni mejl    dugme u podešavanjima: dnevni pregled odmah, da se vidi
                   da slanje radi i kako mejl izgleda.

Svaki mejl ima dva oblika u jednom: običan tekst (za stare programe) i
HTML (boje, spisak). Svi tekstovi iz podataka (nazivi modela, opisi) se u
HTML ubacuju "očišćeni" (html.escape), pa ni čudno ime modela ne može da
ubaci svoj kod u mejl.

BEZBEDNOST SLANJA
-----------------
- Veza sa mejl serverom je UVEK šifrovana: port 465 odmah šifruje, ostali
  traže STARTTLS. Ako server ne podržava šifrovanje, mejl se NE šalje
  (lozinka nikad ne ide nešifrovana).
- Sertifikat servera se proverava (da se ne razgovara sa lažnim serverom).
- Lozinka se čuva šifrovana (vidi app/tajne.py) i nikad se ne ispisuje,
  ni u porukama o greškama.
- U naslov mejla ne mogu da uđu novi redovi (npr. iz imena modela), jer bi
  to omogućilo dodavanje lažnih zaglavlja.
"""

import html
import os
import re
import smtplib
import ssl
from collections import Counter
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from zoneinfo import ZoneInfo

from app.alarmi.evidencija import NAZIVI, REDOSLED, Alarm, StatusAlarma
from app.provere import Ozbiljnost

ADRESA = re.compile(r"^[^@\s<>,;\"']+@[^@\s<>,;\"']+\.[^@\s<>,;\"']+$")
NAJVISE_PRIMALACA = 20
NAJVISE_U_MEJLU = 30  # dalje: "i još N"

BOJE = {  # iste kao na stranici
    "kriticno": ("#dc2626", "#fef2f2", "#fecaca"),
    "upozorenje": ("#d97706", "#fff7e8", "#fcd9a0"),
    "ok": ("#16a34a", "#ecfdf3", "#bbf7d0"),
}
NIVO = {Ozbiljnost.KRITICNO: "Hitno", Ozbiljnost.UPOZORENJE: "Problem", Ozbiljnost.INFO: "Napomena"}


def ispravna_adresa(adresa: str) -> bool:
    return bool(ADRESA.match(adresa)) and len(adresa) <= 254


def bez_novih_redova(tekst: str) -> str:
    return re.sub(r"[\r\n\t]+", " ", tekst).strip()


def mnozina(n: int, jedan: str, dva: str, pet: str) -> str:
    d, s = n % 10, n % 100
    if d == 1 and s != 11:
        return jedan
    if 2 <= d <= 4 and not 12 <= s <= 14:
        return dva
    return pet


def gde(a: Alarm) -> str:
    return a.model if a.izvor == "glavni" else f"{a.model} · {a.izvor}"


def kada(a: Alarm, zona: ZoneInfo) -> str:
    od, do = a.od.astimezone(zona), a.do.astimezone(zona)
    if od.date() == do.date():
        return f"{od:%d.%m.} {od:%H:%M}–{do:%H:%M}"
    return f"{od:%d.%m. %H:%M} – {do:%d.%m. %H:%M}"


def grupisi(alarmi: list[Alarm]) -> list[list[Alarm]]:
    """Isti problem u isto vreme na više izvora jednog modela je jedan red (kao na stranici)."""
    grupe: dict[tuple, list[Alarm]] = {}
    for a in alarmi:
        grupe.setdefault((a.tip, a.model, a.od, a.do, a.ozbiljnost), []).append(a)
    return sorted(grupe.values(), key=lambda g: (-REDOSLED[g[0].ozbiljnost], -g[0].do.timestamp()))


# ---------------------------------------------------------------------------
# Sadržaj mejla
# ---------------------------------------------------------------------------


def _red_teksta(g: list[Alarm], zona: ZoneInfo) -> str:
    a = g[0]
    mesto = gde(a) if len(g) == 1 else f"{a.model} · {len(g)} izvora"
    return (f"- {NIVO[a.ozbiljnost]}: {NAZIVI.get(a.tip, a.tip)} ({mesto}, {kada(a, zona)})\n"
            f"  {a.opis}")


def _red_html(g: list[Alarm], zona: ZoneInfo, proslo: bool = False) -> str:
    a = g[0]
    boja, pozadina, ivica = BOJE["ok" if proslo else ("kriticno" if a.ozbiljnost == Ozbiljnost.KRITICNO else "upozorenje")]
    if proslo:
        pozadina, ivica = "#f8fafc", "#e6e9ef"
    mesto = gde(a) if len(g) == 1 else f"{a.model} · {len(g)} izvora"
    e = html.escape
    oznaka = "Prošlo" if proslo else NIVO[a.ozbiljnost]
    return f"""
<tr><td style="padding:0 0 10px">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{pozadina};border:1px solid {ivica};border-radius:10px">
    <tr><td style="padding:12px 14px;font-family:Arial,Helvetica,sans-serif">
      <div style="font-size:12px;color:#475569"><span style="color:{boja};font-weight:bold">{e(oznaka)}</span>
        &nbsp;·&nbsp; <b style="color:#0f172a">{e(mesto)}</b> &nbsp;·&nbsp; {e(kada(a, zona))}</div>
      <div style="font-size:15px;font-weight:bold;color:#0f172a;margin-top:6px">{e(NAZIVI.get(a.tip, a.tip))}</div>
      <div style="font-size:13px;color:#475569;margin-top:3px">{e(a.opis)}</div>
    </td></tr>
  </table>
</td></tr>"""


def _omot(boja_kljuc: str, naslov: str, podnaslov: str, telo: str, adresa: str | None) -> str:
    boja, pozadina, ivica = BOJE[boja_kljuc]
    e = html.escape
    dugme = ""
    if adresa:
        dugme = (f'<tr><td style="padding:6px 0 0"><a href="{e(adresa, quote=True)}" '
                 'style="display:inline-block;background:#2563eb;color:#ffffff;text-decoration:none;'
                 'font:bold 14px Arial,Helvetica,sans-serif;padding:10px 18px;border-radius:8px">'
                 'Otvori monitoring</a></td></tr>')
    return f"""<!doctype html><html><body style="margin:0;padding:0;background:#f5f7fa">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f5f7fa"><tr><td align="center" style="padding:24px 12px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px">
  <tr><td style="padding:0 0 14px;font:bold 15px Arial,Helvetica,sans-serif;color:#0f172a">Monitoring modela</td></tr>
  <tr><td style="padding:0 0 16px">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{pozadina};border:1px solid {ivica};border-radius:12px">
      <tr><td style="padding:18px 20px;font-family:Arial,Helvetica,sans-serif">
        <div style="font-size:22px;font-weight:bold;color:{boja}">{e(naslov)}</div>
        <div style="font-size:14px;color:#475569;margin-top:4px">{e(podnaslov)}</div>
      </td></tr>
    </table>
  </td></tr>
  {telo}
  {dugme}
  <tr><td style="padding:18px 0 0;font:12px Arial,Helvetica,sans-serif;color:#8391a5">
    Ovaj mejl je poslala aplikacija za praćenje modela. Ko i kada šta dobija podešava se na stranici Podešavanja.
  </td></tr>
</table></td></tr></table></body></html>"""


def mejl_odmah(alarmi: list[Alarm], zona: ZoneInfo, adresa: str | None) -> tuple[str, str, str]:
    """Naslov, tekst i HTML za nove probleme (jedan mejl za sve)."""
    grupe = grupisi(alarmi)
    hitno = any(a.ozbiljnost == Ozbiljnost.KRITICNO for a in alarmi)
    modeli = ", ".join(dict.fromkeys(g[0].model for g in grupe))
    if len(grupe) == 1:
        naslov = f"{'Hitno' if hitno else 'Problem'}: {NAZIVI.get(grupe[0][0].tip, grupe[0][0].tip)} ({modeli})"
    else:
        naslov = f"{'Hitno: ' if hitno else ''}{len(grupe)} {mnozina(len(grupe), 'nov problem', 'nova problema', 'novih problema')} ({modeli})"
    naslov = bez_novih_redova(f"[Monitoring] {naslov}")[:200]

    prikaz = grupe[:NAJVISE_U_MEJLU]
    ostalo = len(grupe) - len(prikaz)
    tekst = "Provera je našla nove probleme:\n\n" + "\n\n".join(_red_teksta(g, zona) for g in prikaz)
    if ostalo:
        tekst += f"\n\n... i još {ostalo}."
    if adresa:
        tekst += f"\n\nPregled: {adresa}"
    telo = "".join(_red_html(g, zona) for g in prikaz)
    if ostalo:
        telo += f'<tr><td style="font:13px Arial,sans-serif;color:#475569;padding:0 0 10px">... i još {ostalo}.</td></tr>'
    broj = f"{len(grupe)} {mnozina(len(grupe), 'nov problem', 'nova problema', 'novih problema')}"
    html_ = _omot("kriticno" if hitno else "upozorenje", "Hitno" if hitno else "Ima problema",
                  f"{broj} · {modeli}", telo, adresa)
    return naslov, tekst, html_


def mejl_pregled(svi: list[Alarm], zona: ZoneInfo, sada: datetime, adresa: str | None,
                 broj_modela: int, proba: bool = False) -> tuple[str, str, str]:
    """Dnevni pregled: otvoreni problemi i šta je prošlo za 24 h. "Sve u redu" kad nema ničega."""
    otvoreni = grupisi([a for a in svi if a.status != StatusAlarma.RESEN and a.ozbiljnost != Ozbiljnost.INFO])
    proslo = grupisi([a for a in svi if a.status == StatusAlarma.RESEN
                      and a.ozbiljnost != Ozbiljnost.INFO and a.poslednji_put >= sada - timedelta(hours=24)])
    lok = sada.astimezone(zona)
    datum = f"{lok.day}.{lok.month}.{lok.year}."
    hitno = any(g[0].ozbiljnost == Ozbiljnost.KRITICNO for g in otvoreni)
    vrsta = "Probni mejl" if proba else "Dnevni pregled"

    if otvoreni:
        n = len(otvoreni)
        stanje = f"{'Hitno: ' if hitno else ''}{n} {mnozina(n, 'otvoren problem', 'otvorena problema', 'otvorenih problema')}"
        boja = "kriticno" if hitno else "upozorenje"
    else:
        stanje, boja = "Sve u redu", "ok"
    naslov = bez_novih_redova(f"[Monitoring] {vrsta} {datum} – {stanje}")
    podnaslov = f"{vrsta} za {datum} · prati se {broj_modela} {mnozina(broj_modela, 'model', 'modela', 'modela')}"

    tekst = f"{vrsta} za {datum}\n\nStanje: {stanje}\n"
    telo = ""
    if otvoreni:
        tekst += "\nOtvoreni problemi:\n\n" + "\n\n".join(_red_teksta(g, zona) for g in otvoreni[:NAJVISE_U_MEJLU])
        telo += "".join(_red_html(g, zona) for g in otvoreni[:NAJVISE_U_MEJLU])
    if proslo:
        tekst += "\n\nProšlo u poslednja 24 h:\n\n" + "\n\n".join(_red_teksta(g, zona) for g in proslo[:10])
        telo += ('<tr><td style="font:bold 13px Arial,sans-serif;color:#8391a5;padding:8px 0 8px">'
                 'Prošlo u poslednja 24 h</td></tr>')
        telo += "".join(_red_html(g, zona, proslo=True) for g in proslo[:10])
    if not otvoreni and not proslo:
        tekst += "\nNema otvorenih problema, i ništa se nije desilo u poslednja 24 h."
        telo += ('<tr><td style="font:14px Arial,sans-serif;color:#475569;padding:0 0 10px">'
                 'Nema otvorenih problema, i ništa se nije desilo u poslednja 24 h.</td></tr>')
    if proba:
        tekst += "\n\nOvo je probni mejl: slanje radi."
        telo = ('<tr><td style="font:14px Arial,sans-serif;color:#1d4ed8;padding:0 0 12px">'
                'Ovo je probni mejl: slanje radi. Ovako će izgledati dnevni pregled.</td></tr>') + telo
    if adresa:
        tekst += f"\n\nPregled: {adresa}"
    return naslov, tekst, _omot(boja, stanje, podnaslov, telo, adresa)


# ---------------------------------------------------------------------------
# Slanje
# ---------------------------------------------------------------------------


class GreskaSlanja(Exception):
    """Greška sa porukom za čoveka (bez lozinke i tehničkih detalja)."""


def bezbedan_kontekst() -> ssl.SSLContext:
    """Šifrovana veza koja proverava sertifikat servera.

    Python sa python.org na Macu ne vidi sertifikate sistema, pa bi provera
    uvek pala. Zato se uz sertifikate sistema učitava i spisak iz paketa
    certifi (isti koji koriste pregledači). Provera se nikad ne isključuje.
    """
    kontekst = ssl.create_default_context()
    try:
        import certifi
        kontekst.load_verify_locations(cafile=certifi.where())
    except (ImportError, OSError):
        pass
    return kontekst


def posalji(server: str, port: int, korisnik: str | None, lozinka: str | None,
            od: str, za: list[str], naslov: str, tekst: str, html_: str) -> None:
    if not za:
        raise GreskaSlanja("Nije upisan nijedan primalac.")
    poruka = EmailMessage()
    poruka["Subject"] = bez_novih_redova(naslov)
    poruka["From"] = od
    poruka["To"] = ", ".join(za)
    poruka["Date"] = formatdate(localtime=True)
    poruka["Message-ID"] = make_msgid(domain=od.split("@")[-1])
    poruka.set_content(tekst)
    poruka.add_alternative(html_, subtype="html")

    kontekst = bezbedan_kontekst()
    try:
        if port == 465:
            veza = smtplib.SMTP_SSL(server, port, timeout=30, context=kontekst)
        else:
            veza = smtplib.SMTP(server, port, timeout=30)
        with veza as smtp:
            if port != 465:
                smtp.ehlo()
                if not smtp.has_extn("starttls"):
                    raise GreskaSlanja("Server ne podržava šifrovanu vezu (STARTTLS), pa mejl nije "
                                       "poslat: lozinka nikad ne ide nešifrovana.")
                smtp.starttls(context=kontekst)
                smtp.ehlo()
            if korisnik:
                smtp.login(korisnik, lozinka or "")
            smtp.send_message(poruka)
    except GreskaSlanja:
        raise
    except smtplib.SMTPAuthenticationError:
        raise GreskaSlanja("Server je odbio nalog ili lozinku. Za Gmail treba posebna "
                           "„lozinka za aplikaciju“ (16 slova), ne obična lozinka.") from None
    except smtplib.SMTPRecipientsRefused:
        raise GreskaSlanja("Server je odbio adresu primaoca. Proverite spisak primalaca.") from None
    except smtplib.SMTPSenderRefused:
        raise GreskaSlanja("Server ne dozvoljava slanje sa te adrese pošiljaoca. "
                           "Kod Gmaila pošiljalac mora biti isti nalog.") from None
    except ssl.SSLCertVerificationError:
        raise GreskaSlanja("Sertifikat mejl servera nije mogao da se proveri, pa mejl nije poslat. "
                           "Najčešće: Python na ovom računaru nema spisak sertifikata "
                           "(pokrenite: pip install -r requirements.txt), ili antivirus / mreža "
                           "firme presreće šifrovanu vezu.") from None
    except ssl.SSLError:
        raise GreskaSlanja("Šifrovana veza sa serverom nije uspela (pogrešan port?). "
                           "Za Gmail: smtp.gmail.com, port 587.") from None
    except (OSError, smtplib.SMTPException) as e:
        raise GreskaSlanja(f"Veza sa mejl serverom nije uspela ({server}:{port}): "
                           f"{type(e).__name__}. Proverite adresu servera, port i internet.") from None


def sazetak_tipova(alarmi: list[Alarm]) -> str:
    """Kratko, za dnevnik: '2× Podaci ne stižu, 1× Neobična vrednost'."""
    c = Counter(NAZIVI.get(a.tip, a.tip) for a in alarmi)
    return ", ".join(f"{n}× {ime}" for ime, n in c.most_common())


# ---------------------------------------------------------------------------
# Veza sa podešavanjima: lozinka, kanal za nove probleme, dnevni pregled
# ---------------------------------------------------------------------------

PROMENLJIVA_LOZINKE = "MONITORING_MEJL_LOZINKA"


def lozinka() -> str | None:
    """Lozinka iz promenljive okruženja (ima prednost), inače sačuvana šifrovana."""
    from app import tajne  # ovde, da ostatak modula radi i bez biblioteke cryptography
    return os.environ.get(PROMENLJIVA_LOZINKE) or tajne.procitaj("mejl")


def posalji_po_podesavanjima(m, naslov: str, tekst: str, html_: str) -> None:
    """Šalje mejl sa podešavanjima sa stranice (`m` je MejlPodesavanja)."""
    if not (m.server and m.za):
        raise GreskaSlanja("Mejl nije podešen: upišite server i bar jednog primaoca.")
    posalji(m.server, m.port, m.korisnik or None, lozinka() if m.korisnik else None,
            m.od or m.korisnik, m.za, naslov, tekst, html_)


class MejlSaStraniceKanal:
    """Kanal za nove probleme (kao ekran, dnevnik...), sa podešavanjima sa stranice."""

    def __init__(self, m, zona: ZoneInfo):
        self.m, self.zona = m, zona

    def posalji(self, alarmi: list[Alarm]) -> None:
        naslov, tekst, html_ = mejl_odmah(alarmi, self.zona, self.m.adresa_aplikacije)
        posalji_po_podesavanjima(self.m, naslov, tekst, html_)


def vreme_za_dnevni(m, sada: datetime, zona: ZoneInfo, poslednji: str | None) -> bool:
    """
    Da li je stiglo vreme za dnevni pregled, a za današnje zakazano vreme još
    nije poslat. `poslednji` je kad je poslat poslednji (npr.
    "2026-11-23T13:19:04+01:00"). Ako se vreme promeni na kasnije u toku dana,
    pregled stiže i u novo vreme.
    """
    if not (m.ukljuceno and m.dnevni):
        return False
    lokalno = sada.astimezone(zona)
    sat, minut = (int(x) for x in m.dnevni_sat.split(":"))
    zakazano = lokalno.replace(hour=sat, minute=minut, second=0, microsecond=0)
    if lokalno < zakazano:
        return False
    if not poslednji:
        return True
    try:
        poslat = datetime.fromisoformat(poslednji)
        if poslat.tzinfo is None:
            # Stari zapis, samo datum ("2026-11-23"): sat se ne zna, pa se
            # uzima ponoć. Tako novo vreme istog dana i dalje stiže.
            poslat = poslat.replace(tzinfo=zona)
        return poslat < zakazano
    except ValueError:
        return True
