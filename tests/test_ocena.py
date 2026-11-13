"""
Glavna provera koraka 3: na podacima iz simulatora provere moraju naći
svih 10 ubačenih problema, bez ijedne lažne uzbune.

Proveravamo na više različitih "semena" (skupova slučajnih podataka),
da bismo bili sigurni da provere ne rade samo slučajno na jednom skupu.
"""

import pytest

from app.provere import proveri_sve
from simulator.modeli import SVI_MODELI
from simulator.ocena import oceni


def simuliraj_sve(seed):
    rezultati, problemi = [], []
    for i, simuliraj in enumerate(SVI_MODELI.values()):
        sim = simuliraj(dani=30, seed=seed * 10 + i + 1)
        rezultati += sim.rezultati
        problemi += sim.problemi_kao_recnik()
    return rezultati, problemi


@pytest.mark.parametrize("seed", [0, 1, 2, 3, 4])
def test_svi_ubaceni_problemi_su_pronadjeni_bez_laznih_uzbuna(seed):
    rezultati, problemi = simuliraj_sve(seed)
    ocena = oceni(proveri_sve(rezultati), problemi)

    assert ocena.promaseni == []
    assert ocena.lazni == []
    assert len(ocena.pronadjeni) == 10


def test_bez_stvarnih_vrednosti_i_dalje_radi_sve_sto_moze():
    # Ako stvarne vrednosti nikad ne dobijemo: pristrasnost, promašen skok
    # i pad tačnosti ne mogu da se otkriju, ali sve ostalo mora da radi,
    # uključujući drift, i opet bez lažnih uzbuna.
    rezultati, problemi = simuliraj_sve(seed=0)
    bez_stvarnih = [r.model_copy(update={"stvarna_vrednost": None,
                                         "stvarna_kategorija": None})
                    for r in rezultati]

    ocena = oceni(proveri_sve(bez_stvarnih), problemi)

    pronadjeni = {p["tip"] for p in ocena.pronadjeni}
    promaseni = {p["tip"] for p in ocena.promaseni}
    assert promaseni == {"pristrasnost", "promasen_skok", "pad_tacnosti"}
    assert {"izostanak", "duplikat", "greska_modela", "prazne_vrednosti",
            "nemoguca_vrednost", "drift"} <= pronadjeni
    assert ocena.lazni == []