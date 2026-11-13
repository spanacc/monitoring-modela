from datetime import datetime

from app.provere.osnova import (
    Granice,
    Nalaz,
    Ozbiljnost,
    Tacke,
    napravi,
    odskoci_od_suseda,
    u_intervale,
)
from app.schema import Rezultat, Status


def vrednosti(serija: list[Rezultat]) -> Tacke:
    """Sve brojčane vrednosti koje je model vratio, sa vremenom."""
    return [(r.vreme, r.vrednost) for r in serija if r.vrednost is not None]


def proveri_prazne(serija: list[Rezultat], g: Granice) -> list[Nalaz]:
    """
    Traži rezultate bez vrednosti, a bez prijavljene greške.

    Rezultati sa greškom se ovde ne računaju, jer njih već prijavljuje
    provera greske_modela. Inače bi isti problem bio prijavljen dvaput.
    """
    vremena = [r.vreme for r in serija if r.status == Status.OK and r.je_prazan]
    return [
        napravi("prazne_vrednosti", serija, od, do, Ozbiljnost.UPOZORENJE,
                "Rezultati su stizali, ali bez vrednosti.")
        for od, do in u_intervale(vremena, g.korak)
    ]


def nemoguce_tacke(serija: list[Rezultat], g: Granice) -> dict[datetime, float]:
    """
    Vraća vrednosti koje odskaču od susednih više od `g.max_odskok_vrednosti`
    (naučeno iz normalnog perioda). Npr. 9999 kad su sve okolo oko 60.

    Ovu funkciju koriste i provere tačnosti, da takve vrednosti ne bi
    pokvarile računanje greške modela.
    """
    if g.max_odskok_vrednosti is None:
        return {}
    tacke = vrednosti(serija)
    odskoci = odskoci_od_suseda(tacke, g.prozor)
    return {t: v for (t, v), o in zip(tacke, odskoci) if abs(o) > g.max_odskok_vrednosti}


def proveri_nemoguce(serija: list[Rezultat], g: Granice) -> list[Nalaz]:
    tacke = nemoguce_tacke(serija, g)
    return [
        napravi("nemoguca_vrednost", serija, od, do, Ozbiljnost.UPOZORENJE,
                f"Vrednost {tacke[od]:g} naglo odskače od susednih vrednosti, "
                "više nego bilo šta u normalnom periodu.")
        for od, do in u_intervale(list(tacke), g.korak)
    ]