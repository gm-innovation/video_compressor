#!/usr/bin/env python3
"""Prova: o Admin LIBERA as funcoes de captura sem virar o app de captura (dono, 16/11/2026).

Pedido do dono, verbatim: "sim, mas deve liberar as funcoes de captura, nao mudar para o app de
captura. nao existe 'as duas unicas opcoes...' estamos desenvolvendo o produto, nos criamos as opcoes".

O que esta prova mede (nada de "deve funcionar"):

  1) `ground/api.py` responde CORS SO' nas rotas de captura e SO' para as origens declaradas — servidor
     de verdade na porta livre, requisicao de verdade, cabecalho lido da resposta de verdade;
  2) `desktop/configuracao.js` NAO troca a base (as telas) quando `capturaLocal` esta ligado: o Admin
     continua no lado terra, logado; o pacote do tecnico a bordo continua igual ao de antes;
  3) as rotas da tela "Enviar video" do Admin (dispositivos, ingestao, compressao, envios) sao de
     captura; as de cadastro/login (`/api/entrar`, `/api/eu`, `/api/cameras`, `/api/usuarios`) NAO sao;
  4) o aplicativo diz a interface para onde ir (`preload.js` -> `enderecoDaCaptura`) e a tela roteia
     (`admin.js` -> `urlDeCaptura`/`fetchCaptura`), com os nomes certos: "Enviar video" e'
     "Teste de video (bancada)".

Uso: python tests/test_captura_no_admin.py     (ou: python -m unittest tests.test_captura_no_admin)
"""
from __future__ import annotations
import importlib.util
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
TERRA = "http://187.127.60.250:8085"
INVASOR = "http://invasor.example"


def porta_livre() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    porta = s.getsockname()[1]
    s.close()
    return porta


def carrega_api():
    """Importa `ground/api.py` como modulo (nao sobe servidor: `principal()` e' so' no __main__)."""
    spec = importlib.util.spec_from_file_location("api_do_produto", RAIZ / "ground" / "api.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def pede(url: str, origem: str | None = None, metodo: str = "GET") -> tuple:
    req = urllib.request.Request(url, method=metodo)
    if origem:
        req.add_header("Origin", origem)
        if metodo == "OPTIONS":
            req.add_header("Access-Control-Request-Method", "GET")
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}


