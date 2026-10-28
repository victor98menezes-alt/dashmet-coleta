"""Sonda das fontes INMET/IBGE/CPTEC (diagnóstico). Grava saida/_sonda/inmet/."""
import json, os, urllib.request, urllib.error
UA = "DashboardMeteorologicoSalto/1.0 (uso institucional nao comercial)"
T = {
    "avisos_ativos": "https://apiprevmet3.inmet.gov.br/avisos/ativos",
    "avisos_rss": "https://apiprevmet3.inmet.gov.br/avisos/rss",
    "previsao_rio": "https://apiprevmet3.inmet.gov.br/previsao/3304557",
    "estacao_proxima_rio": "https://apiprevmet3.inmet.gov.br/estacao/proxima/3304557",
    "alert_as_rss": "http://alert-as.inmet.gov.br/cap_12/rss/alert-as.rss",
    "ibge_municipio": "https://servicodados.ibge.gov.br/api/v1/localidades/municipios/3304557",
    "ibge_rj_municipios": "https://servicodados.ibge.gov.br/api/v1/localidades/estados/RJ/municipios",
    "nominatim_reverse": "https://nominatim.openstreetmap.org/reverse?lat=-22.875&lon=-43.384&format=json&zoom=10&accept-language=pt-BR",
    "cptec_latlon": "http://servicos.cptec.inpe.br/XML/cidade/7dias/-22.87/-43.38/previsaoLatLon.xml",
    "cptec_busca": "http://servicos.cptec.inpe.br/XML/listaCidades?city=rio%20de%20janeiro",
    "openmeteo_8d": "https://api.open-meteo.com/v1/forecast?latitude=-22.875&longitude=-43.384&hourly=temperature_2m,precipitation,cape,weather_code,pressure_msl&models=gfs_seamless,ecmwf_ifs025,icon_seamless&forecast_days=9&timezone=America/Sao_Paulo",
}
os.makedirs("saida/_sonda/inmet", exist_ok=True)
res = {}
for k, u in T.items():
    try:
        req = urllib.request.Request(u, headers={"User-Agent": UA, "Accept": "*/*", "Referer": "https://portal.inmet.gov.br/"})
        with urllib.request.urlopen(req, timeout=60) as r:
            b = r.read()
            open(f"saida/_sonda/inmet/{k}.txt", "wb").write(b[:400000])
            res[k] = {"url": u, "status": r.status, "tipo": r.headers.get("Content-Type"), "cors": r.headers.get("Access-Control-Allow-Origin"), "bytes": len(b)}
    except urllib.error.HTTPError as e:
        res[k] = {"url": u, "status": e.code, "inicio": e.read()[:500].decode("utf-8", "replace")}
    except Exception as e:
        res[k] = {"url": u, "erro": repr(e)}
    print(k, res[k])
json.dump(res, open("saida/_sonda/inmet/resultado.json", "w"), ensure_ascii=False, indent=2)
