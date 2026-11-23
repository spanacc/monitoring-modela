/*
 * Dashboard monitoringa modela: sve što se dešava u pregledaču.
 *
 * Bez ijedne spoljne biblioteke i bez interneta. Grafikoni se crtaju
 * ručno, kao SVG (slika od linija i pravougaonika koju pregledač crta).
 *
 * KAKO RADI
 *   1. Na svakih 15 s pita server samo za "verziju" podataka (par bajtova).
 *   2. Ako se verzija promenila, traži pregled, alarme i izabrani izvor,
 *      pa ponovo crta. Inače ne radi ništa: brzo i bez opterećenja.
 *   3. Sav tekst iz podataka (imena, opisi, napomene) ubacuje se kao TEKST,
 *      nikad kao HTML. Tako ni čudno ime izvora ne može da izvrši kod.
 *
 * Vremena stižu kao milisekunde (UTC), a ispisuju se po vremenskoj zoni iz
 * konfiguracije, ne po zoni računara na kome je pregledač.
 */

const OSVEZAVANJE_MS = 15000;
const DAN = 86400000;
const SAT = 3600000;
const MINUT = 60000;
const SEKUND = 1000;
// "Okrugla" trajanja za ćelije i podeoke: sekunde, minuti, sati, dani.
const KORACI = [1, 2, 5, 10, 15, 30].map((x) => x * SEKUND)
  .concat([1, 2, 5, 10, 15, 30].map((x) => x * MINUT))
  .concat([1, 2, 3, 4, 6, 8, 12, 24, 48, 168].map((x) => x * SAT));
const MIN_CELIJA_PX = 5; // najuža ćelija u traci "Stanje izvora"
const RANG = { info: 1, upozorenje: 2, kriticno: 3 };
// Nivoi običnim rečima: "hitno" traži reakciju odmah, "problem" treba pogledati,
// "napomena" je samo za znanje.
const OZBILJNOST = { kriticno: "Hitno", upozorenje: "Problem", info: "Napomena" };
const PERIODI = [7, 30, 90, 365, 3660]; // 3660 = "sve" (10 godina)
const NAPOMENA_TACKE = { 1: "neobična vrednost", 2: "model javio grešku", 3: "bez vrednosti" };
const M = { levo: 54, desno: 74, gore: 26, dole: 26 }; // margine grafikona

const st = {
  dana: 30,
  model: "",            // filter modela ("" = svi)
  svi: false,           // alarmi: false = samo nerešeni
  izbor: null,          // izabrani izvor: {model, izvor, velicina, horizont}
  izabranAlarm: null,   // broj alarma istaknutog na grafikonu
  verzija: null,
  pregled: null,
  serija: null,
  alarmi: [],
  nadzor: null,
  sadaPoPodacima: false,
  osvezeno: null,
  poznatiAlarmi: null,  // brojevi alarma koje je stranica već videla
  noviAlarmi: new Set(),
  tabela: {},           // koji grafikoni su prikazani kao tabela
  izvori: [],           // šta se prati (iz podešavanja)
  predlog: null,        // predlog kolona za fajl koji se dodaje
};

// ---------------------------------------------------------------------------
// Pomoćne funkcije
// ---------------------------------------------------------------------------

const $ = (id) => document.getElementById(id);
// Ista skripta služi dve stranice: glavnu (semafor, problemi, detalji) i podešavanja.
const STRANICA = document.body.dataset.stranica || "glavna";

/** Pravi HTML element. Tekst iz podataka uvek ide kao tekst, nikad kao HTML. */
function h(oznaka, svojstva, ...deca) {
  const el = document.createElement(oznaka);
  for (const [k, v] of Object.entries(svojstva || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const d of deca.flat()) {
    if (d == null || d === false) continue;
    el.append(d instanceof Node ? d : document.createTextNode(String(d)));
  }
  return el;
}

/** Pravi SVG element (deo grafikona). */
function s(oznaka, atributi, roditelj) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", oznaka);
  for (const [k, v] of Object.entries(atributi || {})) {
    if (v != null) el.setAttribute(k, typeof v === "number" ? +v.toFixed(2) : v);
  }
  if (roditelj) roditelj.append(el);
  return el;
}

function svgTekst(roditelj, x, y, tekst, klasa, sidro = "start") {
  const t = s("text", { x, y, class: klasa, "text-anchor": sidro }, roditelj);
  t.textContent = tekst;
  return t;
}

/** Ikona ozbiljnosti: romb (kritično), trougao (upozorenje), krug (info), kvačica (u redu). */
function oblik(ozbiljnost, cx, cy, r) {
  if (ozbiljnost === "kriticno") {
    return s("path", { d: `M${cx} ${cy - r}L${cx + r} ${cy}L${cx} ${cy + r}L${cx - r} ${cy}Z` });
  }
  if (ozbiljnost === "upozorenje") {
    return s("path", { d: `M${cx} ${cy - r}L${cx + r * 1.05} ${cy + r * 0.8}L${cx - r * 1.05} ${cy + r * 0.8}Z` });
  }
  if (ozbiljnost === "info") return s("circle", { cx, cy, r: r * 0.8 });
  return s("path", { d: `M${cx - r * 0.7} ${cy}L${cx - r * 0.2} ${cy + r * 0.5}L${cx + r * 0.75} ${cy - r * 0.55}` });
}

function ikona(ozbiljnost, potvrdjeno = false) {
  const svg = s("svg", { viewBox: "0 0 12 12", "aria-hidden": "true" });
  const ime = ozbiljnost in RANG ? ozbiljnost : "u-redu";
  svg.setAttribute("class", `ikona ikona--${ime}${potvrdjeno ? " ikona--potvrdjeno" : ""}`);
  svg.append(oblik(ozbiljnost, 6, 6, 5));
  return svg;
}

function zapamti(kljuc, vrednost) {
  try { localStorage.setItem(`monitoring.${kljuc}`, JSON.stringify(vrednost)); } catch { /* nije bitno */ }
}

function seti(kljuc, podrazumevano) {
  try {
    const v = localStorage.getItem(`monitoring.${kljuc}`);
    return v == null ? podrazumevano : JSON.parse(v);
  } catch {
    return podrazumevano;
  }
}

// --- vreme, po zoni iz konfiguracije ---

let formatVremena = null;

