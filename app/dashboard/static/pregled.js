/*
 * Glavna stranica: tri pločice (stanje, odstupanje, problemi), veliki
 * grafikon izabranog modela i spisak problema desno.
 *
 * KAKO RADI
 *   1. Na svakih 15 s pita server samo za "verziju" podataka (par bajtova).
 *   2. Ako se verzija promenila, učita pregled, probleme i grafikon izabranog
 *      modela, pa ponovo crta. Inače ne radi ništa.
 *   3. Grafikon sam prikaže model koji ima problem. Kad čovek klikne neki
 *      drugi model, ostaje na njemu (dok ne osveži stranicu).
 *
 * Aplikacija ne zna ništa o modelu: nazivi modela i izvora stižu iz fajlova
 * koji su dodati u podešavanjima.
 */

import {
  $, DAN, SAT, api, broj, datum, h, mnozina, naslovOblacica, obavesti, postaviZonu, prikaziOblacic,
  raspon, s, saJedinicom, sakrijOblacic, satMinut, seti, starost, svgTekst, vreme, zapamti,
} from "./alati.js";

const OSVEZAVANJE_MS = 15000;
const PERIODI = [1, 7, 30, 180, 3660];
const RANG = { info: 1, upozorenje: 2, kriticno: 3 };
const OZBILJNOST = { kriticno: "Hitno", upozorenje: "Problem", info: "Napomena" };
const GRAFIK = { levo: 52, desno: 18, gore: 18, dole: 30 }; // margine grafikona

const st = {
  dana: 30,
  periodRucno: false, // da li je čovek sam izabrao period
  izbor: null,        // {model, izvor} na grafikonu
  rucno: false,       // da li je čovek sam izabrao model (onda ga ne menjamo sami)
  verzija: null,
  pregled: null,
  alarmi: [],
  serija: null,
  nadzor: null,
  poPodacima: false,
  istaknut: null,     // grupa problema istaknuta na grafikonu ("Prikaži na grafikonu")
};

// ---------------------------------------------------------------------------
// Pomoćno
// ---------------------------------------------------------------------------

/** Fajl bez kolone sa izvorom daje izvor "glavni"; tada se piše samo ime modela. */
const imeIzvora = (izvor, velicina) => (izvor === "glavni" ? (velicina || "rezultat") : izvor);

/** "model" ili "model · izvor", zavisno od toga da li model ima više izvora. */
function gde(model, izvor) {
  const m = st.pregled?.modeli.find((x) => x.model === model);
  if (!m || m.izvori.length < 2 || izvor === "glavni") return model;
  return `${model} · ${izvor}`;
}

/** Najgore stanje među izvorima jednog modela. */
function stanjeModela(m) {
  return m.izvori.reduce((a, i) => ((RANG[i.stanje] ?? 0) > (RANG[a] ?? 0) ? i.stanje : a), "ok");
}

/** Isti problem u isto vreme na više izvora je jedan problem (vidi server). */
function grupisi(alarmi) {
  const grupe = new Map();
  for (const a of alarmi) {
    const k = [a.tip, a.model, a.od, a.do, a.ozbiljnost, a.status].join("|");
    if (!grupe.has(k)) grupe.set(k, []);
    grupe.get(k).push(a);
  }
  return [...grupe.values()];
}

function ikonaZnak(ozbiljnost, status) {
  if (status === "resen") return h("span", { class: "znak znak--proslo", "aria-hidden": "true" }, "✓");
  if (status === "potvrdjen") return h("span", { class: "znak znak--videno", "aria-hidden": "true" }, "✓");
  return h("span", { class: `znak znak--${ozbiljnost}`, "aria-hidden": "true" }, ozbiljnost === "info" ? "i" : "!");
}

// ---------------------------------------------------------------------------
// Zaglavlje i pločice
// ---------------------------------------------------------------------------

function crtajStatus() {
  const n = st.nadzor?.sekundi;
  const tekst = st.poPodacima ? "Stari podaci (proba)"
    : n ? `Uživo · provera ${n <= 60 ? "svakog minuta" : `na svakih ${Math.round(n / 60)} min`}` : "Provera nije uključena";
  $("status").replaceChildren(h("i", { class: st.poPodacima || !n ? "tacka tacka--sivo" : "tacka tacka--zivo" }), tekst);
}

