import { createClient } from 'npm:@supabase/supabase-js@2';

const supabaseUrl = Deno.env.get('SUPABASE_URL')!;
const serviceRoleKey = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!;
const db = createClient(supabaseUrl, serviceRoleKey, {
  auth: { persistSession: false, autoRefreshToken: false },
});
async function authorised(request: Request): Promise<boolean> {
  const candidate = request.headers.get('x-verum-cron-secret') ?? '';
  if (!candidate) return false;
  const { data } = await db.from('verum_internal_config').select('value_hash')
    .eq('key', 'cron_secret_sha256').maybeSingle();
  if (!data?.value_hash) return false;
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(candidate));
  const actual = Array.from(new Uint8Array(digest)).map((byte) => byte.toString(16).padStart(2, '0')).join('');
  const expected = String(data.value_hash);
  if (actual.length !== expected.length) return false;
  let mismatch = 0;
  for (let i = 0; i < actual.length; i++) mismatch |= actual.charCodeAt(i) ^ expected.charCodeAt(i);
  return mismatch === 0;
}

const USDC = 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v';
const FEE_RATE = 0.0025;

async function json(url: string, init?: RequestInit): Promise<any> {
  const response = await fetch(url, { ...init, signal: AbortSignal.timeout(10000) });
  if (!response.ok) throw new Error('provider_http_' + response.status);
  return await response.json();
}

async function currentPair(mint: string): Promise<any | null> {
  const rows = await json('https://api.dexscreener.com/tokens/v1/solana/' + mint);
  const pairs = (Array.isArray(rows) ? rows : []).filter((pair: any) =>
    pair?.baseToken?.address === mint && Number(pair?.priceUsd) > 0
  );
  pairs.sort((a: any, b: any) =>
    Number(b?.liquidity?.usd ?? 0) - Number(a?.liquidity?.usd ?? 0)
  );
  return pairs[0] ?? null;
}

async function decimals(mint: string): Promise<number> {
  const result = await json('https://api.mainnet-beta.solana.com', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      jsonrpc: '2.0', id: 1, method: 'getTokenSupply',
      params: [mint, { commitment: 'confirmed' }],
    }),
  });
  const value = result?.result?.value?.decimals;
  if (!Number.isInteger(value)) throw new Error('token_decimals_unknown');
  return value;
}

let lastJupiterCall = 0;
async function quote(inputMint: string, outputMint: string, amount: number): Promise<any> {
  const apiKey = Deno.env.get('JUPITER_API_KEY') ?? '';
  const minInterval = apiKey ? 1050 : 2100;
  const wait = minInterval - (Date.now() - lastJupiterCall);
  if (wait > 0) await new Promise((resolve) => setTimeout(resolve, wait));
  lastJupiterCall = Date.now();
  const url = 'https://api.jup.ag/swap/v1/quote?inputMint=' + inputMint
    + '&outputMint=' + outputMint + '&amount=' + amount
    + '&slippageBps=100&instructionVersion=V2';
  const headers = apiKey ? { 'x-api-key': apiKey } : undefined;
  return await json(url, { headers });
}

async function alertOnce(userId: string, mint: string, type: string,
                         severity: string, message: string, details: Record<string, unknown>) {
  const cutoff = new Date(Date.now() - 10 * 60 * 1000).toISOString();
  const { data: existing } = await db.from('alerts').select('id')
    .eq('user_id', userId).eq('mint', mint).eq('alert_type', type)
    .gte('created_at', cutoff).limit(1);
  if (existing?.length) return;
  await db.from('alerts').insert({
    user_id: userId, mint, alert_type: type, severity, message, details,
  });
}

async function refreshAccount(userId: string) {
  const { data: account } = await db.from('paper_accounts').select('*')
    .eq('user_id', userId).maybeSingle();
  if (!account) return;
  const { data: open } = await db.from('paper_positions').select('qty,current_price')
    .eq('user_id', userId).eq('status', 'OPEN');
  const marketValue = (open ?? []).reduce((sum: number, row: any) =>
    sum + Number(row.qty ?? 0) * Number(row.current_price ?? 0), 0);
  await db.from('paper_accounts').update({
    equity: Number(account.cash_balance ?? 0) + marketValue,
    updated_at: new Date().toISOString(),
  }).eq('user_id', userId);
}

