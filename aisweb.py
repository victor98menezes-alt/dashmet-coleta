"""Leitura da página pública do AISWEB (DECEA) para um aeródromo: ROTAER, distâncias declaradas, cartas, METAR/TAF e RCR."""
import html as _html
import math
import re


def texto(h):
    body = h[h.find("<body"):] if "<body" in h else h
    t = re.sub(r"<script.*?</script>|<style.*?</style>", "", body, flags=re.S)
    t = re.sub(r"<br\s*/?>", "\n", t)
    t = re.sub(r"</(p|div|li|tr|h\d|td|th)>", "\n", t)
    t = _html.unescape(re.sub(r"<[^>]+>", " ", t))
    t = re.sub(r"[ \t ]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n", t)


def _coord(s):
    m = re.match(r"\s*([NS])\s*(\d{2})\s*(\d{2})\s*(\d{2}(?:[.,]\d+)?)\s*([EW])\s*(\d{3})\s*(\d{2})\s*(\d{2}(?:[.,]\d+)?)", s)
    if not m:
        return None
    la = int(m[2]) + int(m[3]) / 60 + float(m[4].replace(",", ".")) / 3600
    lo = int(m[6]) + int(m[7]) / 60 + float(m[8].replace(",", ".")) / 3600
    return (-la if m[1] == "S" else la, -lo if m[5] == "W" else lo)


