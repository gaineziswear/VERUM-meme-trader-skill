-- Apply after deploying both Supabase Edge Functions.
-- Replace YOUR_PROJECT_REF with the Supabase project reference before executing.
create extension if not exists pg_cron;
create extension if not exists pg_net;
create extension if not exists pgcrypto with schema extensions;

create table if not exists public.verum_internal_config (
  key text primary key,
  value_hash text not null,
  updated_at timestamptz not null default now()
);
alter table public.verum_internal_config enable row level security;
revoke all on public.verum_internal_config from anon, authenticated;
grant all on public.verum_internal_config to service_role;

drop policy if exists "Service role manages internal cron config" on public.verum_internal_config;
create policy "Service role manages internal cron config"
on public.verum_internal_config for all to service_role using (true) with check (true);

do $$
begin
  if not exists (select 1 from vault.decrypted_secrets where name='verum_cron_secret') then
    perform vault.create_secret(
      encode(extensions.gen_random_bytes(32),'hex'),
      'verum_cron_secret',
      'VERUM scheduled Edge Function authentication secret'
    );
  end if;
end $$;

insert into public.verum_internal_config(key,value_hash)
select 'cron_secret_sha256',encode(extensions.digest(decrypted_secret,'sha256'),'hex')
from vault.decrypted_secrets where name='verum_cron_secret'
on conflict(key) do update set value_hash=excluded.value_hash,updated_at=now();

select cron.unschedule(jobid) from cron.job
where jobname in ('verum-radar-ingest','verum-paper-monitor','verum-snapshot-retention');

select cron.schedule(
  'verum-radar-ingest',
  '*/5 * * * *',
  $job$
    select net.http_post(
      url := 'https://YOUR_PROJECT_REF.supabase.co/functions/v1/radar-ingest',
      headers := jsonb_build_object(
        'Content-Type','application/json',
        'x-verum-cron-secret',(select decrypted_secret from vault.decrypted_secrets where name='verum_cron_secret')
      ),
      body := '{}'::jsonb,
      timeout_milliseconds := 30000
    );
  $job$
);

select cron.schedule(
  'verum-paper-monitor',
  '* * * * *',
  $job$
    select net.http_post(
      url := 'https://YOUR_PROJECT_REF.supabase.co/functions/v1/paper-monitor',
      headers := jsonb_build_object(
        'Content-Type','application/json',
        'x-verum-cron-secret',(select decrypted_secret from vault.decrypted_secrets where name='verum_cron_secret')
      ),
      body := '{}'::jsonb,
      timeout_milliseconds := 30000
    );
  $job$
);

select cron.schedule(
  'verum-snapshot-retention',
  '15 3 * * *',
  $job$
    delete from public.token_market_snapshots
    where captured_at < now() - interval '7 days';
  $job$
);