class CORSDeVerdade(unittest.TestCase):
    """Servidor de verdade na porta livre: o cabecalho tem de estar — ou nao estar — na resposta."""

    @classmethod
    def setUpClass(cls):
        cls.porta = porta_livre()
        cls.tmp = tempfile.TemporaryDirectory(prefix="prova-captura-admin-")
        env = dict(os.environ)
        env["LECSOR_BANCO"] = str(Path(cls.tmp.name) / "banco.db")
        env["LECSOR_BIND"] = "127.0.0.1"
        env["LECSOR_CORS_ORIGENS"] = ""      # vazio: volta para a lista de fabrica do produto
        env.pop("LECSOR_CORS_ORIGENS")
        cls.log = open(Path(cls.tmp.name) / "api.log", "w", encoding="utf-8")
        cls.proc = subprocess.Popen([sys.executable, str(RAIZ / "ground" / "api.py"), str(cls.porta)],
                                    cwd=str(RAIZ), env=env, stdout=cls.log, stderr=subprocess.STDOUT)
        cls.base = f"http://127.0.0.1:{cls.porta}"
        limite = time.time() + 40
        while time.time() < limite:
            try:
                if pede(cls.base + "/api/saude")[0] == 200:
                    return
            except Exception:
                pass
            time.sleep(0.5)
        cls.log.flush()
        raise AssertionError("o servidor local nao subiu em 40 s: " +
                             (Path(cls.tmp.name) / "api.log").read_text(encoding="utf-8", errors="replace")[-1500:])

    @classmethod
    def tearDownClass(cls):
        try:
            cls.proc.terminate()
            cls.proc.wait(timeout=10)
        except Exception:
            try:
                cls.proc.kill()
            except Exception:
                pass
        try:
            cls.log.close()
            cls.tmp.cleanup()
        except Exception:
            pass

    def test_01_pre_voo_de_origem_declarada_responde(self):
        codigo, cab = pede(self.base + "/api/dispositivos", origem=TERRA, metodo="OPTIONS")
        self.assertEqual(codigo, 204)
        self.assertEqual(cab.get("access-control-allow-origin"), TERRA)
        self.assertIn("POST", cab.get("access-control-allow-methods", ""))

    def test_02_pre_voo_de_origem_nao_declarada_nao_responde(self):
        codigo, cab = pede(self.base + "/api/dispositivos", origem=INVASOR, metodo="OPTIONS")
        self.assertEqual(codigo, 204)
        self.assertNotIn("access-control-allow-origin", cab, "origem nao declarada recebeu CORS")

    def test_03_leitura_de_rota_de_captura_tem_cors(self):
        codigo, cab = pede(self.base + "/api/dispositivos", origem=TERRA)
        self.assertEqual(codigo, 200)
        self.assertEqual(cab.get("access-control-allow-origin"), TERRA)

    def test_04_rota_de_cadastro_nao_tem_cors(self):
        codigo, cab = pede(self.base + "/api/eu", origem=TERRA)
        self.assertEqual(codigo, 200)
        self.assertNotIn("access-control-allow-origin", cab, "rota de cadastro/login ganhou CORS")

    def test_05_pre_voo_em_rota_de_cadastro_e_recusado(self):
        self.assertEqual(pede(self.base + "/api/eu", metodo="OPTIONS")[0], 405)

    def test_06_sem_origem_nao_manda_cors(self):
        codigo, cab = pede(self.base + "/api/dispositivos")
        self.assertEqual(codigo, 200)
        self.assertNotIn("access-control-allow-origin", cab)

    def test_07_origem_loopback_declarada_e_aceita(self):
        codigo, cab = pede(self.base + "/api/dispositivos", origem="http://localhost:8765")
        self.assertEqual(codigo, 200)
        self.assertEqual(cab.get("access-control-allow-origin"), "http://localhost:8765")


class RotasDeCaptura(unittest.TestCase):
    """A lista de rotas e' a fronteira: captura sim, cadastro/login nunca."""

    @classmethod
    def setUpClass(cls):
        cls.api = carrega_api()

    def test_rotas_da_tela_enviar_video_sao_de_captura(self):
        for rota in ("/api/dispositivos", "/api/envios/destino", "/api/ingestao/comprimir",
                     "/api/ingestao/ao-vivo", "/api/ingestoes", "/api/compressoes",
                     "/api/compressao/publicar", "/api/medicoes"):
            self.assertTrue(self.api.eh_rota_de_captura(rota), f"faltou rota de captura: {rota}")

    def test_rotas_de_cadastro_e_login_nao_sao_de_captura(self):
        for rota in ("/api/entrar", "/api/eu", "/api/cameras", "/api/usuarios", "/api/clientes",
                     "/api/primeiro-acesso", "/api/fluxos"):
            self.assertFalse(self.api.eh_rota_de_captura(rota), f"cadastro virou captura: {rota}")

    def test_nada_de_origem_aberta(self):
        self.assertNotIn("*", self.api.origens_captura())
        self.assertIn(TERRA, self.api.origens_captura())


