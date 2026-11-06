# Pipeline de vídeo bordo→terra — Lecsor Technology

Repositório base do pipeline (ver planos 1, 2 e 3 do projeto). **Fase 0-A** executada:
bancada sem dado de cliente, com vídeo próprio.

## Estrutura
- `bench/`  — scripts de medição (corte de banda, VMAF, latência, benchmark de encode)
- `board/`  — agente de bordo (Fase 2)
- `ground/` — servidor de terra / VPS já existente (Fase 3)
- `portal/` — front do operador + módulo de documentação e acompanhamento (Fase 3)
- `db/`     — schema/migrations (Fase 3)
- `tests/`  — testes automatizados

## Como rodar a Fase 0-A
```
cp .env.example .env      # preencher quando houver credencial (Fase 0-B)
cd bench && ./run.sh
```
Saída: `bench/saida/resultado-fase0.json` e `bench/saida/medicoes.csv`.

## Regras do projeto
1. Nenhum segredo no repositório — credencial só por variável de ambiente/cofre.
2. Toda medição grava valor, fonte, data, hardware/versão e comando.
3. Acesso a câmera só por dentro da VPN; porta RTSP nunca publicada na internet.
