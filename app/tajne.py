"""
Čuvanje tajni (za sad: lozinka mejl naloga).

KAKO
----
Lozinka se upiše jednom, na stranici sa podešavanjima. Aplikacija je odmah
šifruje (biblioteka `cryptography`, postupak Fernet: AES sa proverom da niko
nije menjao sadržaj) i čuva u `data/tajne/`:

    data/tajne/kljuc        ključ za šifrovanje (pravi se sam, prvi put)
    data/tajne/mejl.tajna   šifrovana lozinka

Oba fajla smeju da čita samo korisnik koji pokreće aplikaciju (prava 600),
a folder `data/` nikad ne ide na git. Stranica lozinku posle više ne
prikazuje: server je nikad ne šalje nazad, samo kaže da je sačuvana.

ŠTA OVO ŠTITI, A ŠTA NE (iskreno)
---------------------------------
Štiti od slučajnog curenja: lozinka nije u podešavanjima, nije na git-u, ne
vidi se na ekranu, u snimku ekrana ni u dnevniku. Ako neko kopira samo
`podesavanja.json` ili samo `mejl.tajna`, ne može da je pročita.

Ne štiti od nekoga ko ima potpun pristup računaru (ima i ključ i šifrovan
fajl). Za server je zato bolje da ključ ne stoji pored fajla, nego u
promenljivoj okruženja MONITORING_KLJUC, ili da se lozinka uopšte ne upisuje
na stranici nego postavi kao MONITORING_MEJL_LOZINKA. Ako je ta promenljiva
postavljena, ona ima prednost nad svim ostalim.
"""

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

FOLDER = Path("data/tajne")
PROMENLJIVA_KLJUCA = "MONITORING_KLJUC"
NAJDUZA = 512  # tajna duža od ovoga nije lozinka nego greška


def _upisi_zakljucano(putanja: Path, sadrzaj: bytes) -> None:
    """Upisuje fajl tako da ga od samog početka čita samo vlasnik (600)."""
    putanja.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(putanja.parent, 0o700)
    except OSError:
        pass  # npr. Windows: prava se ne podešavaju ovako
    privremeni = putanja.with_suffix(putanja.suffix + ".novo")
    fd = os.open(privremeni, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(sadrzaj)
    os.replace(privremeni, putanja)  # odjednom: nikad pola fajla


def _kljuc(folder: Path) -> Fernet:
    """Ključ iz promenljive okruženja, inače iz fajla (pravi se prvi put)."""
    iz_okruzenja = os.environ.get(PROMENLJIVA_KLJUCA)
    if iz_okruzenja:
        return Fernet(iz_okruzenja.encode())
    putanja = folder / "kljuc"
    if not putanja.exists():
        _upisi_zakljucano(putanja, Fernet.generate_key())
    return Fernet(putanja.read_bytes().strip())


def sacuvaj(ime: str, vrednost: str, folder: Path | None = None) -> None:
    folder = folder or FOLDER
    if not vrednost or len(vrednost) > NAJDUZA:
        raise ValueError("Lozinka je prazna ili predugačka.")
    _upisi_zakljucano(folder / f"{ime}.tajna", _kljuc(folder).encrypt(vrednost.encode("utf-8")))


def procitaj(ime: str, folder: Path | None = None) -> str | None:
    """Tajna ili None ako nije sačuvana. Greška ako fajl ne može da se dešifruje."""
    folder = folder or FOLDER
    putanja = folder / f"{ime}.tajna"
    if not putanja.exists():
        return None
    try:
        return _kljuc(folder).decrypt(putanja.read_bytes()).decode("utf-8")
    except InvalidToken:
        raise ValueError("Sačuvana lozinka ne može da se pročita (promenjen ključ?). "
                         "Upišite je ponovo u podešavanjima.") from None


def postoji(ime: str, folder: Path | None = None) -> bool:
    return ((folder or FOLDER) / f"{ime}.tajna").exists()


def obrisi(ime: str, folder: Path | None = None) -> None:
    ((folder or FOLDER) / f"{ime}.tajna").unlink(missing_ok=True)
