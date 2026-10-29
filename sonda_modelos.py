"""Sonda: disponibilidade de variáveis por modelo na Open-Meteo (janela curta) e metadados de rodada."""
import json, os, urllib.request, urllib.error
UA = "DashboardMeteorologicoSalto/1.0 (uso institucional nao comercial)"
import coleta as C
SURF = C.SUPERFICIE
LV = [f"{v}_{p}hPa" for p in C.NIVEIS for v in C.VARS_NIVEL]
CAND = ["gfs_seamless", "gfs_global", "ecmwf_ifs", "ecmwf_ifs025", "icon_global", "icon_seamless", "ukmo_global_deterministic_10km", "ukmo_seamless", "meteofrance_arpege_world", "gfs_graphcast025", "ecmwf_aifs025_single", "jma_gsm", "cma_grapes_global", "gem_global"]
os.makedirs("saida/_sonda/modelos", exist_ok=True)
res = {}
for mdl in CAND:
    q = f"https://api.open-meteo.com/v1/forecast?latitude=-22.875&longitude=-43.384&hourly={','.join(SURF + LV)}&models={mdl}&wind_speed_unit=kn&timezone=America/Sao_Paulo&forecast_days=2"
    try:
        with urllib.request.urlopen(urllib.request.Request(q, headers={"User-Agent": UA}), timeout=90) as r:
            j = json.loads(r.read())
        h = j.get("hourly", {}); n = len(h.get("time", []))
        ok = {k: sum(v is not None for v in vals) for k, vals in h.items() if k != "time"}
        res[mdl] = {"n": n, "elev": j.get("elevation"), "vars_ok": sorted(k for k, c in ok.items() if c > n * 0.8), "vars_vazias": sorted(k for k, c in ok.items() if c == 0), "parcial": sorted(k for k, c in ok.items() if 0 < c <= n * 0.8)}
    except urllib.error.HTTPError as e:
        res[mdl] = {"status": e.code, "corpo": e.read()[:300].decode("utf-8", "replace")}
    except Exception as e:
        res[mdl] = {"erro": repr(e)}
    print(mdl, {k: (len(v) if isinstance(v, list) else v) for k, v in res[mdl].items()})
meta = {}
for nome in ["ncep_gfs025", "ncep_gfs013", "ecmwf_ifs025", "ecmwf_ifs", "dwd_icon", "ukmo_global_deterministic_10km", "meteofrance_arpege_world025"]:
    u = f"https://api.open-meteo.com/data/{nome}/static/meta.json"
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=30) as r:
            meta[nome] = json.loads(r.read())
    except Exception as e:
        meta[nome] = {"erro": repr(e)}
    print("meta", nome, str(meta[nome])[:200])
json.dump({"modelos": res, "meta": meta}, open("saida/_sonda/modelos/resultado.json", "w"), ensure_ascii=False, indent=1)