class ConfiguracaoNaoTrocaOAplicativo(unittest.TestCase):
    """Ligar a captura NAO pode mexer nas telas: era o que jogava o login no banco local vazio."""

    @classmethod
    def setUpClass(cls):
        cls.node = subprocess.run(["node", "--version"], capture_output=True, text=True).returncode == 0

    def _resolver(self, script: str) -> dict:
        caminho = RAIZ / "desktop" / "configuracao.js"
        programa = f"""
        const {{resolver}} = require({json.dumps(str(caminho))});
        const PADRAO = {{base:'http://187.127.60.250:8085', destinoSrt:'187.127.60.250:8890',
          abrirAoIniciar:['admin'], servidorLocal:{{ligado:false, repo:'', portaApi:8765}}}};
        const PAPEIS = {{
          terra: {{base:'http://187.127.60.250:8085', destinoSrt:'187.127.60.250:8890'}},
          captura: {{base:'http://127.0.0.1:8765', destinoSrt:'187.127.60.250:8890', servidorLocal:{{ligado:true}}}}
        }};
        const r = resolver(PADRAO, PAPEIS, 'terra', {script});
        console.log(JSON.stringify({{base: r.config.base, corrigido: r.corrigido,
          ligado: !!r.config.servidorLocal.ligado, capturaLocal: r.config.capturaLocal || null,
          destinoSrt: r.config.destinoSrt || null}}));
        """
        r = subprocess.run(["node", "-e", programa], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_captura_liberada_mantem_as_telas_no_lado_terra(self):
        if not self.node:
            self.skipTest("node ausente")
        d = self._resolver("{papel:'terra', base:'http://187.127.60.250:8085', capturaLocal:true,"
                           " servidorLocal:{ligado:true, portaApi:8765}}")
        self.assertEqual(d["base"], TERRA, "as telas sairam do lado terra (voltaria a tela 'primeiro acesso')")
        self.assertTrue(d["ligado"])
        self.assertFalse(d["corrigido"])

    def test_servidor_local_sem_captura_continua_igual_ao_de_antes(self):
        if not self.node:
            self.skipTest("node ausente")
        d = self._resolver("{papel:'terra', base:'http://187.127.60.250:8085',"
                           " servidorLocal:{ligado:true, portaApi:8765}}")
        self.assertEqual(d["base"], "http://127.0.0.1:8765")

    def test_pacote_do_tecnico_a_bordo_continua_apontando_para_o_servidor_local(self):
        if not self.node:
            self.skipTest("node ausente")
        caminho = RAIZ / "desktop" / "configuracao.js"
        programa = f"""
        const {{resolver}} = require({json.dumps(str(caminho))});
        const PADRAO = {{base:'http://187.127.60.250:8085', destinoSrt:'187.127.60.250:8890',
          servidorLocal:{{ligado:false, portaApi:8765}}}};
        const PAPEIS = {{captura: {{base:'http://127.0.0.1:8765', servidorLocal:{{ligado:true}}}}}};
        const r = resolver(PADRAO, PAPEIS, 'captura', {{papel:'captura', servidorLocal:{{ligado:true}}}});
        console.log(JSON.stringify({{base: r.config.base}}));
        """
        r = subprocess.run(["node", "-e", programa], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        self.assertEqual(json.loads(r.stdout.strip().splitlines()[-1])["base"], "http://127.0.0.1:8765")

    def test_captura_local_nao_e_herdada_de_outro_papel(self):
        if not self.node:
            self.skipTest("node ausente")
        caminho = RAIZ / "desktop" / "configuracao.js"
        programa = f"""
        const {{resolver}} = require({json.dumps(str(caminho))});
        const PADRAO = {{base:'http://187.127.60.250:8085', servidorLocal:{{ligado:false, portaApi:8765}}}};
        const PAPEIS = {{terra: {{base:'http://187.127.60.250:8085'}}}};
        const r = resolver(PADRAO, PAPEIS, 'terra',
          {{papel:'captura', capturaLocal:true, base:'http://127.0.0.1:8765', servidorLocal:{{ligado:true}}}});
        console.log(JSON.stringify({{capturaLocal: r.config.capturaLocal || null, base: r.config.base}}));
        """
        r = subprocess.run(["node", "-e", programa], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        d = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertIsNone(d["capturaLocal"], "estado de captura de outro papel foi herdado")
        self.assertEqual(d["base"], TERRA)


class AplicativoEAvisarATela(unittest.TestCase):
    """O menu cria a opcao, o preload entrega o endereco e a tela roteia — os tres, no codigo."""

    def ler(self, rel: str) -> str:
        return (RAIZ / rel).read_text(encoding="utf-8")

    def test_preload_entrega_o_endereco_da_captura(self):
        s = self.ler("desktop/preload.js")
        self.assertIn("enderecoDaCaptura", s)
        self.assertIn("LECSOR_CAPTURA_BASE", s)

    def test_menu_cria_a_opcao_sem_trocar_a_base(self):
        s = self.ler("desktop/main.js")
        self.assertIn("Liberar as funcoes de captura nesta maquina", s)
        # Subir o servidor local libera a captura e NAO joga a tela no loopback (dono, 18/11/2026: o
        # login caia num banco local vazio e parecia senha errada). A troca de base so' existe como
        # preset explicito ("Usar como PC de captura"), nunca por subir o servidor.
        self.assertIn("config.capturaLocal = true;", s)
        self.assertNotIn("if (!config.capturaLocal) config.base = local;", s)
        self.assertIn("aplicarEnderecoDaCaptura", s)

    def test_tela_roteia_so_as_rotas_de_captura(self):
        s = self.ler("admin/admin.js")
        self.assertIn("urlDeCaptura", s)
        self.assertIn("fetchCaptura('/api/dispositivos')", s)
        self.assertIn("fetchCaptura('/api/ingestao/comprimir'", s)
        # a leitura do cadastro de cameras tem de continuar no lado terra: `cameras` NAO esta em
        # ROTAS_CAPTURA, entao `/api/cameras` sai por `fetch` puro (nunca pelo servidor local).
        self.assertIn("await api('/api/cameras')", s)
        self.assertNotIn("fetchCaptura('/api/cameras')", s)

    def test_nomes_das_telas(self):
        s = self.ler("admin/admin.js")
        self.assertIn("envios: ['Enviar vídeo',", s)
        # a bancada e' da OPERACAO; a tela do ADMIN e' transmissao ao vivo (dono, 18/11/2026)
        self.assertIn("Teste de vídeo (bancada): comprimir, medir e publicar + transmissão ao vivo", s)
        self.assertIn("Transmitir ao vivo (contínuo)", s)

    def test_qualidade_por_camera_saiu_e_a_banda_do_vivo_ficou(self):
        s = self.ler("admin/admin.js")
        # a "Qualidade por câmera (lista fechada)" saiu da tela: uma escolha de banda, num lugar so'
        self.assertNotIn("env-qualidade-camera", s)
        self.assertNotIn("Qualidade por câmera (lista fechada) — vale no ar", s)
        self.assertIn("const LISTA_ALVO = ['', '1500k', '1200k', '1000k', '800k', '500k', '300k']", s)
        # a caixa de qualidade do ao vivo passa a mandar BANDA para a API
        self.assertIn("bitrate: (qualidade.value || 'auto')", s)

    def test_blocos_que_saem_da_tela_do_admin(self):
        s = self.ler("admin/admin.js")
        # pedidos, bancada e a lista de compressoes ficam so' com a OPERACAO (ehOperador)
        for trecho in ("if (ehOperador) {\n" , "if (ehOperador) t.appendChild(legenda)",
                       "if (!ehOperador) t.appendChild(caixaNoAr)"):
            self.assertIn(trecho, s)

    def test_admin_continua_com_as_telas_de_cadastro(self):
        s = self.ler("admin/admin.js")
        for rota in ("'/api/eu'", "'/api/entrar'", "'/api/cameras'", "'/api/usuarios'"):
            self.assertIn(rota, s)


if __name__ == "__main__":
    resultado = unittest.main(exit=False, verbosity=2).result
    print("CAPTURA_NO_ADMIN_OK" if resultado.wasSuccessful() else "CAPTURA_NO_ADMIN_FALHOU")
    sys.exit(0 if resultado.wasSuccessful() else 1)