function crtajPlocice() {
  const p = st.pregled;
  const u = p.ukupno;
  const otvoreni = grupisi(st.alarmi.filter((a) => a.status !== "resen" && a.ozbiljnost !== "info"));

  // 1. Stanje
  let boja = "ok", naslov = "Sve u redu", opis;
  if (u.kriticno) { boja = "kriticno"; naslov = `Hitno: ${u.kriticno + u.upozorenje}`; }
  else if (u.upozorenje) { boja = "upozorenje"; naslov = `${u.upozorenje} ${mnozina(u.upozorenje, ["problem", "problema", "problema"])}`; }
  const sveze = Math.min(...p.modeli.flatMap((m) => m.izvori.map((i) => i.starost_s)));
  const kada = p.modeli.every((m) => m.istorijski) ? "stari podaci" : `poslednji rezultat ${starost(sveze)}`;
  if (boja === "ok") opis = `${u.modela} ${mnozina(u.modela, ["model", "modela", "modela"])} · ${kada}`;
  else opis = `${gde(p.najhitniji.model, p.najhitniji.izvor)} · ${kada}`;
  $("p-stanje").className = `plocica plocica--stanje plocica--${boja}`;
  $("p-stanje-lampa").replaceChildren(boja === "ok"
    ? s("svg", { viewBox: "0 0 24 24" }) : document.createTextNode("!"));
  if (boja === "ok") s("path", { d: "M5 12.5l4.5 4.5L19 7.5" }, $("p-stanje-lampa").firstChild);
  $("p-stanje-broj").textContent = naslov;
  $("p-stanje-opis").textContent = opis;

  // 3. Otvoreni problemi
  const nevideni = otvoreni.filter((g) => g[0].status === "otvoren").length;
  $("p-problemi-broj").textContent = String(otvoreni.length);
  $("p-problemi-opis").textContent = !otvoreni.length ? "ništa ne čeka"
    : !nevideni ? (otvoreni.length === 1 ? "neko ga je već video" : "sve je neko već video")
      : otvoreni.length === 1 ? "niko ga još nije video"
        : `${nevideni} još niko nije video`;
  const pre7 = Date.now() - 7 * DAN;
  const proslo = grupisi(st.alarmi.filter((a) => a.status === "resen" && a.poslednji_put >= pre7)).length;
  $("p-problemi-nedelja").textContent = proslo ? `prošlo samo ove nedelje: ${proslo}` : "";
  $("p-problemi").classList.toggle("plocica--upozorenje-tiho", otvoreni.length > 0);
}

function crtajOdstupanje() {
  const o = st.serija?.odstupanje;
  const graf = $("p-odstupanje-grafik");
  graf.replaceChildren();
  if (!o) {
    $("p-odstupanje-broj").textContent = "–";
    $("p-odstupanje-opis").textContent = st.serija ? "još se uči šta je normalno" : "";
    $("p-odstupanje").classList.remove("plocica--preko");
    return;
  }
  const preko = o.procenat >= 100;
  $("p-odstupanje-broj").replaceChildren(broj(o.procenat, 0), h("span", { class: "jedinica" }, "%"));
  $("p-odstupanje-opis").textContent = `${preko ? "preko granice" : "u granicama"} · ${gde(st.serija.model, st.serija.izvor)}`;
  $("p-odstupanje").classList.toggle("plocica--preko", preko);
  $("p-odstupanje").title = "0% = isto kao u normalnom periodu, 100% = granica posle koje se javlja problem.";

  // Mali grafikon: kako se odstupanje menjalo, sa isprekidanom granicom od 100%.
  const v = o.istorija;
  if (v.length < 2) return;
  const W = 120, H = 34, max = Math.max(110, ...v);
  const y = (x) => H - 2 - (x / max) * (H - 4);
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, class: "mini" }, graf);
  s("line", { x1: 0, x2: W, y1: y(100), y2: y(100), class: "mini__granica" }, svg);
  s("path", { d: v.map((x, i) => `${i ? "L" : "M"}${(i * W) / (v.length - 1)},${y(x)}`).join(""),
    class: preko ? "mini__linija mini__linija--preko" : "mini__linija" }, svg);
}

// ---------------------------------------------------------------------------
// Izbor modela, izvora i perioda
// ---------------------------------------------------------------------------

