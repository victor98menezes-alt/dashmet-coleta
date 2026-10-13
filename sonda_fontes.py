"""Sonda de acesso às fontes (diagnóstico). Grava saida/_sonda/resultado.json."""
import datetime as dt
import json
import os
import urllib.error
import urllib.request

UA = "DashboardMeteorologicoSalto/1.0 (uso institucional nao comercial)"
HOJE = dt.date.today().isoformat()
ONTEM = (dt.date.today() - dt.timedelta(days=1)).isoformat()
TESTES = {
    "aisweb_SBAF": "https://aisweb.decea.mil.br/?i=aerodromos&codigo=SBAF",
    "aisweb_SBGL": "https://aisweb.decea.mil.br/?i=aerodromos&codigo=SBGL",
    "aisweb_api_sem_chave": "https://api.decea.mil.br/aisweb/?area=rotaer&icaoCode=SBAF",
    "inmet_A621_ontem_hoje": f"https://apitempo.inmet.gov.br/estacao/{ONTEM}/{HOJE}/A621",
    "inmet_A652_ontem": f"https://apitempo.inmet.gov.br/estacao/{ONTEM}/{ONTEM}/A652",
    "inmet_dados_horarios_dia": f"https://apitempo.inmet.gov.br/estacao/dados/{ONTEM}/1200",
    "inmet_token_invalido": f"https://apitempo.inmet.gov.br/token/estacao/{ONTEM}/{HOJE}/A621/TESTE",
    "inmet_portal_api": "https://portal.inmet.gov.br/manual",

    "inmet_estacoes_automaticas": "https://apitempo.inmet.gov.br/estacoes/T",
    "inmet_dados_dia": f"https://apitempo.inmet.gov.br/estacao/dados/{HOJE}",
    "inmet_estacao_A652": f"https://apitempo.inmet.gov.br/estacao/{HOJE}/{HOJE}/A652",
    "inmet_portal_manual": "https://portal.inmet.gov.br/manual/manual-de-uso-da-api-esta%C3%A7%C3%B5es",
    "redemet_api_sem_chave": "https://api-redemet.decea.mil.br/mensagens/metar/SBGL",
    "redemet_api_chave_invalida": "https://api-redemet.decea.mil.br/mensagens/metar/SBGL?api_key=TESTE",
    "redemet_portal": "https://redemet.decea.mil.br/",
    "usno_rstt": "https://aa.usno.navy.mil/api/rstt/oneday?date=2026-10-14&coords=-22.875,-43.384&tz=-3",
    "timeanddate_sun": "https://www.timeanddate.com/sun/@-22.875,-43.384?month=10&year=2026",
}
res = {}
for nome, url in TESTES.items():
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json,text/html,*/*"})
        with urllib.request.urlopen(req, timeout=45) as r:
            corpo = r.read()
            if nome.startswith("aisweb_SB"):
                os.makedirs("saida/_sonda", exist_ok=True)
                open(f"saida/_sonda/{nome}.html", "wb").write(corpo)
            res[nome] = {"url": url, "status": r.status, "tipo": r.headers.get("Content-Type"), "bytes": len(corpo),
                         "inicio": corpo[:1500].decode("utf-8", "replace")}
    except urllib.error.HTTPError as e:
        res[nome] = {"url": url, "status": e.code, "inicio": e.read()[:1500].decode("utf-8", "replace")}
    except Exception as e:
        res[nome] = {"url": url, "status": None, "erro": repr(e)}
os.makedirs("saida/_sonda", exist_ok=True)
json.dump(res, open("saida/_sonda/resultado.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
for k, v in res.items():
    print(k, v.get("status"), v.get("bytes"), (v.get("erro") or v.get("inicio", ""))[:160].replace("\n", " "))