function postaviZonu(zona) {
  if (formatVremena && formatVremena.resolvedOptions().timeZone === zona) return;
  formatVremena = new Intl.DateTimeFormat("sr-Latn-RS", {
    timeZone: zona, hourCycle: "h23", year: "numeric", month: "2-digit",
    day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
}

function delovi(ms) {
  const d = {};
  for (const p of formatVremena.formatToParts(new Date(ms))) d[p.type] = p.value;
  return d;
}

/** Koliko je lokalno vreme (u zoni iz konfiguracije) ispred UTC-a, u milisekundama. */
function ofset(ms) {
  const d = delovi(ms);
  return Date.UTC(+d.year, +d.month - 1, +d.day, +d.hour, +d.minute, +d.second) - Math.floor(ms / 1000) * 1000;
}

const ovaGodina = String(new Date().getFullYear());
// Godina se piše samo kad nije tekuća (stari podaci), da ne smeta u svakodnevnom radu.
const datum = (ms) => { const d = delovi(ms); return `${+d.day}.${+d.month}.${d.year === ovaGodina ? "" : `${d.year}.`}`; };
const satMinut = (ms) => { const d = delovi(ms); return `${d.hour}:${d.minute}`; };
const vreme = (ms) => `${datum(ms)} ${satMinut(ms)}`;
const vremeGodina = (ms) => { const d = delovi(ms); return `${+d.day}.${+d.month}.${d.year}. ${d.hour}:${d.minute}`; };
const vremeSekunde = (ms) => { const d = delovi(ms); return `${d.hour}:${d.minute}:${d.second}`; };

/** Za česta merenja (ređe od minuta) vreme se piše sa sekundama. */
const vremeZa = (d) => (d.korak_s != null && d.korak_s < 60
  ? (ms) => `${datum(ms)} ${vremeSekunde(ms)}` : vreme);

function raspon(od, doo) {
  // Celi dani (od ponoći do ponoći): samo datumi, bez "00:00–00:00".
  if (satMinut(od) === "00:00" && satMinut(doo) === "00:00" && doo - od >= DAN - SAT) {
    return datum(od) === datum(doo - 1) ? datum(od) : `${datum(od)} – ${datum(doo - 1)}`;
  }
  return datum(od) === datum(doo - 1) ? `${datum(od)} ${satMinut(od)}–${satMinut(doo)}`
    : `${vreme(od)} – ${vreme(doo)}`;
}

// --- brojevi, srpski zapis (1.234,5) ---

const formatiBrojeva = new Map();

function broj(x, decimala) {
  let f = formatiBrojeva.get(decimala);
  if (!f) {
    f = new Intl.NumberFormat("sr-Latn-RS", { minimumFractionDigits: decimala, maximumFractionDigits: decimala });
    formatiBrojeva.set(decimala, f);
  }
  return f.format(x).replace("-", "\u2212"); // pravi znak minus, ne crtica
}

/** Koliko decimala: oko tri cifre (63,5 / 1.235 / 0,53). */
const decimale = (a) => { if (Number.isInteger(a)) return 0; a = Math.abs(a); return a >= 100 || a === 0 ? 0 : a >= 1 ? 1 : a >= 0.1 ? 2 : 3; };

function saJedinicom(x, jedinica, kao) {
  return broj(x, decimale(kao ?? x)) + (jedinica ? ` ${jedinica}` : "");
}

function saZnakom(x, jedinica, kao) {
  const dec = decimale(kao ?? x);
  const r = Number(x.toFixed(dec));
  return (r > 0 ? "+" : "") + broj(r === 0 ? 0 : r, dec) + (jedinica ? ` ${jedinica}` : "");
}

const procenat = (udeo) => `${broj(udeo * 100, 0)}%`;

function mnozina(n, [jedan, dva, pet]) {
  const d = n % 10, s100 = n % 100;
  if (d === 1 && s100 !== 11) return jedan;
  if (d >= 2 && d <= 4 && (s100 < 12 || s100 > 14)) return dva;
  return pet;
}

function trajanje(ms) {
  if (ms < MINUT) return `${broj(ms / SEKUND, ms < 10 * SEKUND && ms % SEKUND ? 1 : 0)} s`;
  const min = Math.round(ms / 60000);
  if (min < 60) return `${min} min`;
  const sati = ms / SAT;
  if (sati < 48) return `${broj(sati, Number.isInteger(+sati.toFixed(1)) ? 0 : 1)} h`;
  const dana = Math.round(ms / DAN);
  return `${dana} ${mnozina(dana, ["dan", "dana", "dana"])}`;
}

function starost(sekundi) {
  if (sekundi < 90) return "upravo";
  if (sekundi < 3600) return `pre ${Math.round(sekundi / 60)} min`;
  if (sekundi < 48 * 3600) return `pre ${Math.round(sekundi / 3600)} h`;
  return `pre ${Math.round(sekundi / 86400)} dana`;
}

// ---------------------------------------------------------------------------
// Razgovor sa serverom
// ---------------------------------------------------------------------------

async function api(putanja, telo, metod = null) {
  const opcije = { headers: { Accept: "application/json" } };
  if (metod) {
    opcije.method = metod;
    opcije.headers["X-Dashboard"] = "1";
  } else if (telo !== undefined) {
    opcije.method = "POST";
    // Bez ovog zaglavlja server odbija svaku izmenu (zaštita od CSRF).
    opcije.headers["X-Dashboard"] = "1";
    opcije.headers["Content-Type"] = "application/json";
    opcije.body = JSON.stringify(telo);
  }
  let odgovor;
  try {
    odgovor = await fetch(putanja, opcije);
  } catch {
    throw new Error("Server ne odgovara. Proverite da li je dashboard još pokrenut u Terminalu.");
  }
  if (!odgovor.ok) {
    let poruka = `Server je vratio grešku ${odgovor.status}.`;
    try {
      const j = await odgovor.json();
      if (typeof j.detail === "string") poruka = j.detail;
      else if (Array.isArray(j.detail)) poruka = "Proverite uneta polja.";
    } catch { /* odgovor nije JSON */ }
    throw new Error(poruka);
  }
  return odgovor.json();
}

// ---------------------------------------------------------------------------
// Oblačić (tooltip) i obaveštenja
// ---------------------------------------------------------------------------

function prikaziOblacic(sadrzaj, x, y) {
  const el = $("tooltip");
  el.replaceChildren(...sadrzaj);
  el.hidden = false;
  const r = el.getBoundingClientRect();
  let levo = x + 14, gore = y + 14;
  if (levo + r.width > innerWidth - 8) levo = x - r.width - 14;
  if (gore + r.height > innerHeight - 8) gore = y - r.height - 14;
  el.style.left = `${Math.max(8, levo)}px`;
  el.style.top = `${Math.max(8, gore)}px`;
}

const sakrijOblacic = () => { $("tooltip").hidden = true; };

const naslovOblacica = (tekst) => h("p", { class: "tooltip__naslov" }, tekst);

/** Jedan red oblačića: vrednost je jača, ime je slabije (čitalac već zna seriju, traži broj). */
function redOblacica(kljuc, vrednost, ime) {
  let znak;
  if (kljuc instanceof Node) znak = kljuc;
  else znak = h("span", { class: kljuc ? `tooltip__kljuc k-${kljuc}` : "tooltip__kljuc" });
  return h("div", { class: "tooltip__red" }, znak,
    h("span", { class: "tooltip__vrednost" }, vrednost), ime ? h("span", { class: "tooltip__ime" }, ime) : null);
}

let tajmerObavestenja;

function obavesti(tekst, greska = false) {
  const el = $("obavestenje");
  el.textContent = tekst;
  el.className = `obavestenje${greska ? " obavestenje--greska" : ""}`;
  el.hidden = false;
  clearTimeout(tajmerObavestenja);
  tajmerObavestenja = setTimeout(() => { el.hidden = true; }, greska ? 9000 : 5000);
}

// ---------------------------------------------------------------------------
// Presuda: stanje rečima, na vrhu
// ---------------------------------------------------------------------------

function crtajSemafor() {
  if (!$("semafor")) return;
  const p = st.pregled;
  const u = p.ukupno;
  let boja, naslov;
  const tekst = [];

  if (!p.modeli.length) {
    boja = "prazno";
    naslov = "Još nema podataka";
    tekst.push(st.izvori.length
      ? `Fajlovi su dodati, ali iz njih još ništa nije učitano. ${(st.nadzor?.izvestaj?.greske ?? []).join(" ")}`
      : "Podaci modela se dodaju u ", h("a", { href: "podesavanja.html" }, "podešavanjima"), " (zupčanik gore desno).");
  } else if (u.kriticno) {
    boja = "kriticno";
    naslov = `Hitno: ${u.kriticno + u.upozorenje} ${mnozina(u.kriticno + u.upozorenje, ["problem", "problema", "problema"])}`;
  } else if (u.upozorenje) {
    boja = "upozorenje";
    naslov = `Ima problema: ${u.upozorenje}`;
  } else {
    boja = "u-redu";
    naslov = "Sve je u redu";
  }

  if (p.modeli.length) {
    // Rečenica ispod: najvažniji problem (ako ga ima) i koliko su sveži podaci.
    const a = p.najhitniji;
    if (a && (u.kriticno || u.upozorenje)) {
      const iz = imeIzvora(a.izvor, null, a.model);
      const gde = p.najhitniji_izvora > 1 ? `${a.model}, ${p.najhitniji_izvora} izvora` : iz === a.model ? a.model : `${a.model}, ${iz}`;
      tekst.push(`${a.naziv} (${gde}, ${raspon(a.od, a.do)}). `);
    }
    const najsvezije = Math.min(...p.modeli.flatMap((m) => m.izvori.map((i) => i.starost_s)));
    if (p.modeli.every((m) => m.istorijski)) tekst.push("Ovo su stari podaci (proba).");
    else tekst.push(`Poslednji podaci su stigli ${starost(najsvezije)}.`);
    if (boja === "u-redu") tekst.push(` Prati se ${u.izvora} ${mnozina(u.izvora, ["izvor", "izvora", "izvora"])}.`);
    if (u.info) tekst.push(` ${u.info} ${mnozina(u.info, ["napomena", "napomene", "napomena"])} za znanje.`);
  }

  const sek = $("semafor");
  sek.className = `semafor semafor--${boja}`;
  $("semafor-lampa").replaceChildren(boja === "u-redu" ? ikona("u-redu") : boja === "prazno" ? "" : h("span", null, "!"));
  if ($("semafor-naslov").textContent !== naslov) $("semafor-naslov").textContent = naslov;
  $("semafor-tekst").replaceChildren(...tekst.map((d) => (d instanceof Node ? d : document.createTextNode(d))));
}

function crtajStatus() {
  const delovi_ = [];
  if (st.osvezeno && formatVremena) delovi_.push(`Osveženo u ${vremeSekunde(st.osvezeno)}.`);
  if (st.nadzor?.sekundi) delovi_.push(`Provera na svakih ${trajanje(st.nadzor.sekundi * SEKUND)}.`);

  $("status").textContent = delovi_.join(" ");
}

// ---------------------------------------------------------------------------
// Stanje izvora: svaki izvor je jedna traka kroz vreme
// ---------------------------------------------------------------------------

function legendaStanja() {
  if (!$("legenda-stanja")) return;
  const celija = (klasa) => {
    const svg = s("svg", { width: 10, height: 14, "aria-hidden": "true", class: "legenda__celija" });
    s("rect", { width: 10, height: 14, rx: 1.5, class: klasa }, svg);
    return svg;
  };
  $("legenda-stanja").replaceChildren(
    h("span", null, celija("celija--u-redu"), "u redu"),
    h("span", null, ikona("upozorenje"), "problem"),
    h("span", null, ikona("kriticno"), "hitno"),
    h("span", null, celija("celija--kriticno celija--reseno"), "rešeno"),
  );
}

/** Kolika je jedna ćelija: okruglo trajanje (5 min, 1 h, 6 h...), tako da sve stane u širinu. */
function mrezaCelija(p, sirina) {
  const najvise = Math.max(8, Math.min(120, Math.floor(sirina / MIN_CELIJA_PX)));
  const ukupno = Math.max(p.sada - p.od, MINUT);
  const korak = KORACI.find((k) => Math.ceil(ukupno / k) <= najvise) ?? Math.ceil(ukupno / najvise);
  // Ćelije počinju na okruglom vremenu: u ponoć (00, 06, 12, 18 h) ili na pun minut.
  let pocetak;
  if (korak >= SAT && p.dani.length) {
    pocetak = p.dani[0] - Math.ceil((p.dani[0] - p.od) / korak) * korak;
  } else {
    const o = ofset(p.od);
    pocetak = Math.floor((p.od + o) / korak) * korak - o;
  }
  const n = Math.max(1, Math.ceil((p.sada - pocetak) / korak));
  return { pocetak, korak, n, kraj: pocetak + n * korak };
}

/**
 * Podeoci vremenske ose: po danima za duže periode, a po satima, minutima
 * ili sekundama za kratke. Natpisi su razmaknuti bar `minPx` piksela.
 */
function podeociVremena(od, doo, sirinaPx, dani, minPx = 64) {
  const pxPoMs = sirinaPx / ((doo - od) || 1);
  minPx = Math.max(minPx, datum(od).length * 6.8 + 10); // natpis sa godinom je širi
  if (doo - od >= 120 * DAN) {
    // Meseci i godine: podeok na prvom danu meseca, natpis "10.2012."
    const prvi = dani.filter((t) => delovi(t).day === "01");
    const korak = [1, 2, 3, 6, 12].find((k) => k * 30 * DAN * pxPoMs >= minPx) ?? 24;
    return prvi.filter((t) => (+delovi(t).month - 1) % korak === 0)
      .map((t) => { const d = delovi(t); return { t, tekst: `${+d.month}.${d.year}.` }; });
  }
  if (doo - od >= 2 * DAN) {
    const korak = [1, 2, 3, 5, 7, 14, 30].find((k) => k * DAN * pxPoMs >= minPx) ?? 60;
    return dani.filter((_, i) => i % korak === 0).map((t) => ({ t, tekst: datum(t) }));
  }
  const korak = KORACI.find((k) => k * pxPoMs >= minPx) ?? DAN;
  const o = ofset(od);
  const lista = [];
  for (let t = Math.ceil((od + o) / korak) * korak - o; t <= doo; t += korak) {
    const d = delovi(t);
    let tekst = korak < MINUT ? `${d.hour}:${d.minute}:${d.second}` : `${d.hour}:${d.minute}`;
    if (d.hour === "00" && d.minute === "00" && d.second === "00") tekst = datum(t); // ponoć: datum
    lista.push({ t, tekst });
  }
  return lista;
}

/** Za svaku ćeliju: -1 nema još podataka, 0 u redu, 1-3 rešen alarm, 11-13 nerešen alarm. */
function kodoviCelija(izvor, mreza) {
  const kodovi = new Int8Array(mreza.n);
  for (let i = 0; i < mreza.n; i++) {
    const a0 = mreza.pocetak + i * mreza.korak, a1 = a0 + mreza.korak;
    if (a1 <= izvor.prvo) { kodovi[i] = -1; continue; }
    let kod = 0;
    for (const [, , ozb, od, doo, status] of izvor.alarmi) {
      if (od < a1 && (doo > a0 || od >= a0)) kod = Math.max(kod, RANG[ozb] + (status === "resen" ? 0 : 10));
    }
    if (kod === 0 && a0 > izvor.poslednje) kod = -1; // posle poslednjeg rezultata nema podataka
    kodovi[i] = kod;
  }
  return kodovi;
}

const IME_RANGA = { 1: "info", 2: "upozorenje", 3: "kriticno" };

function klasaCelije(kod) {
  if (kod === 0) return "celija--u-redu";
  return kod > 10 ? `celija--${IME_RANGA[kod - 10]}` : `celija--${IME_RANGA[kod]} celija--reseno`;
}

function crtajMatricu() {
  const kont = $("matrica");
  if (!kont) return;
  const p = st.pregled;
  if (!p.modeli.length) {
    $("opseg").textContent = "";
    kont.replaceChildren(h("p", { class: "prazno" },
      "Ovde će svaki izvor biti jedna traka kroz vreme: sivo dok je u redu, žuto kad ima problem, crveno kad je hitno."));
    return;
  }
  if ($("detalji") && !$("detalji").open) { kont.replaceChildren(); return; } // crta se kad se otvori

  const modeli = p.modeli.filter((m) => !st.model || m.model === st.model);
  // Svaki model ima svoj period (stari podaci iz raznih godina ne idu na istu
  // osu). Kad je svima isti, piše se jednom, gore; inače uz svaki model.
  const istiPeriod = modeli.every((m) => m.od === modeli[0].od && m.sada === modeli[0].sada);
  $("opseg").textContent = istiPeriod ? `Prikazano: ${raspon(modeli[0].od, modeli[0].sada)}` : "";
  // Kolona sa imenima je široka koliko treba najdužem imenu (npr. "Volume Flow RateRMS").
  const najduze = Math.max(...modeli.flatMap((m) => m.izvori.map((i) => imeIzvora(i.izvor, i.velicina, m.model).length)));
  kont.style.setProperty("--sirina-imena", `${Math.round(Math.min(190, Math.max(96, najduze * 7.6)))}px`);
  const grupe = [];
  const elementi = [];
  for (const m of modeli) {
    elementi.push(h("h3", { class: "matrica__grupa" }, m.model,
      istiPeriod ? null : h("span", { class: "matrica__period" }, raspon(m.od, m.sada))));
    const redovi = [];
    for (const izvor of m.izvori) {
      const red = redIzvora(m.model, izvor);
      redovi.push([red, izvor]);
      elementi.push(red);
    }
    const osa = h("div", { class: "matrica__osa", "aria-hidden": "true" }, h("span"), h("span"), h("div"));
    elementi.push(osa);
    grupe.push({ m, redovi, osa });
  }
  kont.replaceChildren(...elementi);

  // Traka se crta tek kad je red u stranici, jer tek tada se zna njena širina.
  const sirina = grupe[0].redovi[0][0].querySelector(".red__traka").clientWidth;
  for (const { m, redovi, osa } of grupe) {
    const mreza = mrezaCelija(m, sirina);
    for (const [red, izvor] of redovi) crtajTraku(red.querySelector(".red__traka"), m, izvor, mreza, sirina);
    crtajOsuMatrice(osa.lastChild, mreza, m.dani, sirina);
  }
}

/** Fajl bez kolone sa izvorom daje izvor "glavni"; čoveku je jasnije ime veličine (npr. "cnt"). */
function imeIzvora(izvor, velicina, model) {
  if (izvor !== "glavni") return izvor;
  return velicina ? velicina.replaceAll("_", " ") : model;
}

function redIzvora(model, izvor) {
  const izabran = st.izbor?.model === model && st.izbor?.izvor === izvor.izvor;
  let vrednost;
  if (izvor.greska) vrednost = "greška";
  else if (izvor.kategorija != null) vrednost = izvor.kategorija;
  else if (izvor.vrednost != null) vrednost = saJedinicom(izvor.vrednost, izvor.jedinica);
  else vrednost = "prazno";
  const stanje = izvor.stanje === "ok" ? "u redu" : OZBILJNOST[izvor.stanje].toLowerCase();

  return h("button", {
    type: "button", class: "red", "aria-pressed": izabran ? "true" : "false",
    "data-model": model, "data-izvor": izvor.izvor,
    "aria-label": `${imeIzvora(izvor.izvor, izvor.velicina, model)} (${model}): ${stanje}. Poslednji rezultat ${vrednost}, ${izvor.istorijski ? vreme(izvor.poslednje) : starost(izvor.starost_s)}.`,
    onclick: () => izaberiIzvor(model, izvor.izvor),
  },
  h("span", { class: "red__ikona" }, izvor.stanje !== "ok" ? ikona(izvor.stanje, izvor.potvrdjeno) : null),
  h("span", { class: "red__ime", title: izvor.izvor }, imeIzvora(izvor.izvor, izvor.velicina, model)),
  h("span", { class: "red__traka" }),
  h("span", { class: "red__poslednje" },
    h("span", { class: "red__vrednost" }, vrednost),
    h("span", { class: "red__starost" }, izvor.istorijski ? vreme(izvor.poslednje) : starost(izvor.starost_s))));
}

function crtajTraku(kont, m, izvor, mreza, W) {
  const svg = s("svg", { width: W, height: 20, viewBox: `0 0 ${W} 20`, "aria-hidden": "true" });
  const sirina = W / mreza.n;
  const kodovi = kodoviCelija(izvor, mreza);
  for (let i = 0; i < mreza.n; i++) {
    if (kodovi[i] < 0) continue;
    s("rect", { x: i * sirina, y: 2, width: Math.max(sirina - 1, 1), height: 16, rx: 1.5, class: klasaCelije(kodovi[i]) }, svg);
  }
  svg.addEventListener("pointermove", (e) => {
    const r = svg.getBoundingClientRect();
    const i = Math.min(mreza.n - 1, Math.max(0, Math.floor((e.clientX - r.left) / sirina)));
    prikaziOblacic(oblacicCelije(m, izvor, mreza, i, kodovi[i]), e.clientX, e.clientY);
  });
  svg.addEventListener("pointerleave", sakrijOblacic);
  kont.replaceChildren(svg);
}

function oblacicCelije(m, izvor, mreza, i, kod) {
  const p = st.pregled;
  const a0 = Math.max(mreza.pocetak + i * mreza.korak, m.od);
  const a1 = Math.min(mreza.pocetak + (i + 1) * mreza.korak, m.sada);
  const sadrzaj = [naslovOblacica(`${imeIzvora(izvor.izvor, izvor.velicina, m.model)}, ${raspon(a0, Math.max(a1, a0 + 60000))}`)];
  if (kod < 0) {
    sadrzaj.push(redOblacica(null, a0 < izvor.prvo ? "Još nije bilo rezultata"
      : `Nema rezultata posle ${vreme(izvor.poslednje)}`));
    return sadrzaj;
  }
  const alarmi = izvor.alarmi.filter(([, , , od, doo]) => od < a1 && (doo > a0 || od >= a0));
  for (const [id, tip, ozb, , , status] of alarmi) {
    const stanje = { otvoren: "otvoren", potvrdjen: "potvrđen", resen: "rešen" }[status];
    sadrzaj.push(redOblacica(ikona(ozb, status === "potvrdjen"), p.nazivi[tip] ?? tip, `#${id}, ${stanje}`));
  }
  if (!alarmi.length) sadrzaj.push(redOblacica(ikona("u-redu"), "Bez problema"));
  return sadrzaj;
}

function crtajOsuMatrice(kont, mreza, dani, W) {
  const svg = s("svg", { width: W, height: 16, viewBox: `0 0 ${W} 16` });
  const x = (t) => ((t - mreza.pocetak) / (mreza.kraj - mreza.pocetak)) * W;
  for (const { t, tekst } of podeociVremena(mreza.pocetak, mreza.kraj, W, dani, 46)) {
    const px = x(t);
    if (px < 14 || px > W - 14) continue;
    s("line", { x1: px, x2: px, y1: 0, y2: 3, class: "g-osa" }, svg);
    svgTekst(svg, px, 14, tekst, "g-tekst", "middle");
  }
  kont.replaceChildren(svg);
}

function oznaciIzabraniRed() {
  for (const red of document.querySelectorAll(".red")) {
    const da = red.dataset.model === st.izbor?.model && red.dataset.izvor === st.izbor?.izvor;
    red.setAttribute("aria-pressed", da ? "true" : "false");
  }
}

// ---------------------------------------------------------------------------
// Grafikoni: zajednički delovi
// ---------------------------------------------------------------------------

function okvir(kont, visina) {
  const W = Math.max(kont.clientWidth, 280);
  const svg = s("svg", { width: W, height: visina, viewBox: `0 0 ${W} ${visina}`, role: "img", tabindex: "0" });
  kont.replaceChildren(svg);
  return { svg, W, x0: M.levo, x1: W - M.desno, y0: visina - M.dole, y1: M.gore };
}

function skala(d0, d1, r0, r1) {
  const k = (r1 - r0) / ((d1 - d0) || 1);
  const f = (v) => r0 + (v - d0) * k;
  f.obrnuto = (px) => d0 + (px - r0) / k;
  return f;
}

/** Okrugli podeoci ose (1, 2, 2,5 ili 5 puta stepen desetke). */
function podeoci(min, max, koliko = 5) {
  if (!(max > min)) { const d = Math.abs(min) * 0.1 || 1; min -= d; max += d; }
  const grubo = (max - min) / koliko;
  const stepen = 10 ** Math.floor(Math.log10(grubo));
  const korak = [1, 2, 2.5, 5, 10].map((m) => m * stepen).find((k) => k >= grubo);
  const lista = [];
  for (let v = Math.floor(min / korak) * korak; v <= max + korak * 0.999; v += korak) lista.push(+v.toFixed(10));
  if (lista[lista.length - 1] < max) lista.push(+(lista[lista.length - 1] + korak).toFixed(10));
  const dec = (Number(korak.toFixed(10)).toString().split(".")[1] ?? "").length; // decimale samog koraka
  return { lista, dec };
}

function osaY(g, y, pod, format) {
  for (const v of pod.lista) {
    const py = Math.round(y(v)) + 0.5;
    s("line", { x1: g.x0, x2: g.x1, y1: py, y2: py, class: "g-mreza" }, g.svg);
    svgTekst(g.svg, g.x0 - 8, py + 4, format(v), "g-tekst", "end");
  }
}

function osaX(g, x, d) {
  s("line", { x1: g.x0, x2: g.x1, y1: g.y0 + 0.5, y2: g.y0 + 0.5, class: "g-osa" }, g.svg);
  for (const { t, tekst } of podeociVremena(d.od, d.do, g.x1 - g.x0, d.dani)) {
    const px = Math.round(x(t)) + 0.5;
    if (px < g.x0 || px > g.x1 + 1) continue;
    s("line", { x1: px, x2: px, y1: g.y0, y2: g.y0 + 4, class: "g-osa" }, g.svg);
    svgTekst(g.svg, px, g.y0 + 17, tekst, "g-tekst", "middle");
  }
}

/**
 * Pozadinske trake: normalni period (sivo) i vreme alarma (boja ozbiljnosti).
 * Vraća funkciju koja na kraju, preko podataka, ispiše natpis "normalni period".
 */
function trake(g, x, d) {
  const np = d.normalni_period;
  let natpis = () => {};
  if (np && np.do > d.od) {
    const a = Math.max(np.od, d.od), b = Math.min(np.do, d.do);
    s("rect", { x: x(a), y: g.y1, width: x(b) - x(a), height: g.y0 - g.y1, class: "g-normalni-period" }, g.svg);
    if (x(b) - x(a) > 96) natpis = () => svgTekst(g.svg, x(a) + 6, g.y1 + 14, "normalni period", "g-oznaka");
  }
  for (const a of d.alarmi) {
    const od = Math.max(a.od, d.od), doo = Math.min(a.do, d.do);
    if (doo < od) continue;
    let x0 = x(od), x1 = x(doo);
    if (x1 - x0 < 3) { const c = (x0 + x1) / 2; x0 = c - 1.5; x1 = c + 1.5; }
    let klasa = `g-traka g-traka--${a.ozbiljnost}`;
    if (a.status === "resen") klasa += " g-traka--reseno";
    if (a.id === st.izabranAlarm) klasa += " g-traka--izabrana";
    s("rect", { x: x0, y: g.y1, width: x1 - x0, height: g.y0 - g.y1, class: klasa }, g.svg);
    const znak = oblik(a.ozbiljnost, (x0 + x1) / 2, g.y1 - 9, 5);
    znak.setAttribute("class", `ikona--${a.ozbiljnost}${a.status === "potvrdjen" ? " ikona--potvrdjeno" : ""}`);
    g.svg.append(znak);
  }
  return natpis;
}

function alarmiU(d, t) {
  return d.alarmi.filter((a) => a.od <= t && t <= a.do);
}

function redoviAlarma(d, t) {
  return alarmiU(d, t).map((a) => redOblacica(ikona(a.ozbiljnost, a.status === "potvrdjen"), a.naziv, `#${a.id}`));
}

/** Najbliži indeks u poređanom nizu vremena (binarna pretraga). */
function najblizi(vremena, t) {
  let lo = 0, hi = vremena.length - 1;
  while (hi - lo > 1) {
    const sr = (lo + hi) >> 1;
    if (vremena[sr] < t) lo = sr; else hi = sr;
  }
  return Math.abs(vremena[lo] - t) <= Math.abs(vremena[hi] - t) ? lo : hi;
}

/**
 * Nišan: uspravna linija prati miš i "zakači" se za najbliže vreme, a
 * oblačić pokazuje sve vrednosti u tom trenutku. Isto radi i sa
 * tastature: strelice levo/desno, Home, End, Escape.
 */
function dodajNisan(g, x, vremena, { oznaci, sadrzaj }) {
  if (!vremena.length) return;
  const linija = s("line", { y1: g.y1, y2: g.y0, class: "g-nisan", visibility: "hidden" }, g.svg);
  const povrsina = s("rect", { x: g.x0, y: g.y1, width: g.x1 - g.x0, height: g.y0 - g.y1, class: "g-povrsina-dogadjaja" }, g.svg);
  let trenutni = -1;

  const pokazi = (i, cx, cy) => {
    trenutni = i;
    const px = x(vremena[i]);
    linija.setAttribute("x1", px);
    linija.setAttribute("x2", px);
    linija.setAttribute("visibility", "visible");
    oznaci(i);
    prikaziOblacic(sadrzaj(i), cx, cy);
  };
  const sakrij = () => {
    trenutni = -1;
    linija.setAttribute("visibility", "hidden");
    oznaci(-1);
    sakrijOblacic();
  };
  const saTastature = (i) => {
    const r = g.svg.getBoundingClientRect();
    pokazi(i, r.left + x(vremena[i]), r.top + g.y1 + 20);
  };

  povrsina.addEventListener("pointermove", (e) => {
    const r = g.svg.getBoundingClientRect();
    pokazi(najblizi(vremena, x.obrnuto(e.clientX - r.left)), e.clientX, e.clientY);
  });
  povrsina.addEventListener("pointerleave", sakrij);
  g.svg.addEventListener("focus", () => { if (g.svg.matches(":focus-visible")) saTastature(vremena.length - 1); });
  g.svg.addEventListener("blur", sakrij);
  g.svg.addEventListener("keydown", (e) => {
    const n = vremena.length;
    const ciljevi = { ArrowLeft: trenutni - 1, ArrowRight: trenutni + 1, Home: 0, End: n - 1 };
    if (e.key === "Escape") { sakrij(); return; }
    if (!(e.key in ciljevi)) return;
    e.preventDefault();
    saTastature(Math.max(0, Math.min(n - 1, trenutni < 0 ? n - 1 : ciljevi[e.key])));
  });
}

function oznakeNaKraju(g, oznake) {
  // Oznake na kraju linija. Ako bi se preklopile, izostavljaju se:
  // tada vrstu linije kažu legenda i oblačić.
  if (oznake.length === 2 && Math.abs(oznake[0].y - oznake[1].y) < 14) return;
  for (const o of oznake) svgTekst(g.svg, g.x1 + 8, o.y + 4, o.tekst, "g-tekst g-tekst--jace");
}

// ---------------------------------------------------------------------------
// Grafikon vrednosti (modeli koji vraćaju brojeve)
// ---------------------------------------------------------------------------

function putanja(tacke, kolona, x, y, prekid) {
  let d = "", prethodno = null;
  for (const t of tacke) {
    const v = t[kolona];
    if (v == null || (kolona === 1 && t[3] !== 0)) { prethodno = null; continue; }
    const deo = `${x(t[0]).toFixed(1)} ${y(v).toFixed(1)}`;
    d += prethodno != null && (prekid == null || t[0] - prethodno <= prekid) ? `L${deo}` : `M${deo}`;
    prethodno = t[0];
  }
  return d;
}

function grafikVrednosti(kont, d) {
  const g = okvir(kont, 300);
  const T = d.tacke;
  let min = Infinity, max = -Infinity;
  for (const [, v, sv, o] of T) {
    if (v != null && o === 0) { min = Math.min(min, v); max = Math.max(max, v); }
    if (sv != null) { min = Math.min(min, sv); max = Math.max(max, sv); }
  }
  if (min === Infinity) { min = 0; max = 1; }
  const pod = podeoci(min, max, 5);
  const x = skala(d.od, d.do, g.x0, g.x1);
  const y = skala(pod.lista[0], pod.lista[pod.lista.length - 1], g.y0, g.y1);
  const j = d.jedinica;
  g.svg.setAttribute("aria-label", `Grafikon: vrednosti modela i stvarne vrednosti za ${d.izvor}, `
    + `od ${datum(d.od)} do ${datum(d.do)}. Tačni brojevi su u tabeli (dugme Prikaži tabelu).`);

  const natpis = trake(g, x, d);
  osaY(g, y, pod, (v) => broj(v, pod.dec));
  osaX(g, x, d);

  s("path", { d: putanja(T, 2, x, y, d.prekid_ms), class: "g-linija g-linija--stvarno" }, g.svg);
  s("path", { d: putanja(T, 1, x, y, d.prekid_ms), class: "g-linija g-linija--model" }, g.svg);

  // Posebne tačke: neobična vrednost se crta kao trouglić, sa brojem. Ako je
  // iznad skale, trouglić je na vrhu; ako je ispod, na dnu (okrenut nadole);
  // ako staje na skalu, na svom mestu. Greška modela je kratka crtica na dnu.
  const [yMin, yMax] = [pod.lista[0], pod.lista[pod.lista.length - 1]];
  for (const t of T) {
    const px = x(t[0]);
    if (t[3] === 1) {
      if (t[1] > yMax) {
        s("path", { d: `M${px} ${g.y1 - 2}l5 8h-10z`, class: "g-van-opsega" }, g.svg);
        svgTekst(g.svg, px + 8, g.y1 + 8, saJedinicom(t[1], j), "g-oznaka");
      } else if (t[1] < yMin) {
        s("path", { d: `M${px} ${g.y0 + 2}l5 -8h-10z`, class: "g-van-opsega" }, g.svg);
        svgTekst(g.svg, px + 8, g.y0 - 2, saJedinicom(t[1], j), "g-oznaka");
      } else {
        const py = y(t[1]);
        s("path", { d: `M${px} ${py - 6}l5 9h-10z`, class: "g-van-opsega" }, g.svg);
        svgTekst(g.svg, px + 8, py + 4, saJedinicom(t[1], j), "g-oznaka");
      }
    } else if (t[3] === 2) {
      s("line", { x1: px, x2: px, y1: g.y0 - 9, y2: g.y0 - 1, class: "g-greska" }, g.svg);
    }
  }

  const poslM = T.findLast((t) => t[1] != null && t[3] === 0);
  const poslS = T.findLast((t) => t[2] != null);
  oznakeNaKraju(g, [poslM && { y: y(poslM[1]), tekst: "model" }, poslS && { y: y(poslS[2]), tekst: "stvarno" }].filter(Boolean));
  natpis();

  // Tačka stvarne vrednosti se pravi prva, da tačka modela bude iznad nje.
  const tackaS = s("circle", { r: 4.5, class: "g-tacka g-tacka--stvarno", visibility: "hidden" }, g.svg);
  const tackaM = s("circle", { r: 4.5, class: "g-tacka", visibility: "hidden" }, g.svg);
  const postavi = (tacka, t, v) => {
    if (v == null || t[3] === 1) { tacka.setAttribute("visibility", "hidden"); return; }
    tacka.setAttribute("cx", x(t[0]));
    tacka.setAttribute("cy", y(v));
    tacka.setAttribute("visibility", "visible");
  };
  dodajNisan(g, x, T.map((t) => t[0]), {
    oznaci: (i) => {
      if (i < 0) { tackaM.setAttribute("visibility", "hidden"); tackaS.setAttribute("visibility", "hidden"); return; }
      postavi(tackaM, T[i], T[i][1]);
      postavi(tackaS, T[i], T[i][2]);
    },
    sadrzaj: (i) => {
      const [t, v, sv, o] = T[i];
      const redovi = [naslovOblacica(vremeZa(d)(t))];
      if (o === 2) redovi.push(redOblacica("model", "greška", "model nije vratio rezultat"));
      else if (o === 3) redovi.push(redOblacica("model", "prazno", "rezultat bez vrednosti"));
      else redovi.push(redOblacica("model", saJedinicom(v, j), o === 1 ? "model, neobična vrednost" : "model"));
      if (sv != null) redovi.push(redOblacica("stvarno", saJedinicom(sv, j), "stvarno"));
      if (v != null && sv != null && o === 0) redovi.push(redOblacica(null, saZnakom(v - sv, j, Math.abs(sv) > 1 ? 1 : sv), "greška"));
      return redovi.concat(redoviAlarma(d, t));
    },
  });
}

// ---------------------------------------------------------------------------
// Grafikon kategorija (modeli koji vraćaju kategorije)
// ---------------------------------------------------------------------------

function stubSaZaobljenimVrhom(x, y, w, v, r) {
  r = Math.min(r, w / 2, v);
  return `M${x} ${y + v}V${y + r}Q${x} ${y} ${x + r} ${y}H${x + w - r}Q${x + w} ${y} ${x + w} ${y + r}V${y + v}Z`;
}

function grafikKategorija(kont, d) {
  const g = okvir(kont, 270);
  const k = d.kategorije;
  const zbirovi = k.dani.map(([, , brojevi]) => brojevi.reduce((a, b) => a + b, 0));
  const pod = podeoci(0, Math.max(1, ...zbirovi), 4);
  const x = skala(d.od, d.do, g.x0, g.x1);
  const y = skala(0, pod.lista[pod.lista.length - 1], g.y0, g.y1);
  g.svg.setAttribute("aria-label", `Grafikon: koliko puta je model vratio koju kategoriju, po danima, za ${d.izvor}. `
    + "Tačni brojevi su u tabeli.");

  const natpis = trake(g, x, d);
  osaY(g, y, pod, (v) => broj(v, 0));
  osaX(g, x, d);

  const grupe = [];
  for (const [od, doo, brojevi] of k.dani) {
    const slot = x(doo) - x(od);
    const w = Math.max(1, Math.min(24, slot - 3));
    const levo = (x(od) + x(doo)) / 2 - w / 2;
    const grupa = s("g", { class: "g-stub-grupa" }, g.svg);
    const poslednji = brojevi.findLastIndex((b) => b > 0);
    let zbir = 0;
    brojevi.forEach((b, i) => {
      if (!b) return;
      const gore = y(zbir + b), dole = y(zbir);
      const razmak = i === poslednji ? 0 : 2; // 2 px razmaka između delova stuba
      const visina = Math.max(dole - gore - razmak, 0.5);
      const klasa = `g-stub--${i + 1}`;
      if (i === poslednji) s("path", { d: stubSaZaobljenimVrhom(levo, gore, w, visina, 4), class: klasa }, grupa);
      else s("rect", { x: levo, y: gore + razmak, width: w, height: visina, class: klasa }, grupa);
      zbir += b;
    });
    grupe.push(grupa);
  }
  natpis();

  let aktivna = null;
  dodajNisan(g, x, k.dani.map(([od, doo]) => (od + doo) / 2), {
    oznaci: (i) => {
      aktivna?.classList.remove("aktivna");
      aktivna = i >= 0 ? grupe[i] : null;
      aktivna?.classList.add("aktivna");
    },
    sadrzaj: (i) => {
      const [od, doo, brojevi] = k.dani[i];
      const ukupno = brojevi.reduce((a, b) => a + b, 0);
      const redovi = [naslovOblacica(`${datum(od)}, ukupno ${broj(ukupno, 0)}`)];
      // obrnut redosled: kao na stubu, gornji deo prvi
      for (let n = brojevi.length - 1; n >= 0; n--) {
        redovi.push(redOblacica(`kat-${n + 1}`, broj(brojevi[n], 0), `${k.imena[n]}, ${procenat(ukupno ? brojevi[n] / ukupno : 0)}`));
      }
      return redovi.concat(redoviAlarma(d, (od + doo) / 2));
    },
  });
}

// ---------------------------------------------------------------------------
// Dnevni grafikon: broj koji prati provera drifta, sa granicom
// ---------------------------------------------------------------------------

function grafikDnevni(kont, d) {
  const dn = d.dnevno;
  const g = okvir(kont, 210);
  const x = skala(d.od, d.do, g.x0, g.x1);
  const vrednosti = dn.dani.map((dd) => dd[2]);
  const reference = [dn.normalno, dn.gore, dn.dole].filter((v) => v != null);
  let min = Math.min(...vrednosti, ...reference), max = Math.max(...vrednosti, ...reference);
  if (d.dnevno.naziv.startsWith("Tipična")) min = 0; // greška se meri od nule
  const pod = podeoci(min, max, 4);
  const y = skala(pod.lista[0], pod.lista[pod.lista.length - 1], g.y0, g.y1);
  const format = dn.procenat ? (v) => procenat(v) : (v) => saJedinicom(v, dn.jedinica);
  g.svg.setAttribute("aria-label", `Grafikon: ${dn.naziv.toLowerCase()} za ${d.izvor}. Tačni brojevi su u tabeli.`);

  const natpis = trake(g, x, d);
  osaY(g, y, pod, dn.procenat ? (v) => procenat(v) : (v) => broj(v, pod.dec));
  osaX(g, x, d);

  // Normalni nivo i granica za alarm (naučeni iz normalnog perioda).
  const linije = [];
  if (dn.normalno != null) linije.push([dn.normalno, "normalno", "g-referenca"]);
  for (const v of [dn.gore, dn.dole]) if (v != null) linije.push([v, "granica", "g-referenca g-referenca--granica"]);
  let prethodnaOznaka = null;
  for (const [v, ime, klasa] of linije.sort((a, b) => a[0] - b[0])) {
    const py = Math.round(y(v)) + 0.5;
    s("line", { x1: g.x0, x2: g.x1, y1: py, y2: py, class: klasa }, g.svg);
    if (prethodnaOznaka == null || Math.abs(prethodnaOznaka - py) >= 13) {
      svgTekst(g.svg, g.x1 + 8, py + 4, ime, "g-tekst g-tekst--jace");
      prethodnaOznaka = py;
    }
  }

  // Dan sa mnogo manje rezultata nego obično (npr. današnji, tek počeo)
  // daje nepouzdan broj: crta se kao prazan krug i ne spaja se linijom.
  const brojevi = dn.dani.map((dd) => dd[3]).sort((a, b) => a - b);
  const obicno = brojevi[Math.floor(brojevi.length / 2)] ?? 0;
  const nepotpun = dn.dani.map((dd) => dd[3] < obicno / 4);

  // Linija kroz dane (ili prozore); prekida se gde nema podataka ili je dan nepotpun.
  let put = "", prethodniKraj = null;
  const centri = dn.dani.map(([od, doo]) => (od + doo) / 2);
  const najveciRazmak = dn.po_prozoru && dn.dani.length ? 2 * (dn.dani[0][1] - dn.dani[0][0]) : SAT;
  dn.dani.forEach(([od, doo, v], i) => {
    if (nepotpun[i]) { prethodniKraj = null; return; }
    put += `${prethodniKraj != null && od - prethodniKraj < najveciRazmak ? "L" : "M"}${x(centri[i]).toFixed(1)} ${y(v).toFixed(1)}`;
    prethodniKraj = doo;
  });
  s("path", { d: put, class: "g-linija g-linija--model" }, g.svg);
  // Kad je tačaka mnogo (česta merenja), crta se samo linija, a tačka tek kad se pređe mišem.
  const saTackama = dn.dani.length <= 150;
  const tacke = saTackama ? dn.dani.map(([, , v], i) => s("circle", {
    cx: x(centri[i]), cy: y(v), r: 3.5, class: nepotpun[i] ? "g-tacka g-tacka--nepotpuna" : "g-tacka",
  }, g.svg)) : [];
  const aktivna = s("circle", { r: 5, class: "g-tacka", visibility: "hidden" }, g.svg);
  natpis();
  const vremeT = vremeZa(d);

  dodajNisan(g, x, centri, {
    oznaci: (i) => {
      if (saTackama) { tacke.forEach((t, n) => t.setAttribute("r", n === i ? 5.5 : 3.5)); return; }
      aktivna.setAttribute("visibility", i < 0 ? "hidden" : "visible");
      if (i >= 0) { aktivna.setAttribute("cx", x(centri[i])); aktivna.setAttribute("cy", y(dn.dani[i][2])); }
    },
    sadrzaj: (i) => {
      const [od, doo, v, n] = dn.dani[i];
      const kada = dn.po_prozoru ? `${vremeT(od)} – ${vremeT(doo).split(" ")[1]}` : datum(od);
      const redovi = [naslovOblacica(`${kada}, ${n} ${mnozina(n, ["rezultat", "rezultata", "rezultata"])}`),
        redOblacica("model", format(v), dn.naziv.replace(/ po (danu|prozoru.*)$/, "").toLowerCase())];
      if (nepotpun[i]) redovi.push(redOblacica(null, "nepotpun dan", "malo rezultata, broj nije pouzdan"));
      if (dn.normalno != null) redovi.push(redOblacica(null, format(dn.normalno), "normalno"));
      if (dn.gore != null && v > dn.gore) redovi.push(redOblacica(null, "iznad granice", `granica ${format(dn.gore)}`));
      if (dn.dole != null && v < dn.dole) redovi.push(redOblacica(null, "ispod granice", `granica ${format(dn.dole)}`));
      return redovi.concat(redoviAlarma(d, centri[i]));
    },
  });
}

// ---------------------------------------------------------------------------
// Tabele: isti podaci kao na grafikonima, kao brojevi
// ---------------------------------------------------------------------------

function tabela(zaglavlje, redovi, napomena) {
  return h("div", null,
    h("div", { class: "tabela-okvir", tabindex: "0" },
      h("table", { class: "tabela" },
        h("thead", null, h("tr", null, zaglavlje.map((z) => h("th", { scope: "col" }, z)))),
        h("tbody", null, redovi.map((r) => h("tr", null, r.map((c) => h("td", null, c))))))),
    napomena ? h("p", { class: "tabela__napomena" }, napomena) : null);
}

function tabelaVrednosti(d) {
  const j = d.jedinica;
  const poslednje = d.tacke.slice(-300).reverse();
  const vremeT = vremeZa(d);
  const redovi = poslednje.map(([t, v, sv, o]) => [
    vremeT(t),
    v == null ? "–" : saJedinicom(v, j),
    sv == null ? "–" : saJedinicom(sv, j),
    v != null && sv != null && o === 0 ? saZnakom(v - sv, j, Math.abs(sv) > 1 ? 1 : sv) : "–",
    NAPOMENA_TACKE[o] ?? "",
  ]);
  const napomena = d.tacke.length > 300 ? `Prikazano je poslednjih 300 od ${d.tacke.length} tačaka, najnovije prve.` : "Najnovije prve.";
  return tabela(["Vreme", "Model", "Stvarno", "Greška", "Napomena"], redovi, napomena);
}

function tabelaKategorija(d) {
  const k = d.kategorije;
  const redovi = k.dani.slice().reverse().map(([od, , brojevi]) => [
    datum(od), ...brojevi.map((b) => broj(b, 0)), broj(brojevi.reduce((a, b) => a + b, 0), 0)]);
  return tabela(["Dan", ...k.imena, "Ukupno"], redovi, "Najnoviji dani prvi.");
}

function tabelaDnevna(d) {
  const dn = d.dnevno;
  const format = dn.procenat ? procenat : (v) => saJedinicom(v, dn.jedinica);
  const vremeT = vremeZa(d);
  const kada = dn.po_prozoru ? (od, doo) => `${vremeT(od)} – ${vremeT(doo).split(" ")[1]}` : (od) => datum(od);
  const redovi = dn.dani.slice().reverse().map(([od, doo, v, n]) => [kada(od, doo), format(v), broj(n, 0)]);
  // (nepotpuni dani su i u tabeli, sa svojim brojem rezultata, pa se vidi koliko su pouzdani)
  const delovi_ = [];
  if (dn.normalno != null) delovi_.push(`Normalno: ${format(dn.normalno)}.`);
  if (dn.gore != null) delovi_.push(`Granica za alarm: iznad ${format(dn.gore)}.`);
  if (dn.dole != null) delovi_.push(`Granica za alarm: ispod ${format(dn.dole)}.`);
  const vrednost = dn.naziv.replace(/ po (danu|prozoru.*)$/, "");
  return tabela([dn.po_prozoru ? "Prozor" : "Dan", vrednost, "Rezultata"], redovi, delovi_.join(" "));
}

// ---------------------------------------------------------------------------
// Detalj izabranog izvora
// ---------------------------------------------------------------------------

function legenda(stavke) {
  return h("ul", { class: "legenda" }, stavke.map(([vrsta, klasa, tekst]) => h("li", null,
    h("span", { class: `legenda__${vrsta} ${klasa}`, "aria-hidden": "true" }), tekst)));
}

/** Okvir jednog grafikona: naslov, legenda, dugme za tabelu, pa grafikon ili tabela. */
function figura(kljuc, naslov, opis, leg, crtaj, napraviTabelu, kont = "grafikoni") {
  const kaoTabela = Boolean(st.tabela[kljuc]);
  const platno = h("div", { class: "grafik__platno" });
  const fig = h("figure", { class: "grafik" },
    h("div", { class: "grafik__glava" },
      h("h3", { class: "grafik__naslov" }, naslov),
      h("div", { class: "grafik__alati" }, kaoTabela ? null : leg,
        h("button", {
          type: "button", class: "dugme dugme--tiho dugme--malo", "aria-pressed": kaoTabela ? "true" : "false",
          onclick: () => { st.tabela[kljuc] = !kaoTabela; crtajDetalj(); },
        }, kaoTabela ? "Prikaži grafikon" : "Prikaži tabelu"))),
    opis ? h("p", { class: "grafik__opis" }, opis) : null,
    platno);
  $(kont).append(fig);
  if (kaoTabela) platno.replaceChildren(napraviTabelu());
  else crtaj(platno);
}

function opisSerije(d) {
  let t = `${d.model}, ${d.velicina.replaceAll("_", " ")}`;
  if (d.jedinica) t += ` u ${d.jedinica}`;
  if (d.horizont_min) t += `, predviđanje ${trajanje(d.horizont_min * 60000)} unapred`;
  if (d.vrsta === "kategorija") t += ", kategorije";
  return t;
}

function crtajDetalj() {
  const d = st.serija;
  const sekcija = $("detalj");
  if (!sekcija) return;
  if (!d || ($("detalji") && !$("detalji").open)) { sekcija.hidden = true; return; }
  sekcija.hidden = false;

  $("detalj-naslov").textContent = imeIzvora(d.izvor, d.velicina, d.model);
  $("detalj-podnaslov").textContent = opisSerije(d);

  // Ako izvor ima više serija (npr. prognoze za 1 h i 24 h), bira se jedna.
  const izbor = $("izbor-serije");
  izbor.hidden = !d.ostale.length;
  if (d.ostale.length) {
    const sve = [{ velicina: d.velicina, horizont_min: d.horizont_min }, ...d.ostale];
    $("serija").replaceChildren(...sve.map((x, i) => h("option", { value: i },
      `${x.velicina.replaceAll("_", " ")}${x.horizont_min ? `, ${trajanje(x.horizont_min * 60000)} unapred` : ""}`)));
    $("serija").onchange = (e) => {
      const x = sve[+e.target.value];
      st.izbor = { ...st.izbor, velicina: x.velicina, horizont: x.horizont_min };
      ucitajSeriju();
    };
  }

  $("pokazatelji").replaceChildren(...d.pokazatelji.map((p) => h("div", { class: "pokazatelj" },
    h("dt", null, p.naziv),
    h("dd", null, h("span", { class: "pokazatelj__vrednost" }, p.vrednost), h("span", { class: "pokazatelj__opis" }, p.opis)))));

  $("grafikoni").replaceChildren();
  $("grafikoni-vise").replaceChildren();
  if (d.vrsta === "broj") {
    // Bez stvarnih vrednosti (npr. obična merenja) nema ni linije "stvarno".
    const imaStvarnih = d.tacke.some((t) => t[2] != null);
    const stavke = [["linija", "k-model", "model"], ["povrsina", "k-normalno", "normalni period"]];
    if (imaStvarnih) stavke.splice(1, 0, ["linija", "k-stvarno", "stvarno"]);
    figura("vrednosti", `${imaStvarnih ? "Šta model kaže, a šta se zaista desilo" : "Šta model vraća"}${d.jedinica ? `, ${d.jedinica}` : ""}`,
      "Siva pozadina je normalni period: iz njega je aplikacija naučila šta je uobičajeno. Obojena pozadina je vreme problema.",
      legenda(stavke), (p) => grafikVrednosti(p, d), () => tabelaVrednosti(d));
  } else {
    figura("kategorije", "Šta model odgovara, po danima",
      "Koliko puta je model dao koji odgovor. Kad se odnos promeni, to se vidi i bez stvarnih vrednosti.",
      legenda(d.kategorije.imena.map((ime, i) => ["povrsina", `k-kat-${i + 1}`, ime])),
      (p) => grafikKategorija(p, d), () => tabelaKategorija(d));
  }

  // Pod "Više": broj koji provera stvarno gleda, sa granicom, i naučene granice.
  const vise = $("vise");
  vise.hidden = !(d.dnevno?.dani.length || d.naucene_granice.length);
  if (d.dnevno?.dani.length) {
    const jedinica = d.dnevno.procenat ? "%" : d.dnevno.jedinica;
    figura("dnevno", `${d.dnevno.naziv}${jedinica ? `, ${jedinica}` : ""}`, d.dnevno.opis, null,
      (p) => grafikDnevni(p, d), () => tabelaDnevna(d), "grafikoni-vise");
  }
  const naucene = $("naucene");
  naucene.hidden = !d.naucene_granice.length;
  naucene.replaceChildren(
    h("h3", null, "Granice za ovaj izvor"),
    h("p", null, "Aplikacija ih je sama izračunala iz normalnog perioda. Problem se javlja kad se neka od njih pređe."),
    h("ul", null, d.naucene_granice.map((t) => h("li", null, t))));
}

async function ucitajSeriju() {
  if (!$("detalj")) return;
  if (!st.izbor || ($("detalji") && !$("detalji").open)) { st.serija = null; crtajDetalj(); return; }
  const upit = new URLSearchParams({ model: st.izbor.model, izvor: st.izbor.izvor, dana: st.dana });
  if (st.izbor.velicina != null) {
    upit.set("velicina", st.izbor.velicina);
    if (st.izbor.horizont != null) upit.set("horizont", st.izbor.horizont);
  }
  try {
    st.serija = await api(`/api/serija?${upit}`);
  } catch (e) {
    st.serija = null;
    obavesti(e.message, true);
  }
  crtajDetalj();
}

// ---------------------------------------------------------------------------
// Alarmi
// ---------------------------------------------------------------------------

/**
 * Isti problem u isto vreme na više izvora jednog modela (npr. svi senzori
 * iz jedne tabele su ćutali isti minut) prikazuje se jednom, sa spiskom izvora.
 */
function grupisi(alarmi) {
  const grupe = new Map();
  for (const a of alarmi) {
    const kljuc = [a.tip, a.model, a.od, a.do, a.ozbiljnost, a.status].join("|");
    if (!grupe.has(kljuc)) grupe.set(kljuc, []);
    grupe.get(kljuc).push(a);
  }
  return [...grupe.values()];
}

function crtajAlarme() {
  if (!$("lista-alarma")) return;
  const grupe = grupisi(st.alarmi);
  if (!grupe.length) {
    $("lista-alarma").replaceChildren(h("li", { class: "prazno" }, st.svi
      ? "Još nije bilo nijednog problema."
      : "Nema problema. Kad provera nešto nađe, pojaviće se ovde."));
    return;
  }
  $("lista-alarma").replaceChildren(...grupe.map(stavkaAlarma));
  st.noviAlarmi.clear();
}

function stavkaAlarma(grupa) {
  const a = grupa[0];
  const brojevi = grupa.map((x) => x.id);
  let klasa = "alarm";
  if (a.status === "resen") klasa += " alarm--reseno";
  if (brojevi.includes(st.izabranAlarm)) klasa += " alarm--izabran";
  if (brojevi.some((id) => st.noviAlarmi.has(id))) klasa += " alarm--nov";

  let stanje;
  if (a.status === "resen") stanje = a.napomena === "Prestalo samo." ? "Prošlo." : "Rešeno.";
  else if (a.status === "potvrdjen") stanje = `Video ${a.potvrdio}, ${vreme(a.poslednji_put)}.`;
  else stanje = `Primećeno ${vreme(a.prvi_put)}.`;
  const izvorIme = imeIzvora(a.izvor, null, a.model);
  const mesto = grupa.length > 1 ? `${a.model}, ${grupa.length} izvora`
    : (st.pregled?.ukupno.modela > 1 && izvorIme !== a.model ? `${a.model}, ${izvorIme}` : izvorIme);

  return h("li", { class: klasa, "data-grupa": brojevi.join(","), onclick: () => izaberiAlarm(a) },
    h("div", { class: "alarm__glava" },
      ikona(a.ozbiljnost),
      h("span", { class: "alarm__ozbiljnost" }, OZBILJNOST[a.ozbiljnost]),
      h("span", { class: "alarm__broj" }, raspon(a.od, a.do))),
    // Naslov je dugme, da se problem može izabrati i sa tastature (Tab, pa Enter).
    h("h3", { class: "alarm__naziv" }, h("button", {
      type: "button", class: "alarm__izaberi",
      onclick: (e) => { e.stopPropagation(); izaberiAlarm(a); },
    }, a.naziv)),
    h("p", { class: "alarm__mesto" }, mesto),
    grupa.length > 1 ? h("p", { class: "alarm__izvori" }, grupa.map((x) => x.izvor).join(", ")) : null,
    h("p", { class: "alarm__opis" }, a.opis),
    h("div", { class: "alarm__dno" },
      h("span", { class: "alarm__stanje" }, stanje),
      a.status === "otvoren" ? h("button", {
        type: "button", class: "dugme dugme--malo",
        onclick: (e) => { e.stopPropagation(); videoGrupu(grupa, e.currentTarget); },
      }, "Video sam") : null));
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

/** Jedan klik: neko je video problem (na svim izvorima u grupi). Problem se sam gasi kad prođe. */
async function videoGrupu(grupa, dugme) {
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

function izaberiAlarm(a) {
  if ($("detalji") && !$("detalji").open) $("detalji").open = true; // toggle crta matricu
  // Ako je alarm stariji od prikazanog perioda, period se proširi da se vidi.
  const m = st.pregled?.modeli.find((x) => x.model === a.model);
  if (m && a.od < m.od) {
    const dana = PERIODI.find((n) => a.od >= m.sada - n * DAN) ?? PERIODI[PERIODI.length - 1];
    if (dana !== st.dana) {
      st.dana = dana;
      zapamti("dana", dana);
      oznaciPeriod();
      st.izbor = { model: a.model, izvor: a.izvor, velicina: null, horizont: null };
      st.izabranAlarm = a.id;
      osvezi();
      return;
    }
  }
  izaberiIzvor(a.model, a.izvor, a.id);
}

// ---------------------------------------------------------------------------
// Šta se prati: spisak fajlova iz podešavanja, sa uklanjanjem
// ---------------------------------------------------------------------------

function crtajPracene() {
  if (!$("praceno-lista")) return;
  if (!st.izvori.length) {
    $("praceno-lista").replaceChildren(h("li", { class: "prazno" },
      "Još se ništa ne prati. Kliknite Dodaj podatke i ubacite fajl koji model pravi, ili upišite folder u kome ih ostavlja."));
    return;
  }
  $("praceno-lista").replaceChildren(...st.izvori.map((i) => h("li", { class: "praceno__stavka" },
    h("div", null,
      h("strong", null, i.model),
      h("span", { class: "praceno__putanja" }, i.putanja),
      i.kolone ? h("span", { class: "praceno__napomena" }, `${i.kolone.length} ${mnozina(i.kolone.length, ["kolona", "kolone", "kolona"])} kao izvori`) : null,
      i.istorijski ? h("span", { class: "praceno__napomena" }, "stari podaci") : null),
    h("button", {
      type: "button", class: "dugme dugme--tiho dugme--malo",
      onclick: async (e) => {
        if (!confirm(`Ukloniti "${i.model}" sa spiska i obrisati njegove rezultate i probleme iz baze? Sam fajl se ne dira.`)) return;
        e.currentTarget.disabled = true;
        try {
          await api(`/api/izvori/${encodeURIComponent(i.model)}`, null, "DELETE");
          obavesti(`"${i.model}" više se ne prati.`);
          if (st.izbor?.model === i.model) st.izbor = null;
          await osvezi();
        } catch (greska) {
          e.currentTarget.disabled = false;
          obavesti(greska.message, true);
        }
      },
    }, "Ukloni"))));
}

// ---------------------------------------------------------------------------
// Dodavanje podataka: fajl ili putanja -> predlog kolona -> potvrda
// ---------------------------------------------------------------------------

function otvoriDodavanje() {
  st.predlog = null;
  korakFajl();
  $("dijalog").showModal();
}

function korakFajl(greska = null) {
  $("dijalog-naslov").textContent = "Dodaj podatke";
  const ulaz = h("input", { type: "file", accept: ".csv,.txt,text/csv,text/plain", id: "fajl-ulaz" });
  ulaz.addEventListener("change", () => { if (ulaz.files[0]) posaljiFajl(ulaz.files[0]); });
  const zona = h("label", { class: "ubaci", for: "fajl-ulaz" },
    h("span", { class: "ubaci__ikona", "aria-hidden": "true" }, "⤓"),
    h("span", { class: "ubaci__tekst" }, "Izaberite CSV fajl ili ga prevucite ovde"),
    h("span", { class: "ubaci__malo" }, "fajl koji model pravi; Excel tabela sačuvana kao CSV takođe radi"),
    ulaz);
  for (const ime of ["dragenter", "dragover"]) {
    zona.addEventListener(ime, (e) => { e.preventDefault(); zona.classList.add("ubaci--preko"); });
  }
  zona.addEventListener("dragleave", () => zona.classList.remove("ubaci--preko"));
  zona.addEventListener("drop", (e) => {
    e.preventDefault();
    zona.classList.remove("ubaci--preko");
    const f = e.dataTransfer.files[0];
    if (f) posaljiFajl(f);
  });

  const putanja = h("input", { type: "text", id: "putanja-ulaz", maxlength: 1000, spellcheck: "false",
    placeholder: "/Users/ime/rezultati/model.csv  ili  /Users/ime/rezultati" });
  const pogledaj = h("button", { type: "button", class: "dugme dugme--tiho" }, "Pogledaj");
  pogledaj.addEventListener("click", () => { if (putanja.value.trim()) posaljiPutanju(putanja.value.trim(), pogledaj); });
  putanja.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); pogledaj.click(); } });

  $("dijalog-telo").replaceChildren(...[
    h("p", { class: "dijalog__uvod" }, "Aplikacija sama prepozna koja kolona je vreme, a koja rezultat modela. Vi samo potvrdite."),
    greska ? h("p", { class: "dijalog__greska", role: "alert" }, greska) : null,
    zona,
    h("p", { class: "ili" }, "ili"),
    h("label", { class: "polje" }, h("span", null, "Fajl ili folder koji već postoji na ovom računaru"),
      h("div", { class: "polje__red" }, putanja, pogledaj)),
    h("p", { class: "dijalog__napomena" },
      "Folder: prate se svi CSV fajlovi u njemu, i oni koji se tek pojave. Ovo je za pravi rad, kad model sam ostavlja fajlove. "
      + "Aplikacija ih samo čita i ništa u njima ne menja."),
  ].filter(Boolean));
}