/** Ako čovek nije sam birao: model koji ima najhitniji problem, inače prvi. */
function proveriIzbor() {
  const p = st.pregled;
  const postoji = (iz) => iz && p.modeli.some((m) => m.model === iz.model && m.izvori.some((i) => i.izvor === iz.izvor));
  if (st.rucno && postoji(st.izbor)) return;
  const otvoren = st.alarmi.find((a) => a.status !== "resen" && a.ozbiljnost !== "info");
  const izbor = otvoren && postoji(otvoren) ? { model: otvoren.model, izvor: otvoren.izvor }
    : p.modeli.length ? { model: p.modeli[0].model, izvor: p.modeli[0].izvori[0].izvor } : null;
  if (!st.rucno || !postoji(st.izbor)) { st.izbor = izbor; st.rucno = false; }
  // Kad čovek nije sam birao period, prikaz se proširi da se problem vidi.
  if (otvoren && !st.periodRucno && st.izbor?.model === otvoren.model) {
    const m = p.modeli.find((x) => x.model === otvoren.model);
    if (otvoren.od < m.sada - st.dana * DAN) {
      st.dana = PERIODI.find((n) => otvoren.od >= m.sada - n * DAN) ?? PERIODI[PERIODI.length - 1];
    }
  }
}

function crtajTabove() {
  const p = st.pregled;
  $("tabovi").replaceChildren(...p.modeli.map((m) => h("button", {
    type: "button", class: "tab", "aria-pressed": String(m.model === st.izbor?.model),
    onclick: () => izaberi(m.model, null),
  }, h("i", { class: `tacka tacka--${stanjeModela(m)}` }), m.model)));

  const m = p.modeli.find((x) => x.model === st.izbor?.model);
  const sel = $("izvor");
  $("izvor-izbor").hidden = !m || m.izvori.length < 2;
  if (m && m.izvori.length > 1) {
    sel.replaceChildren(...m.izvori.map((i) => h("option", { value: i.izvor, selected: i.izvor === st.izbor.izvor },
      `${i.izvor}${i.stanje !== "ok" ? " (!)" : ""}`)));
  }
  for (const b of $("period").querySelectorAll("button")) b.setAttribute("aria-pressed", String(+b.dataset.dana === st.dana));
}

async function izaberi(model, izvor, alarm = null) {
  const m = st.pregled.modeli.find((x) => x.model === model);
  if (!m) return;
  // Za model sa više izvora: izvor sa problemom, inače prvi.
  izvor ??= (m.izvori.find((i) => i.stanje !== "ok") ?? m.izvori[0]).izvor;
  st.izbor = { model, izvor };
  st.rucno = true;
  st.istaknut = alarm;
  // Ako je problem stariji od prikazanog perioda, period se proširi.
  if (alarm && alarm.od < m.sada - st.dana * DAN) {
    st.dana = PERIODI.find((n) => alarm.od >= m.sada - n * DAN) ?? PERIODI[PERIODI.length - 1];
    zapamti("dana", st.dana);
    await osvezi();
    return;
  }
  crtajTabove();
  await ucitajSeriju();
}

// ---------------------------------------------------------------------------
// Veliki grafikon
// ---------------------------------------------------------------------------

function skala(d0, d1, r0, r1) {
  const k = (r1 - r0) / ((d1 - d0) || 1);
  return (v) => r0 + (v - d0) * k;
}

/** "Lepi" podeoci ose: 0, 20, 40, 60 ili 0, 2.500, 5.000... */
function podeoci(min, max, koliko = 4) {
  const raspon_ = max - min || Math.abs(max) || 1;
  const grubo = raspon_ / koliko;
  const stepen = 10 ** Math.floor(Math.log10(grubo));
  const korak = [1, 2, 2.5, 5, 10].map((x) => x * stepen).find((x) => x >= grubo);
  const od = Math.floor(min / korak) * korak;
  const lista = [];
  for (let v = od; v <= max + korak * 0.001; v += korak) lista.push(Number(v.toPrecision(12)));
  if (lista[lista.length - 1] < max) lista.push(Number((lista[lista.length - 1] + korak).toPrecision(12)));
  return { lista, korak };
}

