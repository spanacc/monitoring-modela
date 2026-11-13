from collections import Counter
from datetime import datetime

from app.provere.osnova import Granice, Nalaz, Ozbiljnost, napravi, trajanje, u_intervale
from app.schema import Rezultat, Status


def proveri_izostanke(serija: list[Rezultat], g: Granice, sada: datetime) -> list[Nalaz]:
    """
    Traži pauze duže od `g.max_pauza` (naučeno iz normalnog perioda).

    Proverava i kraj: ako je poslednji rezultat star, model je možda
    stao. To je "tišina" iz plana, i to je najvažniji alarm, jer model
    koji ćuti ne može ni da prijavi da nešto ne valja.
    """
    vremena = sorted({r.vreme for r in serija})
    nalazi = []

    for pre, posle in zip(vremena, vremena[1:]):
        if posle - pre > g.max_pauza:
            nalazi.append(napravi(
                "izostanak", serija, pre + g.korak, posle, Ozbiljnost.KRITICNO,
                f"Rezultati nisu stizali {trajanje(posle - pre - g.korak)} "
                f"(inače stižu na svakih {trajanje(g.korak)}).",
            ))

    if sada - vremena[-1] > g.max_pauza:
        nalazi.append(napravi(
            "izostanak", serija, vremena[-1] + g.korak, sada, Ozbiljnost.KRITICNO,
            f"Poslednji rezultat je star {trajanje(sada - vremena[-1])}. "
            "Model je možda prestao da radi.",
        ))
    return nalazi


def proveri_duplikate(serija: list[Rezultat], g: Granice) -> list[Nalaz]:
    """Traži više rezultata za isto vreme (u istoj seriji)."""
    broj = Counter(r.vreme for r in serija)
    ponovljena = [t for t, n in broj.items() if n > 1]
    return [
        napravi("duplikat", serija, od, do, Ozbiljnost.INFO,
                f"Isti rezultat je stigao više puta (najviše {max(broj.values())} puta).")
        for od, do in u_intervale(ponovljena, g.korak)
    ]


def proveri_greske_modela(serija: list[Rezultat], g: Granice) -> list[Nalaz]:
    """Traži rezultate u kojima je model javio grešku."""
    sa_greskom = [r for r in serija if r.status == Status.GRESKA]
    nalazi = []
    for od, do in u_intervale([r.vreme for r in sa_greskom], g.korak):
        poruka = next(r.poruka for r in sa_greskom if r.vreme == od) or "bez poruke"
        nalazi.append(napravi(
            "greska_modela", serija, od, do, Ozbiljnost.UPOZORENJE,
            f"Model je javio grešku: {poruka}",
        ))
    return nalazi