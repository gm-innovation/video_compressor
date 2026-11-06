#!/usr/bin/env python3
"""Agente de analise de video (Fase 5) — roda a bordo, ao lado do encoder.

O que ele faz: le o fluxo da camera (fluxo publicado internamente), detecta pessoas, rastreia,
conta travessias de linha e permanencia em zona, e sobe para o servidor **evento e contagem**
(nunca o video). O video continua sendo responsabilidade do encoder.

Uso na bancada:
  python analytics/agente.py --perfil analytics/perfis/cam-03.json --duracao 60

Sem a API no ar (para medir so a contagem):
  python analytics/agente.py --perfil analytics/perfis/cam-03.json --duracao 60 --sem-api
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from analytics.detector import CLASSES_COCO, Detector          # noqa: E402
from analytics.rastreador import ContadorLinha, Rastreador, ZonaRisco  # noqa: E402


def agora() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


class Agente:
    def __init__(self, perfil: dict, api: str = "", chave: str = "", nome: str = "", sem_api: bool = False,
                 json_saida: Path | None = None):
        self.p = perfil
        self.api = api.rstrip("/")
        self.chave = chave
        self.nome = nome or perfil.get("nome", "agente-bordo")
        self.sem_api = sem_api or not self.api
        self.json_saida = json_saida
        modelo = Path(perfil.get("modelo", "analytics/modelos/yolov10n.onnx"))
        if not modelo.is_absolute():
            modelo = RAIZ / modelo
        self.detector = Detector(modelo, tamanho=int(perfil.get("tamanho", 640)),
                                 confianca=float(perfil.get("confianca", 0.35)))
        self.classes = set(perfil.get("classes", [0]))
        self.decimar = max(1, int(perfil.get("decimar", 1)))
        self.anuncio_s = float(perfil.get("anuncio_s", 5.0))
        self.rastreador = Rastreador(iou_minimo=float(perfil.get("iou_minimo", 0.25)),
                                     distancia_maxima=float(perfil.get("distancia_maxima", 120)))
        cfg = perfil.get("linha") or {}
        self.contador = ContadorLinha(tuple(cfg["a"]), tuple(cfg["b"]),
                                      quadros_de_confirmacao=int(cfg.get("confirmacao", 3)),
                                      espera_s=float(cfg.get("espera_s", 1.5)),
                                      fps=float(perfil.get("fps_nominal", 12)),
                                      sentido_positivo=cfg.get("sentido_positivo", "entrada")) if cfg else None
        self.zonas = [ZonaRisco(z["nome"], [tuple(p) for p in z["poligono"]],
                                segundos=float(z.get("segundos", 3.0)), espera_s=float(z.get("espera_s", 30)))
                      for z in (perfil.get("zonas") or [])]
        self.eventos_pendentes: list[dict] = []
        self.erros = 0

    # ---------------------------------------------------------------- envio
    def _post(self, rota: str, corpo: dict) -> bool:
        if self.sem_api:
            return True
        req = urllib.request.Request(self.api + rota, data=json.dumps(corpo).encode(),
                                     headers={"Content-Type": "application/json", "X-Chave-Analytics": self.chave},
                                     method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return 200 <= r.status < 300
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            self.erros += 1
            print(f"  ! falha ao enviar {rota}: {e}")
            return False

    def enviar_eventos(self) -> int:
        if not self.eventos_pendentes:
            return 0
        eventos, self.eventos_pendentes = self.eventos_pendentes, []
        if self._post("/api/analytics/eventos", {"camera_id": self.p["camera_id"], "eventos": eventos}):
            return len(eventos)
        self.eventos_pendentes = eventos + self.eventos_pendentes
        return 0

    def enviar_contagem(self, quadros: int, analisados: int, tempo_s: float, caixas: list, estado: str) -> bool:
        c = self.contador
        if c is None:
            entrou = saiu = pico = 0
        else:
            entrou, saiu, pico = c.entrou, c.saiu, c.pico
        return self._post("/api/analytics/contagens", {
            "camera_id": self.p["camera_id"], "agente": self.nome,
            "modelo": Path(self.p.get("modelo", "")).name or "yolov10n.onnx",
            "fonte": f"fluxo {self.p.get('fluxo_id', self.p.get('camera_id'))} · {self.nome}", "estado": estado,
            "fps": round(analisados / tempo_s, 2) if tempo_s > 0 else 0.0,
            "quadros": quadros, "entrou": entrou, "saiu": saiu, "pico": pico,
            "janela_inicio": self.inicio_iso, "janela_fim": agora(),
            "caixas": caixas, "linhas": [self.p.get("linha")] if self.p.get("linha") else [],
            "erros": self.erros})

    # ---------------------------------------------------------------- laco
    def rodar(self, fonte: str, duracao: float = 0.0, limite_quadros: int = 0) -> dict:
        import av  # PyAV: decodificacao do fluxo publicado (RTSP/SRT/arquivo)
        self.inicio_iso = agora()
        inicio = time.time()
        quadros = analisados = 0
        ultimo_anuncio = 0.0
        ultimas_caixas: list = []
        estado = "no ar"
        tentativas = 0
        while True:
            try:
                opcoes = {"rtsp_transport": "tcp", "rtsp_flags": "prefer_tcp", "timeout": "5000000"} \
                    if fonte.startswith("rtsp") else {}
                container = av.open(fonte, options=opcoes)
                tentativas = 0
                estado = "no ar"
                if self.contador:
                    self.contador.fps = float(container.streams.video[0].average_rate or 12) or 12
                for quadro in container.decode(video=0):
                    quadros += 1
                    tempo_s = time.time() - inicio
                    if limite_quadros and quadros > limite_quadros:
                        break
                    if (quadros - 1) % self.decimar:
                        continue
                    analisados += 1
                    img = quadro.to_ndarray(format="rgb24")
                    h, w = img.shape[:2]
                    deteccoes = self.detector.detectar(img, self.classes)
                    alvos = self.rastreador.atualizar(deteccoes)
                    eventos = []
                    if self.contador:
                        eventos += self.contador.atualizar(alvos, tempo_s)
                    for z in self.zonas:
                        eventos += z.atualizar(alvos, tempo_s)
                    for ev in eventos:
                        self.eventos_pendentes.append({
                            "tipo": ev["tipo"], "em": agora(), "confianca": ev.get("confianca", 0.0),
                            "metadados": {"alvo": ev.get("alvo"), "zona": ev.get("zona"),
                                          "ponto": [round(v) for v in ev.get("ponto", (0, 0))],
                                          "agente": self.nome}})
                    if eventos:
                        n = self.enviar_eventos()
                        print(f"  evento(s): {[e['tipo'] for e in eventos]} — gravados: {n}")
                    ultimas_caixas = [{"classe": d["nome"], "confianca": round(d["confianca"], 2),
                                       "caixa": [round(d["caixa"][0] / w, 4), round(d["caixa"][1] / h, 4),
                                                 round(d["caixa"][2] / w, 4), round(d["caixa"][3] / h, 4)]}
                                      for d in deteccoes]
                    if tempo_s - ultimo_anuncio >= self.anuncio_s:
                        ultimo_anuncio = tempo_s
                        c = self.contador
                        print(f"  t={tempo_s:6.1f}s quadros={quadros:5d} analisados={analisados:5d} "
                              f"pessoas_agora={len(alvos):2d} entrou={c.entrou if c else 0} saiu={c.saiu if c else 0} "
                              f"pico={c.pico if c else 0}")
                        self.enviar_contagem(quadros, analisados, tempo_s, ultimas_caixas, "no ar")
                    if duracao and tempo_s >= duracao:
                        break
                container.close()
                if duracao and (time.time() - inicio) >= duracao:
                    break
                if limite_quadros and quadros >= limite_quadros:
                    break
                if duracao:
                    continue  # o fluxo terminou antes do tempo: reabre (o publicador esta em laco)
                break
            except Exception as e:  # sem sinal: avisa o servidor e tenta de novo
                tentativas += 1
                self.erros += 1
                estado = "sem sinal"
                print(f"  ! sem sinal ({tentativas}): {e}")
                self.enviar_contagem(quadros, analisados, max(0.1, time.time() - inicio), [], "sem sinal")
                if duracao and (time.time() - inicio) >= duracao:
                    break
                time.sleep(min(10, 2 * tentativas))
        tempo_s = time.time() - inicio
        self.enviar_eventos()
        self.enviar_contagem(quadros, analisados, max(0.1, tempo_s), ultimas_caixas, "parado")
        resumo = {"agente": self.nome, "camera_id": self.p["camera_id"], "fonte": fonte,
                  "segundos": round(tempo_s, 1), "quadros": quadros, "analisados": analisados,
                  "fps_analise": round(analisados / max(0.1, tempo_s), 2),
                  "entrou": self.contador.entrou if self.contador else 0,
                  "saiu": self.contador.saiu if self.contador else 0,
                  "pico": self.contador.pico if self.contador else 0,
                  "erros": self.erros, "terminado_em": agora(), "api": self.api or "(sem api)"}
        print("\nRESUMO", json.dumps(resumo, ensure_ascii=False))
        if self.json_saida:
            self.json_saida.parent.mkdir(parents=True, exist_ok=True)
            with open(self.json_saida, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(resumo, ensure_ascii=False) + "\n")
        return resumo


def principal(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Agente de analise de video do pipeline (Fase 5)")
    ap.add_argument("--perfil", required=True, help="arquivo JSON com camera, modelo, linha e zonas")
    ap.add_argument("--fonte", default="", help="sobrepoe a fonte do perfil (rtsp://... ou arquivo)")
    ap.add_argument("--api", default=os.environ.get("LECSOR_API", "http://127.0.0.1:8765"))
    ap.add_argument("--chave", default=os.environ.get("LECSOR_CHAVE_ANALYTICS", ""))
    ap.add_argument("--nome", default="", help="identificacao do agente (ex.: agente-bordo-01)")
    ap.add_argument("--sem-api", action="store_true", help="nao envia nada: so mede a contagem local")
    ap.add_argument("--duracao", type=float, default=0, help="segundos de execucao (0 = sem limite)")
    ap.add_argument("--quadros", type=int, default=0, help="limite de quadros decodificados")
    ap.add_argument("--json-saida", default="", help="arquivo onde anexar o resumo (uma linha por execucao)")
    args = ap.parse_args(argv)
    perfil = json.loads(Path(args.perfil).read_text(encoding="utf-8"))
    fonte = args.fonte or perfil.get("fonte") or ""
    if not fonte:
        print("informe --fonte ou 'fonte' no perfil"); return 2
    if not args.sem_api and not args.chave:
        print("sem LECSOR_CHAVE_ANALYTICS (ou --chave) a API recusa a ingestao: use --sem-api para medir so a contagem")
        return 2
    agente = Agente(perfil, api=args.api, chave=args.chave, nome=args.nome, sem_api=args.sem_api,
                    json_saida=Path(args.json_saida) if args.json_saida else None)
    agente.rodar(fonte, duracao=args.duracao, limite_quadros=args.quadros)
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
