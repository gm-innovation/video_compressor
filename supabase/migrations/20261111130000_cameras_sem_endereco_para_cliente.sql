-- Correção de segurança: o cliente autenticado não pode ler o endereço da câmera.
--
-- Achado (11/11/2026, teste com has_column_privilege no projeto gscfcobpejxhtyzwfrjp):
-- a política de RLS de public.cameras LIMITA A LINHA, não a coluna. O papel 'authenticated' tinha
-- SELECT de tabela e por isso conseguia ler cameras.ip / cameras.porta do próprio cliente — contra a
-- regra declarada na migração 20261109140000 ("o cliente NÃO pode ler ip/porta").
--
-- Correção: tira o SELECT de tabela e devolve SELECT só nas colunas seguras. O endereço da câmera
-- (ip/porta) fica legível apenas pelo service role (a API em terra), nunca pelo navegador.

revoke select on public.cameras from anon, authenticated;

grant select (id, embarcacao_id, rotulo, fluxo_id, protocolo, canal, ativo, criado_em)
  on public.cameras to authenticated;

-- anon não lê cameras de forma alguma (o produto entra pela API em terra).
revoke all on public.cameras from anon;