/** Natpisi vremenske ose: meseci, dani ili sati, zavisno od dužine perioda. */
function natpisiVremena(od, doo, sirina) {
  const raspon_ = doo - od;
  const koliko = Math.max(2, Math.floor(sirina / 90));
  const korak = [SAT, 3 * SAT, 6 * SAT, 12 * SAT, DAN, 2 * DAN, 7 * DAN, 14 * DAN, 30 * DAN, 61 * DAN, 91 * DAN, 182 * DAN, 365 * DAN]
    .find((k) => raspon_ / k <= koliko) ?? 365 * DAN;
  const MESECI = ["jan", "feb", "mar", "apr", "maj", "jun", "jul", "avg", "sep", "okt", "nov", "dec"];
  const lista = [];
  if (korak >= 30 * DAN) {
    // Prvi dan meseca, svaki n-ti mesec.
    const n = Math.round(korak / (30 * DAN));
    const d = new Date(od);
    let t = Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1);
    while (t <= doo) {
      const m = new Date(t).getUTCMonth();
      if (m % n === 0) lista.push([t, m === 0 ? String(new Date(t).getUTCFullYear()) : MESECI[m]]);
      t = Date.UTC(new Date(t).getUTCFullYear(), m + 1, 1);
    }
  } else {
    for (let t = Math.ceil(od / korak) * korak; t <= doo; t += korak) {
      lista.push([t, korak >= DAN ? datum(t) : satMinut(t)]);
    }
  }
  return lista;
}

function crtajGrafik() {
  const kont = $("grafik");
  sakrijOblacic();
  const d = st.serija;
  if (!d) { kont.replaceChildren(); $("legenda").replaceChildren(); return; }

  const W = kont.clientWidth || 700;
  const H = W < 520 ? 230 : 320;
  const { levo, desno, gore, dole } = GRAFIK;
  const x = skala(d.od, d.do, levo, W - desno);
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img",
    "aria-label": `${gde(d.model, d.izvor)}: rezultati modela kroz vreme` });
  kont.replaceChildren(svg);

  if (d.vrsta === "kategorija") { grafikKategorija(svg, d, x, W, H); return; }

  const tacke = d.tacke.filter((t) => t[1] != null);
  const vrednosti = tacke.map((t) => t[1]).concat(d.tacke.filter((t) => t[2] != null).map((t) => t[2]));
  const opseg = d.normalni_opseg;
  let min = Math.min(...vrednosti, ...(opseg ?? []));
  let max = Math.max(...vrednosti, ...(opseg ?? []));
  if (!vrednosti.length) { min = 0; max = 1; }
  if (min > 0 && min < (max - min) * 0.6) min = 0; // nula na osi kad nije daleko
  const pod = podeoci(min, max);
  const y = skala(pod.lista[0], pod.lista[pod.lista.length - 1], H - dole, gore);

  // Normalni opseg (zeleni pojas).
  if (opseg) {
    s("rect", { x: levo, width: W - levo - desno, y: y(opseg[1]), height: Math.max(1, y(opseg[0]) - y(opseg[1])), class: "g-normalno" }, svg);
  }
  // Mreža i ose.
  for (const v of pod.lista) {
    s("line", { x1: levo, x2: W - desno, y1: y(v), y2: y(v), class: "g-mreza" }, svg);
    svgTekst(svg, levo - 8, y(v) + 4, broj(v, pod.korak < 1 ? Math.min(3, Math.ceil(-Math.log10(pod.korak))) : 0), "g-osa", "end");
  }
  for (const [t, tekst] of natpisiVremena(d.od, d.do, W - levo - desno)) {
    svgTekst(svg, x(t), H - 8, tekst, "g-osa", "middle");
  }
  // Vreme problema (obojene trake).
  for (const a of d.alarmi) {
    if (a.ozbiljnost === "info") continue;
    const x0 = Math.max(levo, x(a.od)), x1 = Math.min(W - desno, x(a.do));
    s("rect", { x: Math.min(x0, x1 - 6), width: Math.max(6, x1 - x0), y: gore, height: H - gore - dole,
      class: `g-problem g-problem--${a.ozbiljnost}${a.status === "resen" ? " g-problem--proslo" : ""}` }, svg);
  }
  // Linija (prekida se gde rezultati nisu stizali) i ispuna ispod nje.
  let linija = "", ispuna = "", pocetak = null, prethodna = null;
  const zatvori = () => {
    if (pocetak != null) ispuna += `L${x(prethodna[0])},${y(pod.lista[0])}L${x(pocetak[0])},${y(pod.lista[0])}Z`;
  };
  for (const t of tacke) {
    if (!prethodna || (d.prekid_ms && t[0] - prethodna[0] > d.prekid_ms)) {
      zatvori();
      linija += `M${x(t[0])},${y(t[1])}`;
      ispuna += `M${x(t[0])},${y(t[1])}`;
      pocetak = t;
    } else {
      linija += `L${x(t[0])},${y(t[1])}`;
      ispuna += `L${x(t[0])},${y(t[1])}`;
    }
    prethodna = t;
  }
  zatvori();
  s("path", { d: ispuna, class: "g-ispuna" }, svg);
  const stvarne = d.tacke.filter((t) => t[2] != null);
  if (stvarne.length) {
    s("path", { d: stvarne.map((t, i) => `${i ? "L" : "M"}${x(t[0])},${y(t[2])}`).join(""), class: "g-stvarno" }, svg);
  }
  s("path", { d: linija, class: "g-linija" }, svg);
  // Posebne tačke: neobična vrednost (krug), greška modela (crtica dole).
  for (const t of d.tacke) {
    if (t[3] === 1 && t[1] != null) s("circle", { cx: x(t[0]), cy: y(t[1]), r: 5, class: "g-neobicna" }, svg);
    if (t[3] === 2) s("line", { x1: x(t[0]), x2: x(t[0]), y1: H - dole, y2: H - dole - 8, class: "g-greska" }, svg);
  }
  const posl = tacke[tacke.length - 1];
  if (posl) s("circle", { cx: x(posl[0]), cy: y(posl[1]), r: 4.5, class: "g-poslednja" }, svg);

  oznaciProblem(svg, d, x, y, W, H);
  nisan(svg, d, x, y, W, H);
  $("legenda").replaceChildren(...[
    h("span", null, h("i", { class: "l-linija" }), "rezultat modela"),
    stvarne.length ? h("span", null, h("i", { class: "l-stvarno" }), "stvarna vrednost") : null,
    opseg ? h("span", null, h("i", { class: "l-normalno" }), "normalno") : null,
    d.alarmi.some((a) => a.ozbiljnost !== "info") ? h("span", null, h("i", { class: "l-problem" }), "problem") : null,
  ].filter(Boolean));
}