async function monitorPosition(position: any) {
  const mint = String(position.mint);
  const pair = await currentPair(mint);
  if (!pair) return { status: 'NO_MARKET', mint };
  const price = Number(pair.priceUsd);
  const qty = Number(position.qty);
  const entry = Number(position.entry_price);
  const stop = Number(position.stop_loss);
  const tp1 = Number(position.take_profit_1);
  const tp2 = Number(position.take_profit_2);
  const unrealised = (price - entry) * qty;
  await db.from('paper_positions').update({
    current_price: price, unrealised_pnl: unrealised, updated_at: new Date().toISOString(),
  }).eq('id', position.id).eq('status', 'OPEN');
  await refreshAccount(position.user_id);

  const firstTarget = !position.take_profit_1_hit && price >= tp1;
  const stopHit = price <= stop;
  const finalTarget = price >= tp2;
  const ageMinutes = (Date.now() - new Date(position.opened_at).getTime()) / 60000;
  const timeStop = ageMinutes >= 60;
  const partialTarget = firstTarget && !stopHit && !finalTarget && !timeStop;
  if (!partialTarget && !stopHit && !finalTarget && !timeStop) return { status: 'MARKED', mint, price };

  try {
    const tokenDecimals = await decimals(mint);
    const sellQty = partialTarget ? qty * 0.5 : qty;
    const rawAmount = Math.floor(sellQty * (10 ** tokenDecimals));
    const route = await quote(mint, USDC, rawAmount);
    const proceeds = Number(route.outAmount) / 1_000_000;
    if (!(proceeds > 0)) throw new Error('empty_exit_quote');
    const { data: riskSettings } = await db.from('paper_accounts').select('max_slippage_pct')
      .eq('user_id', position.user_id).maybeSingle();
    if (route.priceImpactPct === undefined || route.priceImpactPct === null) throw new Error('exit_price_impact_unknown');
    const impactRaw = Number(route.priceImpactPct);
    if (!Number.isFinite(impactRaw)) throw new Error('exit_price_impact_unknown');
    const impactPct = Math.abs(impactRaw < 1 ? impactRaw * 100 : impactRaw);
    if (impactPct > Number(riskSettings?.max_slippage_pct ?? 1.5)) throw new Error('exit_price_impact_limit');
    const fee = proceeds * FEE_RATE;
    const exitPrice = proceeds / sellQty;
    const remainingBasis = Number(position.amount_usd) * (partialTarget ? 0.5 : 0);
    const allocatedBasis = Number(position.amount_usd) * (partialTarget ? 0.5 : 1);
    const realised = proceeds - fee - allocatedBasis;
    const reason = partialTarget ? 'take_profit_1_partial' : stopHit ? 'stop_loss' : finalTarget ? 'take_profit_2' : 'time_stop';
    const quoteDetails = {
      provider: 'Jupiter', quote_at: new Date().toISOString(),
      price_impact_pct: route.priceImpactPct ?? null,
      route_plan: route.routePlan ?? [],
    };

    if (partialTarget) {
      const remainingQty = qty - sellQty;
      const { data: updatedPartial } = await db.from('paper_positions').update({
        qty: remainingQty,
        amount_usd: remainingBasis,
        realised_pnl: Number(position.realised_pnl ?? 0) + realised,
        unrealised_pnl: (price - entry) * remainingQty,
        fees_usd: Number(position.fees_usd ?? 0) + fee,
        take_profit_1_hit: true,
        stop_loss: entry,
        exit_quote: quoteDetails,
        updated_at: new Date().toISOString(),
      }).eq('id', position.id).eq('status', 'OPEN').eq('take_profit_1_hit', false).select('id');
      if (!updatedPartial?.length) return { status: 'RACE_LOST', mint };
    } else {
      const { data: updatedClosed } = await db.from('paper_positions').update({
        status: 'CLOSED', current_price: exitPrice, exit_price: exitPrice,
        closed_at: new Date().toISOString(), exit_reason: reason,
        realised_pnl: Number(position.realised_pnl ?? 0) + realised,
        unrealised_pnl: 0, fees_usd: Number(position.fees_usd ?? 0) + fee,
        exit_quote: quoteDetails, updated_at: new Date().toISOString(),
      }).eq('id', position.id).eq('status', 'OPEN').select('id');
      if (!updatedClosed?.length) return { status: 'RACE_LOST', mint };
    }

    await db.from('paper_trades').insert({
      user_id: position.user_id, position_id: position.id, mint,
      symbol: position.symbol, side: 'SELL', qty: sellQty,
      price: exitPrice, gross_usd: proceeds, fees_usd: fee,
      slippage_usd: 0, pnl_usd: realised, reason,
      quote_timestamp: new Date().toISOString(), source: 'Jupiter quote simulation',
    });

    const { data: account } = await db.from('paper_accounts').select('cash_balance')
      .eq('user_id', position.user_id).maybeSingle();
    await db.from('paper_accounts').update({
      cash_balance: Number(account?.cash_balance ?? 0) + proceeds - fee,
      updated_at: new Date().toISOString(),
    }).eq('user_id', position.user_id);
    await refreshAccount(position.user_id);
    await alertOnce(position.user_id, mint, reason.toUpperCase(),
      stopHit ? 'WARNING' : 'SUCCESS',
      firstTarget ? 'First target reached; 50% paper position closed and stop moved to break-even.'
        : stopHit ? 'Stop-loss condition reached; paper position closed using an executable quote.'
          : 'Second target reached; remaining paper position closed using an executable quote.',
      { price, exit_price: exitPrice, proceeds_usd: proceeds, realised_pnl_usd: realised });
    return { status: 'EXITED', mint, reason, realised_pnl_usd: realised };
  } catch (error) {
    await alertOnce(position.user_id, mint, 'EXIT_QUOTE_UNAVAILABLE', 'WARNING',
      'Exit threshold reached, but no executable Jupiter quote was available. Position remains open.',
      { observed_price: price, threshold: stopHit ? stop : finalTarget ? tp2 : tp1,
        error: error instanceof Error ? error.name : 'unknown' });
    return { status: 'EXIT_QUOTE_UNAVAILABLE', mint };
  }
}

Deno.serve(async (request: Request) => {
  if (request.method === 'OPTIONS') return new Response('ok');
  if (!(await authorised(request))) return Response.json({ ok: false, error: 'unauthorized' }, { status: 401 });
  try {
    const { data: positions, error } = await db.from('paper_positions')
      .select('*').eq('status', 'OPEN').order('opened_at', { ascending: true }).limit(100);
    if (error) throw error;
    const results = [];
    for (const position of positions ?? []) {
      try {
        results.push(await monitorPosition(position));
      } catch (error) {
        results.push({ status: 'ERROR', mint: position.mint,
          error: error instanceof Error ? error.name : 'unknown' });
      }
    }
    return Response.json({ ok: true, checked: results.length, results,
      timestamp: new Date().toISOString() });
  } catch (error) {
    console.error('paper-monitor failed', error instanceof Error ? error.name : 'unknown');
    return Response.json({ ok: false, error: 'paper_monitor_failed' }, { status: 500 });
  }
});