function prikaziCekanje(tekst) {
  $("dijalog-telo").replaceChildren(h("p", { class: "dijalog__cekanje" }, tekst));
}

async function posaljiFajl(fajl) {
  prikaziCekanje(`Čitam ${fajl.name}…`);
  try {
    const odgovor = await fetch("/api/izvori/predlog", {
      method: "POST", body: fajl,
      headers: { "X-Dashboard": "1", "X-Fajl": encodeURIComponent(fajl.name), "Content-Type": "application/octet-stream" },
    });
    if (!odgovor.ok) throw new Error((await odgovor.json()).detail ?? `Greška ${odgovor.status}.`);
    st.predlog = await odgovor.json();
    korakPotvrda();
  } catch (e) {
    korakFajl(e.message === "Failed to fetch" ? "Server ne odgovara." : e.message);
  }
}

async function posaljiPutanju(putanja, dugme) {
  dugme.disabled = true;
  try {
    st.predlog = await api("/api/izvori/predlog", { putanja });
    korakPotvrda();
  } catch (e) {
    korakFajl(e.message);
  }
}

/** Drugi korak: šta je prepoznato, sa mogućnošću ispravke, pa "Dodaj i proveri". */
function korakPotvrda(greska = null) {
  const pr = st.predlog;
  $("dijalog-naslov").textContent = "Proverite šta je prepoznato";
  const kolone = pr.kolone;
  const opisKolone = (k) => `${k.naziv}  (${k.vrsta}${k.razlicitih > 1 ? `, ${broj(k.razlicitih, 0)} različitih` : ""})`;

  const model = h("input", { type: "text", value: pr.model, maxlength: 100, required: true, spellcheck: "false" });
  const istorijski = h("input", { type: "checkbox", checked: pr.istorijski });
  const siroka = h("input", { type: "radio", name: "oblik", value: "siroka", checked: pr.siroka });
  const uska = h("input", { type: "radio", name: "oblik", value: "uska", checked: !pr.siroka });
  const dm = h("input", { type: "radio", name: "redosled", value: "dm", checked: pr.redosled_datuma === "dm" });
  const md = h("input", { type: "radio", name: "redosled", value: "md", checked: pr.redosled_datuma === "md" });

  const izbori = {};
  const poljaUska = ["vrednost", "kategorija", "stvarna_vrednost", "stvarna_kategorija", "izvor"];
  const poljaSvuda = pr.polja_za_izbor.filter((p) => !poljaUska.includes(p.polje));
  const napraviIzbor = (polje) => {
    const sel = h("select", null, h("option", { value: "" }, "—"),
      ...kolone.map((k) => h("option", { value: k.naziv, selected: pr.polja[polje] === k.naziv }, opisKolone(k))));
    izbori[polje] = sel;
    return sel;
  };
  const redPolja = (p) => h("label", { class: "polje polje--izbor", title: p.opis },
    h("span", null, p.naziv, p.polje === "vreme" ? " *" : ""), napraviIzbor(p.polje));

  const kvadratici = {};
  const listaKolona = h("div", { class: "kolone-izbor" }, ...pr.brojcane.map((naziv) => {
    const k = kolone.find((x) => x.naziv === naziv);
    // Unapred označene: merenja (mnogo različitih vrednosti), ne šifre (mesec 1-12, dan u nedelji 0-6).
    const cb = h("input", { type: "checkbox", value: naziv, checked: pr.brojcane.length <= 3 || k.razlicitih >= 25 });
    kvadratici[naziv] = cb;
    return h("label", { class: "kolone-izbor__stavka" }, cb, h("span", null, naziv),
      h("span", { class: "kolone-izbor__malo" }, `${broj(k.razlicitih, 0)} različitih`));
  }));
  const deoSiroka = h("div", { class: "deo-oblika" },
    h("p", { class: "dijalog__napomena" }, "Svaka označena kolona postaje poseban izvor (npr. senzor), a pratiće se zajedno."),
    listaKolona);
  const deoUska = h("div", { class: "deo-oblika polja" }, ...pr.polja_za_izbor.filter((p) => poljaUska.includes(p.polje)).map(redPolja));
  const osveziOblik = () => { deoSiroka.hidden = !siroka.checked; deoUska.hidden = siroka.checked; };
  siroka.addEventListener("change", osveziOblik);
  uska.addEventListener("change", osveziOblik);
  osveziOblik();

  const posalji = h("button", { type: "submit", class: "dugme" }, "Dodaj i proveri");
  const nazad = h("button", { type: "button", class: "dugme dugme--tiho", onclick: () => korakFajl() }, "Nazad");
  const forma = $("dijalog-forma");
  forma.onsubmit = async (e) => {
    e.preventDefault();
    posalji.disabled = true;
    const polja = {};
    for (const [polje, sel] of Object.entries(izbori)) {
      if (sel.value && (!siroka.checked || !poljaUska.includes(polje))) polja[polje] = sel.value;
    }
    const izabrane = siroka.checked ? Object.values(kvadratici).filter((cb) => cb.checked).map((cb) => cb.value) : null;
    try {
      const r = await api("/api/izvori", {
        putanja: pr.putanja, model: model.value.trim(), polja, kolone: izabrane,
        istorijski: istorijski.checked, redosled_datuma: md.checked ? "md" : "dm",
      });
      $("dijalog").close();
      const iz = r.izvestaj;
      let tekst = `Učitano ${broj(iz.novih_rezultata, 0)} ${mnozina(iz.novih_rezultata, ["rezultat", "rezultata", "rezultata"])}, `
        + `${iz.novih_alarma} ${mnozina(iz.novih_alarma, ["problem", "problema", "problema"])}.`;
      if (iz.greske.length) tekst += ` ${iz.greske.join(" ")}`;
      obavesti(tekst, iz.greske.length > 0);
      st.izbor = null;
      st.model = "";
      $("provera-opis") && ($("provera-opis").textContent = tekst);
      await osvezi();
    } catch (greska) {
      posalji.disabled = false;
      korakPotvrda(greska.message);
    }
  };

  const opseg = pr.od ? `${vremeGodina(Date.parse(pr.od))} – ${vremeGodina(Date.parse(pr.do))}` : "vreme nije prepoznato";
  $("dijalog-telo").replaceChildren(...[
    h("p", { class: "dijalog__uvod" },
      h("strong", null, pr.fajl.split("/").pop()), `: ${broj(pr.redova, 0)} ${mnozina(pr.redova, ["red", "reda", "redova"])}, ${opseg}.`),
    greska ? h("p", { class: "dijalog__greska", role: "alert" }, greska) : null,
    pr.upozorenja.length ? h("ul", { class: "dijalog__upozorenja" }, pr.upozorenja.map((u) => h("li", null, u))) : null,
    h("div", { class: "polja" },
      h("label", { class: "polje" }, h("span", null, "Naziv modela"), model),
      ...poljaSvuda.map(redPolja)),
    h("fieldset", { class: "oblik" },
      h("legend", null, "Kako je zapisan rezultat modela?"),
      h("label", null, uska, " u jednoj koloni"),
      h("label", null, siroka, " u više kolona, svaka je poseban izvor")),
    deoUska,
    deoSiroka,
    pr.kolone.some((k) => k.primeri.some((v) => /\d\/\d/.test(v))) ? h("fieldset", { class: "oblik" },
      h("legend", null, "Datumi sa kosim crtama: šta je prvo?"),
      h("label", null, dm, " dan pa mesec (11/10 = 11. oktobar)"),
      h("label", null, md, " mesec pa dan (11/10 = 10. novembar)")) : null,
    h("label", { class: "polje polje--kvadratic" }, istorijski,
      h("span", null, "Ovo su stari podaci (proba ili arhiva)",
        h("span", { class: "polje__malo" }, pr.istorijski
          ? ` Poslednji rezultat je od ${vremeGodina(Date.parse(pr.do))}, pa se vreme računa od njega. Inače bi pisalo da podaci ne stižu.`
          : " Za fajl koji model i dalje dopunjava ostavite prazno."))),
    h("div", { class: "dijalog__dugmad" }, nazad, posalji),
  ].filter(Boolean));
  model.focus();
}

