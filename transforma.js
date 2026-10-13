// Converte a saída bruta da coleta para os documentos lidos pelo dashboard.
// Uso: node transforma.js saida/<RUN_ID>
// Gera: modelos.json (documento dados/modelos) e sondagem.json (documento dados/sondagem).
const fs = require('fs');
const path = require('path');
const MET = require('./core.js');

const dir = process.argv[2];
if (!dir || !fs.existsSync(dir)) { console.error('Pasta de saída inexistente:', dir); process.exit(1); }
const meta = JSON.parse(fs.readFileSync(path.join(dir, 'meta.json'), 'utf8'));
meta.transformacao = {};

const om = path.join(dir, 'openmeteo.json');
if (fs.existsSync(om)) {
  try {
    const p = MET.parseOpenMeteo(fs.readFileSync(om, 'utf8'));
    const doc = Object.assign(p, { fetchedAt: meta.coletado_em_utc, url: meta.fontes.openmeteo.url, source: 'Open-Meteo via coleta automática (GitHub Actions)', runId: meta.run_id });
    const s = JSON.stringify(doc);
    if (s.length > 250000) throw new Error('documento de modelos com ' + Math.round(s.length / 1024) + ' KB (limite 250 KB)');
    fs.writeFileSync(path.join(dir, 'modelos.json'), s);
    meta.transformacao.modelos = { ok: true, modelos: Object.keys(p.models), horas: p.time.length, kb: Math.round(s.length / 1024) };
  } catch (e) { meta.transformacao.modelos = { ok: false, erro: e.message }; }
}

const sd = path.join(dir, 'sondagem.txt');
if (fs.existsSync(sd)) {
  try {
    const p = MET.parseGSD(fs.readFileSync(sd, 'utf8'));
    const tent = (meta.fontes.sondagem_noaa || []).find(t => t.niveis) || {};
    const doc = Object.assign(p, { fetchedAt: meta.coletado_em_utc, source: (tent.fonte || 'NOAA') + ' via coleta automática', url: tent.url, validoPara: tent.valido_para_utc, ciclo: tent.ciclo_utc || null, prazo: tent.prazo_h ?? null, runId: meta.run_id });
    fs.writeFileSync(path.join(dir, 'sondagem.json'), JSON.stringify(doc));
    meta.transformacao.sondagem = { ok: true, niveis: p.levels.length, validoPara: tent.valido_para_utc };
  } catch (e) { meta.transformacao.sondagem = { ok: false, erro: e.message }; }
}

fs.writeFileSync(path.join(dir, 'meta.json'), JSON.stringify(meta, null, 2));
console.log(JSON.stringify(meta.transformacao, null, 2));
