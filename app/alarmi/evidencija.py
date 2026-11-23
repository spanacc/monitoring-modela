"""
Evidencija alarma: jedan problem je jedan alarm, ma koliko puta bio pronađen.

KAKO RADI
---------
Svaki put kad provere završe, nalazi se "usklađuju" sa evidencijom:

- Nalaz koji odgovara postojećem alarmu (isti tip, model i izvor, i vremena
  se dodiruju) samo produži taj alarm. Obaveštenje se NE šalje ponovo.
- Nalaz kome ne odgovara nijedan alarm postaje NOV alarm i šalje se.
- Obaveštenje se šalje ponovo samo kad se nešto bitno promeni:
    * problem se pogoršao (npr. upozorenje je postalo kritično), ili
    * problem je bio označen kao rešen, a ponovo se javlja.
- Alarm koji provere više ne nalaze (problem je prošao, npr. podaci su
  opet počeli da stižu) sam se zatvara, sa napomenom "Prestalo samo."
  (korak 7). Tako niko ne mora ručno da "rešava" probleme.

STATUSI
-------
    otvoren    nov alarm, niko ga još nije pogledao
    potvrdjen  neko ga je video i zna za njega ("radimo na tome")
    resen      problem je otklonjen

ČUVANJE
-------
U bazi (korak 5). Za testove i probu može i u JSON fajlu. Ostatak
aplikacije ne zna razliku, jer koristi samo ovu klasu.
"""

import json
from datetime import datetime
from enum import Enum
from pathlib import Path

from pydantic import BaseModel

from app.provere import Nalaz, Ozbiljnost

# Redosled ozbiljnosti, da bi moglo da se kaže "kritično je gore od upozorenja".
REDOSLED = {Ozbiljnost.INFO: 0, Ozbiljnost.UPOZORENJE: 1, Ozbiljnost.KRITICNO: 2}


class StatusAlarma(str, Enum):
    OTVOREN = "otvoren"
    POTVRDJEN = "potvrdjen"
    RESEN = "resen"


class Alarm(BaseModel):
    """Jedan alarm: nalaz, plus sve što treba da bi se pratio kroz vreme."""

    id: int
    tip: str
    model: str
    izvor: str
    od: datetime
    do: datetime
    ozbiljnost: Ozbiljnost
    opis: str
    status: StatusAlarma = StatusAlarma.OTVOREN
    prvi_put: datetime  # kad ga je aplikacija prvi put primetila
    poslednji_put: datetime  # kad ga je poslednji put videla
    za_slanje: bool = True  # obaveštenje čeka da bude poslato
    potvrdio: str | None = None
    napomena: str | None = None


