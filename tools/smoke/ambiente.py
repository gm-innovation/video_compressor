#!/usr/bin/env python3
"""Ambiente do SMOKE de ponta a ponta (bancada): mediamtx + lado terra + bordo + navegador.

Nao existe dubl^e no caminho de midia: o SRT, o mediamtx, o ffmpeg, o SQLite e o Chromium sao os de
verdade. O que este ambiente responde e' a pergunta do dono (23/11/2026): *"o sistema realmente
funciona como esperado?"* — acao de usuario -> comando real -> efeito medido.

Modos:
  `Ambiente(modo="bancada")`  — tudo nesta maquina: banco temporario, mediamtx local, fonte sintetica
                                (e' a unica fonte possivel numa maquina sem camera plugada).
  `Ambiente(modo="producao")` — o lado terra e' a VPS de producao e o bordo e' o PC de captura real
                                (quem passa os enderecos e' quem chama: `terra=`, `bordo=`).

O JSON do resultado nunca leva segredo: senha/token vem de `LECSOR_SENHA_DEMO`/`LECSOR_TOKEN_INGESTAO`
ou de argumento, e o que sai no relatorio e' so' nome de campo.
"""
from __future__ import annotations

import json
import os
import pathlib
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

RAIZ = pathlib.Path(__file__).resolve().parents[2]
FFMPEG = RAIZ / "tools" / "ffmpeg" / "ffmpeg.exe"
FFPROBE = RAIZ / "tools" / "ffmpeg" / "ffprobe.exe"
MEDIAMTX = RAIZ / "tools" / "mediamtx" / "mediamtx.exe"
MEDIAMTX_YML = RAIZ / "ground" / "mediamtx.yml"

# Portas FIXAS do lado terra: `ground/api.py` as le' do codigo (8889/8888/9997) e o mediamtx
# `ground/mediamtx.yml` abre 8554/8890/8888/8889/9997. Nao sao negociaveis por env, entao o smoke usa
# as mesmas e REUSA um mediamtx que ja' esteja no ar (a bancada costuma estar ligada).
PORTA_RTSP = 8554
PORTA_SRT = 8890
PORTA_HLS = 8888
PORTA_WEBRTC = 8889
PORTA_API_MEDIAMTX = 9997

TOKEN_PADRAO = "token-do-smoke-do-bordo"
SENHA_PADRAO = "senha-do-smoke-bancada"


def senha_de_demo() -> str:
    return os.environ.get("LECSOR_SENHA_DEMO") or SENHA_PADRAO


def token_do_bordo() -> str:
    return os.environ.get("LECSOR_TOKEN_INGESTAO") or TOKEN_PADRAO


def porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def porta_aberta(porta: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", int(porta)), timeout=0.7):
            return True
    except Exception:  # noqa: BLE001
        return False


def espera_porta(porta: int, segundos: float = 25.0) -> bool:
    fim = time.time() + segundos
    while time.time() < fim:
        if porta_aberta(porta):
            return True
        time.sleep(0.3)
    return False


def sem_janela() -> int:
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


def chromium() -> str | None:
    base = pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    achados = sorted(base.glob("chromium-*/chrome-win64/chrome.exe"), reverse=True)
    return str(achados[0]) if achados else None


def pedir_completo(metodo: str, url: str, corpo=None, sessao: str = "", token: str = "",
                   timeout: float = 40.0) -> tuple[int, object, dict]:
    """Igual a `pedir`, mas devolve tambem os cabecalhos da resposta (de onde sai o cookie de sessao)."""
    dados = json.dumps(corpo).encode("utf-8") if corpo is not None else None
    cabecalhos = {"Content-Type": "application/json"} if dados is not None else {}
    if sessao:
        cabecalhos["Cookie"] = f"sessao={sessao}"
    if token:
        cabecalhos["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=dados, method=metodo, headers=cabecalhos)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as f:
            texto = f.read().decode("utf-8", "replace")
            try:
                return f.status, json.loads(texto or "{}"), dict(f.headers)
            except Exception:  # noqa: BLE001
                return f.status, {"bruto": texto[:800]}, dict(f.headers)
    except urllib.error.HTTPError as e:
        texto = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(texto or "{}"), dict(e.headers or {})
        except Exception:  # noqa: BLE001
            return e.code, {"bruto": texto[:800]}, dict(e.headers or {})
    except Exception as e:  # noqa: BLE001
        return 0, {"erro": f"nao alcancei {url} ({type(e).__name__}: {e})"}, {}


def cookie_de(cabecalhos: dict) -> str:
    """Tira o `sessao=...` do Set-Cookie (o navegador faz o mesmo; aqui e' so' ler a linha)."""
    bruto = ""
    for chave, valor in (cabecalhos or {}).items():
        if str(chave).lower() == "set-cookie" and "sessao=" in str(valor):
            bruto = str(valor)
            break
    for pedaco in bruto.split(";"):
        if pedaco.strip().startswith("sessao="):
            return pedaco.strip()[len("sessao="):]
    return ""


def pedir(metodo: str, url: str, corpo=None, sessao: str = "", token: str = "", timeout: float = 40.0,
          bruto: bool = False):
    """Um pedido HTTP de verdade. Devolve `(codigo, corpo)`; `bruto=True` devolve o texto cru."""
    dados = json.dumps(corpo).encode("utf-8") if corpo is not None else None
    cabecalhos = {"Content-Type": "application/json"} if dados is not None else {}
    if sessao:
        cabecalhos["Cookie"] = f"sessao={sessao}"
    if token:
        cabecalhos["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=dados, method=metodo, headers=cabecalhos)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as f:
            texto = f.read().decode("utf-8", "replace")
            return f.status, (texto if bruto else json.loads(texto or "{}"))
    except urllib.error.HTTPError as e:
        texto = e.read().decode("utf-8", "replace")
        try:
            return e.code, (texto if bruto else json.loads(texto or "{}"))
        except Exception:  # noqa: BLE001
            return e.code, {"bruto": texto[:500]}
    except Exception as e:  # noqa: BLE001
        return 0, {"erro": f"nao alcancei {url} ({type(e).__name__}: {e})"}


def sql(banco: pathlib.Path, consulta: str, args: tuple = ()) -> list[sqlite3.Row]:
    con = sqlite3.connect(str(banco))
    con.row_factory = sqlite3.Row
    try:
        return list(con.execute(consulta, args).fetchall())
    finally:
        con.close()


def escrever_sql(banco: pathlib.Path, consulta: str, args: tuple = ()) -> None:
    con = sqlite3.connect(str(banco))
    try:
        con.execute(consulta, args)
        con.commit()
    finally:
        con.close()


class Ambiente:
    """Sobe (e derruba) o lado terra, o bordo e o mediamtx. Guarda as migalhas para o relatorio."""

    def __init__(self, modo: str = "bancada", embarcacao: str = "bancada", cliente: str = "lecsor",
                 terra: str = "", bordo: str = "", raiz_saida: pathlib.Path | None = None,
                 subir_bordo: bool = True) -> None:
        if modo not in ("bancada", "producao"):
            raise ValueError("modo tem que ser 'bancada' ou 'producao'")
        self.modo = modo
        self.embarcacao = embarcacao
        self.cliente = cliente
        self.producao = modo == "producao"
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="lecsor-smoke-"))
        self.saida = pathlib.Path(raiz_saida) if raiz_saida else (RAIZ / "smoke" / "saida")
        self.log = self.tmp / "ambiente.log"
        self.procs: list[subprocess.Popen] = []
        self.nomes: dict[str, subprocess.Popen] = {}
        self.terra_externo = terra
        self.bordo_externo = bordo
        self.banco_terra = self.tmp / "terra" / "pipeline.db"
        self.banco_bordo = self.tmp / "bordo" / "pipeline.db"
        self.licenca = self.tmp / "bordo" / "licenca.json"
        self.gravacoes = self.tmp / "gravacoes"
        self.porta_terra = 0
        self.porta_bordo = 0
        self.porta_media = 0          # mediamtx (RTSP) — o que o medidor le'
        self.mediamtx_proprio = False
        self.terra = terra
        self.bordo = bordo
        self._log("inicio")

    # ------------------------------------------------------------------ apoio
    def _log(self, linha: str) -> None:
        try:
            with self.log.open("a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%H:%M:%S')} {linha}\n")
        except Exception:  # noqa: BLE001
            pass

    def _abrir(self, nome: str, comando: list[str], env: dict | None = None) -> subprocess.Popen:
        destino = (self.tmp / f"{nome}.log").open("wb")
        self._log(f"subindo {nome}: {' '.join(comando[:3])}...")
        p = subprocess.Popen(comando, stdout=destino, stderr=subprocess.STDOUT,
                             cwd=str(RAIZ), env=env, creationflags=sem_janela())
        self.procs.append(p)
        self.nomes[nome] = p
        return p

    def log_de(self, nome: str, cauda: int = 400) -> str:
        arquivo = self.tmp / f"{nome}.log"
        try:
            return arquivo.read_text(encoding="utf-8", errors="replace")[-cauda:]
        except Exception:  # noqa: BLE001
            return ""

    def _env(self, **extra) -> dict:
        """Ambiente limpo das provas: sem Supabase e sem ambiente.json do dono no meio do caminho."""
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        env["LECSOR_SEM_AMBIENTE"] = "1"
        env["LECSOR_SENHA_DEMO"] = senha_de_demo()
        env["LECSOR_TOKEN_INGESTAO"] = token_do_bordo()
        env["LECSOR_EMBARCACAO"] = self.embarcacao
        env.pop("LECSOR_DESTINO_SRT", None)
        for k in ("LECSOR_SUPABASE_URL", "LECSOR_SUPABASE_ANON_KEY", "LECSOR_SUPABASE_SERVICE_KEY"):
            env.pop(k, None)
        env.update({k: str(v) for k, v in extra.items() if v is not None})
        return env

    # ------------------------------------------------------------ as tres partes
    def subir_mediamtx(self) -> bool:
        """Sobe o mediamtx da bancada — ou REUSA o que ja' esta' no ar (bancada ligada)."""
        if porta_aberta(PORTA_RTSP):
            self.porta_media = PORTA_RTSP
            self._log("mediamtx: ja' havia um no ar nesta maquina (reusando o da bancada)")
            return True
        if not MEDIAMTX.exists() or not MEDIAMTX_YML.exists():
            self._log("mediamtx: binario ou config ausente")
            return False
        self._abrir("mediamtx", [str(MEDIAMTX), str(MEDIAMTX_YML)])
        self.mediamtx_proprio = True
        self.porta_media = PORTA_RTSP
        return espera_porta(PORTA_RTSP, 25)

    def subir_terra(self, semear_demo: bool = True) -> bool:
        """O LADO TERRA (autoridade): banco proprio, sem Supabase, com a semeadura de demonstracao."""
        if self.terra_externo:
            self.terra = self.terra_externo.rstrip("/")
            return self._espera_json(f"{self.terra}/api/saude")
        self.porta_terra = porta_livre()
        self.banco_terra.parent.mkdir(parents=True, exist_ok=True)
        env = self._env(LECSOR_BANCO=self.banco_terra, LECSOR_GRAVACOES_DIR=self.gravacoes,
                        LECSOR_PORTA_RTSP=PORTA_RTSP, LECSOR_PORTA_LOCAL=str(self.porta_terra + 1000))
        args = [sys.executable, str(RAIZ / "ground" / "api.py"), str(self.porta_terra)]
        if semear_demo:
            args.append("--semear-demo")
        self._abrir("terra", args, env=env)
        self.terra = f"http://127.0.0.1:{self.porta_terra}"
        return self._espera_json(f"{self.terra}/api/saude")

    def subir_bordo(self) -> bool:
        """O BORDO: banco proprio (o PC de captura), olhando para o lado terra. Nunca abre porta para terra."""
        if self.bordo_externo:
            self.bordo = self.bordo_externo.rstrip("/")
            return self._espera_json(f"{self.bordo}/api/saude")
        self.porta_bordo = porta_livre()
        self.banco_bordo.parent.mkdir(parents=True, exist_ok=True)
        env = self._env(LECSOR_BANCO=self.banco_bordo, LECSOR_LICENCA=self.licenca,
                        LECSOR_LADO_TERRA_API=self.terra, LECSOR_GRAVACOES_DIR=self.gravacoes,
                        LECSOR_PORTA_RTSP=PORTA_RTSP, LECSOR_PORTA_LOCAL=str(self.porta_bordo))
        self._abrir("bordo", [sys.executable, str(RAIZ / "ground" / "api.py"), str(self.porta_bordo)], env=env)
        self.bordo = f"http://127.0.0.1:{self.porta_bordo}"
        return self._espera_json(f"{self.bordo}/api/saude")

    def subir_agente(self, token: str | None = None, intervalo: float = 2.0) -> bool:
        """O agente do bordo de verdade (`ground/agente_de_ordens.py`), olhando a flag do lado terra.

        A unica substituicao esta' declarada em `bordo_de_bancada.py`: nesta maquina nao ha' camera
        plugada, entao quem serve a rota local `/api/cameras/ligar` e' um atendedor fino que chama a
        FUNCAO REAL `ingestao.ligar_camera` — o encode e o envio em SRT sao os do produto.
        """
        env = self._env(LECSOR_BANCO=self.banco_bordo, LECSOR_LICENCA=self.licenca,
                        LECSOR_LADO_TERRA_API=self.terra, LECSOR_PORTA_LOCAL=str(self.porta_bordo),
                        LECSOR_TOKEN_INGESTAO=token or token_do_bordo())
        linha = self.tmp / "agente-endereco.txt"
        self._abrir("agente", [sys.executable, str(RAIZ / "tools" / "smoke" / "bordo_de_bancada.py"),
                               "--local", f"127.0.0.1:{porta_livre()}", "--terra", self.terra,
                               "--emb", self.embarcacao, "--intervalo", str(intervalo),
                               "--endereco", str(linha)], env=env)
        fim = time.time() + 20
        while time.time() < fim:
            if linha.exists() and linha.read_text(encoding="utf-8").strip():
                self._log(f"agente no ar em {linha.read_text(encoding='utf-8').strip()}")
                return True
            time.sleep(0.3)
        return False

    def _espera_json(self, url: str, segundos: float = 45.0) -> bool:
        fim = time.time() + segundos
        while time.time() < fim:
            codigo, _ = pedir("GET", url, timeout=5)
            if codigo == 200:
                return True
            time.sleep(0.4)
        return False

    def subir(self, com_agente: bool = False) -> dict:
        pronto = {"mediamtx": self.subir_mediamtx(), "terra": self.subir_terra(),
                  "bordo": self.subir_bordo()}
        if com_agente and pronto["terra"] and pronto["bordo"]:
            pronto["agente"] = self.subir_agente()
        self._log(f"ambiente: {pronto}")
        return pronto

    # ------------------------------------------------------------------ sessoes
    def entrar(self, email: str, senha: str | None = None) -> str:
        """Entra no lado terra e devolve o cookie de sessao (o mesmo que o navegador recebe)."""
        codigo, r, cabecalhos = pedir_completo("POST", f"{self.terra}/api/entrar",
                                               {"email": email, "senha": senha or senha_de_demo()})
        if codigo != 200:
            self._log(f"entrar {email}: HTTP {codigo} {str(r)[:120]}")
        return cookie_de(cabecalhos) or str((r or {}).get("sessao") or "")

    def cookie_do_navegador(self, pagina) -> str:
        for c in pagina.context.cookies():
            if c.get("name") == "sessao":
                return str(c.get("value") or "")
        return ""

    # ------------------------------------------------------------------ licenca
    def gerar_licenca(self, sessao: str, embarcacao: str = "", maquinas: int = 2) -> tuple[int, dict]:
        return pedir("POST", f"{self.terra}/api/licencas",
                     {"embarcacao_id": embarcacao or self.embarcacao, "validade_tipo": "indeterminada",
                      "maquinas_max": maquinas}, sessao=sessao)

    def ativar_no_bordo(self, chave: str) -> tuple[int, dict]:
        return pedir("POST", f"{self.bordo}/api/licenca/ativar", {"chave": chave,
                                                                 "maquina": "smoke-bancada"})

    def licenca_do_bordo(self) -> dict:
        try:
            return json.loads(self.licenca.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}

    def camera_do_bordo(self, camera_id: str, fonte: str = "live:sintetica", fluxo: str = "",
                        bitrate: str = "2500k", resolucao: str = "1280x720", fps: int = 30) -> None:
        """Cadastra A CAMERA DO BARCO no banco do bordo (na bancada ela e' sintetica: nao ha' camera).

        Os campos `srt_host`/`srt_port` sao os do lado terra — e' para la' que o bordo publica o SRT.
        """
        fluxo = fluxo or camera_id
        agora = time.strftime("%Y-%m-%dT%H:%M:%S")
        reg = sql(self.banco_bordo, "SELECT id FROM cameras WHERE id=?", (camera_id,))
        if reg:
            escrever_sql(self.banco_bordo,
                         "UPDATE cameras SET embarcacao_id=?, fluxo_id=?, ativo=1, alvo=? WHERE id=?",
                         (self.embarcacao, fluxo, bitrate, camera_id))
        else:
            escrever_sql(self.banco_bordo,
                         """INSERT INTO cameras (id,embarcacao_id,rotulo,fluxo_id,local,ativo,alvo)
                            VALUES (?,?,?,?,'',1,?)""",
                         (camera_id, self.embarcacao, f"Smoke {camera_id}", fluxo, bitrate))
        # colunas REAIS de `ingestoes` (db/schema-ingestao.sql): nao ha' `fps_alvo` nem `srt_port` —
        # a porta do SRT e' a 8890 (o produto a assume quando a linha nao diz outra coisa).
        antigo = sql(self.banco_bordo, "SELECT id FROM ingestoes WHERE fluxo_id=?", (fluxo,))
        if antigo:
            escrever_sql(self.banco_bordo,
                         """UPDATE ingestoes SET camera_id=?, rotulo=?, fonte=?, tipo='sintetica',
                                bitrate_alvo=?, resolucao=?, fps=?, srt_host='127.0.0.1', estado='parado',
                                atualizado_em=? WHERE fluxo_id=?""",
                         (camera_id, f"Smoke {camera_id}", fonte, bitrate, resolucao, fps, agora, fluxo))
        else:
            escrever_sql(self.banco_bordo,
                         """INSERT INTO ingestoes (fluxo_id,camera_id,rotulo,fonte,tipo,repetir,codec,
                                bitrate_alvo,resolucao,fps,estado,srt_host,criado_em,atualizado_em)
                            VALUES (?,?,?,?,'sintetica',0,'libx264',?,?,?,'parado','127.0.0.1',?,?)""",
                         (fluxo, camera_id, f"Smoke {camera_id}", fonte, bitrate, resolucao, fps, agora, agora))

    def publicar_camera_no_terra(self, camera_id: str) -> tuple[int, dict]:
        """Manda o cadastro ao lado terra pelo caminho do produto (`POST /api/publicacao` no bordo)."""
        return pedir("POST", f"{self.bordo}/api/publicacao", {}, token=token_do_bordo(), bruto=True)

    # ------------------------------------------------------------------ midia
    def fluxo_no_ar(self, fluxo: str, segundos: float = 25.0) -> bool:
        """O fluxo esta' publicado no mediamtx do lado terra? (quem responde e' o ffprobe)"""
        fim = time.time() + segundos
        while time.time() < fim:
            r = subprocess.run([str(FFPROBE), "-v", "error", "-print_format", "json", "-show_streams",
                                f"rtsp://127.0.0.1:{PORTA_RTSP}/{fluxo}"],
                               capture_output=True, timeout=40)
            try:
                info = json.loads((r.stdout or b"{}").decode("utf-8", "ignore"))
            except Exception:  # noqa: BLE001
                info = {}
            if any(s.get("codec_type") == "video" for s in (info.get("streams") or [])):
                return True
            time.sleep(0.7)
        return False

    def processo_da_midia(self, gatilho: str = "ffmpeg") -> list[dict]:
        """Os ffmpeg desta maquina (medido pelo sistema, nao pelo banco do produto)."""
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "Get-CimInstance Win32_Process -Filter \"Name='ffmpeg.exe'\" | "
                            "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"],
                           capture_output=True, text=True, timeout=60)
        try:
            dados = json.loads((r.stdout or "[]").strip() or "[]")
        except Exception:  # noqa: BLE001
            return []
        if isinstance(dados, dict):
            dados = [dados]
        return [{"pid": d.get("ProcessId"), "comando": (d.get("CommandLine") or "")} for d in dados
                if gatilho.lower() in (d.get("CommandLine") or "").lower()]

    # ------------------------------------------------------------------ fim
    def fechar(self) -> None:
        for nome in ("agente", "bordo", "terra"):
            p = self.nomes.pop(nome, None)
            if p is None or p.poll() is not None:
                continue
            try:
                p.terminate()
                p.wait(timeout=10)
            except Exception:  # noqa: BLE001
                try:
                    p.kill()
                except Exception:  # noqa: BLE001
                    pass
        # ffmpeg do smoke e' filho do bordo: se ficou orfao, mata (nunca deixa processo pendurado)
        for f in self.processo_da_midia("srt://127.0.0.1"):
            try:
                subprocess.run(["taskkill", "/F", "/PID", str(f["pid"])], capture_output=True, timeout=20)
            except Exception:  # noqa: BLE001
                pass
        if self.mediamtx_proprio:
            p = self.nomes.pop("mediamtx", None)
            if p is not None and p.poll() is None:
                try:
                    p.terminate()
                    p.wait(timeout=10)
                except Exception:  # noqa: BLE001
                    try:
                        p.kill()
                    except Exception:  # noqa: BLE001
                        pass
        self._log("fim")
