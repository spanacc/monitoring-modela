import json
import os
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from app.alarmi.kanali import DnevnikKanal, EkranKanal, MejlKanal, WebhookKanal
from app.provere import Ozbiljnost, Podesavanja


class Strogo(BaseModel):
    # Nepoznato polje je greška: tako se odmah vidi slovna greška u fajlu.
    model_config = ConfigDict(extra="forbid")


class Izvor(Strogo):
    putanja: Path  # CSV fajl sa rezultatima
    model: str | None = None  # naziv modela; podrazumevano ime fajla
    mapiranje: Path | None = None  # ručno mapiranje kolona (korak 2)


class OsetljivostModela(Strogo):
    rezerva: float | None = None
    udeo_osnove: float | None = None
    prag_pristrasnosti: float | None = None


class Kanal(Strogo):
    tip: Literal["ekran", "dnevnik", "mejl", "poruka"]
    # dnevnik
    putanja: Path | None = None
    # mejl
    server: str | None = None
    port: int = 587
    korisnik: str | None = None
    lozinka_iz: str | None = None  # IME promenljive okruženja sa lozinkom
    od: str | None = None
    za: list[str] = []
    # poruka (webhook)
    adresa_iz: str | None = None  # IME promenljive okruženja sa adresom


class Konfiguracija(Strogo):
    izvori: list[Izvor]
    zona: str = "Europe/Belgrade"
    evidencija: Path = Path("data/alarmi.json")
    provere: OsetljivostModela = OsetljivostModela()
    modeli: dict[str, OsetljivostModela] = {}
    kanali: dict[str, Kanal] = {"ekran": Kanal(tip="ekran")}
    slanje: dict[Ozbiljnost, list[str]] = {
        Ozbiljnost.INFO: [],
        Ozbiljnost.UPOZORENJE: ["ekran"],
        Ozbiljnost.KRITICNO: ["ekran"],
    }

    @model_validator(mode="after")
    def proveri_slanje(self) -> "Konfiguracija":
        for nivo, imena in self.slanje.items():
            for ime in imena:
                if ime not in self.kanali:
                    raise ValueError(
                        f"U 'slanje' za '{nivo.value}' piše kanal '{ime}', a on nije "
                        f"definisan u 'kanali' (postoje: {', '.join(self.kanali)})."
                    )
        return self

    def podesavanja_za(self, model: str) -> Podesavanja:
        """Opšta osetljivost, a preko nje posebna za ovaj model, ako postoji."""
        vrednosti = self.provere.model_dump(exclude_none=True)
        if model in self.modeli:
            vrednosti.update(self.modeli[model].model_dump(exclude_none=True))
        return Podesavanja(**vrednosti)

    def napravi_kanal(self, ime: str):
        """Pravi kanal po imenu. Tajne čita iz promenljivih okruženja."""
        k = self.kanali[ime]
        zona = ZoneInfo(self.zona)
        if k.tip == "ekran":
            return EkranKanal(zona)
        if k.tip == "dnevnik":
            return DnevnikKanal(k.putanja or Path("data/obavestenja.log"), zona)
        if k.tip == "mejl":
            if not (k.server and k.od and k.za):
                raise ValueError(f"Kanal '{ime}': za mejl su obavezni 'server', 'od' i 'za'.")
            lozinka = procitaj_tajnu(k.lozinka_iz, ime) if k.lozinka_iz else None
            return MejlKanal(k.server, k.port, k.korisnik, lozinka, k.od, k.za, zona)
        if k.tip == "poruka":
            if not k.adresa_iz:
                raise ValueError(f"Kanal '{ime}': za poruku je obavezno 'adresa_iz'.")
            return WebhookKanal(procitaj_tajnu(k.adresa_iz, ime), zona)
        raise ValueError(f"Nepoznat tip kanala: {k.tip}")


def procitaj_tajnu(promenljiva: str, kanal: str) -> str:
    vrednost = os.environ.get(promenljiva)
    if not vrednost:
        raise ValueError(
            f"Kanal '{kanal}' traži promenljivu okruženja {promenljiva}, a ona nije "
            f"postavljena. Na Mac-u/Linux-u: export {promenljiva}=..."
        )
    return vrednost


def ucitaj_konfiguraciju(putanja: Path) -> Konfiguracija:
    """Učitava i proverava fajl. Svaku grešku pretvara u jasnu poruku."""
    try:
        podaci = json.loads(Path(putanja).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(f"Nema fajla {putanja}. "
                         "Napravite ga po uzoru na konfiguracija.primer.json.")
    except json.JSONDecodeError as e:
        raise ValueError(f"{putanja} nije ispravan JSON: {e.msg}, red {e.lineno}, kolona {e.colno}.")
    try:
        return Konfiguracija.model_validate(podaci)
    except ValidationError as e:
        poruke = [f"{'.'.join(str(x) for x in g['loc']) or 'fajl'}: "
                  f"{PREVODI.get(g['type'], g['msg'].removeprefix('Value error, '))}"
                  for g in e.errors()]
        raise ValueError("\n  ".join([f"{putanja} ne valja:"] + poruke))


# Prevodi najčešćih grešaka iz pydantic-a.
PREVODI = {
    "extra_forbidden": "nepoznato polje (proverite da li je dobro napisano)",
    "missing": "obavezno polje nedostaje",
}