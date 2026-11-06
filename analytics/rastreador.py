"""Rastreio e contagem.

- `Rastreador`: associa deteccoes a identidades por sobreposicao (IoU) e distancia de centro;
  mantem o id por alguns quadros sem deteccao para nao contar a mesma pessoa duas vezes.
- `ContadorLinha`: conta travessias de uma linha com **histerese** — a pessoa precisa estar
  de um lado, cruzar e permanecer do outro lado por N quadros — e um **tempo de espera** por id,
  para que ruido de deteccao nao vire entrada ou saida.
- `ZonaRisco`: gera evento quando a pessoa permanece D segundos dentro de uma zona.
"""
from __future__ import annotations

from dataclasses import dataclass, field


def iou(a, b) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    inter = (ix2 - ix1) * (iy2 - iy1)
    area_a = (ax2 - ax1) * (ay2 - ay1)
    area_b = (bx2 - bx1) * (by2 - by1)
    return inter / max(1e-6, area_a + area_b - inter)


def centro(caixa):
    x1, y1, x2, y2 = caixa
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


@dataclass
class Alvo:
    id: int
    caixa: tuple
    classe: int
    confianca: float
    perdido: int = 0
    quadros: int = 1
    historico: list = field(default_factory=list)


class Rastreador:
    def __init__(self, iou_minimo: float = 0.25, distancia_maxima: float = 120.0, quadros_sem_ver: int = 12):
        self.iou_minimo = iou_minimo
        self.distancia_maxima = distancia_maxima
        self.quadros_sem_ver = quadros_sem_ver
        self.alvos: dict[int, Alvo] = {}
        self.proximo_id = 1

    def atualizar(self, deteccoes: list[dict]) -> list[Alvo]:
        usados = set()
        for alvo in self.alvos.values():
            melhor, nota = None, -1.0
            cx, cy = centro(alvo.caixa)
            for i, d in enumerate(deteccoes):
                if i in usados or d["classe"] != alvo.classe:
                    continue
                sobreposicao = iou(alvo.caixa, d["caixa"])
                if sobreposicao < self.iou_minimo:
                    continue
                dx, dy = centro(d["caixa"])
                distancia = ((cx - dx) ** 2 + (cy - dy) ** 2) ** 0.5
                if distancia > self.distancia_maxima:
                    continue
                nota_atual = sobreposicao + max(0.0, 1.0 - distancia / self.distancia_maxima)
                if nota_atual > nota:
                    melhor, nota = i, nota_atual
            if melhor is None:
                alvo.perdido += 1
                continue
            usados.add(melhor)
            d = deteccoes[melhor]
            alvo.caixa, alvo.classe, alvo.confianca = d["caixa"], d["classe"], d["confianca"]
            alvo.perdido = 0
            alvo.quadros += 1
            alvo.historico.append(centro(d["caixa"]))
            if len(alvo.historico) > 120:
                alvo.historico.pop(0)
        for i, d in enumerate(deteccoes):
            if i in usados:
                continue
            alvo = Alvo(self.proximo_id, d["caixa"], d["classe"], d["confianca"], historico=[centro(d["caixa"])])
            self.alvos[alvo.id] = alvo
            self.proximo_id += 1
        for ident in [k for k, v in self.alvos.items() if v.perdido > self.quadros_sem_ver]:
            del self.alvos[ident]
        return list(self.alvos.values())


