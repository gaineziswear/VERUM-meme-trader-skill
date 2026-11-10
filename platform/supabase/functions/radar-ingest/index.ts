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

type Launch = {
  mint: string;
  name?: string | null;
  symbol?: string | null;
  creator_wallet?: string | null;
  bonding_curve_key?: string | null;
  metadata_uri?: string | null;
  initial_buy?: number | null;
  v_sol_in_curve?: number | null;
  v_tokens_in_curve?: number | null;
  graduation_status: string;
  pool_address?: string | null;
  discovery_source: string;
  last_seen_at: string;
  raw_event: Record<string, unknown>;
  data_quality: Record<string, unknown>;
};

function normalizePumpEvent(event: Record<string, unknown>): Launch | null {
  const mint = String(event.mint ?? '');
  if (!mint) return null;
  const txType = String(event.txType ?? event.type ?? '').toLowerCase();
  const migrated = txType.includes('migrate') || Boolean(event.pool);
  return {
    mint,
    name: event.name ? String(event.name) : null,
    symbol: event.symbol ? String(event.symbol) : null,
    creator_wallet: event.traderPublicKey ? String(event.traderPublicKey) : null,
    bonding_curve_key: event.bondingCurveKey ? String(event.bondingCurveKey) : null,
    metadata_uri: event.uri ? String(event.uri) : null,
    initial_buy: Number(event.initialBuy ?? 0) || null,
    v_sol_in_curve: Number(event.vSolInBondingCurve ?? 0) || null,
    v_tokens_in_curve: Number(event.vTokensInBondingCurve ?? 0) || null,
    graduation_status: migrated ? 'GRADUATED' : 'BONDING_CURVE',
    pool_address: event.pool ? String(event.pool) : null,
    discovery_source: 'PumpPortal websocket',
    last_seen_at: new Date().toISOString(),
    raw_event: event,
    data_quality: { source: 'PumpPortal', observed_at: new Date().toISOString() },
  };
}

async function collectPumpPortal(): Promise<{ launches: Launch[]; status: string; error?: string }> {
  if (typeof WebSocket === 'undefined') {
    return { launches: [], status: 'UNAVAILABLE', error: 'WebSocket runtime unavailable' };
  }
  const launches: Launch[] = [];
  return await new Promise((resolve) => {
    let settled = false;
    let socket: WebSocket | null = null;
    const finish = (status: string, error?: string) => {
      if (settled) return;
      settled = true;
      try { socket?.close(); } catch { /* best effort */ }
      resolve({ launches, status, error });
    };
    const timer = setTimeout(() => finish('OK'), 12000);
    try {
      socket = new WebSocket('wss://pumpportal.fun/api/data');
      socket.onopen = () => {
        socket?.send(JSON.stringify({ method: 'subscribeNewToken' }));
        socket?.send(JSON.stringify({ method: 'subscribeMigration' }));
      };
      socket.onmessage = (message) => {
        try {
          const event = JSON.parse(String(message.data)) as Record<string, unknown>;
          const row = normalizePumpEvent(event);
          if (row) launches.push(row);
        } catch {
          // Ignore malformed frames; do not fail the whole ingestion window.
        }
      };
      socket.onerror = () => {
        clearTimeout(timer);
        finish('UNAVAILABLE', 'PumpPortal websocket error');
      };
      socket.onclose = () => {
        clearTimeout(timer);
        finish(launches.length ? 'OK' : 'UNAVAILABLE',
               launches.length ? undefined : 'PumpPortal closed before events arrived');
      };
    } catch (error) {
      clearTimeout(timer);
      finish('UNAVAILABLE', error instanceof Error ? error.name : 'connection_error');
    }
  });
}

async function upsertLaunches(rows: Launch[]): Promise<number> {
  if (!rows.length) return 0;
  const unique = new Map<string, Launch>();
  for (const row of rows) {
    const previous = unique.get(row.mint);
    unique.set(row.mint, previous
      ? { ...previous, ...row, raw_event: { ...previous.raw_event, ...row.raw_event } }
      : row);
  }
  const { error } = await db.from('token_launches').upsert([...unique.values()], { onConflict: 'mint' });
  if (error) throw error;
  return unique.size;
}