// ---------------------------------------------------------------------------
// Izbor, filteri, osvežavanje
// ---------------------------------------------------------------------------

function izaberiIzvor(model, izvor, alarm = null) {
  const isti = st.izbor?.model === model && st.izbor?.izvor === izvor;
  st.izbor = isti ? st.izbor : { model, izvor, velicina: null, horizont: null };
  st.izabranAlarm = alarm;
  zapamti("izbor", { model, izvor });
  oznaciIzabraniRed();
  crtajAlarme();
  if (isti && st.serija) crtajDetalj(); else ucitajSeriju();
  if (alarm != null && $("detalj")) {
    const detalj = $("detalj");
    const r = detalj.getBoundingClientRect();
    if (r.top > innerHeight - 120 || r.bottom < 0) {
      detalj.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
    }
  }
}

/** Ako izabrani izvor više ne postoji (ili nije izabran), bira se najvažniji. */
function proveriIzbor() {
  const p = st.pregled;
  const postoji = (m, i) => p.modeli.some((x) => x.model === m && (!st.model || x.model === st.model) && x.izvori.some((y) => y.izvor === i));
  if (st.izbor && postoji(st.izbor.model, st.izbor.izvor)) return;
  const a = p.najhitniji;
  if (a && postoji(a.model, a.izvor)) {
    st.izbor = { model: a.model, izvor: a.izvor, velicina: null, horizont: null };
    return;
  }
  const kandidati = p.modeli.filter((m) => !st.model || m.model === st.model);
  const najgori = kandidati.flatMap((m) => m.izvori.map((i) => [m.model, i]))
    .sort((a, b) => (RANG[b[1].stanje] ?? 0) - (RANG[a[1].stanje] ?? 0))[0];
  st.izbor = najgori ? { model: najgori[0], izvor: najgori[1].izvor, velicina: null, horizont: null } : null;
}