/** Oblačić na grafikonu za istaknut (ili najvažniji otvoren) problem ovog izvora. */
function oznaciProblem(svg, d, x, y, W, H) {
  const a = st.istaknut && st.istaknut.model === d.model && st.istaknut.izvor === d.izvor ? st.istaknut
    : d.alarmi.find((z) => z.status !== "resen" && z.ozbiljnost !== "info");
  if (!a || a.do < d.od) return;
  // Tačka problema: neobična vrednost u tom periodu, ili sredina perioda.
  const u = d.tacke.filter((t) => t[0] >= a.od && t[0] <= a.do && t[1] != null);
  const posebna = u.find((t) => t[3] === 1);
  const t = posebna ?? u[Math.floor(u.length / 2)];
  const px = x(t ? t[0] : (a.od + a.do) / 2);
  const py = t ? y(t[1]) : GRAFIK.gore + 30;
  if (t) s("circle", { cx: px, cy: py, r: 6, class: "g-oznaka-tacka" }, svg);

  const red1 = t ? `${datum(t[0])} · ${saJedinicom(t[1], d.jedinica)}` : `${raspon(a.od, a.do)}`;
  const red2 = d.normalni_opseg
    ? `obično između ${saJedinicom(d.normalni_opseg[0], null)} i ${saJedinicom(d.normalni_opseg[1], d.jedinica)}` : a.naziv;
  const sirina = Math.max(red1.length, red2.length) * 6.6 + 24;
  let bx = px - sirina - 12;
  if (bx < GRAFIK.levo + 4) bx = px + 12;
  if (bx + sirina > W - 4) bx = W - sirina - 4;
  const by = Math.min(Math.max(py - 54, GRAFIK.gore), H - GRAFIK.dole - 44);
  const g = s("g", { class: "g-oznaka", transform: `translate(${bx},${by})` }, svg);
  s("rect", { width: sirina, height: 42, rx: 8 }, g);
  svgTekst(g, 12, 18, red1, "g-oznaka__1");
  svgTekst(g, 12, 33, red2, "g-oznaka__2");
}

