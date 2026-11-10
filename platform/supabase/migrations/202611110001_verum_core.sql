-- VERUM Meme Intelligence core schema.
-- The upstream 13-skill repository remains MIT-licensed; this migration adds the platform database.
create table if not exists public.token_launches (
  mint text primary key, name text, symbol text, creator_wallet text, bonding_curve_key text,
  metadata_uri text, initial_buy numeric, v_sol_in_curve numeric, v_tokens_in_curve numeric,
  graduation_status text not null default 'UNKNOWN', pool_address text,
  discovery_source text not null default 'unknown',
  first_seen_at timestamptz not null default now(), last_seen_at timestamptz not null default now(),
  raw_event jsonb not null default '{}'::jsonb, data_quality jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);
create index if not exists token_launches_seen_idx on public.token_launches(last_seen_at desc);
create index if not exists token_launches_creator_idx on public.token_launches(creator_wallet);

create table if not exists public.token_market_snapshots (
  id uuid primary key default gen_random_uuid(), mint text not null,
  captured_at timestamptz not null default now(), pair_address text, dex_id text,
  price_usd numeric, liquidity_usd numeric, volume_m5 numeric, volume_h1 numeric, volume_h24 numeric,
  buys_m5 integer, sells_m5 integer, price_change_m5 numeric, market_cap numeric, fdv numeric,
  price_source text, raw_data jsonb not null default '{}'::jsonb, unique(mint,captured_at)
);
create index if not exists token_market_mint_time_idx on public.token_market_snapshots(mint,captured_at desc);

create table if not exists public.provider_status (
  provider text primary key, status text not null default 'UNKNOWN',
  last_success_at timestamptz, last_error text, records_seen integer not null default 0,
  latency_ms integer, updated_at timestamptz not null default now()
);
insert into public.provider_status(provider,status) values
 ('PumpPortal','UNKNOWN'),('DexScreener','UNKNOWN'),('RugCheck','UNKNOWN'),
 ('GoPlus','UNKNOWN'),('Jupiter','UNKNOWN'),('Solana RPC','UNKNOWN')
on conflict(provider) do nothing;

create table if not exists public.signals (
  id uuid primary key default gen_random_uuid(), mint text not null, symbol text,
  status text not null, strategy text not null, confidence numeric not null default 0,
  evidence_coverage numeric not null default 0, entry_price numeric, stop_loss numeric,
  take_profit_1 numeric, take_profit_2 numeric, risk_reward numeric,
  quote_at timestamptz, expires_at timestamptz,
  reasons jsonb not null default '[]'::jsonb, provenance jsonb not null default '[]'::jsonb,
  council jsonb not null default '[]'::jsonb, created_at timestamptz not null default now()
);
create index if not exists signals_created_idx on public.signals(created_at desc);
create index if not exists signals_mint_idx on public.signals(mint,created_at desc);

create table if not exists public.wallet_assessments (
  wallet_address text primary key, first_seen_at timestamptz, last_seen_at timestamptz,
  tx_count integer not null default 0, creator_launches integer not null default 0,
  cluster_id text, realised_pnl_usd numeric, performance_status text not null default 'UNKNOWN',
  coverage_pct numeric not null default 0, evidence jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

create table if not exists public.paper_accounts (
  user_id uuid primary key references auth.users(id) on delete cascade,
  starting_balance numeric not null default 1000 check(starting_balance>0),
  cash_balance numeric not null default 1000 check(cash_balance>=0),
  equity numeric not null default 1000 check(equity>=0),
  max_risk_per_trade_pct numeric not null default 0.5 check(max_risk_per_trade_pct>0 and max_risk_per_trade_pct<=2),
  max_daily_loss_pct numeric not null default 2 check(max_daily_loss_pct>0 and max_daily_loss_pct<=10),
  max_open_positions integer not null default 3 check(max_open_positions between 1 and 10),
  max_total_exposure_pct numeric not null default 20 check(max_total_exposure_pct>0 and max_total_exposure_pct<=100),
  max_slippage_pct numeric not null default 1.5 check(max_slippage_pct>0 and max_slippage_pct<=10),
  updated_at timestamptz not null default now()
);
create table if not exists public.paper_positions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  mint text not null, symbol text, qty numeric not null check(qty>0),
  amount_usd numeric not null check(amount_usd>0), entry_price numeric not null check(entry_price>0),
  current_price numeric, stop_loss numeric not null, take_profit_1 numeric, take_profit_2 numeric,
  risk_usd numeric not null, unrealised_pnl numeric not null default 0,
  realised_pnl numeric not null default 0, status text not null default 'OPEN',
  take_profit_1_hit boolean not null default false,
  opened_at timestamptz not null default now(), closed_at timestamptz, exit_price numeric,
  exit_reason text, fees_usd numeric not null default 0, slippage_pct numeric,
  entry_quote jsonb not null default '{}'::jsonb, exit_quote jsonb,
  strategy text not null default 'lifecycle_momentum',
  created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
  constraint paper_positions_status_check check(status in ('OPEN','CLOSED','BLOCKED'))
);
alter table public.paper_positions add column if not exists take_profit_1_hit boolean not null default false;
create index if not exists paper_positions_user_status_idx on public.paper_positions(user_id,status,opened_at desc);
create unique index if not exists paper_positions_one_open_per_mint on public.paper_positions(user_id,mint) where status='OPEN';

