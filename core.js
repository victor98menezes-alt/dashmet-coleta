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
    return { icmn: icmn ? icmn.t : null, fcvn: fcvn ? fcvn.t : null };
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
      icmn: D.icmn, fcvn: D.fcvn,
      moonrise: rise ? rise.t : null, moonset: set ? set.t : null,
      illum: noonIllum,
      nightBefore: nightAnalysis(Dm.fcvn, D.icmn, lat, lon),
      nightAfter: nightAnalysis(D.fcvn, Dp.icmn, lat, lon),
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
  const MODELS = [
    { key: 'gfs_seamless', id: 'GFS', label: 'GFS (NOAA/NCEP)' },
    { key: 'ecmwf_ifs025', id: 'ECMWF', label: 'ECMWF IFS 0,25°' },
    { key: 'icon_seamless', id: 'ICON', label: 'ICON (DWD)' },
  ];
  const SURF = ['temperature_2m', 'dew_point_2m', 'precipitation_probability', 'precipitation', 'showers', 'cloud_cover', 'cloud_cover_low', 'cloud_cover_mid', 'cloud_cover_high', 'wind_speed_10m', 'wind_direction_10m', 'wind_gusts_10m', 'cape', 'pressure_msl'];
  const LEVELS = [1000, 925, 850, 700, 600, 500, 400, 300];
  const LVARS = ['wind_speed', 'wind_direction', 'geopotential_height', 'temperature'];
  function openMeteoUrl(m) {
    const hourly = [...SURF];
    LEVELS.forEach(p => LVARS.forEach(v => hourly.push(`${v}_${p}hPa`)));
    const q = new URLSearchParams({
      latitude: m.lat.toFixed(4), longitude: m.lon.toFixed(4), hourly: hourly.join(','),
      models: MODELS.map(x => x.key).join(','), wind_speed_unit: 'kn', timezone: m.tz,
      start_date: shiftDate(m.date, -1), end_date: shiftDate(m.date, 1),
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
      models[M.id] = o;
    });
    if (!Object.keys(models).length) { // resposta de modelo único (sem sufixo)
      const o = {}; keys.forEach(k => { if (k !== 'time') o[k] = h[k]; });
      models['MODELO'] = o;
    }
    const units = j.hourly_units || {};
    if (units.wind_speed_10m && !/kn/.test(units.wind_speed_10m)) throw new Error('Unidade de vento diferente de nós (' + units.wind_speed_10m + '). Use o link gerado, que pede wind_speed_unit=kn.');
    return { time: h.time, models, meta: { lat: j.latitude, lon: j.longitude, elevation: j.elevation, tz: j.timezone, generationtime_ms: j.generationtime_ms } };
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
    const re = kind === 'TAF' ? /TAF\b[\s\S]*?(?==|(?=\bTAF\b)|$)/g : /(METAR|SPECI)\b[\s\S]*?(?==|(?=\b(?:METAR|SPECI)\b)|$)/g;
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

  return { tzOffsetMin, zonedToUtc, localParts, hhmm, ddmm, localKey, isoDate, shiftDate, pad, parseCoord, fmtCoord, astronomy, sunAlt, moonAlt, moonIllum, phaseName, cardinal, angDiff, weightedMedian, circularMedoid, spread, coverCode, lclFt, MODELS, SURF, LEVELS, LVARS, openMeteoUrl, parseOpenMeteo, soundingUrl, parseGSD, parseMetar, splitMessages, parseTaf, tafAt };
})();
if (typeof module !== 'undefined') module.exports = MET;