/** Vertikalna linija i oblačić za tačku najbližu mišu (ili prstu). */
function nisan(svg, d, x, y, W, H) {
  const tacke = d.tacke.filter((t) => t[1] != null);
  if (!tacke.length) return;
  const linija = s("line", { y1: GRAFIK.gore, y2: H - GRAFIK.dole, class: "g-nisan", visibility: "hidden" }, svg);
  const krug = s("circle", { r: 5, class: "g-nisan-tacka", visibility: "hidden" }, svg);
  const povrsina = s("rect", { x: GRAFIK.levo, y: 0, width: W - GRAFIK.levo - GRAFIK.desno, height: H, fill: "transparent" }, svg);
  const pomeri = (e) => {
    const r = svg.getBoundingClientRect();
    const mx = ((e.clientX - r.left) / r.width) * W;
    let najbliza = tacke[0];
    for (const t of tacke) if (Math.abs(x(t[0]) - mx) < Math.abs(x(najbliza[0]) - mx)) najbliza = t;
    const px = x(najbliza[0]);
    linija.setAttribute("x1", px); linija.setAttribute("x2", px); linija.setAttribute("visibility", "visible");
    krug.setAttribute("cx", px); krug.setAttribute("cy", y(najbliza[1])); krug.setAttribute("visibility", "visible");
    const sadrzaj = [naslovOblacica(d.korak_s && d.korak_s < 60 ? `${vreme(najbliza[0])}` : vreme(najbliza[0])),
      h("p", { class: "oblacic__vrednost" }, saJedinicom(najbliza[1], d.jedinica))];
    if (najbliza[2] != null) sadrzaj.push(h("p", null, `stvarno: ${saJedinicom(najbliza[2], d.jedinica)}`));
    if (d.normalni_opseg) sadrzaj.push(h("p", { class: "oblacic__slabo" }, `obično ${saJedinicom(d.normalni_opseg[0], null)}–${saJedinicom(d.normalni_opseg[1], d.jedinica)}`));
    const problem = d.alarmi.find((a) => a.ozbiljnost !== "info" && najbliza[0] >= a.od && najbliza[0] <= a.do);
    if (problem) sadrzaj.push(h("p", { class: "oblacic__problem" }, problem.naziv));
    prikaziOblacic(sadrzaj, e.clientX, e.clientY);
  };
  const sakrij = () => { linija.setAttribute("visibility", "hidden"); krug.setAttribute("visibility", "hidden"); sakrijOblacic(); };
  povrsina.addEventListener("pointermove", pomeri);
  povrsina.addEventListener("pointerdown", pomeri);
  povrsina.addEventListener("pointerleave", sakrij);
}

/** Model koji vraća kategorije: koliki deo odgovora je bila koja kategorija, po danu. */
function grafikKategorija(svg, d, x, W, H) {
  const { gore, dole, levo, desno } = GRAFIK;
  const y = skala(0, 1, H - dole, gore);
  for (const v of [0, 0.25, 0.5, 0.75, 1]) {
    s("line", { x1: levo, x2: W - desno, y1: y(v), y2: y(v), class: "g-mreza" }, svg);
    svgTekst(svg, levo - 8, y(v) + 4, `${v * 100}%`, "g-osa", "end");
  }
  for (const [t, tekst] of natpisiVremena(d.od, d.do, W - levo - desno)) svgTekst(svg, x(t), H - 8, tekst, "g-osa", "middle");
  for (const [od, doo, brojevi] of d.kategorije.dani) {
    const ukupno = brojevi.reduce((a, b) => a + b, 0) || 1;
    let zbir = 0;
    brojevi.forEach((b, i) => {
      const y0 = y(zbir / ukupno), y1 = y((zbir + b) / ukupno);
      s("rect", { x: x(od) + 0.5, width: Math.max(1, x(doo) - x(od) - 1), y: y1, height: y0 - y1, class: `g-kat g-kat--${i + 1}` }, svg);
      zbir += b;
    });
  }
  $("legenda").replaceChildren(...d.kategorije.imena.map((ime, i) => h("span", null, h("i", { class: `l-kat l-kat--${i + 1}` }), ime)));
}

// ---------------------------------------------------------------------------
// Problemi (kolona desno)
// ---------------------------------------------------------------------------