create table if not exists public.paper_trades (
  id uuid primary key default gen_random_uuid(), user_id uuid not null references auth.users(id) on delete cascade,
  position_id uuid references public.paper_positions(id) on delete set null,
  mint text not null, symbol text, side text not null check(side in ('BUY','SELL')),
  qty numeric not null, price numeric not null, gross_usd numeric not null,
  fees_usd numeric not null default 0, slippage_usd numeric not null default 0,
  pnl_usd numeric, reason text, quote_timestamp timestamptz,
  source text not null default 'Jupiter quote simulation', created_at timestamptz not null default now()
);
create index if not exists paper_trades_user_time_idx on public.paper_trades(user_id,created_at desc);

create table if not exists public.research_runs (
  id uuid primary key default gen_random_uuid(), user_id uuid not null references auth.users(id) on delete cascade,
  mint text not null, strategy text not null, dataset_fingerprint text not null,
  data_start timestamptz, data_end timestamptz, bars integer not null default 0,
  in_sample_metrics jsonb not null default '{}'::jsonb,
  out_of_sample_metrics jsonb not null default '{}'::jsonb,
  assumptions jsonb not null default '{}'::jsonb, result jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
create index if not exists research_runs_user_time_idx on public.research_runs(user_id,created_at desc);

create table if not exists public.user_settings (
  user_id uuid primary key references auth.users(id) on delete cascade,
  timezone text not null default 'UTC', paper_starting_balance numeric not null default 1000 check(paper_starting_balance>0),
  max_risk_per_trade_pct numeric not null default 0.5 check(max_risk_per_trade_pct>0 and max_risk_per_trade_pct<=2),
  max_daily_loss_pct numeric not null default 2 check(max_daily_loss_pct>0 and max_daily_loss_pct<=10),
  max_open_positions integer not null default 3 check(max_open_positions between 1 and 10),
  max_total_exposure_pct numeric not null default 20 check(max_total_exposure_pct>0 and max_total_exposure_pct<=100),
  max_slippage_pct numeric not null default 1.5 check(max_slippage_pct>0 and max_slippage_pct<=10),
  created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create table if not exists public.user_watchlists (
  id uuid primary key default gen_random_uuid(), user_id uuid not null references auth.users(id) on delete cascade,
  mint text not null, notes text, created_at timestamptz not null default now(), unique(user_id,mint)
);
create index if not exists user_watchlists_user_idx on public.user_watchlists(user_id,created_at desc);
create table if not exists public.alerts (
  id uuid primary key default gen_random_uuid(), user_id uuid not null references auth.users(id) on delete cascade,
  mint text, alert_type text not null, severity text not null default 'INFO',
  message text not null, details jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(), read_at timestamptz
);
create index if not exists alerts_user_time_idx on public.alerts(user_id,created_at desc);

create table if not exists public.verum_internal_config (
  key text primary key, value_hash text not null, updated_at timestamptz not null default now()
);

alter table public.token_launches enable row level security;
alter table public.token_market_snapshots enable row level security;
alter table public.provider_status enable row level security;
alter table public.signals enable row level security;
alter table public.wallet_assessments enable row level security;
alter table public.paper_accounts enable row level security;
alter table public.paper_positions enable row level security;
alter table public.paper_trades enable row level security;
alter table public.research_runs enable row level security;
alter table public.user_settings enable row level security;
alter table public.user_watchlists enable row level security;
alter table public.alerts enable row level security;
alter table public.verum_internal_config enable row level security;

drop policy if exists "Public can read launches" on public.token_launches;
create policy "Public can read launches" on public.token_launches for select to anon,authenticated using(true);
drop policy if exists "Public can read market snapshots" on public.token_market_snapshots;
create policy "Public can read market snapshots" on public.token_market_snapshots for select to anon,authenticated using(true);
drop policy if exists "Public can read provider status" on public.provider_status;
create policy "Public can read provider status" on public.provider_status for select to anon,authenticated using(true);
drop policy if exists "Public can read signals" on public.signals;
create policy "Public can read signals" on public.signals for select to anon,authenticated using(true);
drop policy if exists "Public can read wallet assessments" on public.wallet_assessments;
create policy "Public can read wallet assessments" on public.wallet_assessments for select to anon,authenticated using(true);

drop policy if exists "Users manage own paper accounts" on public.paper_accounts;
create policy "Users manage own paper accounts" on public.paper_accounts for all to authenticated using((select auth.uid())=user_id) with check((select auth.uid())=user_id);
drop policy if exists "Users manage own paper positions" on public.paper_positions;
create policy "Users manage own paper positions" on public.paper_positions for all to authenticated using((select auth.uid())=user_id) with check((select auth.uid())=user_id);
drop policy if exists "Users manage own paper trades" on public.paper_trades;
create policy "Users manage own paper trades" on public.paper_trades for all to authenticated using((select auth.uid())=user_id) with check((select auth.uid())=user_id);
drop policy if exists "Users manage own research runs" on public.research_runs;
create policy "Users manage own research runs" on public.research_runs for all to authenticated using((select auth.uid())=user_id) with check((select auth.uid())=user_id);
drop policy if exists "Users manage own settings" on public.user_settings;
create policy "Users manage own settings" on public.user_settings for all to authenticated using((select auth.uid())=user_id) with check((select auth.uid())=user_id);
drop policy if exists "Users manage own watchlists" on public.user_watchlists;
create policy "Users manage own watchlists" on public.user_watchlists for all to authenticated using((select auth.uid())=user_id) with check((select auth.uid())=user_id);
drop policy if exists "Users manage own alerts" on public.alerts;
create policy "Users manage own alerts" on public.alerts for all to authenticated using((select auth.uid())=user_id) with check((select auth.uid())=user_id);

grant select on public.token_launches,public.token_market_snapshots,public.provider_status,public.signals,public.wallet_assessments to anon,authenticated;
grant select,insert,update,delete on public.paper_accounts,public.paper_positions,public.paper_trades,public.research_runs,public.user_settings,public.user_watchlists,public.alerts to authenticated;
revoke all on public.verum_internal_config from anon,authenticated;
grant all on public.verum_internal_config to service_role;

create or replace function public.open_paper_position(
  p_mint text,p_symbol text,p_qty numeric,p_amount_usd numeric,p_entry_price numeric,p_stop_loss numeric,
  p_take_profit_1 numeric,p_take_profit_2 numeric,p_risk_usd numeric,p_fees_usd numeric,
  p_slippage_pct numeric,p_entry_quote jsonb,p_strategy text default 'lifecycle_momentum'
) returns uuid language plpgsql security invoker set search_path=pg_catalog,public as $$
declare
  v_user uuid:=auth.uid(); v_account public.paper_accounts%rowtype;
  v_open_count integer; v_exposure numeric; v_daily_loss numeric; v_recent_losses integer;
  v_position_id uuid:=gen_random_uuid();
begin
  if v_user is null then raise exception 'authentication_required'; end if;
  if p_qty<=0 or p_amount_usd<=0 or p_entry_price<=0 or p_stop_loss>=p_entry_price then raise exception 'invalid_trade_parameters'; end if;
  insert into public.paper_accounts(user_id) values(v_user) on conflict(user_id) do nothing;
  select * into v_account from public.paper_accounts where user_id=v_user for update;
  select count(*),coalesce(sum(amount_usd),0) into v_open_count,v_exposure from public.paper_positions where user_id=v_user and status='OPEN';
  select coalesce(sum(abs(pnl_usd)),0) into v_daily_loss from public.paper_trades
    where user_id=v_user and side='SELL' and pnl_usd<0 and created_at>=date_trunc('day',now());
  select count(*) into v_recent_losses from (
    select pnl_usd from public.paper_trades where user_id=v_user and side='SELL' and pnl_usd is not null order by created_at desc limit 3
  ) recent where recent.pnl_usd<0;
  if v_open_count>=v_account.max_open_positions then raise exception 'max_open_positions_reached'; end if;
  if exists(select 1 from public.paper_positions where user_id=v_user and mint=p_mint and status='OPEN') then raise exception 'duplicate_open_position'; end if;
  if p_amount_usd>v_account.cash_balance then raise exception 'insufficient_paper_cash'; end if;
  if v_exposure+p_amount_usd>v_account.equity*v_account.max_total_exposure_pct/100.0 then raise exception 'max_total_exposure_reached'; end if;
  if p_risk_usd>v_account.equity*v_account.max_risk_per_trade_pct/100.0+0.01 then raise exception 'max_risk_per_trade_exceeded'; end if;
  if v_daily_loss+p_risk_usd>v_account.equity*v_account.max_daily_loss_pct/100.0 then raise exception 'daily_loss_limit_reached'; end if;
  if v_recent_losses>=3 then raise exception 'consecutive_loss_protection'; end if;
  if v_account.equity<v_account.starting_balance*0.90 then raise exception 'portfolio_drawdown_protection'; end if;
  if coalesce(p_slippage_pct,0)>v_account.max_slippage_pct then raise exception 'slippage_limit_reached'; end if;
  insert into public.paper_positions(id,user_id,mint,symbol,qty,amount_usd,entry_price,current_price,stop_loss,take_profit_1,take_profit_2,risk_usd,fees_usd,slippage_pct,entry_quote,strategy,status)
  values(v_position_id,v_user,p_mint,p_symbol,p_qty,p_amount_usd,p_entry_price,p_entry_price,p_stop_loss,p_take_profit_1,p_take_profit_2,p_risk_usd,p_fees_usd,p_slippage_pct,coalesce(p_entry_quote,'{}'::jsonb),p_strategy,'OPEN');
  insert into public.paper_trades(user_id,position_id,mint,symbol,side,qty,price,gross_usd,fees_usd,slippage_usd,reason,quote_timestamp,source)
  values(v_user,v_position_id,p_mint,p_symbol,'BUY',p_qty,p_entry_price,p_amount_usd-coalesce(p_fees_usd,0),coalesce(p_fees_usd,0),p_amount_usd*greatest(coalesce(p_slippage_pct,0),0)/100.0,'paper_entry',now(),'Jupiter quote simulation');
  update public.paper_accounts set cash_balance=cash_balance-p_amount_usd,updated_at=now() where user_id=v_user;
  return v_position_id;
end;
$$;

create or replace function public.close_paper_position(
  p_position_id uuid,p_exit_price numeric,p_proceeds_usd numeric,p_fees_usd numeric,p_exit_quote jsonb,p_reason text
) returns jsonb language plpgsql security invoker set search_path=public as $$
declare v_user uuid:=auth.uid(); v_position public.paper_positions%rowtype; v_pnl numeric;
begin
  if v_user is null then raise exception 'authentication_required'; end if;
  select * into v_position from public.paper_positions where id=p_position_id and user_id=v_user and status='OPEN' for update;
  if not found then raise exception 'open_position_not_found'; end if;
  if p_exit_price<=0 or p_proceeds_usd<0 then raise exception 'invalid_exit_quote'; end if;
  v_pnl:=p_proceeds_usd-v_position.amount_usd-coalesce(p_fees_usd,0);
  update public.paper_positions set status='CLOSED',current_price=p_exit_price,exit_price=p_exit_price,closed_at=now(),exit_reason=p_reason,
    realised_pnl=realised_pnl+v_pnl,unrealised_pnl=0,fees_usd=fees_usd+coalesce(p_fees_usd,0),exit_quote=coalesce(p_exit_quote,'{}'::jsonb),updated_at=now()
    where id=p_position_id and user_id=v_user;
  update public.paper_accounts a set cash_balance=a.cash_balance+p_proceeds_usd-coalesce(p_fees_usd,0),
    equity=a.cash_balance+p_proceeds_usd-coalesce(p_fees_usd,0)+coalesce((
      select sum(p.current_price*p.qty) from public.paper_positions p where p.user_id=v_user and p.status='OPEN' and p.id<>p_position_id
    ),0),updated_at=now() where a.user_id=v_user;
  insert into public.paper_trades(user_id,position_id,mint,symbol,side,qty,price,gross_usd,fees_usd,pnl_usd,reason,quote_timestamp,source)
  values(v_user,p_position_id,v_position.mint,v_position.symbol,'SELL',v_position.qty,p_exit_price,p_proceeds_usd,coalesce(p_fees_usd,0),v_pnl,p_reason,now(),'Jupiter quote simulation');
  return jsonb_build_object('position_id',p_position_id,'realised_pnl_usd',v_pnl,'proceeds_usd',p_proceeds_usd);
end;
$$;
revoke all on function public.open_paper_position(text,text,numeric,numeric,numeric,numeric,numeric,numeric,numeric,numeric,numeric,jsonb,text) from public,anon;
revoke all on function public.close_paper_position(uuid,numeric,numeric,numeric,jsonb,text) from public,anon;
grant execute on function public.open_paper_position(text,text,numeric,numeric,numeric,numeric,numeric,numeric,numeric,numeric,numeric,jsonb,text) to authenticated;
grant execute on function public.close_paper_position(uuid,numeric,numeric,numeric,jsonb,text) to authenticated;


-- Narrow supporting indexes for paper journal and time-series access.
create index if not exists paper_trades_position_id_idx on public.paper_trades(position_id);
create index if not exists token_market_captured_idx on public.token_market_snapshots(captured_at desc);
create index if not exists research_runs_user_mint_time_idx on public.research_runs(user_id,mint,created_at desc);

drop policy if exists "Service role manages internal cron config" on public.verum_internal_config;
create policy "Service role manages internal cron config"
on public.verum_internal_config for all to service_role using (true) with check (true);
