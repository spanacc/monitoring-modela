"""
Univerzalni format jednog rezultata modela.

ŠTA JE OVO
----------
Ma koji model da pratimo, svaki njegov rezultat prevodimo u ovaj isti oblik.
Ostatak aplikacije (provere, alarmi, dashboard) radi samo sa ovim oblikom i
ne zna ništa o tome odakle je rezultat stigao ni šta model radi.

ZAŠTO
-----
Zato što o modelu ne znamo ništa. Ako bi aplikacija bila pravljena za jedan
konkretan model, morala bi da se prepravlja za svaki novi. Ovako se za novi
model pravi samo mali "prevodilac" (adapter), a sve ostalo ostaje isto.

KAKO
----
Koristimo biblioteku `pydantic`. Ona automatski proverava da li je svako polje
ispravnog tipa (vreme je vreme, broj je broj) i odbija neispravne podatke sa
jasnom porukom o grešci.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, model_validator


class Status(str, Enum):
    """Da li je model uspešno vratio rezultat ili je javio grešku."""

    OK = "ok"
    GRESKA = "greska"


class Rezultat(BaseModel):
    """Jedan rezultat koji je model vratio."""

    # --- Obavezna polja: bez njih rezultat nema smisla ---

    vreme: datetime = Field(
        description="Kada je rezultat nastao. Mora imati vremensku zonu, "
        "da ne bi bilo zabune oko letnjeg i zimskog računanja vremena."
    )
    model: str = Field(
        min_length=1,
        description="Naziv modela koji je dao rezultat, npr. 'senzori'. "
        "Omogućava da jedna aplikacija prati više modela.",
    )
    izvor: str = Field(
        min_length=1,
        description="Na šta se rezultat odnosi: mašina, lokacija, uređaj...",
    )
    velicina: str = Field(
        min_length=1,
        description="Šta je predviđeno ili izmereno, npr. 'temperatura'.",
    )

    # --- Vrednost: model vraća ili broj, ili kategoriju ---

    vrednost: float | None = Field(
        default=None,
        description="Broj koji je model vratio. Prazno ako model vraća "
        "kategoriju ili ako rezultat nedostaje.",
    )
    kategorija: str | None = Field(
        default=None,
        description="Kategorija koju je model vratio, npr. 'ispravno'. "
        "Koristi se za modele koji ne vraćaju brojeve.",
    )

    # --- Neobavezna polja: koriste se kad postoje ---

    jedinica: str | None = Field(default=None, description="Npr. '°C', 'kWh'.")
    horizont_min: int | None = Field(
        default=None,
        ge=0,
        description="Koliko minuta unapred model predviđa. Prazno ako model "
        "ne predviđa budućnost nego procenjuje sadašnjost.",
    )
    stvarna_vrednost: float | None = Field(
        default=None,
        description="Ono što se zaista desilo (izmereno). Stiže kasnije i "
        "služi za merenje tačnosti. Često ne postoji.",
    )
    stvarna_kategorija: str | None = Field(
        default=None,
        description="Ista stvar kao stvarna_vrednost, ali za kategorije.",
    )
    status: Status = Field(default=Status.OK)
    poruka: str | None = Field(
        default=None, description="Poruka o grešci, ako je model javi."
    )

    # --- Provere koje važe za ceo rezultat ---

    @model_validator(mode="after")
    def proveri(self) -> "Rezultat":
        """
        Dodatna pravila koja pydantic ne može sam da zna:

        1. Vreme mora imati vremensku zonu.
        2. Rezultat je ili broj ili kategorija, ne oba.

        Namerno NE zahtevamo da vrednost postoji: prazan rezultat je
        upravo jedna od stvari koje monitoring treba da primeti i prijavi,
        a ne da odbaci pre nego što ga vidi.
        """
        if self.vreme.tzinfo is None:
            raise ValueError(
                "Vreme mora imati vremensku zonu (npr. 2026-11-10T14:00:00+01:00)."
            )
        if self.vrednost is not None and self.kategorija is not None:
            raise ValueError("Rezultat ne može istovremeno imati i broj i kategoriju.")
        return self

    @property
    def je_prazan(self) -> bool:
        """Da li rezultat nema ni broj ni kategoriju."""
        return self.vrednost is None and self.kategorija is None