function crtajProbleme() {
  const sve = grupisi(st.alarmi);
  const otvoreni = sve.filter((g) => g[0].status !== "resen" && g[0].ozbiljnost !== "info");
  const napomene = sve.filter((g) => g[0].status !== "resen" && g[0].ozbiljnost === "info");
  const pre7 = Date.now() - 7 * DAN;
  const prosli = sve.filter((g) => g[0].status === "resen" && g[0].poslednji_put >= pre7)
    .sort((a, b) => b[0].poslednji_put - a[0].poslednji_put).slice(0, 5);
  const n = otvoreni.length;
  $("problemi-broj").textContent = `${n} ${mnozina(n, ["otvoren", "otvorena", "otvorenih"])}`;

  const lista = otvoreni.map(karticaProblema);
  if (!n) {
    lista.push(h("div", { class: "nema-problema" },
      h("span", { class: "nema-problema__znak", "aria-hidden": "true" }, "✓"),
      h("p", null, "Nema problema."), h("p", { class: "slabo" }, "Kad nešto iskrsne, pojaviće se ovde.")));
  }
  if (napomene.length) {
    // Napomene (sitnice, npr. isti podatak stigao dvaput) su samo za znanje.
    lista.push(h("p", { class: "problemi__podnaslov" }, "Napomene, samo za znanje"));
    lista.push(...napomene.map(karticaProblema));
  }
  if (prosli.length) {
    lista.push(h("p", { class: "problemi__podnaslov" }, "Prošlo u poslednjih 7 dana"));
    lista.push(...prosli.map(karticaProblema));
  }
  $("lista-problema").replaceChildren(...lista);
}

function karticaProblema(grupa) {
  const a = grupa[0];
  const izvori = grupa.length > 1 ? `${a.model} · ${grupa.length} izvora` : gde(a.model, a.izvor);
  let dno;
  if (a.status === "otvoren") {
    dno = h("div", { class: "kartica__dno" },
      h("button", { type: "button", class: a.ozbiljnost === "info" ? "dugme dugme--tiho dugme--malo" : "dugme dugme--malo",
        onclick: (e) => videoSam(grupa, e.currentTarget) }, "Video sam"),
      h("button", { type: "button", class: "veza", onclick: () => izaberi(a.model, a.izvor, a) }, "Prikaži na grafikonu"));
  } else {
    const tekst = a.status === "potvrdjen" ? `Video ${a.potvrdio}, ${vreme(a.poslednji_put)}.`
      : a.napomena === "Prestalo samo." ? `Prošlo samo${a.potvrdio ? `. Video ${a.potvrdio}` : ""}.` : "Rešeno.";
    dno = h("div", { class: "kartica__dno" }, h("span", { class: "slabo" }, tekst),
      h("button", { type: "button", class: "veza", onclick: () => izaberi(a.model, a.izvor, a) }, "Prikaži"));
  }
  const klasa = a.status === "resen" ? "kartica kartica--proslo"
    : a.status === "potvrdjen" ? "kartica kartica--videno" : `kartica kartica--${a.ozbiljnost}`;
  return h("article", { class: klasa },
    h("div", { class: "kartica__glava" }, ikonaZnak(a.ozbiljnost, a.status),
      h("span", { class: "kartica__model" }, izvori), h("span", { class: "kartica__kada" }, raspon(a.od, a.do))),
    h("h3", null, a.status === "otvoren" && a.ozbiljnost === "kriticno" ? `Hitno: ${a.naziv.toLowerCase()}` : a.naziv),
    h("p", null, a.opis),
    dno);
}

/** Ime onoga ko klikće "Video sam": pita se jednom, pamti se u pregledaču. */
function trazenjeImena() {
  return new Promise((resolve) => {
    const dij = $("dijalog-ime");
    const ulaz = $("ime-ulaz");
    ulaz.value = "";
    const gotovo = (ime) => { dij.close(); resolve(ime); };
    $("ime-forma").onsubmit = (e) => { e.preventDefault(); if (ulaz.value.trim()) gotovo(ulaz.value.trim()); };
    $("ime-odustani").onclick = () => gotovo(null);
    dij.oncancel = () => resolve(null);
    dij.showModal();
    ulaz.focus();
  });
}

async function videoSam(grupa, dugme) {
  let ime = seti("ime", "");
  if (!ime) {
    ime = await trazenjeImena();
    if (!ime) return;
    zapamti("ime", ime);
  }
  dugme.disabled = true;
  try {
    for (const a of grupa) await api(`/api/alarmi/${a.id}/potvrdi`, { ko: ime, napomena: null });
    await osvezi();
  } catch (e) {
    dugme.disabled = false;
    obavesti(e.message, true);
  }
}

