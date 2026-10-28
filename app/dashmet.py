"""Dashboard Meteorológico de Salto — aplicativo Windows (Batalhão de Precursores).

Servidor local (127.0.0.1) que entrega o dashboard e executa a coleta de dados no próprio computador.
Janela própria via WebView2 (pywebview); se indisponível, abre o Microsoft Edge em modo aplicativo.
Dados e configurações ficam em %LOCALAPPDATA%\\DashMetPrecursores.
"""
import datetime as dt
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from zoneinfo import ZoneInfo

APP_NOME = "Dashboard Meteorológico de Salto"
VERSAO = "1.5.0"

# --- caminhos -------------------------------------------------------------------------------
BASE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.dirname(BASE))
WEB = os.path.join(BASE, "web")
DADOS = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/.local/share"), "DashMetPrecursores")
DOCS = os.path.join(DADOS, "docs")
EFEM = os.path.join(DADOS, "efemerides")
for p in (DOCS, EFEM):
    os.makedirs(p, exist_ok=True)
# efeméride JPL incluída no executável é copiada na primeira execução
_bsp = os.path.join(BASE, "de421.bsp")
if os.path.exists(_bsp) and not os.path.exists(os.path.join(EFEM, "de421.bsp")):
    shutil.copy(_bsp, os.path.join(EFEM, "de421.bsp"))

import coleta as C  # noqa: E402  (reaproveita a coleta do repositório)
import fontes_extra as FX  # noqa: E402
import aisweb as AW  # noqa: E402

NOMES = {"mission", "models", "sounding", "models_raw", "sounding_raw", "obs", "analysis", "history", "astro", "oficiais", "aer", "config"}
_lock = threading.Lock()
STATUS = {"rodando": False, "etapas": [], "inicio": None, "fim": None, "erro": None}


