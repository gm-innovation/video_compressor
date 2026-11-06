"""Deteccao de objetos com um modelo ONNX (YOLOv10n, saida ja pos-NMS).

Nao depende de torch nem de OpenCV: decodificacao por PyAV e inferencia por onnxruntime.
O modelo vive em analytics/modelos/ (fora do git) e o perfil diz qual usar.
"""
from __future__ import annotations

import numpy as np
import onnxruntime as ort

# classes COCO de interesse por padrao
PESSOA = 0
CLASSES_COCO = {0: "pessoa", 1: "bicicleta", 2: "carro", 3: "moto", 5: "onibus", 7: "caminhao", 67: "celular"}


class Detector:
    """Carrega o ONNX e devolve caixas em pixels do quadro original."""

    def __init__(self, caminho_modelo: str, tamanho: int = 640, confianca: float = 0.35, provedores=None):
        self.tamanho = tamanho
        self.confianca = confianca
        self.sessao = ort.InferenceSession(str(caminho_modelo), providers=provedores or ["CPUExecutionProvider"])
        self.entrada = self.sessao.get_inputs()[0].name
        self.forma = self.sessao.get_inputs()[0].shape  # [1,3,t,t]

    def _letra_caixa(self, quadro: np.ndarray):
        """Redimensiona preservando a proporcao e completa com cinza (letterbox)."""
        h, w = quadro.shape[:2]
        escala = min(self.tamanho / h, self.tamanho / w)
        nh, nw = max(1, int(round(h * escala))), max(1, int(round(w * escala)))
        tela = np.full((self.tamanho, self.tamanho, 3), 114, np.uint8)
        # reamostragem bilinear por indices (sem OpenCV)
        yi = np.linspace(0, h - 1, nh)
        xi = np.linspace(0, w - 1, nw)
        y0 = np.floor(yi).astype(int); y1 = np.minimum(y0 + 1, h - 1); fy = (yi - y0)[:, None, None]
        x0 = np.floor(xi).astype(int); x1 = np.minimum(x0 + 1, w - 1); fx = (xi - x0)[None, :, None]
        topo = quadro[y0][:, x0] * (1 - fx) + quadro[y0][:, x1] * fx
        baixo = quadro[y1][:, x0] * (1 - fx) + quadro[y1][:, x1] * fx
        red = (topo * (1 - fy) + baixo * fy).astype(np.uint8)
        desloc_y, desloc_x = (self.tamanho - nh) // 2, (self.tamanho - nw) // 2
        tela[desloc_y:desloc_y + nh, desloc_x:desloc_x + nw] = red
        return tela, escala, desloc_x, desloc_y

    def detectar(self, quadro: np.ndarray, classes=None) -> list[dict]:
        tela, escala, dx, dy = self._letra_caixa(quadro)
        x = np.transpose(tela.astype(np.float32) / 255.0, (2, 0, 1))[None]
        saida = self.sessao.run(None, {self.entrada: x})[0][0]  # [N, 6] = x1,y1,x2,y2,score,classe
        h, w = quadro.shape[:2]
        achados = []
        for bx1, by1, bx2, by2, score, classe in saida:
            if score < self.confianca:
                continue
            classe = int(classe)
            if classes is not None and classe not in classes:
                continue
            cx1 = float(np.clip((bx1 - dx) / escala, 0, w))
            cy1 = float(np.clip((by1 - dy) / escala, 0, h))
            cx2 = float(np.clip((bx2 - dx) / escala, 0, w))
            cy2 = float(np.clip((by2 - dy) / escala, 0, h))
            if cx2 - cx1 < 4 or cy2 - cy1 < 4:
                continue
            achados.append({"classe": classe, "nome": CLASSES_COCO.get(classe, str(classe)),
                            "confianca": float(score), "caixa": (cx1, cy1, cx2, cy2)})
        return achados
