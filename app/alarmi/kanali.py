import json
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

from app.alarmi.evidencija import REDOSLED, Alarm
from app.provere import Ozbiljnost

OZNAKE = {Ozbiljnost.INFO: "INFO", Ozbiljnost.UPOZORENJE: "UPOZORENJE",
          Ozbiljnost.KRITICNO: "KRITIČNO"}


def tekst_poruke(alarmi: list[Alarm], zona: ZoneInfo) -> tuple[str, str]:
    """Vraća naslov i telo poruke. Vremena su po lokalnom vremenu (`zona`)."""
    if len(alarmi) == 1:
        a = alarmi[0]
        naslov = f"[{OZNAKE[a.ozbiljnost]}] {a.tip}: {a.model} / {a.izvor}"
    else:
        najgori = max(alarmi, key=lambda a: REDOSLED[a.ozbiljnost])
        naslov = f"[{OZNAKE[najgori.ozbiljnost]}] {len(alarmi)} alarma iz monitoringa modela"

    redovi = []
    for a in alarmi:
        od = a.od.astimezone(zona)
        do = a.do.astimezone(zona)
        redovi += [
            f"#{a.id} [{OZNAKE[a.ozbiljnost]}] {a.tip} | {a.model} / {a.izvor}",
            f"    od {od:%d.%m.%Y %H:%M} do {do:%d.%m.%Y %H:%M}",
            f"    {a.opis}",
            "",
        ]
    redovi.append("Pregled i potvrda: python -m app.alarmi")
    return naslov, "\n".join(redovi)


class EkranKanal:
    def __init__(self, zona: ZoneInfo):
        self.zona = zona

    def posalji(self, alarmi: list[Alarm]) -> None:
        naslov, telo = tekst_poruke(alarmi, self.zona)
        print(f"\n=== {naslov} ===\n{telo}\n")


class DnevnikKanal:
    def __init__(self, putanja: Path, zona: ZoneInfo):
        self.putanja, self.zona = Path(putanja), zona

    def posalji(self, alarmi: list[Alarm]) -> None:
        naslov, telo = tekst_poruke(alarmi, self.zona)
        self.putanja.parent.mkdir(parents=True, exist_ok=True)
        with self.putanja.open("a", encoding="utf-8") as f:
            f.write(f"=== {naslov} ===\n{telo}\n\n")


class MejlKanal:
    """Mejl iz ručno napisane konfiguracije (koraci 4-6). Šalje se isto kao sa stranice (korak 8)."""

    def __init__(self, server: str, port: int, korisnik: str | None, lozinka: str | None,
                 posiljalac: str, primaoci: list[str], zona: ZoneInfo):
        self.server, self.port = server, port
        self.korisnik, self.lozinka = korisnik, lozinka
        self.posiljalac, self.primaoci, self.zona = posiljalac, primaoci, zona

    def posalji(self, alarmi: list[Alarm]) -> None:
        from app.alarmi.mejl import mejl_odmah, posalji  # šifrovana veza, provera sertifikata
        naslov, tekst, html_ = mejl_odmah(alarmi, self.zona, None)
        posalji(self.server, self.port, self.korisnik, self.lozinka, self.posiljalac,
                self.primaoci, naslov, tekst, html_)


class WebhookKanal:
    """Šalje {"text": "..."} na zadatu adresu. To razume većina alata za ćaskanje."""

    def __init__(self, url: str, zona: ZoneInfo):
        self.url, self.zona = url, zona

    def posalji(self, alarmi: list[Alarm]) -> None:
        naslov, telo = tekst_poruke(alarmi, self.zona)
        podaci = json.dumps({"text": f"{naslov}\n\n{telo}"}).encode("utf-8")
        zahtev = urllib.request.Request(self.url, data=podaci, method="POST",
                                        headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(zahtev, timeout=30):
            pass