class Evidencija:
    """
    Spisak svih alarma. Čuva se u bazi (korak 5) ili, za probu, u JSON fajlu.
    Ostatak aplikacije ne zna gde: koristi samo ovu klasu.
    """

    def __init__(self, putanja: Path | None = None, baza=None):
        self.putanja = Path(putanja) if putanja else None
        self.baza = baza
        self.alarmi: list[Alarm] = []
        if self.baza:
            self.alarmi = self.baza.ucitaj_alarme()
        elif self.putanja and self.putanja.exists():
            podaci = json.loads(self.putanja.read_text(encoding="utf-8"))
            self.alarmi = [Alarm.model_validate(a) for a in podaci]

    def sacuvaj(self) -> None:
        if self.baza:
            self.baza.sacuvaj_alarme(self.alarmi)
            return
        self.putanja.parent.mkdir(parents=True, exist_ok=True)
        podaci = [a.model_dump(mode="json") for a in self.alarmi]
        self.putanja.write_text(json.dumps(podaci, ensure_ascii=False, indent=2),
                                encoding="utf-8")

    # --- usklađivanje sa nalazima ---

    PRESTALO = "Prestalo samo."

    def uskladi(self, nalazi: list[Nalaz], sada: datetime,
                zatvori_nestale: bool = False) -> list[Alarm]:
        """
        Upisuje nalaze u evidenciju. Vraća alarme o kojima treba obavestiti
        ljude (novi, pogoršani i oni koji su se vratili posle rešavanja).

        zatvori_nestale: alarme koje nijedan nalaz nije potvrdio označi kao
        rešene ("prestalo samo"). Koristi se samo kad je krug prošao bez
        greške, da privremeni kvar (npr. fajl trenutno nedostupan) ne bi
        zatvorio prave probleme.
        """
        za_obavestenje = []
        vidjeni: set[int] = set()
        for n in nalazi:
            a = self._nadji(n)
            if a is not None:
                vidjeni.add(a.id)
            if a is None:
                a = Alarm(id=self._sledeci_id(), tip=n.tip, model=n.model, izvor=n.izvor,
                          od=n.od, do=n.do, ozbiljnost=n.ozbiljnost, opis=n.opis,
                          prvi_put=sada, poslednji_put=sada)
                self.alarmi.append(a)
                za_obavestenje.append(a)
                vidjeni.add(a.id)
                continue

            traje_duze = n.do > a.do
            a.od, a.do = min(a.od, n.od), max(a.do, n.do)
            a.opis, a.poslednji_put = n.opis, sada

            if a.status == StatusAlarma.RESEN and traje_duze:
                # Bio je rešen, a problem se nastavlja: otvara se ponovo.
                a.status, a.potvrdio = StatusAlarma.OTVOREN, None
                a.za_slanje = True
                za_obavestenje.append(a)
            elif REDOSLED[n.ozbiljnost] > REDOSLED[a.ozbiljnost]:
                # Pogoršalo se: javljamo ponovo.
                a.ozbiljnost = n.ozbiljnost
                a.za_slanje = True
                za_obavestenje.append(a)

        if zatvori_nestale:
            for a in self.alarmi:
                if a.id not in vidjeni and a.status != StatusAlarma.RESEN:
                    a.status = StatusAlarma.RESEN
                    a.napomena = self.PRESTALO
                    a.poslednji_put = sada
        return za_obavestenje

    def _nadji(self, n: Nalaz) -> Alarm | None:
        """Postojeći alarm za isti problem: isti tip, model, izvor i vremena se dodiruju."""
        kandidati = [a for a in self.alarmi
                     if (a.tip, a.model, a.izvor) == (n.tip, n.model, n.izvor)
                     and a.od <= n.do and n.od <= a.do]
        return kandidati[-1] if kandidati else None

    def _sledeci_id(self) -> int:
        return max((a.id for a in self.alarmi), default=0) + 1

    # --- rad sa alarmima (ljudi) ---

    def nadji_po_id(self, id_: int) -> Alarm:
        for a in self.alarmi:
            if a.id == id_:
                return a
        raise KeyError(f"Nema alarma sa brojem {id_}.")

    def potvrdi(self, id_: int, ko: str, napomena: str | None = None) -> Alarm:
        """Neko je video alarm. Dok traje, više se ne javlja."""
        a = self.nadji_po_id(id_)
        a.status, a.potvrdio = StatusAlarma.POTVRDJEN, ko
        if napomena:
            a.napomena = napomena
        return a

    def resi(self, id_: int, napomena: str | None = None) -> Alarm:
        """Problem je otklonjen. Ako se ponovo javi, alarm se ponovo otvara."""
        a = self.nadji_po_id(id_)
        a.status = StatusAlarma.RESEN
        if napomena:
            a.napomena = napomena
        return a

    def otvoreni(self) -> list[Alarm]:
        """Alarmi koji nisu rešeni, najozbiljniji prvi."""
        return sorted((a for a in self.alarmi if a.status != StatusAlarma.RESEN),
                      key=lambda a: (-REDOSLED[a.ozbiljnost], a.od))
