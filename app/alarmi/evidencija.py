import json
from datetime import datetime
from enum import Enum
from pathlib import Path

from pydantic import BaseModel

from app.provere import Nalaz,Ozbiljnost

REDOSLED = {Ozbiljnost.INFO: 0, Ozbiljnost.UPOZORENJE: 1, Ozbiljnost.KRITICNO: 2}

class StatusAlarma(str,Enum):
    OTVOREN = "otvoren"
    POTVRDJEN = "potvrdjen"
    RESEN =  "resen"

class Alarm(BaseModel):
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

    def __init__(self,putanja:Path):
        self.putanja = Path(putanja)
        self.alarmi: list[Alarm] = []
        if self.putanja.exists():
            podaci = json.loads(self.putanja.read_text(encoding="utf-8"))
            self.alarmi = [Alarm.model_validate(a) for a in podaci]

    def sacuvaj(self) -> None:
        self.putanja.parent.mkdir(parents=True, exist_ok=True)
        podaci = [a.model_dump(mode="json") for a in self.alarmi]
        self.putanja.write_text(json.dumps(podaci, ensure_ascii=False, indent=2),
                                encoding="utf-8")

    def uskladi(self, nalazi: list[Nalaz], sada: datetime) -> list[Alarm]:
        """
        Upisuje nalaze u evidenciju. Vraća alarme o kojima treba obavestiti
        ljude (novi, pogoršani i oni koji su se vratili posle rešavanja).
        """
        za_obavestenje = []
        for n in nalazi:
            a = self._nadji(n)
            if a is None:
                a = Alarm(id=self._sledeci_id(), tip=n.tip, model=n.model, izvor=n.izvor,
                          od=n.od, do=n.do, ozbiljnost=n.ozbiljnost, opis=n.opis,
                          prvi_put=sada, poslednji_put=sada)
                self.alarmi.append(a)
                za_obavestenje.append(a)
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