async function recordProvider(provider: string, status: string, records: number,
                              latencyMs: number | null, errorText?: string) {
  const now = new Date().toISOString();
  const payload: Record<string, unknown> = {
    provider, status, records_seen: records, latency_ms: latencyMs,
    last_error: errorText ?? null, updated_at: now,
  };
  if (status === 'OK') payload.last_success_at = now;
  const { data: existing } = await db.from('provider_status').select('provider')
    .eq('provider', provider).maybeSingle();
  if (existing) await db.from('provider_status').update(payload).eq('provider', provider);
  else await db.from('provider_status').insert({ ...payload, last_success_at: status === 'OK' ? now : null });
}

async function probeProvider(provider: string, url: string,
  init: RequestInit, valid: (body: any) => boolean): Promise<Record<string, unknown>> {
  const started = Date.now();
  try {
    const response = await fetch(url, { ...init, signal: AbortSignal.timeout(8000) });
    const body = await response.json();
    const ok = response.ok && valid(body);
    const errorText = ok ? undefined : 'HTTP ' + response.status;
    await recordProvider(provider, ok ? 'OK' : 'UNAVAILABLE', ok ? 1 : 0,
                         Date.now() - started, errorText);
    return { provider, status: ok ? 'OK' : 'UNAVAILABLE', latency_ms: Date.now() - started };
  } catch (error) {
    const errorText = error instanceof Error ? error.name : 'provider_probe_failed';
    await recordProvider(provider, 'UNAVAILABLE', 0, Date.now() - started, errorText);
    return { provider, status: 'UNAVAILABLE', error: errorText, latency_ms: Date.now() - started };
  }
}

async function probeProviderHealth(mint: string): Promise<Record<string, unknown>[]> {
  const usdc = 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v';
  const sol = 'So11111111111111111111111111111111111111112';
  const jupiterKey = Deno.env.get('JUPITER_API_KEY') ?? '';
  const jupiterHeaders: Record<string, string> = { accept: 'application/json' };
  if (jupiterKey) jupiterHeaders['x-api-key'] = jupiterKey;
  const checks = [
    probeProvider('RugCheck',
      'https://api.rugcheck.xyz/v1/tokens/' + mint + '/report',
      { headers: { accept: 'application/json' } },
      (body) => Boolean(body?.token && Array.isArray(body?.risks))),
    probeProvider('GoPlus',
      'https://api.gopluslabs.io/api/v1/solana/token_security?contract_addresses=' + mint,
      { headers: { accept: 'application/json' } },
      (body) => body?.code === 1 && Boolean(body?.result?.[mint])),
    probeProvider('Jupiter',
      'https://api.jup.ag/swap/v1/quote?inputMint=' + usdc + '&outputMint=' + sol
        + '&amount=25000000&slippageBps=100&instructionVersion=V2',
      { headers: jupiterHeaders },
      (body) => Boolean(body?.outAmount)),
    probeProvider('Solana RPC', 'https://api.mainnet-beta.solana.com',
      { method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'getHealth' }) },
      (body) => body?.result === 'ok'),
  ];
  const { data: market } = await db.from('token_market_snapshots').select('pair_address')
    .eq('mint', mint).order('captured_at', { ascending: false }).limit(1).maybeSingle();
  if (market?.pair_address) {
    checks.push(probeProvider('GeckoTerminal',
      'https://api.geckoterminal.com/api/v2/networks/solana/pools/' + market.pair_address
        + '/ohlcv/minute?aggregate=1&limit=2&currency=usd&token=base',
      { headers: { accept: 'application/json;version=20230203' } },
      (body) => Boolean(body?.data?.attributes?.ohlcv_list?.length)));
  }
  return await Promise.all(checks);
}

