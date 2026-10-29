/* ===== NÚCLEO DE CÁLCULO — funções puras (sem DOM) ===== */
const MET = (() => {
  const PI = Math.PI, rad = PI / 180, dayMs = 864e5, J1970 = 2440588, J2000 = 2451545, E = rad * 23.4397;

  /* ---------- Fuso horário ---------- */
  function tzOffsetMin(utcMs, tz) {
    const p = {};
    new Intl.DateTimeFormat('en-US', { timeZone: tz, hourCycle: 'h23', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' })
      .formatToParts(new Date(utcMs)).forEach(x => { p[x.type] = x.value; });
    const asUTC = Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour % 24, +p.minute, +p.second);
    return Math.round((asUTC - Math.floor(utcMs / 1000) * 1000) / 60000);
  }
  function zonedToUtc(y, mo, d, h, mi, tz) {
    const g = Date.UTC(y, mo - 1, d, h, mi);
    let off = tzOffsetMin(g, tz);
    off = tzOffsetMin(g - off * 6e4, tz);
    return g - off * 6e4;
  }
  function localParts(ms, tz) {
    const p = {};
    new Intl.DateTimeFormat('en-US', { timeZone: tz, hourCycle: 'h23', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
      .formatToParts(new Date(ms)).forEach(x => { p[x.type] = x.value; });
    return { y: +p.year, mo: +p.month, d: +p.day, h: +p.hour % 24, mi: +p.minute };
  }
  const pad = n => String(n).padStart(2, '0');
  function hhmm(ms, tz) { if (ms == null || isNaN(ms)) return '—'; const p = localParts(ms, tz); return pad(p.h) + ':' + pad(p.mi); }
  function ddmm(ms, tz) { const p = localParts(ms, tz); return pad(p.d) + '/' + pad(p.mo); }
  function localKey(ms, tz) { const p = localParts(ms, tz); return `${p.y}-${pad(p.mo)}-${pad(p.d)}T${pad(p.h)}:00`; }
  function isoDate(y, mo, d) { return `${y}-${pad(mo)}-${pad(d)}`; }
  function shiftDate(dateStr, days) {
    const [y, m, d] = dateStr.split('-').map(Number);
    const t = new Date(Date.UTC(y, m - 1, d + days));
    return isoDate(t.getUTCFullYear(), t.getUTCMonth() + 1, t.getUTCDate());
  }

  /* ---------- Coordenadas ---------- */
  function parseCoord(str, isLat) {
    if (str == null) return null;
    let s = String(str).trim().toUpperCase().replace(',', '.');
    if (!s) return null;
    let sign = 1;
    if (/[SW]/.test(s)) sign = -1;
    if (/[NE]/.test(s) && !/[SW]/.test(s)) sign = 1;
    s = s.replace(/[NSEWO]/g, ' ').replace(/[°º'’"”]/g, ' ').trim();
    if (/^-/.test(s)) { sign = -1; s = s.slice(1); }
    const parts = s.split(/\s+/).filter(Boolean).map(Number);
    if (!parts.length || parts.some(isNaN)) return null;
    const v = sign * (parts[0] + (parts[1] || 0) / 60 + (parts[2] || 0) / 3600);
    const lim = isLat ? 90 : 180;
    if (Math.abs(v) > lim) return null;
    return v;
  }
  function fmtCoord(v, isLat) {
    if (v == null) return '—';
    const h = isLat ? (v < 0 ? 'S' : 'N') : (v < 0 ? 'W' : 'E');
    const a = Math.abs(v), d = Math.floor(a), mf = (a - d) * 60, m = Math.floor(mf), s = Math.round((mf - m) * 60);
    return `${d}°${pad(m)}'${pad(s === 60 ? 59 : s)}"${h}`;
  }

  /* ---------- Astronomia (algoritmos de baixa precisão, base SunCalc/Meeus) ---------- */
  const toDays = ms => ms / dayMs - 0.5 + J1970 - J2000;
  const raOf = (l, b) => Math.atan2(Math.sin(l) * Math.cos(E) - Math.tan(b) * Math.sin(E), Math.cos(l));
  const decOf = (l, b) => Math.asin(Math.sin(b) * Math.cos(E) + Math.cos(b) * Math.sin(E) * Math.sin(l));
  const altOf = (H, phi, dec) => Math.asin(Math.sin(phi) * Math.sin(dec) + Math.cos(phi) * Math.cos(dec) * Math.cos(H));
  const sidereal = (d, lw) => rad * (280.16 + 360.9856235 * d) - lw;
  function refraction(h) { if (h < 0) h = 0; return 0.0002967 / Math.tan(h + 0.00312536 / (h + 0.08901179)); }
  function sunCoords(d) {
    const M = rad * (357.5291 + 0.98560028 * d);
    const C = rad * (1.9148 * Math.sin(M) + 0.02 * Math.sin(2 * M) + 0.0003 * Math.sin(3 * M));
    const L = M + C + rad * 102.9372 + PI;
    return { dec: decOf(L, 0), ra: raOf(L, 0) };
  }
  function moonCoords(d) {
    const L = rad * (218.316 + 13.176396 * d), M = rad * (134.963 + 13.064993 * d), F = rad * (93.272 + 13.229350 * d);
    const l = L + rad * 6.289 * Math.sin(M), b = rad * 5.128 * Math.sin(F), dist = 385001 - 20905 * Math.cos(M);
    return { ra: raOf(l, b), dec: decOf(l, b), dist };
  }
  /** Altitude geométrica do Sol (graus). */
  function sunAlt(ms, lat, lon) {
    const lw = rad * -lon, phi = rad * lat, d = toDays(ms), c = sunCoords(d);
    return altOf(sidereal(d, lw) - c.ra, phi, c.dec) / rad;
  }
  /** Altitude aparente da Lua (graus, com refração). */
  function moonAlt(ms, lat, lon) {
    const lw = rad * -lon, phi = rad * lat, d = toDays(ms), c = moonCoords(d);
    let h = altOf(sidereal(d, lw) - c.ra, phi, c.dec);
    h = h + refraction(h);
    return h / rad;
  }
  function moonIllum(ms) {
    const d = toDays(ms), s = sunCoords(d), m = moonCoords(d), sdist = 149598000;
    const phi = Math.acos(Math.sin(s.dec) * Math.sin(m.dec) + Math.cos(s.dec) * Math.cos(m.dec) * Math.cos(s.ra - m.ra));
    const inc = Math.atan2(sdist * Math.sin(phi), m.dist - sdist * Math.cos(phi));
    const angle = Math.atan2(Math.cos(s.dec) * Math.sin(s.ra - m.ra), Math.sin(s.dec) * Math.cos(m.dec) - Math.cos(s.dec) * Math.sin(m.dec) * Math.cos(s.ra - m.ra));
    return { fraction: (1 + Math.cos(inc)) / 2, phase: 0.5 + 0.5 * inc * (angle < 0 ? -1 : 1) / PI };
  }
  /** Nome da fase a partir do ângulo de fase (0° = Nova, 90° = Quarto Crescente, 180° = Cheia, 270° = Quarto Minguante). */
  function phaseNameDeg(d) {
    d = ((d % 360) + 360) % 360;
    if (d < 6 || d >= 354) return 'Lua Nova';
    if (d < 84) return 'Lua Crescente';
    if (d < 96) return 'Quarto Crescente';
    if (d < 174) return 'Crescente Gibosa';
    if (d < 186) return 'Lua Cheia';
    if (d < 264) return 'Minguante Gibosa';
    if (d < 276) return 'Quarto Minguante';
    return 'Lua Minguante';
  }
  function phaseName(p) {
    if (p < 0.03 || p > 0.97) return 'Lua Nova';
    if (p < 0.22) return 'Crescente (côncava)';
    if (p < 0.28) return 'Quarto Crescente';
    if (p < 0.47) return 'Crescente Gibosa';
    if (p < 0.53) return 'Lua Cheia';
    if (p < 0.72) return 'Minguante Gibosa';
    if (p < 0.78) return 'Quarto Minguante';
    return 'Minguante (côncava)';
  }
  /** Cruzamentos de limiar de uma função f(ms) entre t0 e t1 (passo 60 s, refino por bisseção). */
  function crossings(f, thr, t0, t1, step = 60000) {
    const out = [];
    let pt = t0, pv = f(t0) - thr;
    for (let t = t0 + step; t <= t1; t += step) {
      const v = f(t) - thr;
      if ((pv <= 0 && v > 0) || (pv > 0 && v <= 0)) {
        let a = pt, b = t, fa = pv;
        for (let i = 0; i < 20; i++) { const m = (a + b) / 2, fm = f(m) - thr; if ((fa <= 0) === (fm <= 0)) { a = m; fa = fm; } else b = m; }
        out.push({ t: (a + b) / 2, rising: pv <= 0 });
      }
      pt = t; pv = v;
    }
    return out;
  }
  const NAUT = -12, MOON_H0 = 0.133;
  function dayBounds(dateStr, tz) {
    const [y, m, d] = dateStr.split('-').map(Number);
    return [zonedToUtc(y, m, d, 0, 0, tz), zonedToUtc(y, m, d + 1, 0, 0, tz)];
  }
  function twilight(dateStr, lat, lon, tz) {
    const [a, b] = dayBounds(dateStr, tz);
    const cs = crossings(t => sunAlt(t, lat, lon), NAUT, a, b);
    const icmn = cs.find(c => c.rising), fcvn = [...cs].reverse().find(c => !c.rising);
    const cv = crossings(t => sunAlt(t, lat, lon), -6, a, b);
    const icmc = cv.find(c => c.rising), fcvc = [...cv].reverse().find(c => !c.rising);
    return { icmn: icmn ? icmn.t : null, fcvn: fcvn ? fcvn.t : null, icmc: icmc ? icmc.t : null, fcvc: fcvc ? fcvc.t : null };
  }
  function nightAnalysis(t0, t1, lat, lon) {
    if (t0 == null || t1 == null || t1 <= t0) return null;
    const cs = crossings(t => moonAlt(t, lat, lon), MOON_H0, t0, t1);
    const intervals = [];
    let cur = t0, up = moonAlt(t0, lat, lon) > MOON_H0;
    cs.forEach(c => { intervals.push({ from: cur, to: c.t, moon: up }); cur = c.t; up = c.rising; });
    intervals.push({ from: cur, to: t1, moon: up });
    let maxAlt = -90, maxT = null;
    for (let t = t0; t <= t1; t += 300000) { const h = moonAlt(t, lat, lon); if (h > maxAlt) { maxAlt = h; maxT = t; } }
    const mid = (t0 + t1) / 2;
    return { t0, t1, intervals: intervals.filter(i => i.to - i.from > 30000), maxAlt, maxT, illum: moonIllum(mid) };
  }
  function astronomy(dateStr, lat, lon, tz) {
    const D = twilight(dateStr, lat, lon, tz), Dm = twilight(shiftDate(dateStr, -1), lat, lon, tz), Dp = twilight(shiftDate(dateStr, 1), lat, lon, tz);
    const [a, b] = dayBounds(dateStr, tz);
    const mc = crossings(t => moonAlt(t, lat, lon), MOON_H0, a, b);
    const rise = mc.find(c => c.rising), set = mc.find(c => !c.rising);
    const noonIllum = moonIllum((a + b) / 2);
    return {
      icmn: D.icmn, fcvn: D.fcvn, icmc: D.icmc, fcvc: D.fcvc,
      moonrise: rise ? rise.t : null, moonset: set ? set.t : null,
      illum: noonIllum,
      nightBefore: Object.assign(nightAnalysis(Dm.fcvc, D.icmc, lat, lon) || {}, { fcvn: Dm.fcvn, icmn: D.icmn }),
      nightAfter: Object.assign(nightAnalysis(D.fcvc, Dp.icmc, lat, lon) || {}, { fcvn: D.fcvn, icmn: Dp.icmn }),
    };
  }

  /* ---------- Utilidades meteorológicas ---------- */
  const CARD = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];
  const cardinal = deg => deg == null ? '—' : CARD[Math.round(((deg % 360) + 360) % 360 / 22.5) % 16];
  const angDiff = (a, b) => { const d = Math.abs(((a - b) % 360 + 540) % 360 - 180); return d; };
  function weightedMedian(vals) { // vals: [{v,w}]
    const a = vals.filter(x => x.v != null && !isNaN(x.v) && x.w > 0).sort((p, q) => p.v - q.v);
    if (!a.length) return null;
    const tot = a.reduce((s, x) => s + x.w, 0);
    let acc = 0;
    for (let i = 0; i < a.length; i++) {
      acc += a[i].w;
      if (acc > tot / 2 + 1e-9) return a[i].v;
      if (Math.abs(acc - tot / 2) < 1e-9) return (a[i].v + a[i + 1].v) / 2;
    }
    return a[a.length - 1].v;
  }
  function circularMedoid(vals) { // direção que minimiza a soma ponderada das diferenças angulares
    const a = vals.filter(x => x.v != null && !isNaN(x.v) && x.w > 0);
    if (!a.length) return null;
    let best = null, bs = Infinity;
    a.forEach(c => { const s = a.reduce((t, x) => t + x.w * angDiff(c.v, x.v), 0); if (s < bs) { bs = s; best = c.v; } });
    return best;
  }
  function spread(vals, circular) {
    const a = vals.filter(v => v != null && !isNaN(v));
    if (a.length < 2) return null;
    if (circular) { let m = 0; for (let i = 0; i < a.length; i++) for (let j = i + 1; j < a.length; j++) m = Math.max(m, angDiff(a[i], a[j])); return m; }
    return Math.max(...a) - Math.min(...a);
  }
  function coverCode(pct) {
    if (pct == null) return null;
    if (pct < 6) return 'NSC';
    if (pct <= 25) return 'FEW';
    if (pct <= 50) return 'SCT';
    if (pct <= 87) return 'BKN';
    return 'OVC';
  }
  /** Base estimada de nuvem convectiva/baixa pelo NCL (≈ 125 m por °C de depressão do ponto de orvalho). */
  const lclFt = (t, td) => (t == null || td == null) ? null : Math.max(0, Math.round((t - td) * 125 * 3.28084 / 100) * 100);

  /* ---------- Open-Meteo ---------- */
  /** Janela H a H+5 (itens 1 a 3): quatro centros independentes, na maior resolução disponível para o Brasil.
      ECMWF: superfície do IFS HRES 9 km (ecmwf_ifs) + níveis de pressão do IFS 0,25° (o 9 km não publica níveis). */
  const MODELS = [
    { key: 'gfs_seamless', id: 'GFS', label: 'GFS (NOAA/NCEP)', meta: 'ncep_gfs013' },
    { key: 'ecmwf_ifs025', hires: 'ecmwf_ifs', id: 'ECMWF', label: 'ECMWF IFS HRES 9 km + níveis 0,25°', meta: 'ecmwf_ifs' },
    { key: 'icon_seamless', id: 'ICON', label: 'ICON global (DWD)', meta: 'dwd_icon' },
    { key: 'ukmo_global_deterministic_10km', id: 'UKMO', label: 'UK Met Office global 10 km', meta: 'ukmo_global_deterministic_10km' },
  ];
  /** Tendência D a D+7 (item 4): modelos de alcance de 7 dias ou mais, só variáveis de superfície. */
  const MODELS7 = [MODELS[0], { key: 'ecmwf_ifs025', id: 'ECMWF', label: 'ECMWF IFS 0,25°' }, MODELS[2]];
  const SURF7 = ['temperature_2m', 'precipitation', 'showers', 'precipitation_probability', 'pressure_msl', 'wind_speed_10m', 'wind_direction_10m', 'wind_gusts_10m', 'cape', 'weather_code', 'cloud_cover'];
  const metaUrl = id => { const x = MODELS.find(mm => mm.id === id); return x && x.meta ? `https://api.open-meteo.com/data/${x.meta}/static/meta.json` : null; };
  const SURF = ['temperature_2m', 'apparent_temperature', 'dew_point_2m', 'precipitation_probability', 'precipitation', 'showers', 'cloud_cover', 'cloud_cover_low', 'cloud_cover_mid', 'cloud_cover_high', 'wind_speed_10m', 'wind_direction_10m', 'wind_gusts_10m', 'cape', 'pressure_msl', 'visibility', 'wind_speed_80m', 'wind_direction_80m', 'wind_speed_120m', 'wind_direction_120m', 'wind_speed_180m', 'wind_direction_180m', 'freezing_level_height', 'lifted_index', 'weather_code'];
  const LEVELS = [1000, 975, 950, 925, 900, 850, 800, 700, 600, 500, 400, 300];
  const LVARS = ['wind_speed', 'wind_direction', 'geopotential_height', 'temperature', 'relative_humidity', 'cloud_cover'];
  /** Último dia necessário para a janela: o próprio dia D, ou D+1 só quando H+5 passa da meia-noite. */
  const janelaFim = m => (+m.hour || 0) + 5 >= 24 ? shiftDate(m.date, 1) : m.date;
  /** kind 'janela' = somente o dia D (D+1 apenas se H+5 cruzar a meia-noite), quatro modelos, superfície + níveis; 'tendencia' = D-1 a D+7, três modelos, superfície. */
  function openMeteoUrl(m, kind = 'janela') {
    const jan = kind !== 'tendencia', hourly = jan ? [...SURF] : [...SURF7];
    if (jan) LEVELS.forEach(p => LVARS.forEach(v => hourly.push(`${v}_${p}hPa`)));
    const keys = jan ? MODELS.flatMap(x => x.hires ? [x.key, x.hires] : [x.key]) : MODELS7.map(x => x.key);
    const q = new URLSearchParams({
      latitude: m.lat.toFixed(4), longitude: m.lon.toFixed(4), hourly: hourly.join(','),
      models: keys.join(','), wind_speed_unit: 'kn', timezone: m.tz,
      start_date: m.date, end_date: jan ? janelaFim(m) : shiftDate(m.date, 7),
    });
    return 'https://api.open-meteo.com/v1/forecast?' + q.toString().replace(/%2C/g, ',');
  }
  function parseOpenMeteo(text) {
    let j;
    try { j = JSON.parse(text); } catch (e) { throw new Error('O texto colado não é um JSON válido. Copie a resposta inteira da página da Open-Meteo.'); }
    if (j.error) throw new Error('A Open-Meteo retornou erro: ' + (j.reason || 'motivo não informado'));
    if (!j.hourly || !Array.isArray(j.hourly.time)) throw new Error('JSON sem o bloco "hourly". Use o link gerado pelo dashboard.');
    const h = j.hourly, keys = Object.keys(h);
    const models = {};
    MODELS.forEach(M => {
      const has = keys.some(k => k.endsWith('_' + M.key));
      if (!has) return;
      const o = {};
      keys.forEach(k => { if (k.endsWith('_' + M.key)) o[k.slice(0, -(M.key.length + 1))] = h[k]; });
      // alta resolução (mesmo modelo): substitui as variáveis que ela publica
      if (M.hires) keys.forEach(k => { if (k.endsWith('_' + M.hires)) { const arr = h[k], v = k.slice(0, -(M.hires.length + 1)); if (Array.isArray(arr) && arr.some(x => x != null)) o[v] = arr; } });
      models[M.id] = o;
    });
    if (!Object.keys(models).length) { // resposta de modelo único (sem sufixo)
      const o = {}; keys.forEach(k => { if (k !== 'time') o[k] = h[k]; });
      models['MODELO'] = o;
    }
    const units = j.hourly_units || {};
    if (units.wind_speed_10m && !/kn/.test(units.wind_speed_10m)) throw new Error('Unidade de vento diferente de nós (' + units.wind_speed_10m + '). Use o link gerado, que pede wind_speed_unit=kn.');
    return { time: h.time, models, kind: h.time.length > 100 ? 'tendencia' : 'janela', meta: { lat: j.latitude, lon: j.longitude, elevation: j.elevation, tz: j.timezone, generationtime_ms: j.generationtime_ms } };
  }

  /* ---------- Sondagem NOAA (formato GSD, rucsoundings.noaa.gov) ---------- */
  function soundingUrl(m, model) {
    const q = new URLSearchParams({ data_source: model || 'GFS', latest: 'latest', start_year: m.date.slice(0, 4), start_month_name: '', start_mday: '', start_hour: '', start_min: '0', n_hrs: '1', fcst_len: 'shortest', airport: `${m.lat.toFixed(3)},${m.lon.toFixed(3)}`, text: 'Ascii text (GSD format)', hydrometeors: 'false', start: 'latest' });
    return 'https://rucsoundings.noaa.gov/get_soundings.cgi?' + q.toString();
  }
  function parseGSD(text) {
    const lines = String(text).split(/\r?\n/);
    const levels = []; let header = [], units = 'kt', station = '';
    lines.forEach(line => {
      const t = line.trim(); if (!t) return;
      const f = t.split(/\s+/);
      if (f[0] === '3' && f.length >= 3) { if (/kt|ms/i.test(f[f.length - 1])) units = f[f.length - 1].toLowerCase(); if (isNaN(+f[1])) station = f[1]; return; }
      if (/^[4-9]$/.test(f[0]) && f.length >= 7 && f.slice(1, 7).every(x => /^-?\d+$/.test(x))) {
        const n = x => (+x === 99999 ? null : +x);
        const p = n(f[1]), hgt = n(f[2]), tc = n(f[3]), td = n(f[4]), dir = n(f[5]), spd = n(f[6]);
        if (p == null || hgt == null) return;
        levels.push({ type: +f[0], p: p / 10, hgtM: hgt, tC: tc == null ? null : tc / 10, tdC: td == null ? null : td / 10, dir, kt: spd == null ? null : (units === 'ms' ? spd * 1.94384 : spd) });
        return;
      }
      if (header.length < 3 && !/^[0-9]/.test(f[0])) header.push(t);
    });
    if (!levels.length) throw new Error('Nenhum nível reconhecido. Selecione "Ascii text (GSD format)" na página da NOAA e copie o texto completo.');
    levels.sort((a, b) => a.hgtM - b.hgtM);
    // remove níveis duplicados de mesma altura
    const uniq = levels.filter((l, i) => i === 0 || l.hgtM !== levels[i - 1].hgtM || l.p !== levels[i - 1].p);
    return { header, station, units, levels: uniq };
  }

  /* ---------- METAR / TAF ---------- */
  function parseMetar(raw) {
    const s = raw.replace(/\s+/g, ' ').trim();
    const r = { raw: s, station: null, time: null, wind: null, vis: null, wx: [], clouds: [], t: null, td: null, q: null, cavok: false, cb: false, tcu: false, ts: false };
    const tk = s.split(' ');
    tk.forEach(x => {
      let m;
      if (!r.station && /^[A-Z]{4}$/.test(x) && x !== 'METAR' && x !== 'SPECI') r.station = x;
      else if ((m = x.match(/^(\d{2})(\d{2})(\d{2})Z$/))) r.time = { d: +m[1], h: +m[2], mi: +m[3] };
      else if ((m = x.match(/^(\d{3}|VRB)(\d{2,3})(?:G(\d{2,3}))?(KT|MPS)$/))) { const k = m[4] === 'MPS' ? 1.94384 : 1; r.wind = { dir: m[1] === 'VRB' ? null : +m[1], vrb: m[1] === 'VRB', kt: Math.round(+m[2] * k), gust: m[3] ? Math.round(+m[3] * k) : null }; }
      else if (x === 'CAVOK') { r.cavok = true; r.vis = 9999; }
      else if (/^\d{4}$/.test(x) && r.wind && r.vis == null) r.vis = +x;
      else if ((m = x.match(/^(FEW|SCT|BKN|OVC|VV)(\d{3}|\/\/\/)(CB|TCU)?$/))) { const base = /\d/.test(m[2]) ? +m[2] * 100 : null; r.clouds.push({ cov: m[1], base, type: m[3] || '' }); if (m[3] === 'CB') r.cb = true; if (m[3] === 'TCU') r.tcu = true; }
      else if ((m = x.match(/^(M?\d{2})\/(M?\d{2})$/))) { const c = v => v[0] === 'M' ? -+v.slice(1) : +v; r.t = c(m[1]); r.td = c(m[2]); }
      else if ((m = x.match(/^Q(\d{4})$/))) r.q = +m[1];
      else if (/^(\+|-|VC)?(TS|SH|FZ|MI|BC|DR|BL|PR)?(RA|DZ|SN|GR|GS|BR|FG|HZ|FU|SQ|UP|PL)+$|^(\+|-|VC)?TS$/.test(x)) { r.wx.push(x); if (/TS/.test(x)) r.ts = true; }
    });
    return r;
  }
  function splitMessages(text, kind) {
    const t = String(text).replace(/=/g, ' =').replace(/\r/g, '');
    const re = kind === 'TAF' ? /TAF\b[\s\S]*?(?==|(?=\b(?:TAF|METAR|SPECI)\b)|$)/g : /(METAR|SPECI)\b[\s\S]*?(?==|(?=\b(?:METAR|SPECI|TAF)\b)|$)/g;
    const out = (t.match(re) || []).map(x => x.replace(/\s+/g, ' ').trim()).filter(x => x.length > 10);
    return out;
  }
  /** Grupos do TAF com período de validade (UTC) e marcadores de convecção. ref = {y, mo} do mês de emissão. */
  function parseTaf(raw, ref) {
    const s = raw.replace(/\s+/g, ' ').trim();
    const station = (s.match(/\bTAF\s+(?:AMD\s+|COR\s+)?([A-Z]{4})\b/) || [])[1] || null;
    const mk = (d, h) => { let mo = ref.mo, y = ref.y; return Date.UTC(y, mo - 1, d, h); };
    const fixWrap = (a, b) => (b <= a ? b + 30 * dayMs : b); // simplificação na virada do mês
    const tokens = s.split(' ');
    const groups = []; let cur = null;
    const isStart = (x, i) => /^(BECMG|TEMPO|PROB\d{2}|FM\d{6})$/.test(x) && !(x === 'TEMPO' && /^PROB\d{2}$/.test(tokens[i - 1] || ''));
    tokens.forEach((x, i) => {
      if (isStart(x, i) || cur == null) { cur = { kind: cur == null ? 'BASE' : x.replace(/\d+/, ''), prob: (x.match(/^PROB(\d{2})/) || [])[1] || null, tokens: [] }; groups.push(cur); if (/^FM\d{6}$/.test(x)) { cur.kind = 'FM'; const d = +x.slice(2, 4), h = +x.slice(4, 6), mi = +x.slice(6, 8); cur.from = mk(d, h) + mi * 6e4; } if (cur.kind !== 'BASE') return; }
      cur.tokens.push(x);
      const m = x.match(/^(\d{2})(\d{2})\/(\d{2})(\d{2})$/);
      if (m && cur.from == null) { cur.from = mk(+m[1], +m[2]); cur.to = fixWrap(cur.from, mk(+m[3], +m[4])); }
    });
    // períodos FM terminam no próximo FM ou no fim do TAF
    const base = groups[0];
    groups.forEach((g, i) => {
      if (g.kind === 'FM') { const nx = groups.slice(i + 1).find(x => x.kind === 'FM'); g.to = nx ? nx.from : base.to; }
      if (g.kind === 'BECMG' && g.from != null) g.to = base.to; // a mudança persiste até o fim da validade (simplificação conservadora)
    });
    groups.forEach(g => { const txt = g.tokens.join(' '); g.cb = /\d{3}CB\b/.test(txt); g.tcu = /\d{3}TCU\b/.test(txt); g.ts = /(^|\s)(\+|-|VC)?TS/.test(txt); g.text = txt; });
    return { raw: s, station, groups, validFrom: base.from, validTo: base.to };
  }
  function tafAt(taf, utcMs) {
    if (!taf || taf.validFrom == null) return null;
    if (utcMs < taf.validFrom || utcMs >= taf.validTo) return { valid: false };
    const act = taf.groups.filter(g => g.from != null && utcMs >= g.from && utcMs < g.to);
    return { valid: true, cb: act.some(g => g.cb), tcu: act.some(g => g.tcu), ts: act.some(g => g.ts), groups: act.map(g => (g.kind === 'BASE' ? '' : g.kind === 'PROB' ? 'PROB' + g.prob + ' ' : g.kind + ' ') + g.text) };
  }



  /* ---------- Tempo presente (código WMO dos modelos → abreviatura METAR) ---------- */
  const WMO = { 45: 'FG', 48: 'FG', 51: '-DZ', 53: 'DZ', 55: '+DZ', 56: '-FZDZ', 57: 'FZDZ', 61: '-RA', 63: 'RA', 65: '+RA', 66: '-FZRA', 67: 'FZRA', 71: '-SN', 73: 'SN', 75: '+SN', 77: 'SG', 80: '-SHRA', 81: 'SHRA', 82: '+SHRA', 85: '-SHSN', 86: 'SHSN', 95: 'TSRA', 96: 'TSGR', 99: '+TSGR' };
  const wmoWx = c => c == null ? null : (WMO[Math.round(c)] || null);
  const WXDESC = { SH: 'pancadas', TSSH: 'trovoada com pancadas', GR: 'granizo', SQ: 'tempestade de vento', NSW: 'sem tempo significativo', BCFG: 'bancos de nevoeiro', MIFG: 'nevoeiro baixo', FG: 'nevoeiro', BR: 'névoa úmida', HZ: 'névoa seca', DZ: 'chuvisco', RA: 'chuva', SHRA: 'pancadas de chuva', TSRA: 'trovoada com chuva', TS: 'trovoada', TSGR: 'trovoada com granizo', SN: 'neve', FZRA: 'chuva congelante', FZDZ: 'chuvisco congelante', SHSN: 'pancadas de neve', SG: 'grãos de neve' };
  /** Decodificação do tempo presente conforme a Tabela 4678 (qualificador de intensidade/proximidade + descritor + precipitação/obscurecedor/outros). */
  const WX_DESCR = { MI: 'baixo', BC: 'em bancos', PR: 'parcial', DR: 'flutuante', BL: 'soprada', SH: 'pancada', TS: 'trovoada', FZ: 'congelante' };
  const WX_FEN = { DZ: 'chuvisco', RA: 'chuva', SN: 'neve', SG: 'grãos de neve', IC: 'cristais de gelo', PE: 'pelotas de gelo', PL: 'pelotas de gelo', GR: 'granizo', GS: 'granizo pequeno e/ou grãos de neve',
    BR: 'névoa úmida', FG: 'nevoeiro', FU: 'fumaça', VA: 'cinzas vulcânicas', DU: 'poeira extensa', SA: 'areia', HZ: 'névoa seca',
    PO: 'poeira/areia em redemoinhos', SQ: 'tempestade', FC: 'nuvem funil (tornado ou tromba d\'água)', SS: 'tempestade de areia', DS: 'tempestade de poeira', UP: 'precipitação desconhecida' };
  const wxDesc = w => {
    if (!w) return '';
    if (w === 'NSW') return 'sem tempo significativo';
    let s = w, q = '';
    if (s.startsWith('VC')) { q = 'nas vizinhanças'; s = s.slice(2); } else if (s[0] === '-') { q = 'leve'; s = s.slice(1); } else if (s[0] === '+') { q = 'forte'; s = s.slice(1); }
    const d = (s.match(/^(MI|BC|PR|DR|BL|SH|TS|FZ)/) || [])[1]; if (d) s = s.slice(2);
    const f = (s.match(/.{2}/g) || []).map(x => WX_FEN[x] || x);
    const fen = f.join(' e ');
    let txt;
    if (d === 'TS') txt = fen ? `trovoada com ${fen}` : 'trovoada';
    else if (d === 'SH') txt = fen ? `pancada de ${fen}` : 'pancadas';
    else if (d) txt = `${fen} ${WX_DESCR[d]}`;
    else txt = fen;
    if (w.startsWith('+') && /FC/.test(w)) return 'tornado ou tromba d\'água';
    return q ? `${txt} ${q}` : txt;
  };
  const COVDESC = { FEW: 'poucas nuvens', SCT: 'nuvens esparsas', BKN: 'nuvens fragmentadas', OVC: 'céu encoberto' };
  /** Camadas no formato METAR a partir de [{zAgl (m), cover (%)}] ordenado; até 3 camadas; base em centenas de pés. */
  function layersFrom(levels, nclFt) {
    const out = []; let cur = null, prevClear = 0;
    levels.forEach(l => {
      if (l.cover != null && l.cover >= 6) {
        if (!cur) { let baseFt = l.zAgl / 0.3048; if (nclFt != null && nclFt > prevClear / 0.3048 && nclFt < baseFt) baseFt = nclFt; cur = { baseFt, max: l.cover }; }
        else cur.max = Math.max(cur.max, l.cover);
      } else { if (cur) { out.push(cur); cur = null; } prevClear = l.zAgl; }
    });
    if (cur) out.push(cur);
    return out.slice(0, 3).map(x => ({ cov: coverCode(x.max), baseFt: Math.max(100, Math.round(x.baseFt / 100) * 100), pct: x.max }))
      .filter(x => x.cov && x.cov !== 'NSC')
      .map(x => Object.assign(x, { code: x.cov + String(Math.min(999, Math.round(x.baseFt / 100))).padStart(3, '0') }));
  }

  /* ---------- Vento por altura (interpolação linear em u/v na vertical, altitude MSL) ---------- */
  const toUV = (kt, dir) => (kt == null || dir == null) ? null : { u: -kt * Math.sin(dir * Math.PI / 180), v: -kt * Math.cos(dir * Math.PI / 180) };
  const fromUV = (u, v) => ({ kt: Math.hypot(u, v), dir: (Math.atan2(-u, -v) * 180 / Math.PI + 360) % 360 });
  /** pts: [{z (m MSL), kt, dir, tag}] ; devolve vento interpolado em zt (m MSL) e os dois níveis usados. */
  function windAt(pts, zt) {
    const a = pts.filter(p => p.z != null && p.kt != null && p.dir != null).sort((x, y) => x.z - y.z);
    if (!a.length) return null;
    if (zt <= a[0].z) return Object.assign({ below: true, from: a[0], to: a[0] }, { kt: a[0].kt, dir: a[0].dir });
    for (let i = 1; i < a.length; i++) {
      if (zt <= a[i].z) {
        const f = (zt - a[i - 1].z) / (a[i].z - a[i - 1].z), p = toUV(a[i - 1].kt, a[i - 1].dir), q = toUV(a[i].kt, a[i].dir);
        return Object.assign({ from: a[i - 1], to: a[i] }, fromUV(p.u + f * (q.u - p.u), p.v + f * (q.v - p.v)));
      }
    }
    return null;
  }
  /** Componentes do vento (vento de onde sopra, graus verdadeiros) para uma pista de rumo verdadeiro rwy. */
  function components(kt, dir, rwy) {
    if (kt == null || dir == null || rwy == null) return null;
    const a = (dir - rwy) * Math.PI / 180;
    return { head: kt * Math.cos(a), cross: kt * Math.sin(a) };
  }
  /** Vento previsto pelo TAF num instante: grupo base/BECMG/FM mais recente; TEMPO/PROB como variação. */
  function tafWind(taf, utcMs) {
    if (!taf || taf.validFrom == null || utcMs < taf.validFrom || utcMs >= taf.validTo) return null;
    const wind = txt => { const m = txt.match(/(?:^|\s)(\d{3}|VRB)(\d{2,3})(?:G(\d{2,3}))?KT\b/); return m ? { dir: m[1] === 'VRB' ? null : +m[1], vrb: m[1] === 'VRB', kt: +m[2], gust: m[3] ? +m[3] : null } : null; };
    let prev = wind(taf.groups[0].tokens.join(' ')), vari = [];
    taf.groups.slice(1).forEach(g => {
      if (g.from == null) return;
      const w = wind(g.tokens.join(' '));
      if (!w) return;
      if ((g.kind === 'BECMG' && utcMs >= g.from) || (g.kind === 'FM' && utcMs >= g.from && utcMs < g.to)) prev = w;
      else if ((g.kind === 'TEMPO' || g.kind === 'PROB') && utcMs >= g.from && utcMs < g.to) vari.push(Object.assign({ tipo: g.kind === 'PROB' ? 'PROB' + g.prob : 'TEMPO' }, w));
    });
    return { prev, vari };
  }
  /** Teto adotado para o salto (ft) = base da camada mais baixa, de FEW a OVC (ou VV), de um METAR já interpretado. */
  const ceilingFt = m => { const c = (m && m.clouds || []).filter(x => /FEW|SCT|BKN|OVC|VV/.test(x.cov) && x.base != null).map(x => x.base); return c.length ? Math.min(...c) : null; };


  /* ---------- Atmosfera padrão e altitude-densidade ---------- */
  /** Altitude-pressão (ft) a partir da elevação (ft) e do QNH (hPa): 1 hPa ≈ 27 ft próximo ao nível do mar (fórmula barométrica ISA). */
  function pressureAlt(elevFt, qnh) {
    if (elevFt == null || qnh == null) return null;
    // pressão na estação pela ISA a partir do QNH, depois altitude-pressão exata pela ISA
    const h = elevFt * 0.3048, p = qnh * Math.pow(1 - 2.25577e-5 * h, 5.25588);
    return (1 - Math.pow(p / 1013.25, 0.190263)) * 145366.45;
  }
  /** Altitude-densidade (ft): DA ≈ PA + 118,8 × (OAT − T_ISA), T_ISA = 15 − 1,98 °C/1000 ft. */
  function densityAlt(pa, oat) { if (pa == null || oat == null) return null; const isa = 15 - 1.98 * pa / 1000; return pa + 118.8 * (oat - isa); }
  /** Interpolação linear de um escalar em altitude MSL. pts: [{z, v}] */
  function scalarAt(pts, zt) {
    const a = pts.filter(p => p.z != null && p.v != null).sort((x, y) => x.z - y.z);
    if (!a.length) return null;
    if (zt <= a[0].z) return a[0].v;
    for (let i = 1; i < a.length; i++) if (zt <= a[i].z) { const f = (zt - a[i - 1].z) / (a[i].z - a[i - 1].z); return a[i - 1].v + f * (a[i].v - a[i - 1].v); }
    return null;
  }
  /** Condições previstas no TAF num instante: visibilidade (m) e teto (ft) do grupo predominante; TEMPO/PROB como variação. */
  function tafCond(taf, utcMs) {
    if (!taf || taf.validFrom == null || utcMs < taf.validFrom || utcMs >= taf.validTo) return null;
    const parse = txt => {
      const tk = txt.split(' '), o = {};
      tk.forEach(x => {
        let m;
        if (x === 'CAVOK') { o.vis = 9999; o.ceil = null; o.cavok = true; o.cl = true; }
        else if (/^\d{4}$/.test(x) && !/\//.test(x) && o.vis == null) o.vis = +x;
        else if ((m = x.match(/^(FEW|SCT|BKN|OVC|VV)(\d{3})/))) { o.cl = true; o.ceil = o.ceil == null ? +m[2] * 100 : Math.min(o.ceil, +m[2] * 100); (o.clouds = o.clouds || []).push(x); }
        else if (/^NSC$|^SKC$|^NCD$/.test(x)) { o.cl = true; (o.clouds = o.clouds || []).push(x); }
        else if (/^(\+|-|VC)?(TS|SH|FZ|MI|BC|DR|BL)?(RA|DZ|SN|GR|GS|BR|FG|HZ|FU|SQ|PL)+$|^(\+|-|VC)?TS$|^NSW$/.test(x)) (o.wx = o.wx || []).push(x);
      });
      return o;
    };
    const tokensNoTime = g => g.tokens.filter(x => !/^\d{4}\/\d{4}$/.test(x) && !/^\d{6}Z$/.test(x) && !/^T[XN]/.test(x)).join(' ');
    const base = parse(tokensNoTime(taf.groups[0]).replace(/^TAF (AMD |COR )?[A-Z]{4} /, ''));
    let prev = { vis: base.vis ?? null, ceil: base.cl ? base.ceil ?? null : null, clouds: base.clouds || (base.cavok ? ['CAVOK'] : []), wx: base.wx || [] };
    const vari = [];
    taf.groups.slice(1).forEach(g => {
      if (g.from == null) return;
      const p = parse(tokensNoTime(g));
      if ((g.kind === 'BECMG' && utcMs >= g.from) || (g.kind === 'FM' && utcMs >= g.from && utcMs < g.to)) { if (p.vis != null) prev.vis = p.vis; if (p.cl) { prev.ceil = p.ceil ?? null; prev.clouds = p.clouds || []; } if (p.wx) prev.wx = p.wx.filter(w => w !== 'NSW'); }
      else if ((g.kind === 'TEMPO' || g.kind === 'PROB') && utcMs >= g.from && utcMs < g.to && (p.vis != null || p.cl || p.wx)) vari.push({ tipo: g.kind === 'PROB' ? 'PROB' + g.prob : 'TEMPO', vis: p.vis ?? null, ceil: p.cl ? p.ceil ?? null : undefined, clouds: p.clouds || [], wx: p.wx || [] });
    });
    return { prev, vari };
  }

  return { wmoWx, wxDesc, COVDESC, layersFrom, phaseNameDeg, pressureAlt, densityAlt, scalarAt, tafCond, windAt, components, tafWind, ceilingFt, toUV, fromUV, tzOffsetMin, zonedToUtc, localParts, hhmm, ddmm, localKey, isoDate, shiftDate, pad, parseCoord, fmtCoord, astronomy, sunAlt, moonAlt, moonIllum, phaseName, cardinal, angDiff, weightedMedian, circularMedoid, spread, coverCode, lclFt, MODELS, MODELS7, SURF, SURF7, LEVELS, LVARS, metaUrl, janelaFim, openMeteoUrl, parseOpenMeteo, soundingUrl, parseGSD, parseMetar, splitMessages, parseTaf, tafAt };
})();
if (typeof module !== 'undefined') module.exports = MET;