def _rumo(a, b):
    r = math.pi / 180
    y = math.sin((b[1] - a[1]) * r) * math.cos(b[0] * r)
    x = math.cos(a[0] * r) * math.sin(b[0] * r) - math.sin(a[0] * r) * math.cos(b[0] * r) * math.cos((b[1] - a[1]) * r)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def ler(h, icao):
    t = texto(h)
    out = {"icao": icao, "fonte": "AISWEB — DECEA (página pública do aeródromo)",
           "url": f"https://aisweb.decea.mil.br/?i=aerodromos&codigo={icao}"}
    i0 = t.find("D-AMDT")
    if i0 < 0:
        out["erro"] = "ROTAER não encontrado na página (código inexistente ou layout alterado)."
        return out
    rot = t[i0:]
    m = re.search(r"D-AMDT\s+(\S+)", rot)
    out["emenda"] = m[1] if m else None
    m = re.search(r"\n\s*(.+?)\s*\n\(\s*" + icao + r"\s*\)", rot)
    out["nome"] = m[1].strip() if m else None
    m = re.search(r"\(\s*" + icao + r"\s*\)\s*/\s*\n?\s*([^,\n]+?)\s*,\s*\n?\s*([A-Z]{2})", rot)
    if m:
        out["cidade"], out["uf"] = m[1].strip().title(), m[2]
    m = re.search(r"(\d{2} \d{2} \d{2}[NS])/(\d{3} \d{2} \d{2}[EW])", rot)
    if m:
        a, b = m[1], m[2]
        la = int(a[:2]) + int(a[3:5]) / 60 + int(a[6:8]) / 3600
        lo = int(b[:3]) + int(b[4:6]) / 60 + int(b[7:9]) / 3600
        out["lat"], out["lon"] = (-la if a[-1] == "S" else la), (-lo if b[-1] == "W" else lo)
    m = re.search(r"\nAD\s*\n\s*([A-Z/ ]+?)\s*\n", rot)
    out["tipo"] = m[1].strip() if m else None
    out["regras"] = re.findall(r"\n(VFR(?: IFR)?|IFR)\s*\n", rot[:1500])[:1]
    m = re.search(r"\n\s*(-?[\d.]+)\s*\((-?\d+)\)\s*\n", rot[:2500])
    if m:
        out["elev_m"], out["elev_ft"] = float(m[1]), int(m[2])
    fim_pistas = rot.find("COM -")
    bloco = rot[:fim_pistas if fim_pistas > 0 else 4000]
    pistas = []
    for pm in re.finditer(r"\(\s*\n?\s*(\d+)x(\d+)\s*\n\s*([A-Z]+)\s*\n\s*([^\s\n]+)", bloco):
        antes = bloco[:pm.start()]
        d1 = re.findall(r"\n\s*(\d{2}[LRC]?)\s*-\s", antes)
        depois = bloco[pm.end():]
        d2 = re.search(r"\)\s*\n-[\s\S]*?\n\s*(\d{2}[LRC]?)\s*\n", depois)
        pistas.append({"cabeceiras": [d1[-1] if d1 else None, d2[1] if d2 else None], "comprimento_m": int(pm[1]), "largura_m": int(pm[2]),
                       "piso": pm[3], "resistencia": pm[4]})
    # distâncias declaradas e coordenadas das cabeceiras
    dd = {}
    k = t.find("DISTÂNCIA(S) DECLARADA(S)")
    if k > 0:
        seg = t[k:t.find("COMPL", k) if t.find("COMPL", k) > 0 else k + 3000]
        for r in re.finditer(r"\n\s*(\d{2}[LRC]?)\s*\n\s*(\d+)\s*\n\s*(\d+)\s*\n\s*(\d+)\s*\n\s*(\d+)\s*\n\s*([-\d ,.]+)\s*\n\s*([NS] ?\d{2} \d{2} \d{2}(?:[.,]\d+)? [EW] ?\d{3} \d{2} \d{2}(?:[.,]\d+)?)", seg):
            dd[r[1]] = {"tora": int(r[2]), "toda": int(r[3]), "asda": int(r[4]), "lda": int(r[5]), "coord": _coord(r[7])}
    out["distancias"] = dd
    for p in pistas:
        a, b = p["cabeceiras"]
        p["rumo_verdadeiro"] = {}
        if a in dd and b in dd and dd[a]["coord"] and dd[b]["coord"]:
            p["rumo_verdadeiro"][a] = round(_rumo(dd[a]["coord"], dd[b]["coord"]), 1)
            p["rumo_verdadeiro"][b] = round(_rumo(dd[b]["coord"], dd[a]["coord"]), 1)
    out["pistas"] = pistas
    # auxílios-rádio
    k = rot.find("RDONAV -")
    aux = []
    if k > 0:
        seg = rot[k + 8: rot.find(" CMB -", k) if rot.find(" CMB -", k) > 0 else k + 1500]
        linhas = [x.strip() for x in seg.split("\n") if x.strip()]
        for i, l in enumerate(linhas):
            if re.match(r"(ILS|LOC|GP|VOR|NDB|DME|IM|MM|OM|TACAN|GBAS)", l):
                aux.append(l + (" — " + linhas[i + 1] if i + 1 < len(linhas) and re.match(r"[\d.]", linhas[i + 1]) else ""))
    out["auxilios"] = aux
    # cartas
    cartas = {}
    k = t.find("Cartas (", t.find("Cartas (") + 1) if t.count("Cartas (") > 1 else t.find("Cartas (")
    if k > 0:
        seg = t[k: t.find("Rotas Preferenciais (", k) if t.find("Rotas Preferenciais (", k) > 0 else k + 4000]
        atual = None
        for l in [x.strip() for x in seg.split("\n")[1:] if x.strip()]:
            if re.fullmatch(r"[A-Z]{2,4}", l):
                atual = l
                cartas[atual] = []
            elif atual:
                cartas[atual].append(l)
    out["cartas"] = cartas
    iac = cartas.get("IAC", [])
    por_cab = {}
    for c in iac:
        for cab in re.findall(r"RWY ((?:\d{2}[LRC]?/?)+)", c):
            for x in cab.split("/"):
                if x:
                    por_cab.setdefault(x, []).append(c)
    out["procedimentos_por_cabeceira"] = por_cab
    # restrições e observações relevantes para lançamento de paraquedistas / operação
    rmk = rot[rot.find("RMK -"): rot.find("DISTÂNCIA(S) DECLARADA(S)")] if "RMK -" in rot else ""
    rel = []
    for l in [x.strip() for x in rmk.split("\n") if x.strip()]:
        if re.search(r"paraqued|lançamento|\bPJE\b|uso exclusivo|\bPPR\b|restri|horário|\bDLY\b|\bMON\b|\bSAT\b|\bSUN\b|\bHOL\b|\bcivil\b", l, re.I) and len(l) < 300:
            rel.append(l)
    out["observacoes"] = rel[:12]
    out["notas"] = [x.strip() for x in re.findall(r"\[\s*\d+\s*\]\s*([^\[\n]{3,200})", t[t.find("COMPL -"):t.find("TEMP (")])][:20] if "COMPL -" in t else []
    # METAR / TAF / RCR publicados na página
    k = t.rfind("Nascer/Por do Sol")
    seg = t[k: t.find("OPEA/Obst", k)] if k > 0 else ""
    out["metar"] = [re.sub(r"\s+", " ", x).strip().rstrip("=") for x in re.findall(r"((?:METAR|SPECI) " + icao + r"[^=]+)=", seg)]
    out["taf"] = [re.sub(r"\s+", " ", x).strip().rstrip("=") for x in re.findall(r"(TAF (?:AMD |COR )?" + icao + r"[^=]+)=", seg)]
    out["rcr"] = [re.sub(r"\s+", " ", x).strip() for x in re.findall(icao + r" \d{8} \d{2}[LRC]? [^\n]+", seg)]
    return out
