"""Login pelo Supabase Auth com os MESMOS usuarios e senha que o app ja usa.

O navegador nunca fala com o Supabase — quem conversa e este modulo, no servidor:
chave anonima para conferir a senha (`token?grant_type=password`) e chave de servico
para criar/listar usuarios. Nenhum valor de segredo entra em log ou em resposta.

Variaveis de ambiente:
    LECSOR_SUPABASE_URL          https://<ref>.supabase.co
    LECSOR_SUPABASE_ANON_KEY     chave publica (so no servidor)
    LECSOR_SUPABASE_SERVICE_KEY  chave de servico (so no servidor, usada para criar usuario)
"""

import json
import os
import urllib.error
import urllib.request

TEMPO_PADRAO = 8.0


def _url() -> str:
    return (os.environ.get("LECSOR_SUPABASE_URL") or "").rstrip("/")


def _anon() -> str:
    return os.environ.get("LECSOR_SUPABASE_ANON_KEY") or ""


def _servico() -> str:
    return os.environ.get("LECSOR_SUPABASE_SERVICE_KEY") or ""


def configurado() -> bool:
    """Login pelo Supabase existe quando a URL e a chave anonima estao no ambiente."""
    return bool(_url() and _anon())


def _pedido(caminho: str, corpo: dict | None, chave: str, metodo: str = "POST", tempo: float = TEMPO_PADRAO):
    dados = json.dumps(corpo).encode() if corpo is not None else None
    pedido = urllib.request.Request(
        _url() + caminho, data=dados, method=metodo,
        headers={"apikey": chave, "Authorization": f"Bearer {chave}",
                 "Content-Type": "application/json", "Accept": "application/json"})
    with urllib.request.urlopen(pedido, timeout=tempo) as r:
        return json.loads(r.read().decode() or "{}")


def entrar(email: str, senha: str, tempo: float = TEMPO_PADRAO) -> dict | None:
    """Confere e-mail e senha no Supabase Auth.

    Devolve `None` quando o Supabase nao esta configurado ou nao respondeu (rede fora) —
    quem chamou decide cair no hash local. Devolve `{"ok": False}` quando o Supabase
    RESPONDEU que a credencial nao vale (senha trocada la vale aqui tambem).
    """
    if not configurado():
        return None
    try:
        d = _pedido("/auth/v1/token?grant_type=password",
                    {"email": email, "password": senha}, _anon(), tempo=tempo)
    except urllib.error.HTTPError as e:
        if e.code in (400, 401, 403, 422):
            return {"ok": False, "erro": "e-mail ou senha invalidos", "codigo": e.code}
        return None
    except Exception:
        return None
    u = d.get("user") or {}
    return {"ok": True, "id": u.get("id"), "email": (u.get("email") or email).lower()}


def id_por_email(email: str, tempo: float = TEMPO_PADRAO) -> str | None:
    """Id do usuario no Supabase Auth (ou None se nao existir)."""
    if not (_url() and _servico()):
        return None
    alvo = email.strip().lower()
    for pagina in range(1, 21):
        try:
            d = _pedido(f"/auth/v1/admin/users?page={pagina}&per_page=200", None, _servico(),
                        metodo="GET", tempo=tempo)
        except Exception:
            return None
        usuarios = d.get("users") or []
        for u in usuarios:
            if (u.get("email") or "").strip().lower() == alvo:
                return u.get("id")
        if len(usuarios) < 200:
            return None
    return None


def criar_usuario(email: str, senha: str, nome: str = "", tempo: float = TEMPO_PADRAO) -> dict:
    """Cria o usuario com a MESMA senha do app. Idempotente: se ja existe, devolve o id.

    Nao imprime nem devolve a senha — so o id e o e-mail.
    """
    if not (_url() and _servico()):
        raise RuntimeError("faltam LECSOR_SUPABASE_URL / LECSOR_SUPABASE_SERVICE_KEY")
    alvo = email.strip().lower()
    corpo = {"email": alvo, "password": senha, "email_confirm": True,
             "user_metadata": {"nome": nome or alvo}}
    try:
        u = _pedido("/auth/v1/admin/users", corpo, _servico(), tempo=tempo)
        return {"id": u.get("id"), "email": (u.get("email") or alvo).lower(), "criado": True}
    except urllib.error.HTTPError as e:
        if e.code not in (409, 422):
            raise
        existente = id_por_email(alvo, tempo=tempo)
        if not existente:
            raise
        return {"id": existente, "email": alvo, "criado": False}


__all__ = ["configurado", "entrar", "criar_usuario", "id_por_email"]
