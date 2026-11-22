"""Chave de licenca do PC de captura (dono, 19/11/2026).

Pedido do dono, VERBATIM: *"quero apenas instalar o app no computador de captura, inserir a chave da
licenca e assim fazer a conexao com a empresa e embarcacao cadastradas, e a licenca pode ser
configuravel por tempo ou indeterminado"*.

Decisoes do dono (19/11/2026), todas registradas aqui porque mandam no desenho:
  * quantos PCs por licenca -> **AJUSTAVEL** (`maquinas_max` e' campo da licenca, por EMBARCACAO);
  * sem internet por dias   -> **MANTEM TUDO NORMALMENTE**: nao existe corte por falta de rede. O
    corte acontece por VENCIMENTO ou REVOGACAO, e so' quando o app consegue falar com o lado terra
    (sem rede ele nem descobre que venceu — e nao para);
  * o token de ingestao continua **UNICO** (a licenca decide o BARCO, nao troca o token);
  * o admin **PODE ver e copiar a chave inteira** depois (por isso ela fica recuperavel no banco do
    lado terra).

Este modulo e' o unico lugar que sabe duas coisas: o FORMATO da chave e onde mora o arquivo do
vinculo no bordo (`<dados>/licenca.json`, ao lado do banco — sobrevive a atualizacao do app).
Quem GERA e quem REVOGA e' o lado terra (tabela `licencas`); o bordo so' guarda a resposta que
recebeu e a revalida de tempos em tempos, sempre por pedido de SAIDA (nunca aceita comando de fora).
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import urllib.error
import urllib.request
import uuid
from pathlib import Path

# Alfabeto sem `I` e sem `O` (os dois que mais se confundem com 1 e 0 digitados a mao), e a
# normalizacao troca as letras parecidas pelo digito: quem digitar `O` esta' querendo `0`.
ALFABETO = "0123456789ABCDEFGHJKLMNPQRSTUVWXYZ"
TROCA = {"I": "1", "O": "0", "L": "1"}
GRUPOS, POR_GRUPO = 4, 4
TAMANHO = GRUPOS * POR_GRUPO          # 16 caracteres, 34^16 ~ 2^81: nao se adivinha por tentativa
VAR_ARQUIVO = "LECSOR_LICENCA"


def _limpo(texto: str) -> str:
    """So' o que a chave usa, em maiuscula, com as parecidas trocadas pelo digito."""
    saida = []
    for c in str(texto or "").upper():
        if c in TROCA:
            c = TROCA[c]
        if c in ALFABETO:
            saida.append(c)
    return "".join(saida)


def formatar(texto: str) -> str:
    """Junta de novo em `XXXX-XXXX-XXXX-XXXX` (o formato que o dono pediu para ler/ditar)."""
    limpo = _limpo(texto)
    return "-".join(limpo[i:i + POR_GRUPO] for i in range(0, len(limpo), POR_GRUPO))


def normalizar(texto: str) -> str:
    """Chave canonica (com os tracos) ou `""` quando nao tem o tamanho certo."""
    limpo = _limpo(texto)
    return formatar(limpo) if len(limpo) == TAMANHO else ""


def parece_chave(texto: str) -> bool:
    return bool(normalizar(texto))


def gerar() -> str:
    """Uma chave nova. `uuid4` (128 bits de aleatorio do sistema) e' cortado no tamanho da chave."""
    import secrets

    limpo = "".join(secrets.choice(ALFABETO) for _ in range(TAMANHO))
    return formatar(limpo)


def pegada(chave: str) -> str:
    """Impressao da chave para procurar/auditar SEM precisar guardar a chave (nunca vai o valor)."""
    return hashlib.sha256(normalizar(chave).encode("utf-8")).hexdigest()[:16]


def ultimos4(chave: str) -> str:
    limpo = _limpo(chave)
    return limpo[-4:] if limpo else ""


# --------------------------------------------------------------------------------------------------
# Maquina de captura: identificacao estavel, sem identificar pessoa (hostname + MAC hasheado).
# --------------------------------------------------------------------------------------------------