function popuniModele() {
  const select = $("filter-model");
  if (!select) return;
  const modeli = st.pregled.modeli.map((m) => m.model);
  const postojeci = [...select.options].slice(1).map((o) => o.value);
  if (postojeci.join("|") !== modeli.join("|")) {
    select.replaceChildren(h("option", { value: "" }, "Svi modeli"), ...modeli.map((m) => h("option", { value: m }, m)));
  }
  if (st.model && !modeli.includes(st.model)) st.model = "";
  select.value = st.model;
  $("izbor-modela").hidden = modeli.length < 2;
  $("filteri").hidden = !st.pregled.modeli.length;
}

function oznaciPeriod() {
  if ($("period")) $("period").value = String(st.dana);
  if ($("koji-alarmi")) {
    $("koji-alarmi").setAttribute("aria-pressed", String(st.svi));
    $("koji-alarmi").textContent = st.svi ? "Sakrij prošle" : "Prikaži i prošle";
  }
}

let tekuceOsvezavanje = null;

async function osvezi() {
  if (tekuceOsvezavanje) return tekuceOsvezavanje; // ne dva osvežavanja odjednom
  tekuceOsvezavanje = (async () => {
    // Dok stižu novi podaci, stari prikaz ostaje (samo bleđi): bez treptanja i skakanja.
    const tajmer = setTimeout(() => document.body.classList.add("ucitava"), 250);
    try {
      const [pregled, alarmi, izvori] = await Promise.all([
        api(`/api/pregled?dana=${st.dana}`), api(`/api/alarmi?svi=${st.svi}`), api("/api/izvori")]);
      postaviZonu(pregled.zona);
      st.pregled = pregled;
      st.alarmi = alarmi;
      st.izvori = izvori;
      st.verzija = pregled.verzija;
      st.osvezeno = Date.now();
      primetiNoveAlarme(alarmi);
      proveriIzbor();
      crtajSemafor();
      popuniModele();
      crtajMatricu();
      crtajPracene();
      crtajAlarme();
      crtajStatus();
      await ucitajSeriju();
    } catch (e) {
      obavesti(e.message, true);
    } finally {
      clearTimeout(tajmer);
      document.body.classList.remove("ucitava");
      tekuceOsvezavanje = null;
    }
  })();
  return tekuceOsvezavanje;
}