def ler(nome, padrao=None):
    f = os.path.join(DOCS, nome + ".json")
    if not os.path.exists(f):
        return padrao
    try:
        with open(f, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return padrao


def gravar(nome, dado):
    with _lock:
        tmp = os.path.join(DOCS, nome + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(dado, fh, ensure_ascii=False)
        os.replace(tmp, os.path.join(DOCS, nome + ".json"))


def agora():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def historico(texto):
    h = ler("history", {"items": []}) or {"items": []}
    h["items"] = (h.get("items", []) + [{"when": agora(), "what": texto}])[-40:]
    gravar("history", h)


def etapa(txt, ok=None):
    STATUS["etapas"].append({"t": agora(), "txt": txt, "ok": ok})


# --- coleta ---------------------------------------------------------------------------------
def coletar():
    m = ler("mission")
    if not m or m.get("lat") is None or m.get("lon") is None or not m.get("date"):
        raise RuntimeError("Missão não definida: salve coordenada, data e horário H.")
    lat, lon, data, hora, fuso = float(m["lat"]), float(m["lon"]), m["date"], int(m.get("hour", 10)), m.get("tz") or "America/Sao_Paulo"
    icao = (m.get("icao") or "").strip().upper()
    ads = [x for x in re.split(r"[ ,;]+", (m.get("aerodromos") or "").upper()) if re.match(r"^[A-Z0-9]{4}$", x)][:4]
    cfg = ler("config", {}) or {}
    marca = agora()

    # 1) Modelos — Open-Meteo (GFS, ECMWF, ICON)
    etapa("Modelos GFS, ECMWF e ICON (Open-Meteo)…")
    u = C.url_open_meteo(lat, lon, data, fuso)
    st, corpo = C.baixar(u, tentativas=2, timeout=90)
    if st:
        gravar("models_raw", {"raw": corpo, "url": u, "fetchedAt": marca})
        etapa("Modelos carregados", True)
    else:
        etapa("Modelos indisponíveis: " + str(corpo)[:160], False)

    # 2) Sondagem NOAA — rucsoundings (GSD); alternativa NOMADS (GRIB2, se ecCodes disponível)
    etapa("Sondagem NOAA…")
    h_local = dt.datetime.fromisoformat(f"{data}T{hora:02d}:00").replace(tzinfo=ZoneInfo(fuso))
    h_utc = h_local.astimezone(dt.timezone.utc)
    h3 = h_utc.replace(hour=h_utc.hour - h_utc.hour % 3, minute=0, second=0, microsecond=0)
    sond = None
    for quando in (h3, None):
        u2 = C.url_sondagem(lat, lon, quando)
        st2, c2 = C.baixar(u2, tentativas=1, timeout=40)
        if st2 and C.tem_niveis(c2):
            sond = {"raw": c2, "fonte": "NOAA rucsoundings (GSD)", "url": u2, "validoPara": quando.isoformat() if quando else "latest"}
            break
    if not sond:
        try:
            import eccodes  # noqa: F401
            for ciclo, f in C.ciclos_gfs(h_utc)[:3]:
                u3 = C.url_nomads(ciclo, f, lat, lon)
                st3, c3 = C.baixar(u3, tentativas=2, timeout=90, binario=True)
                if st3 and c3[:4] == b"GRIB":
                    caminho = os.path.join(DADOS, "gfs.grib2")
                    open(caminho, "wb").write(c3)
                    txt = C.grib_para_gsd(caminho, lat, lon, ciclo, f)
                    os.remove(caminho)
                    if C.tem_niveis(txt):
                        sond = {"raw": txt, "fonte": "NOAA NOMADS GFS 0,25°", "url": u3, "validoPara": h_utc.isoformat(), "ciclo": ciclo.isoformat(), "prazo": f}
                        break
        except Exception as e:  # ecCodes ausente ou falha na decodificação
            etapa("NOMADS indisponível: " + repr(e)[:120], False)
    if sond:
        sond["fetchedAt"] = marca
        gravar("sounding_raw", sond)
        etapa("Sondagem: " + sond["fonte"], True)
    else:
        etapa("Sondagem NOAA indisponível (o dashboard usa os níveis de pressão dos modelos)", False)

    # 3) Astronomia — JPL (Skyfield) + USNO
    etapa("Astronomia JPL/USNO…")
    astro = {"coletado_em_utc": marca, "lat": lat, "lon": lon, "data": data, "fuso": fuso}
    try:
        astro["skyfield"] = FX.astronomia_skyfield(lat, lon, data, fuso, EFEM)
        etapa("Efemérides JPL calculadas", True)
    except Exception as e:
        astro["skyfield"] = {"erro": repr(e)}
        etapa("JPL indisponível: " + repr(e)[:120], False)
    astro["usno"] = FX.usno(lat, lon, data, fuso, C.baixar)
    gravar("astro", astro)

    # 4) Aeródromos — AISWEB
    lista = list(dict.fromkeys(ads + ([icao] if icao else [])))
    aer = {"coletado_em_utc": marca, "aerodromos": {}}
    for c in lista:
        etapa(f"AISWEB {c}…")
        st4, c4 = C.baixar(f"https://aisweb.decea.mil.br/?i=aerodromos&codigo={c}", tentativas=2, timeout=60)
        try:
            aer["aerodromos"][c] = AW.ler(c4, c) if st4 else {"icao": c, "erro": str(c4)[:200]}
        except Exception as e:
            aer["aerodromos"][c] = {"icao": c, "erro": "leitura: " + repr(e)}
    gravar("aer", aer)

    # 5) INMET e REDEMET (credenciais nas Configurações)
    etapa("INMET e REDEMET…")
    try:
        of = {"coletado_em_utc": marca, "lat": lat, "lon": lon,
              "inmet": FX.inmet(lat, lon, C.baixar, cfg.get("inmet_token", "")),
              "redemet": FX.redemet(icao, C.baixar, cfg.get("redemet_api_key", ""))}
    except Exception as e:
        of = {"coletado_em_utc": marca, "lat": lat, "lon": lon, "erro": repr(e)}
    gravar("oficiais", of)

    # 6) OPMET — NOAA/AWC (mesmas mensagens OACI)
    etapa("METAR, TAF e SIGMET (NOAA/AWC)…")
    ids = ",".join(lista)
    metars, tafs, sigmets = [], [], []
    if ids:
        st5, c5 = C.baixar(f"https://aviationweather.gov/api/data/metar?ids={ids}&format=raw&hours=6", tentativas=2, timeout=40)
        if st5:
            metars = [re.sub(r"\s+", " ", x).strip().rstrip("=") for x in c5.splitlines() if x.strip()]
        st6, c6 = C.baixar(f"https://aviationweather.gov/api/data/taf?ids={ids}&format=raw", tentativas=2, timeout=40)
        if st6:
            tafs = [re.sub(r"\s+", " ", x).strip().rstrip("=") for x in re.split(r"\n(?=TAF )", c6) if x.strip().startswith("TAF")]
    st7, c7 = C.baixar("https://aviationweather.gov/api/data/isigmet?format=raw", tentativas=1, timeout=40)
    if st7:
        for blk in re.split(r"\n\s*\n", c7):
            if re.search(r"\b(SBAZ|SBBS|SBCW|SBRE|SBAO)\b", blk):
                sigmets.append(re.sub(r"\s+", " ", blk).strip())
    if not (metars or tafs or sigmets):
        etapa("OPMET indisponível (dados anteriores mantidos)", False)
        historico("Atualização no aplicativo (OPMET indisponível)")
        return
    gravar("obs", {"metars": metars, "tafs": tafs, "sigmets": sigmets, "updatedAt": marca,
                   "source": "NOAA/AWC (aviationweather.gov) — mensagens OACI; SIGMET das FIR brasileiras (sem filtro de área)"})
    etapa(f"OPMET: {len(metars)} METAR, {len(tafs)} TAF, {len(sigmets)} SIGMET", True)
    historico("Atualização no aplicativo: modelos, sondagem, astronomia, AISWEB, INMET/REDEMET e OPMET")


def _rodar():
    STATUS.update({"rodando": True, "etapas": [], "inicio": agora(), "fim": None, "erro": None})
    try:
        coletar()
    except Exception as e:
        STATUS["erro"] = str(e)
        etapa("Erro: " + str(e), False)
        traceback.print_exc()
    finally:
        STATUS.update({"rodando": False, "fim": agora()})


# --- servidor -------------------------------------------------------------------------------
class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _corpo(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n).decode("utf-8") or "{}") if n else {}

    def do_GET(self):
        p = urllib.parse.urlparse(self.path).path
        if p == "/api/state":
            out = {n: ler(n) for n in NOMES if n != "config"}
            cfg = ler("config", {}) or {}
            out["config"] = {"redemet": bool(cfg.get("redemet_api_key")), "inmet": bool(cfg.get("inmet_token"))}
            out["app"] = {"versao": VERSAO, "dados": DADOS}
            return self._json(out)
        if p == "/api/status":
            return self._json(STATUS)
        arq = "index.html" if p in ("/", "") else p.lstrip("/")
        f = os.path.normpath(os.path.join(WEB, arq))
        if not f.startswith(WEB) or not os.path.isfile(f):
            self.send_error(404)
            return
        tipo = {".html": "text/html; charset=utf-8", ".js": "application/javascript", ".png": "image/png", ".ico": "image/x-icon"}.get(os.path.splitext(f)[1], "application/octet-stream")
        b = open(f, "rb").read()
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_POST(self):
        p = urllib.parse.urlparse(self.path).path
        try:
            d = self._corpo()
        except Exception:
            return self._json({"erro": "JSON inválido"}, 400)
        m = re.fullmatch(r"/api/doc/([a-z_]+)", p)
        if m and m[1] in NOMES and m[1] != "config":
            gravar(m[1], d)
            return self._json({"ok": True})
        if p == "/api/atualizar":
            if STATUS["rodando"]:
                return self._json({"ok": False, "erro": "Atualização já em andamento"})
            threading.Thread(target=_rodar, daemon=True).start()
            return self._json({"ok": True})
        if p == "/api/config":
            cfg = ler("config", {}) or {}
            for k in ("redemet_api_key", "inmet_token"):
                if k in d:
                    cfg[k] = (d[k] or "").strip()
            gravar("config", cfg)
            return self._json({"ok": True, "redemet": bool(cfg.get("redemet_api_key")), "inmet": bool(cfg.get("inmet_token"))})
        if p == "/api/salvar":
            nome = re.sub(r"[^\w.\-]", "_", d.get("filename") or "arquivo.txt")[:120]
            pasta = os.path.join(os.path.expanduser("~"), "Downloads")
            os.makedirs(pasta, exist_ok=True)
            destino = os.path.join(pasta, nome)
            if d.get("base64"):
                import base64
                open(destino, "wb").write(base64.b64decode(d["base64"]))
            else:
                open(destino, "w", encoding="utf-8-sig", newline="").write(d.get("text", ""))
            return self._json({"ok": True, "path": destino})
        if p == "/api/abrir":
            url = d.get("url", "")
            if url.startswith("https://"):
                import webbrowser
                webbrowser.open(url)
            return self._json({"ok": True})
        self._json({"erro": "rota inexistente"}, 404)


def porta_livre():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def main():
    porta = porta_livre()
    srv = ThreadingHTTPServer(("127.0.0.1", porta), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{porta}/"
    if "--diagnostico" in sys.argv:  # verificação do executável
        diag = {"versao": VERSAO, "web": os.path.exists(os.path.join(WEB, "index.html")), "efemeride": os.path.exists(os.path.join(EFEM, "de421.bsp"))}
        try:
            diag["fuso"] = str(ZoneInfo("America/Sao_Paulo"))
        except Exception as e:
            diag["fuso"] = repr(e)[:200]
        try:
            import webview
            diag["webview_versao"] = getattr(webview, "__version__", "?")
        except Exception as e:
            diag["webview_versao"] = repr(e)[:200]
        for mod in ("webview", "skyfield", "eccodes", "tzdata"):
            try:
                __import__(mod)
                diag[mod] = True
            except Exception as e:
                diag[mod] = repr(e)[:200]
        try:
            import eccodes
            diag["eccodes_versao"] = eccodes.codes_get_api_version()
        except Exception as e:
            diag["eccodes_versao"] = repr(e)[:200]
        try:
            a = FX.astronomia_skyfield(-22.875, -43.384, "2026-10-14", "America/Sao_Paulo", EFEM)
            diag["astronomia"] = a["dias"]["2026-10-14"].get("fcvc")
        except Exception as e:
            diag["astronomia"] = repr(e)[:200]
        import urllib.request
        try:
            diag["servidor"] = json.loads(urllib.request.urlopen(url + "api/state", timeout=10).read()).get("app")
            diag["pagina_bytes"] = len(urllib.request.urlopen(url, timeout=10).read())
        except Exception as e:
            diag["servidor"] = repr(e)[:200]
        if "--teste-coleta" in sys.argv:
            amanha = (dt.date.today() + dt.timedelta(days=1)).isoformat()
            gravar("mission", {"name": "TESTE", "lat": -22.875, "lon": -43.384, "date": amanha, "hour": 10, "tz": "America/Sao_Paulo",
                               "icao": "SBAF", "aerodromos": "SBAF,SBGL", "zlElevFt": 112})
            _rodar()
            diag["coleta"] = STATUS["etapas"]
            diag["docs"] = {n: os.path.getsize(os.path.join(DOCS, n + ".json")) for n in NOMES if os.path.exists(os.path.join(DOCS, n + ".json"))}
        with open(os.path.join(DADOS, "diagnostico.json"), "w", encoding="utf-8") as fh:
            json.dump(diag, fh, ensure_ascii=False, indent=1)
        srv.shutdown()
        return
    if "--sem-janela" in sys.argv:  # modo de teste
        with open(os.path.join(DADOS, "url.txt"), "w") as fh:
            fh.write(url)
        if sys.stdout:
            print(url, flush=True)
        while True:
            time.sleep(3600)
    try:
        import webview
        webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
        webview.create_window(APP_NOME, url, width=1440, height=920, min_size=(420, 600))
        webview.start()
    except Exception:
        # alternativa: Microsoft Edge em modo aplicativo
        edge = None
        for c in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"):
            if os.path.exists(c):
                edge = c
        if edge:
            subprocess.Popen([edge, f"--app={url}", "--window-size=1440,920"])
        else:
            import webbrowser
            webbrowser.open(url)
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, "O dashboard está aberto no navegador.\nFeche esta mensagem para encerrar o aplicativo.", APP_NOME, 0x40)
        except Exception:
            while True:
                time.sleep(3600)
    srv.shutdown()


if __name__ == "__main__":
    main()