async function snapshotMint(mint: string): Promise<boolean> {
  try {
    const response = await fetch('https://api.dexscreener.com/tokens/v1/solana/' + mint, {
      headers: { accept: 'application/json' }, signal: AbortSignal.timeout(9000),
    });
    if (!response.ok) return false;
    const body = await response.json();
    const pairs = (Array.isArray(body) ? body : []).filter((pair: Record<string, any>) =>
      pair?.baseToken?.address === mint && Number(pair?.priceUsd) > 0
    );
    pairs.sort((a: Record<string, any>, b: Record<string, any>) =>
      Number(b?.liquidity?.usd ?? 0) - Number(a?.liquidity?.usd ?? 0)
    );
    const pair = pairs[0];
    if (!pair) return false;
    const capturedAt = new Date().toISOString();
    const volume = pair.volume ?? {};
    const txns = pair.txns ?? {};
    const change = pair.priceChange ?? {};
    const { error } = await db.from('token_market_snapshots').insert({
      mint, captured_at: capturedAt, pair_address: pair.pairAddress ?? null,
      dex_id: pair.dexId ?? null, price_usd: Number(pair.priceUsd) || null,
      liquidity_usd: Number(pair.liquidity?.usd) || null,
      volume_m5: Number(volume.m5) || null, volume_h1: Number(volume.h1) || null,
      volume_h24: Number(volume.h24) || null,
      buys_m5: Number(txns.m5?.buys) || 0, sells_m5: Number(txns.m5?.sells) || 0,
      price_change_m5: Number(change.m5) || null,
      market_cap: Number(pair.marketCap) || null, fdv: Number(pair.fdv) || null,
      price_source: 'DexScreener', raw_data: pair,
    });
    if (error) throw error;
    await db.from('token_launches').update({
      graduation_status: 'GRADUATED', pool_address: pair.pairAddress ?? null,
      last_seen_at: capturedAt, updated_at: capturedAt,
    }).eq('mint', mint);
    return true;
  } catch {
    return false;
  }
}

Deno.serve(async (request: Request) => {
  if (request.method === 'OPTIONS') return new Response('ok');
  if (!(await authorised(request))) return Response.json({ ok: false, error: 'unauthorized' }, { status: 401 });
  const started = Date.now();
  try {
    const pump = await collectPumpPortal();
    const profilesResponse = await fetch('https://api.dexscreener.com/token-profiles/latest/v1', {
      headers: { 'accept': 'application/json', 'user-agent': 'VERUM-Meme-Intelligence/0.1' },
      signal: AbortSignal.timeout(12000),
    });
    let profileRows: Launch[] = [];
    let dexStatus = 'UNAVAILABLE';
    let dexError: string | undefined;
    if (profilesResponse.ok) {
      const profiles = await profilesResponse.json();
      profileRows = (Array.isArray(profiles) ? profiles : [])
        .filter((item: Record<string, unknown>) => item.chainId === 'solana' && item.tokenAddress)
        .slice(0, 100)
        .map((item: Record<string, unknown>) => ({
          mint: String(item.tokenAddress),
          name: null,
          symbol: null,
          creator_wallet: null,
          graduation_status: 'UNKNOWN',
          discovery_source: 'DexScreener latest profile',
          last_seen_at: new Date().toISOString(),
          raw_event: item,
          data_quality: { source: 'DexScreener', profile_only: true },
        }));
      dexStatus = 'OK';
    } else {
      dexError = 'HTTP ' + profilesResponse.status;
    }

    const launchCount = await upsertLaunches([...profileRows, ...pump.launches]);
    const { data: recentLaunches } = await db.from('token_launches')
      .select('mint').order('last_seen_at', { ascending: false }).limit(100);
    const candidateMints = [...new Set([
      ...pump.launches, ...profileRows, ...(recentLaunches ?? []),
    ].map(row => row.mint))].slice(0, 25);
    let snapshotCount = 0;
    for (let offset = 0; offset < candidateMints.length; offset += 5) {
      const batch = await Promise.all(candidateMints.slice(offset, offset + 5).map(snapshotMint));
      snapshotCount += batch.filter(Boolean).length;
    }
    await recordProvider('PumpPortal', pump.status, pump.launches.length, Date.now() - started, pump.error);
    await recordProvider('DexScreener', dexStatus, launchCount + snapshotCount, Date.now() - started, dexError);
    const healthMint = candidateMints[0];
    const providerHealth = healthMint ? await probeProviderHealth(healthMint) : [];

    return Response.json({
      ok: true, pumpportal: { status: pump.status, received: pump.launches.length, error: pump.error ?? null },
      dexscreener: { status: dexStatus, profiles: profileRows.length, snapshots: snapshotCount, error: dexError ?? null },
      stored: launchCount, provider_health: providerHealth, elapsed_ms: Date.now() - started,
      timestamp: new Date().toISOString(),
    });
  } catch (error) {
    console.error('radar-ingest failed', error instanceof Error ? error.message : 'unknown');
    return Response.json({ ok: false, error: 'ingestion_failed' }, { status: 500 });
  }
});