function primetiNoveAlarme(alarmi) {
  const nereseni = alarmi.filter((a) => a.status !== "resen");
  if (st.poznatiAlarmi) {
    const novi = nereseni.filter((a) => !st.poznatiAlarmi.has(a.id));
    for (const a of novi) st.noviAlarmi.add(a.id);
    if (novi.length === 1) obavesti(`Nov problem: ${novi[0].naziv.toLowerCase()} (${novi[0].model}, ${imeIzvora(novi[0].izvor, null, novi[0].model)}).`);
    else if (novi.length > 1) obavesti(`${novi.length} ${mnozina(novi.length, ["nov problem", "nova problema", "novih problema"])}.`);
  }
  st.poznatiAlarmi = new Set([...(st.poznatiAlarmi ?? []), ...nereseni.map((a) => a.id)]);
}

async function proveriVerziju() {
  if (document.hidden) return; // kartica nije vidljiva: ne opterećuj server
  try {
    const stanje = await api("/api/stanje");
    st.nadzor = stanje.nadzor;
    st.sadaPoPodacima = stanje.sada_po_podacima;
    if (stanje.verzija !== st.verzija) await osvezi();
    else crtajStatus();
  } catch {
    $("status").textContent = "Server ne odgovara. Prikazani su poslednji poznati podaci.";
  }
}

