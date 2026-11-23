"""
Konfiguracija: sva podešavanja nadzora u jednom JSON fajlu.

ŠTA JE U FAJLU
--------------
    izvori       koji fajlovi se prate (i, ako treba, ručno mapiranje kolona)
    provere      osetljivost (rezerva) za sve modele
    modeli       posebna osetljivost za pojedinačne modele, ako treba
    kanali       kuda se šalju obaveštenja (ekran, dnevnik, mejl, poruka)
    slanje       koji nivo ozbiljnosti ide na koje kanale
    zona         vremenska zona za čitanje fajlova i za vremena u porukama
    baza         adresa baze u kojoj se čuvaju rezultati i alarmi
    dana_provere koliko poslednjih dana se proverava

Primer je u `konfiguracija.primer.json` u glavnom folderu projekta.

ZAŠTO FAJL, A NE KOD
--------------------
Princip iz plana: podešava se, ne programira. Da bi se dodao nov fajl za
praćenje, promenio primalac mejla ili smanjio broj alarma za jedan model,
menja se samo ovaj fajl.

PROVERA
-------
Fajl se proverava pri učitavanju (pydantic). Ako nešto ne valja, npr.
kanal koji ne postoji ili pogrešno napisano polje, aplikacija odmah javlja
jasnu grešku, umesto da se pokvari kasnije, usred noći.
"""

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
    # CSV fajl sa rezultatima. Može i sa zvezdicom, npr. "data/rezultati/*.csv":
    # tada se prate svi takvi fajlovi (uz zvezdicu obavezno zadati i model).
    putanja: Path
    model: str | None = None  # naziv modela; podrazumevano ime fajla
    mapiranje: Path | None = None  # ručno mapiranje kolona u posebnom JSON fajlu (korak 2)
    # Isto to, ali upisano ovde: koje polje je koja kolona, npr.
    # {"vreme": "dteday", "doba_dana": "hr", "vrednost": "cnt"}. Ovo upisuje
    # dashboard kad se podaci dodaju sa stranice (korak 7).
    polja: dict[str, str] | None = None
    redosled_datuma: Literal["dm", "md"] = "dm"  # za datume sa kosim crtama
    # Široka tabela: svaka od ovih kolona je poseban izvor (npr. senzor).
    # ["sve"] = sve kolone sa brojevima.
    kolone: list[str] | None = None
    # Stari podaci (proba, arhiva): "sada" je vreme poslednjeg rezultata, pa
    # aplikacija ne javlja da model ćuti godinama. U pravom radu je False.
    istorijski: bool = False

    def napravi_mapiranje(self):
        """Mapiranje kolona iz podešavanja, ako je zadato (inače se prepoznaje samo)."""
        from app.prepoznavanje import Mapiranje
        if self.polja:
            return Mapiranje.iz_recnika({"polja": self.polja, "redosled_datuma": self.redosled_datuma})
        if self.mapiranje:
            return Mapiranje.ucitaj(self.mapiranje)
        return None


class OsetljivostModela(Strogo):
    rezerva: float | None = None
    udeo_osnove: float | None = None
    dana_osnove: float | None = None
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
    baza: str = "sqlite:///data/monitoring.db"  # adresa baze (korak 5)
    # Prijavljuju se samo problemi iz poslednjih toliko dana. Starije ne
    # treba ni čitati iz baze, pa nadzor ostaje brz. None = proveri sve.
    dana_provere: float | None = 30
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

    def istorijski_modeli(self) -> set[str]:
        """Modeli čiji su izvori označeni kao stari podaci."""
        return {i.model or i.putanja.stem for i in self.izvori if i.istorijski}

    def sacuvaj(self, putanja: Path) -> None:
        """Upisuje podešavanja u JSON fajl (samo ono što nije podrazumevano)."""
        podaci = self.model_dump(mode="json", exclude_defaults=True)
        podaci["izvori"] = [i.model_dump(mode="json", exclude_defaults=True) for i in self.izvori]
        Path(putanja).parent.mkdir(parents=True, exist_ok=True)
        Path(putanja).write_text(json.dumps(podaci, ensure_ascii=False, indent=2), encoding="utf-8")

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


# Podešavanja koja dashboard sam pravi i menja kad se podaci dodaju sa stranice.
PODRAZUMEVANA_PUTANJA = Path("data/podesavanja.json")


def ucitaj_ili_prazna(putanja: Path = PODRAZUMEVANA_PUTANJA) -> Konfiguracija:
    """Podešavanja iz fajla, a ako fajla još nema: prazna (bez ijednog izvora)."""
    if Path(putanja).exists():
        return ucitaj_konfiguraciju(putanja)
    return Konfiguracija(izvori=[])


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
