// Edge Function: telemetria-ingestao
// Recebe do servidor de BORDO um lote de medições (minuto fechado por fluxo) e grava no Postgres.
//
// Por que Edge Function e não o navegador: a chave de serviço fica só no ambiente da função
// (SUPABASE_SERVICE_ROLE_KEY é injetada pelo Supabase), então o cliente nunca carrega credencial.
//
// Deploy:
//   supabase secrets set LECSOR_TOKEN_INGESTAO=<token-do-servidor-de-bordo>
//   supabase functions deploy telemetria-ingestao --no-verify-jwt   # autenticação própria por token
//
// Corpo aceito (um lote por chamada — o servidor de bordo manda a cada 60 s):
// {
//   "embarcacao": "<uuid ou imo>",
//   "fluxos": [
//     { "fluxo_id": "cam-01", "camera_id": "cam-01", "minuto": "2026-11-09T14:03:00-03:00",
//       "entrada_kbps": 1809.2, "saida_kbps": 477.0, "compressao_pct": 73.64,
//       "mb_enviados": 3.58, "segundos_no_ar": 60 },
//     ...
//   ],
//   "link": { "fluxo_id": "cam-01", "rtt_ms": 42.1, "capacidade_mbps": 3.2,
//             "taxa_envio_mbps": 1.5, "atraso_buffer_ms": 120, "perda_pct": 0.0,
//             "latencia_internet_ms": 27, "fonte": "srt+ping" }
// }

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

type Fluxo = {
  fluxo_id: string; camera_id?: string; minuto: string;
  entrada_kbps?: number; saida_kbps?: number; compressao_pct?: number;
  mb_enviados?: number; segundos_no_ar?: number;
};
type Link = {
  fluxo_id?: string; rtt_ms?: number; capacidade_mbps?: number; taxa_envio_mbps?: number;
  atraso_buffer_ms?: number; perda_pct?: number; latencia_internet_ms?: number; fonte?: string;
};

const json = (status: number, corpo: unknown) =>
  new Response(JSON.stringify(corpo), { status, headers: { "content-type": "application/json" } });

Deno.serve(async (req: Request) => {
  if (req.method !== "POST") return json(405, { erro: "use POST" });

  const esperado = Deno.env.get("LECSOR_TOKEN_INGESTAO") ?? "";
  const recebido = (req.headers.get("x-token-embarcacao") ?? "").trim();
  if (!esperado || recebido !== esperado) return json(401, { erro: "token da embarcacao invalido" });

  let corpo: { embarcacao?: string; fluxos?: Fluxo[]; link?: Link };
  try {
    corpo = await req.json();
  } catch {
    return json(400, { erro: "corpo nao e JSON" });
  }
  const fluxos = Array.isArray(corpo.fluxos) ? corpo.fluxos : [];
  if (!fluxos.length && !corpo.link) return json(422, { erro: "nada para gravar" });

  // embarcacao pode vir por uuid ou por IMO: resolve para uuid antes de gravar
  const admin = createClient(
    Deno.env.get("SUPABASE_URL")!,
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
    { auth: { persistSession: false } },
  );

  let embarcacaoId: string | null = null;
  if (corpo.embarcacao) {
    const porId = corpo.embarcacao.match(/^[0-9a-f-]{36}$/i);
    const { data } = porId
      ? await admin.from("embarcacoes").select("id").eq("id", corpo.embarcacao).maybeSingle()
      : await admin.from("embarcacoes").select("id").eq("imo", corpo.embarcacao).maybeSingle();
    embarcacaoId = data?.id ?? null;
    if (!embarcacaoId) return json(422, { erro: "embarcacao nao encontrada", embarcacao: corpo.embarcacao });
  }

  // aceita só números finitos; o resto vira null em vez de derrubar o lote
  const numero = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);

  let gravados = 0;
  if (fluxos.length) {
    const linhas = fluxos
      .filter((f) => typeof f?.fluxo_id === "string" && typeof f?.minuto === "string")
      .map((f) => ({
        fluxo_id: f.fluxo_id,
        camera_id: f.camera_id ?? f.fluxo_id,
        embarcacao_id: embarcacaoId,
        minuto: f.minuto,
        entrada_kbps: numero(f.entrada_kbps),
        saida_kbps: numero(f.saida_kbps),
        compressao_pct: numero(f.compressao_pct),
        mb_enviados: numero(f.mb_enviados),
        segundos_no_ar: f.segundos_no_ar ?? null,
      }));
    if (linhas.length) {
      const { error } = await admin.from("telemetria_minuto")
        .upsert(linhas, { onConflict: "fluxo_id,minuto" });
      if (error) return json(500, { erro: "falha ao gravar telemetria", detalhe: error.message });
      gravados = linhas.length;
    }
  }

  if (corpo.link) {
    const l = corpo.link;
    const { error } = await admin.from("link_amostras").insert({
      fluxo_id: l.fluxo_id ?? null,
      rtt_ms: numero(l.rtt_ms),
      capacidade_mbps: numero(l.capacidade_mbps),
      taxa_envio_mbps: numero(l.taxa_envio_mbps),
      atraso_buffer_ms: numero(l.atraso_buffer_ms),
      perda_pct: numero(l.perda_pct),
      latencia_internet_ms: numero(l.latencia_internet_ms),
      fonte: l.fonte ?? null,
    });
    if (error) return json(500, { erro: "falha ao gravar link", detalhe: error.message });
  }

  return json(200, { ok: true, minutos_gravados: gravados, link: Boolean(corpo.link) });
});