async function proveriSada() {
  const dugme = $("proveri");
  dugme.disabled = true;
  dugme.textContent = "Proveravam…";
  try {
    const iz = await api("/api/nadzor", {});
    let tekst = `Provera je završena: ${iz.novih_rezultata} ${mnozina(iz.novih_rezultata, ["nov rezultat", "nova rezultata", "novih rezultata"])}, `
      + `${iz.novih_alarma} ${mnozina(iz.novih_alarma, ["nov problem", "nova problema", "novih problema"])}.`;
    if (iz.greske.length) tekst += ` Problemi: ${iz.greske.join(" ")}`;
    obavesti(tekst, iz.greske.length > 0);
    await osvezi();
  } catch (e) {
    obavesti(e.message, true);
  } finally {
    dugme.disabled = false;
    dugme.textContent = "Proveri sada";
  }
}

// ---------------------------------------------------------------------------
// Pokretanje
// ---------------------------------------------------------------------------

function pokreni() {
  // Tema prati podešavanje računara (svetla ili tamna); nema šta da se bira.
  st.dana = PERIODI.includes(seti("dana", 30)) ? seti("dana", 30) : 30;
  const izbor = seti("izbor", null);
  if (izbor?.model && izbor?.izvor) st.izbor = { model: izbor.model, izvor: izbor.izvor, velicina: null, horizont: null };
  oznaciPeriod();
  legendaStanja();

  $("proveri")?.addEventListener("click", proveriSada);
  $("dodaj")?.addEventListener("click", otvoriDodavanje);
  $("dijalog-zatvori")?.addEventListener("click", () => $("dijalog").close());
  $("period")?.addEventListener("change", (e) => {
    const dana = +e.target.value;
    if (!dana || dana === st.dana) return;
    st.dana = dana;
    zapamti("dana", dana);
    osvezi();
  });
  $("koji-alarmi")?.addEventListener("click", async () => {
    st.svi = !st.svi;
    oznaciPeriod();
    try {
      st.alarmi = await api(`/api/alarmi?svi=${st.svi}`);
      crtajAlarme();
    } catch (greska) {
      obavesti(greska.message, true);
    }
  });
  $("filter-model")?.addEventListener("change", (e) => {
    st.model = e.target.value;
    const pre = st.izbor;
    proveriIzbor();
    crtajMatricu();
    if (st.izbor !== pre) ucitajSeriju();
  });
  // Detalji se crtaju tek kad se otvore (zatvoreni nemaju širinu).
  $("detalji")?.addEventListener("toggle", () => { if (st.pregled) { crtajMatricu(); ucitajSeriju(); } });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") sakrijOblacic(); });
  addEventListener("scroll", sakrijOblacic, { passive: true });

  // Kad se promeni širina prozora, grafikoni se ponovo nacrtaju u novoj širini.
  let sirina = 0, tajmer;
  new ResizeObserver(() => {
    const nova = $("sadrzaj").clientWidth;
    if (nova === sirina) return;
    sirina = nova;
    clearTimeout(tajmer);
    tajmer = setTimeout(() => { if (st.pregled) { crtajMatricu(); crtajDetalj(); } }, 120);
  }).observe($("sadrzaj"));

  proveriVerziju();
  setInterval(proveriVerziju, OSVEZAVANJE_MS);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) proveriVerziju(); });
}

pokreni();