def maquina() -> str:
    try:
        nome = socket.gethostname()
    except Exception:  # noqa: BLE001
        nome = "pc"
    try:
        serial = f"{uuid.getnode():012x}"
    except Exception:  # noqa: BLE001
        serial = "sem-mac"
    return f"{nome}-{hashlib.sha256(serial.encode('utf-8')).hexdigest()[:8]}"


# --------------------------------------------------------------------------------------------------
# O arquivo do vinculo no bordo.
# --------------------------------------------------------------------------------------------------

def caminho() -> Path:
    """Onde mora o vinculo desta maquina.

    `LECSOR_LICENCA` manda (a bancada e as provas apontam para uma pasta temporaria); sem ele, e' ao
    lado do banco do app (`LECSOR_BANCO`) — a pasta do usuario, que sobrevive a atualizacao.
    """
    da_variavel = (os.environ.get(VAR_ARQUIVO) or "").strip()
    if da_variavel:
        return Path(da_variavel)
    try:
        from ferramentas import caminho_banco

        return caminho_banco().parent / "licenca.json"
    except Exception:  # noqa: BLE001
        return Path(__file__).resolve().parent.parent / "db" / "licenca.json"


def ler() -> dict:
    """O vinculo guardado nesta maquina (vazio quando o app ainda nao foi ativado)."""
    caminho_arquivo = caminho()
    try:
        dados = json.loads(caminho_arquivo.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    if not isinstance(dados, dict) or not normalizar(dados.get("chave", "")):
        return {}
    dados["chave"] = normalizar(dados["chave"])
    return dados


def gravar(dados: dict) -> dict:
    """Grava o vinculo local. Nada aqui e' segredo de camera: e' a chave de PRODUTO desta maquina."""
    arquivo = caminho()
    guardado = dict(dados or {})
    if guardado.get("chave"):
        guardado["chave"] = normalizar(guardado["chave"])
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    arquivo.write_text(json.dumps(guardado, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return guardado


def apagar() -> bool:
    """Esquece o vinculo desta maquina (o admin faz isso pela tela, nunca o cliente)."""
    arquivo = caminho()
    try:
        arquivo.unlink()
        return True
    except FileNotFoundError:
        return False
    except Exception:  # noqa: BLE001
        return False


def embarcacao() -> str:
    """A embarcacao DESTA maquina: a da licenca quando existe, senao a do pacote (`ambiente.json`).

    E' a fonte unica usada por tudo o que precisa saber "de que barco esta' maquina e'": a varredura
    que cadastra a camera, o repasse do cadastro, a telemetria e o agente de ordens. Instalacao
    antiga (sem licenca) continua valendo pela variavel de ambiente — nada e' apagado nem quebra.
    """
    lic = ler()
    if lic.get("embarcacao_id"):
        return str(lic["embarcacao_id"]).strip()
    return (os.environ.get("LECSOR_EMBARCACAO") or "").strip()


# --------------------------------------------------------------------------------------------------
# Estado da licenca (o que a tela mostra e o que decide parar a transmissao).
# --------------------------------------------------------------------------------------------------

def vencida(validade_tipo: str, validade_em: str, agora_iso: str = "") -> bool:
    """Licenca `ate <data>` vencida? `indeterminada` nunca vence (dono: "configuravel por tempo ou
    indeterminado"). A data e' comparada por dia (`AAAA-MM-DD`): vence no fim do dia combinado."""
    if str(validade_tipo or "").strip().lower() != "ate":
        return False
    limite = str(validade_em or "").strip()[:10]
    if not limite:
        return False
    hoje = (agora_iso or "")[:10] or _hoje()
    return limite < hoje


def _hoje() -> str:
    import datetime as dt

    return dt.datetime.now(dt.timezone.utc).date().isoformat()


def dias_para_vencer(validade_tipo: str, validade_em: str) -> int | None:
    """Quantos dias faltam para vencer (`None` = indeterminada) — a tela avisa antes."""
    if str(validade_tipo or "").strip().lower() != "ate":
        return None
    limite = str(validade_em or "").strip()[:10]
    if not limite:
        return None
    import datetime as dt

    try:
        fim = dt.date.fromisoformat(limite)
    except ValueError:
        return None
    return (fim - dt.date.fromisoformat(_hoje())).days


def estado(validade_tipo: str, validade_em: str, status: str, motivo: str = "") -> dict:
    """O estado em uma palavra, com o texto pronto para a tela."""
    if str(status or "ativa").strip().lower() == "revogada":
        return {"estado": "revogada", "bloqueada": True,
                "texto": "licença revogada" + (f" ({motivo})" if motivo else "") +
                         " — fale com a LECSOR para liberar de novo"}
    if vencida(validade_tipo, validade_em):
        return {"estado": "vencida", "bloqueada": True,
                "texto": f"licença vencida em {str(validade_em or '')[:10]} — fale com a LECSOR"}
    faltam = dias_para_vencer(validade_tipo, validade_em)
    return {"estado": "ativa", "bloqueada": False, "dias_para_vencer": faltam,
            "texto": ("licença sem prazo (indeterminada)" if faltam is None
                      else f"licença ativa — vence em {faltam} dia(s)")}


def resumo() -> dict:
    """O que ESTA maquina tem guardado, sem precisar de rede (a tela abre offline e diz a verdade)."""
    lic = ler()
    if not lic:
        return {"tem": False, "ativada": False, "chave": "", "embarcacao_id": "",
                "texto": "esta máquina ainda não foi ativada"}
    st = estado(lic.get("validade_tipo", "indeterminada"), lic.get("validade_em", ""),
                lic.get("status", "ativa"), lic.get("motivo", ""))
    return {"tem": True, "ativada": True, "chave": lic.get("chave", ""),
            "chave_ultimos4": ultimos4(lic.get("chave", "")),
            "embarcacao_id": lic.get("embarcacao_id", ""),
            "embarcacao_nome": lic.get("embarcacao_nome", ""),
            "cliente_id": lic.get("cliente_id", ""), "cliente_nome": lic.get("cliente_nome", ""),
            "validade_tipo": lic.get("validade_tipo", "indeterminada"),
            "validade_em": lic.get("validade_em", ""),
            "maquina": lic.get("maquina", "") or maquina(),
            "ativada_em": lic.get("ativada_em", ""), "origem": lic.get("origem", "terra"),
            **st}


# --------------------------------------------------------------------------------------------------
# Falar com o lado terra (sempre SAIDA: o bordo pergunta, terra responde).
# --------------------------------------------------------------------------------------------------

def base_do_terra(destino: str = "") -> str:
    """Endereco HTTP do lado terra — a mesma conta que o repasse usa, para nao existir duas."""
    try:
        from repasse import _api_lado_terra  # noqa: PLC0415

        return _api_lado_terra(destino or (os.environ.get("LECSOR_DESTINO_SRT") or ""))
    except Exception:  # noqa: BLE001
        return (os.environ.get("LECSOR_LADO_TERRA_API") or "").strip().rstrip("/")


def pedir_ao_terra(caminho_rota: str, corpo: dict, segundos: int = 15) -> dict:
    """POST para o lado terra. Devolve sempre um dicionario: `{"ok": False, "motivo": ...}` sem rede.

    Sem internet NAO e' erro fatal nesta funcao: o chamador decide. Regra do dono (19/11/2026):
    "mante'm tudo normalmente" — o bordo nao para por falta de rede.
    """
    base = base_do_terra()
    if not base:
        return {"ok": False, "motivo": "sem endereço do lado terra configurado",
                "sem_rede": True}
    req = urllib.request.Request(f"{base}{caminho_rota}", data=json.dumps(corpo).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=segundos) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read() or b"{}")
        except Exception:  # noqa: BLE001
            return {"ok": False, "motivo": f"lado terra respondeu {e.code}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "motivo": f"nao falei com o lado terra ({type(e).__name__})",
                "sem_rede": True, "detalhe": str(e)}
