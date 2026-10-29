"""Sonda: produtos de radar públicos (Alerta Rio, REDEMET, CPTEC) e documentação da API REDEMET."""
import json, os, urllib.request, urllib.error, re
UA = "Mozilla/5.0 (DashboardMeteorologicoSalto/1.0; uso institucional)"
OUT = "saida/_sonda/radar"; os.makedirs(OUT, exist_ok=True)
res = {}
def get(u, timeout=40):
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=timeout) as r:
            b = r.read(); return {"status": r.status, "bytes": len(b), "ctype": r.headers.get("Content-Type"), "body": b}
    except urllib.error.HTTPError as e:
        return {"status": e.code, "erro": e.read()[:300].decode("utf-8", "replace")}
    except Exception as e:
        return {"erro": repr(e)}
U = {
 "redemet_doc": "https://ajuda.decea.mil.br/base-de-conhecimento/api-redemet-produtos-radar/",
 "redemet_doc_lista": "https://ajuda.decea.mil.br/base-de-conhecimento/api-redemet-lista-de-produtos/",
 "redemet_radar_semchave": "https://api-redemet.decea.mil.br/produtos/radar/maxcappi",
 "alertario_radar000": "http://alertario.rio.rj.gov.br/upload/Mapa/semfundo/radar000.png",
 "alertario_radar_pagina": "https://www.sistema-alerta-rio.com.br/previsao-do-tempo/radar/",
 "cptec_radar": "http://sigma.cptec.inpe.br/radar/",
 "cemaden_radar": "https://www.cemaden.gov.br/mapainterativo/",
}
for k, u in U.items():
    r = get(u); d = {x: y for x, y in r.items() if x != "body"}
    if "body" in r:
        if r.get("ctype") and ("html" in r["ctype"] or "json" in r["ctype"] or "text" in r["ctype"]):
            t = r["body"].decode("utf-8", "replace"); t = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", "", t); t = re.sub(r"<[^>]+>", " ", t); d["texto"] = re.sub(r"\s+", " ", t)[:6000]
            d["links"] = sorted(set(re.findall(r'(?:href|src)="([^"]+(?:radar|api|\.png|\.gif|\.jpg)[^"]*)"', r["body"].decode("utf-8", "replace"))))[:80]
        else: open(f"{OUT}/{k}.bin", "wb").write(r["body"][:3_000_000])
    res[k] = d; print(k, {x: (y if x not in ("texto", "links") else len(y)) for x, y in d.items()})
json.dump(res, open(f"{OUT}/res.json", "w"), indent=1, ensure_ascii=False)