// ---------------------------------------------------------------------------
// Učitavanje i osvežavanje
// ---------------------------------------------------------------------------

function crtajPoslednje() {
  const d = st.serija;
  if (!d) { $("poslednje-vrednost").textContent = ""; $("poslednje-opis").textContent = ""; return; }
  const m = st.pregled.modeli.find((x) => x.model === d.model);
  const i = m?.izvori.find((x) => x.izvor === d.izvor);
  let vrednost = "–";
  if (i?.greska) vrednost = "greška";
  else if (i?.kategorija != null) vrednost = i.kategorija;
  else if (i?.vrednost != null) vrednost = saJedinicom(i.vrednost, i.jedinica);
  $("poslednje-vrednost").textContent = vrednost;
  const ime = d.izvor === "glavni" ? "" : `${imeIzvora(d.izvor, d.velicina)}, `;
  $("poslednje-opis").textContent = i ? `${ime}poslednji rezultat · ${vreme(i.poslednje)}` : "";
}

async function ucitajSeriju() {
  if (!st.izbor) { st.serija = null; crtajSve(); return; }
  try {
    const q = new URLSearchParams({ model: st.izbor.model, izvor: st.izbor.izvor, dana: st.dana });
    st.serija = await api(`/api/serija?${q}`);
  } catch (e) {
    st.serija = null;
    obavesti(e.message, true);
  }
  crtajPoslednje();
  crtajOdstupanje();
  crtajGrafik();
}

function crtajSve() {
  const prazno = !st.pregled.modeli.length;
  $("prazno").hidden = !prazno;
  $("glavno").hidden = prazno;
  document.querySelector(".plocice").hidden = prazno;
  crtajStatus();
  if (prazno) return;
  crtajPlocice();
  crtajTabove();
  crtajProbleme();
}

let tekuce = null;

async function osvezi() {
  if (tekuce) return tekuce;
  tekuce = (async () => {
    try {
      const [pregled, alarmi] = await Promise.all([api(`/api/pregled?dana=${st.dana}`), api("/api/alarmi?svi=true")]);
      postaviZonu(pregled.zona);
      st.pregled = pregled;
      st.alarmi = alarmi;
      st.verzija = pregled.verzija;
      proveriIzbor();
      crtajSve();
      if (pregled.modeli.length) await ucitajSeriju();
    } catch (e) {
      obavesti(e.message, true);
    } finally {
      tekuce = null;
    }
  })();
  return tekuce;
}

async function proveriVerziju() {
  if (document.hidden) return; // kartica nije vidljiva: ne opterećuj server
  try {
    const stanje = await api("/api/stanje");
    st.nadzor = stanje.nadzor;
    st.poPodacima = stanje.sada_po_podacima;
    if (stanje.verzija !== st.verzija) await osvezi();
    else crtajStatus();
  } catch {
    $("status").textContent = "Server ne odgovara. Prikazani su poslednji poznati podaci.";
  }
}

function pokreni() {
  st.dana = PERIODI.includes(seti("dana", 30)) ? seti("dana", 30) : 30;
  st.periodRucno = seti("dana", null) != null;
  $("period").addEventListener("click", (e) => {
    const dana = +e.target.closest("button")?.dataset.dana;
    if (!dana || dana === st.dana) return;
    st.dana = dana;
    st.periodRucno = true;
    zapamti("dana", dana);
    st.istaknut = null;
    osvezi();
  });
  $("izvor").addEventListener("change", (e) => { st.izbor = { model: st.izbor.model, izvor: e.target.value }; st.rucno = true; ucitajSeriju(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") sakrijOblacic(); });
  addEventListener("scroll", sakrijOblacic, { passive: true });

  // Kad se promeni širina prozora, grafikon se ponovo nacrta u novoj širini.
  let sirina = 0, tajmer;
  new ResizeObserver(() => {
    const nova = $("grafik").clientWidth;
    if (nova === sirina) return;
    sirina = nova;
    clearTimeout(tajmer);
    tajmer = setTimeout(crtajGrafik, 120);
  }).observe($("grafik"));

  proveriVerziju();
  setInterval(proveriVerziju, OSVEZAVANJE_MS);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) proveriVerziju(); });
}

pokreni();