class ContadorLinha:
    """Conta travessias de uma linha horizontal ou vertical, com histerese e espera por id."""

    def __init__(self, ponto_a, ponto_b, quadros_de_confirmacao: int = 3, espera_s: float = 1.5,
                 fps: float = 12.0, sentido_positivo: str = "entrada"):
        self.a, self.b = ponto_a, ponto_b
        self.quadros_de_confirmacao = quadros_de_confirmacao
        self.espera_s = espera_s
        self.fps = fps
        self.sentido_positivo = sentido_positivo
        self.entrou = 0
        self.saiu = 0
        self.pico = 0
        self._lado: dict[int, int] = {}
        self._candidato: dict[int, tuple] = {}
        self._ultima_contagem: dict[int, float] = {}
        self._dentro: set[int] = set()
        self._ultimo_visto: dict[int, float] = {}
        self.esquecimento_s = 10.0   # id sem ser visto por tanto tempo sai da conta (nao infla o pico)

    def _lado_de(self, ponto) -> int:
        (x1, y1), (x2, y2) = self.a, self.b
        # sinal do produto vetorial: > 0 de um lado, < 0 do outro
        v = (x2 - x1) * (ponto[1] - y1) - (y2 - y1) * (ponto[0] - x1)
        return 1 if v > 0 else (-1 if v < 0 else 0)

    def atualizar(self, alvos: list[Alvo], tempo_s: float) -> list[dict]:
        eventos = []
        vistos = set()
        for alvo in alvos:
            vistos.add(alvo.id)
            self._ultimo_visto[alvo.id] = tempo_s
            ponto = centro(alvo.caixa)
            lado = self._lado_de(ponto)
            if lado == 0:
                continue
            anterior = self._lado.get(alvo.id)
            if anterior is None:
                self._lado[alvo.id] = lado
                if lado > 0:
                    self._dentro.add(alvo.id)
                self.pico = max(self.pico, len(self._dentro))
                continue
            if lado == anterior:
                self._candidato.pop(alvo.id, None)
                continue
            # trocou de lado: exige confirmacao em quadros seguidos
            candidato = self._candidato.get(alvo.id)
            if candidato is None or candidato[0] != lado:
                self._candidato[alvo.id] = (lado, 1)
                continue
            quadros = candidato[1] + 1
            self._candidato[alvo.id] = (lado, quadros)
            if quadros < self.quadros_de_confirmacao:
                continue
            ultima = self._ultima_contagem.get(alvo.id, -999.0)
            if tempo_s - ultima < self.espera_s:
                continue
            self._ultima_contagem[alvo.id] = tempo_s
            self._lado[alvo.id] = lado
            self._candidato.pop(alvo.id, None)
            if lado > 0:
                tipo = "entrada" if self.sentido_positivo == "entrada" else "saida"
                self._dentro.add(alvo.id)
            else:
                tipo = "saida" if self.sentido_positivo == "entrada" else "entrada"
                self._dentro.discard(alvo.id)
            if tipo == "entrada":
                self.entrou += 1
            else:
                self.saiu += 1
            self.pico = max(self.pico, len(self._dentro))
            eventos.append({"tipo": tipo, "alvo": alvo.id, "confianca": alvo.confianca,
                            "ponto": ponto, "em": round(tempo_s, 3)})
        # id que sumiu do video nao pode continuar contando no pico
        for ident in [k for k, visto_em in self._ultimo_visto.items()
                      if tempo_s - visto_em > self.esquecimento_s]:
            self._lado.pop(ident, None)
            self._dentro.discard(ident)
            self._candidato.pop(ident, None)
            self._ultimo_visto.pop(ident, None)
        self.pico = max(self.pico, len(self._dentro))
        return eventos


class ZonaRisco:
    """Evento de permanencia: dispara quando a pessoa fica D segundos dentro do poligono."""

    def __init__(self, nome: str, poligono, segundos: float = 3.0, espera_s: float = 30.0):
        self.nome = nome
        self.poligono = poligono
        self.segundos = segundos
        self.espera_s = espera_s
        self._inicio: dict[int, float] = {}
        self._ultimo_evento: dict[int, float] = {}

    def _dentro(self, ponto) -> bool:
        x, y = ponto
        dentro = False
        n = len(self.poligono)
        for i in range(n):
            x1, y1 = self.poligono[i]
            x2, y2 = self.poligono[(i + 1) % n]
            if (y1 > y) != (y2 > y):
                xint = (x2 - x1) * (y - y1) / (y2 - y1) + x1
                if x < xint:
                    dentro = not dentro
        return dentro

    def atualizar(self, alvos: list[Alvo], tempo_s: float) -> list[dict]:
        eventos = []
        vistos = set()
        for alvo in alvos:
            vistos.add(alvo.id)
            dentro = self._dentro(centro(alvo.caixa))
            if not dentro:
                self._inicio.pop(alvo.id, None)
                continue
            inicio = self._inicio.setdefault(alvo.id, tempo_s)
            if tempo_s - inicio < self.segundos:
                continue
            if tempo_s - self._ultimo_evento.get(alvo.id, -999.0) < self.espera_s:
                continue
            self._ultimo_evento[alvo.id] = tempo_s
            eventos.append({"tipo": "zona_risco", "alvo": alvo.id, "zona": self.nome,
                            "confianca": alvo.confianca, "em": round(tempo_s, 3)})
        for ident in list(self._inicio):
            if ident not in vistos:
                self._inicio.pop(ident, None)
        return eventos
