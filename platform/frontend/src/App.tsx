import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { createClient, Session } from '@supabase/supabase-js';
import {
  Activity, AlertTriangle, BookOpen, Bell, ChevronRight, CircleDollarSign,
  Clock3, Database, FileSearch, FlaskConical, Gauge, LogOut, Menu, Radar as RadarIcon,
  RefreshCw, Search, ShieldAlert, ShieldCheck, SlidersHorizontal, Sparkles,
  Wallet, XCircle, Zap,
} from 'lucide-react';

const SUPABASE_URL = import.meta.env.VITE_SUPABASE_URL as string;
const SUPABASE_KEY = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY as string;
const API_BASE = (import.meta.env.VITE_API_BASE_URL as string || '').replace(/\/$/, '');
const supabase = createClient(SUPABASE_URL || 'https://invalid.supabase.co', SUPABASE_KEY || 'missing-key');

type Page = 'Signals' | 'Radar' | 'Analysis' | 'Wallets' | 'Strategy Lab' | 'Paper Trading' | 'Journal' | 'Settings';
type ApiError = { detail?: string | { code?: string; status?: string; flags?: { message: string }[]; missing_evidence?: string[] } };
const NAV: { name: Page; icon: typeof Activity }[] = [
  { name: 'Signals', icon: Activity }, { name: 'Radar', icon: RadarIcon },
  { name: 'Analysis', icon: FileSearch }, { name: 'Wallets', icon: Wallet },
  { name: 'Strategy Lab', icon: FlaskConical }, { name: 'Paper Trading', icon: CircleDollarSign },
  { name: 'Journal', icon: BookOpen }, { name: 'Settings', icon: SlidersHorizontal },
];
const money = (value?: number | null) => value == null || !Number.isFinite(Number(value))
  ? '—' : new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: Number(value) < 1 ? 6 : 2 }).format(Number(value));
const pct = (value?: number | null) => value == null || !Number.isFinite(Number(value)) ? '—' : \`${Number(value).toFixed(2)}%\`;
const shortMint = (value?: string) => value ? \`${value.slice(0, 5)}…${value.slice(-5)}\` : '—';
const stamp = (value?: string | number | null) => {
  if (!value) return '—';
  const date = new Date(typeof value === 'number' ? value * 1000 : value);
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString();
};
const errorText = (value: unknown) => value instanceof Error ? value.message : 'Request failed';

async function api<T>(path: string, session: Session | null, method = 'GET', body?: unknown): Promise<T> {
  if (!API_BASE) throw new Error('API endpoint is not configured');
  if (!session?.access_token) throw new Error('Sign in to access this workspace');
  const response = await fetch(\`${API_BASE}/api/v1${path}\`, {
    method,
    headers: { 'Content-Type': 'application/json', Authorization: \`Bearer ${session.access_token}\` },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({})) as ApiError & T;
  if (!response.ok) {
    const detail = payload?.detail;
    if (typeof detail === 'string') throw new Error(detail.replaceAll('_', ' '));
    if (detail && typeof detail === 'object') {
      const messages = [...(detail.flags || []).map(item => item.message), ...(detail.missing_evidence || [])];
      throw new Error([detail.code, detail.status, ...messages].filter(Boolean).join(' · ') || 'Request rejected');
    }
    throw new Error((payload as ApiError)?.detail as string || \`HTTP ${response.status}\`);
  }
  return payload as T;
}

function Pill({ value }: { value: string }) {
  const v = value.toUpperCase();
  const cls = ['BUY', 'PASS', 'OPEN', 'OK', 'VALIDATED', 'SUCCESS', 'GRADUATED'].includes(v) ? 'good'
    : ['BLOCKED', 'AVOID', 'WARNING', 'ERROR', 'STOP'].includes(v) ? 'bad'
    : ['INSUFFICIENT_DATA', 'UNKNOWN', 'UNAVAILABLE', 'VETO'].includes(v) ? 'muted' : 'wait';
  return <span className={\`pill ${cls}\`}>{value.replaceAll('_', ' ')}</span>;
}
function Panel({ title, subtitle, action, children, className = '' }: {
  title: string; subtitle?: string; action?: ReactNode; children: ReactNode; className?: string;
}) {
  return <section className={\`panel ${className}\`}>
    <div className="panel-head"><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>{action}</div>
    {children}
  </section>;
}
function Metric({ label, value, note }: { label: string; value: ReactNode; note?: string }) {
  return <div className="metric"><span>{label}</span><strong>{value}</strong>{note && <small>{note}</small>}</div>;
}
function Empty({ title, note }: { title: string; note: string }) {
  return <div className="empty"><div className="empty-icon"><Database size={20}/></div><strong>{title}</strong><p>{note}</p></div>;
}
function Loading({ label = 'Loading evidence…' }: { label?: string }) {
  return <div className="loading"><RefreshCw size={16} className="spin"/>{label}</div>;
}

export default function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [authReady, setAuthReady] = useState(false);
  const [email, setEmail] = useState('');
  const [authMessage, setAuthMessage] = useState('');
  const [authBusy, setAuthBusy] = useState(false);
  const [page, setPage] = useState<Page>('Signals');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [signals, setSignals] = useState<any[]>([]);
  const [launches, setLaunches] = useState<any[]>([]);
  const [providers, setProviders] = useState<any[]>([]);
  const [analysisMint, setAnalysisMint] = useState('');
  const [analysis, setAnalysis] = useState<any>(null);
  const [walletAddress, setWalletAddress] = useState('');
  const [walletReport, setWalletReport] = useState<any>(null);
  const [backtestMint, setBacktestMint] = useState('');
  const [backtest, setBacktest] = useState<any>(null);
  const [account, setAccount] = useState<any>(null);
  const [positions, setPositions] = useState<any[]>([]);
  const [journal, setJournal] = useState<any>(null);
  const [alerts, setAlerts] = useState<any[]>([]);
  const [settings, setSettings] = useState<any>({
    timezone: 'Indian/Mauritius', paper_starting_balance: 1000,
    max_risk_per_trade_pct: 0.5, max_daily_loss_pct: 2,
    max_open_positions: 3, max_total_exposure_pct: 20, max_slippage_pct: 1.5,
  });
  const [mobileMenu, setMobileMenu] = useState(false);

  useEffect(() => {
    let active = true;
    supabase.auth.getSession().then(({ data }) => {
      if (active) { setSession(data.session); setAuthReady(true); }
    }).catch(() => { if (active) setAuthReady(true); });
    const { data: listener } = supabase.auth.onAuthStateChange((_event, next) => setSession(next));
    return () => { active = false; listener.subscription.unsubscribe(); };
  }, []);

  const run = useCallback(async <T,>(task: () => Promise<T>, onSuccess: (value: T) => void) => {
    setBusy(true); setError('');
    try { const value = await task(); onSuccess(value); }
    catch (e) { setError(errorText(e)); }
    finally { setBusy(false); }
  }, []);

  const loadSignals = useCallback(() => run(
    () => api<{ signals: any[] }>('/signals?limit=12', session),
    value => setSignals(value.signals || []),
  ), [run, session]);
  const loadRadar = useCallback(() => run(
    () => Promise.all([
      api<{ tokens: any[] }>('/radar?limit=60', session),
      api<{ providers: any[] }>('/providers', session),
    ]),
    value => { setLaunches(value[0].tokens || []); setProviders(value[1].providers || []); },
  ), [run, session]);
  const loadPaper = useCallback(() => run(
    () => Promise.all([
      api<{ account: any }>('/paper/account', session),
      api<{ positions: any[] }>('/paper/positions', session),
    ]),
    value => { setAccount(value[0].account); setPositions(value[1].positions || []); },
  ), [run, session]);
  const loadJournal = useCallback(() => run(
    () => api<any>('/journal', session), value => setJournal(value),
  ), [run, session]);
  const loadSettings = useCallback(() => run(
    () => api<any>('/settings', session),
    value => {
      const saved = value.settings || {}; const a = value.paper_account || {};
      setSettings({
        timezone: saved.timezone || 'Indian/Mauritius',
        paper_starting_balance: Number(a.starting_balance ?? saved.paper_starting_balance ?? 1000),
        max_risk_per_trade_pct: Number(a.max_risk_per_trade_pct ?? saved.max_risk_per_trade_pct ?? 0.5),
        max_daily_loss_pct: Number(a.max_daily_loss_pct ?? saved.max_daily_loss_pct ?? 2),
        max_open_positions: Number(a.max_open_positions ?? saved.max_open_positions ?? 3),
        max_total_exposure_pct: Number(a.max_total_exposure_pct ?? saved.max_total_exposure_pct ?? 20),
        max_slippage_pct: Number(a.max_slippage_pct ?? saved.max_slippage_pct ?? 1.5),
      });
    },
  ), [run, session]);

  useEffect(() => {
    if (!session) return;
    if (page === 'Signals') loadSignals();
    if (page === 'Radar') loadRadar();
    if (page === 'Paper Trading') loadPaper();
    if (page === 'Journal') {
      loadJournal();
      api<{ alerts: any[] }>('/alerts', session).then(value => setAlerts(value.alerts || [])).catch(() => undefined);
    }
    if (page === 'Settings') loadSettings();
    if (page === 'Signals' || page === 'Radar') {
      api<{ alerts: any[] }>('/alerts', session).then(value => setAlerts(value.alerts || [])).catch(() => undefined);
    }
  }, [page, session, loadSignals, loadRadar, loadPaper, loadJournal, loadSettings]);

  const signIn = async () => {
    if (!email.trim()) { setAuthMessage('Enter an email address.'); return; }
    setAuthBusy(true); setAuthMessage('');
    const { error: signInError } = await supabase.auth.signInWithOtp({
      email: email.trim(), options: { emailRedirectTo: window.location.origin },
    });
    setAuthBusy(false);
    setAuthMessage(signInError ? signInError.message : 'Sign-in link sent. Open the email on this device to continue.');
  };
  const signOut = async () => {
    await supabase.auth.signOut();
    setSession(null); setSignals([]); setLaunches([]); setPositions([]); setAnalysis(null);
  };
  const selectToken = (mint: string) => { setAnalysisMint(mint); setPage('Analysis'); setAnalysis(null); };
  const analyse = () => run(
    () => api<any>(\`/tokens/${encodeURIComponent(analysisMint.trim())}/analysis\`, session),
    value => setAnalysis(value),
  );
  const analyseWallet = () => run(
    () => api<any>(\`/wallets/${encodeURIComponent(walletAddress.trim())}\`, session),
    value => setWalletReport(value),
  );
  const runBacktest = () => run(
    () => api<any>('/strategy-lab/backtest', session, 'POST', { mint: backtestMint.trim() }),
    value => setBacktest(value.result),
  );
  const openPaper = (mint: string) => run(
    () => api<any>('/paper/trades', session, 'POST', { mint, strategy: 'manual_paper_research' }),
    async () => {
      setPage('Paper Trading');
      const [a, p] = await Promise.all([
        api<{ account: any }>('/paper/account', session),
        api<{ positions: any[] }>('/paper/positions', session),
      ]);
      setAccount(a.account); setPositions(p.positions || []);
    },
  );
  const closePaper = (id: string) => run(
    () => api<any>(\`/paper/positions/${id}/close\`, session, 'POST', {}),
    async () => {
      const [a, p] = await Promise.all([
        api<{ account: any }>('/paper/account', session),
        api<{ positions: any[] }>('/paper/positions', session),
      ]);
      setAccount(a.account); setPositions(p.positions || []);
    },
  );
  const saveSettings = () => run(
    () => api<any>('/settings', session, 'PUT', settings),
    value => { setAccount(value.paper_account || account); setAuthMessage('Risk settings saved.'); },
  );
  const unreadAlerts = useMemo(() => alerts.filter(item => !item.read_at).length, [alerts]);

  if (!authReady) return <div className="auth-shell"><Loading label="Restoring secure session…"/></div>;
  if (!session) return <div className="auth-shell">
    <div className="auth-card">
      <div className="brand-mark"><span>V</span></div>
      <div className="eyebrow">INDEPENDENT SOLANA INTELLIGENCE</div>
      <h1>VERUM</h1><p className="auth-sub">Evidence before signals. Risk before execution.</p>
      <div className="auth-divider"/>
      <label htmlFor="email">Email address</label>
      <input id="email" type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="you@example.com" autoComplete="email"/>
      <button className="primary wide" onClick={signIn} disabled={authBusy}>{authBusy ? 'Sending link…' : 'Send secure sign-in link'}</button>
      {authMessage && <p className="inline-note">{authMessage}</p>}
      <div className="auth-foot"><ShieldCheck size={15}/> Supabase-authenticated · Private paper records · No wallet connection</div>
    </div>
  </div>;

  return <div className="app-shell">
    <header className="topbar">
      <div className="brand"><div className="brand-mark small"><span>V</span></div><div><strong>VERUM</strong><small>MEME INTELLIGENCE</small></div></div>
      <div className="top-status"><span className="live-dot"/> DATA-LED RESEARCH <span className="paper-label">PAPER ONLY</span></div>
      <div className="top-actions">
        <button className="icon-button alert-button" onClick={() => setPage('Journal')} aria-label="Open journal and alerts"><Bell size={18}/>{unreadAlerts > 0 && <i>{unreadAlerts}</i>}</button>
        <span className="user-chip">{session.user.email?.split('@')[0] || 'Researcher'}</span>
        <button className="icon-button" onClick={signOut} aria-label="Sign out"><LogOut size={17}/></button>
        <button className="icon-button mobile-menu-button" onClick={() => setMobileMenu(!mobileMenu)} aria-label="Toggle navigation">{mobileMenu ? <XCircle size={18}/> : <Menu size={18}/>}</button>
      </div>
    </header>
    <div className="workspace">
      <aside className={\`sidebar ${mobileMenu ? 'show' : ''}\`}>
        <div className="side-caption">WORKSPACE</div>
        {NAV.map(item => {
          const Icon = item.icon;
          return <button key={item.name} className={\`nav-item ${page === item.name ? 'active' : ''}\`} onClick={() => { setPage(item.name); setMobileMenu(false); setError(''); }}>
            <Icon size={17}/><span>{item.name}</span>{item.name === 'Signals' && <span className="nav-count">{signals.length || '—'}</span>}
          </button>;
        })}
        <div className="sidebar-foot"><div className="side-caption">SYSTEM STATUS</div>
          <div className="system-line"><span className="live-dot"/> API session active</div>
          <div className="system-line"><ShieldCheck size={14}/> Live trading disabled</div>
          <div className="system-line"><Database size={14}/> Persistent database</div>
          <small>VERUM v0.1.0 · Research release</small>
        </div>
      </aside>
      <main className="main-content">
        <div className="page-heading"><div><div className="eyebrow">VERUM / {page.toUpperCase()}</div><h1>{page}</h1></div><div className="heading-right"><span className="paper-label"><ShieldAlert size={13}/> PAPER ENVIRONMENT</span></div></div>
        {error && <div className="error-banner"><AlertTriangle size={16}/><span>{error}</span><button onClick={() => setError('')} aria-label="Dismiss error"><XCircle size={16}/></button></div>}

        {page === 'Signals' && <div className="page-stack">
          <div className="intro-strip"><div><Sparkles size={18}/><span>Qualified opportunities only. Missing evidence is not a green light.</span></div><button className="secondary" onClick={loadSignals} disabled={busy}><RefreshCw size={15} className={busy ? 'spin' : ''}/> Refresh intelligence</button></div>
          {busy && signals.length === 0 ? <Loading label="Investigating recent launches…"/> :
            signals.length === 0 ? <Empty title="No qualified signals" note="The engine has no sufficiently evidenced candidates yet. Check Radar for recent launches or refresh the investigation."/> :
            <div className="signal-grid">{signals.map(item => <button className="signal-card" key={item.mint} onClick={() => selectToken(item.mint)}>
              <div className="signal-top"><div><strong>{item.token?.symbol || shortMint(item.mint)}</strong><small>{item.token?.name || shortMint(item.mint)}</small></div><Pill value={item.signal?.status || 'UNKNOWN'}/></div>
              <div className="signal-price">{money(item.market?.price_usd)}<small>Current reference price</small></div>
              <div className="signal-levels"><div><span>ENTRY</span><b>{money(item.trade_plan?.entry)}</b></div><div><span>TP1</span><b>{money(item.trade_plan?.take_profit_1)}</b></div><div><span>STOP</span><b>{money(item.trade_plan?.stop_loss)}</b></div></div>
              <div className="signal-foot"><span>Confidence <b>{pct((item.signal?.confidence || 0) * 100)}</b></span><span>Liquidity <b>{money(item.market?.liquidity_usd)}</b></span></div>
              <div className="freshness"><Clock3 size={12}/> Checked {stamp(item.data_freshness?.checked_at)}</div>
              <p className="signal-reason">{item.signal?.reasons?.[0] || 'Review evidence and quote availability'}</p>
            </button>)}</div>}
          <Panel title="Signal discipline" subtitle="A signal is not an instruction to risk capital.">
            <div className="discipline-grid"><div><ShieldCheck size={18}/><strong>Security veto</strong><span>Critical authority, transfer or liquidity risks override momentum.</span></div><div><Gauge size={18}/><strong>Empirical gate</strong><span>BUY remains disabled until independent out-of-sample evidence qualifies.</span></div><div><Zap size={18}/><strong>Quote validation</strong><span>Paper fills require a fresh executable Jupiter route.</span></div></div>
          </Panel>
        </div>}

        {page === 'Radar' && <div className="page-stack">
          <Panel title="Pump.fun launch radar" subtitle="Observed create and migration events, supplemented by DEX discovery." action={<button className="secondary" onClick={loadRadar} disabled={busy}><RefreshCw size={14} className={busy?'spin':''}/> Refresh</button>}>
            {busy && launches.length === 0 ? <Loading/> : launches.length === 0 ? <Empty title="Waiting for launch observations" note="The persistent ingestion job samples PumpPortal every five minutes. New observations will appear here."/> :
              <div className="table-wrap"><table><thead><tr><th>Token</th><th>Lifecycle</th><th>Price</th><th>Liquidity</th><th>Creator</th><th>Discovery source</th><th>Last seen</th><th></th></tr></thead><tbody>
                {launches.map(item => <tr key={item.mint}><td><strong>{item.symbol || shortMint(item.mint)}</strong><small>{item.name || shortMint(item.mint)}</small></td><td><Pill value={item.graduation_status || 'UNKNOWN'}/></td><td>{money(item.market?.price_usd)}</td><td>{money(item.market?.liquidity_usd)}</td><td className="mono">{shortMint(item.creator_wallet)}</td><td>{item.discovery_source}</td><td>{stamp(item.last_seen_at)}</td><td><button className="text-button" onClick={() => selectToken(item.mint)}>Investigate <ChevronRight size={13}/></button></td></tr>)}
              </tbody></table></div>}
          </Panel>
          <Panel title="Provider health" subtitle="Availability is not a guarantee of complete or current data.">
            <div className="provider-grid">{providers.length ? providers.map(item => <div className="provider-row" key={item.provider}><span>{item.provider}</span><Pill value={item.status}/><small>{stamp(item.last_success_at)}</small></div>) : <Empty title="No provider heartbeat recorded" note="Provider status appears after the first background ingestion cycle."/>}</div>
          </Panel>
        </div>}

        {page === 'Analysis' && <div className="page-stack">
          <Panel title="Token investigation" subtitle="Enter the exact Solana mint address. Ticker symbols are not unique.">
            <div className="search-row"><input value={analysisMint} onChange={e => setAnalysisMint(e.target.value)} placeholder="Solana token mint address" spellCheck={false}/><button className="primary" onClick={analyse} disabled={busy || !analysisMint.trim()}><Search size={15}/> Analyse</button></div>
          </Panel>
          {analysis && <div className="page-stack">
            <div className="analysis-title"><div><h2>{analysis.token?.name || shortMint(analysis.mint)} <span>{analysis.token?.symbol}</span></h2><code>{analysis.mint}</code></div><div className="analysis-status"><Pill value={analysis.signal?.status || 'UNKNOWN'}/><Pill value={analysis.security?.status || 'UNKNOWN'}/></div></div>
            <div className="metric-grid"><Metric label="Reference price" value={money(analysis.market?.price_usd)}/><Metric label="Liquidity" value={money(analysis.market?.liquidity_usd)}/><Metric label="Market cap" value={money(analysis.market?.market_cap)}/><Metric label="Evidence coverage" value={pct((analysis.evidence_coverage || 0)*100)}/></div>
            <Panel title="Security assessment" subtitle="Unknown fields are not interpreted as safe.">
              <div className="security-summary"><Pill value={analysis.security?.status || 'UNKNOWN'}/><span>{analysis.security?.interpretation}</span></div>
              <div className="fact-grid"><div><span>Mint authority</span><b>{analysis.security?.mint_authority ?? 'UNKNOWN'}</b></div><div><span>Freeze authority</span><b>{analysis.security?.freeze_authority ?? 'UNKNOWN'}</b></div><div><span>Top 10 holders</span><b>{pct(analysis.security?.top10_holder_pct)}</b></div><div><span>Developer holdings</span><b>{pct(analysis.security?.dev_hold_pct)}</b></div><div><span>LP locked/burned</span><b>{pct(analysis.security?.lp_locked_pct)}</b></div><div><span>RugCheck score</span><b>{analysis.security?.rugcheck_score ?? 'UNKNOWN'}</b></div></div>
              {analysis.security?.flags?.length ? <div className="finding-list">{analysis.security.flags.map((flag:any,i:number)=><div className="finding" key={i}><AlertTriangle size={14}/><span>{flag.message}</span><Pill value={flag.level}/></div>)}</div> : <p className="muted-copy">No reported flags in the returned provider data. This is not a safety guarantee.</p>}
              {analysis.security?.missing_evidence?.length > 0 && <div className="missing-list"><strong>Missing evidence</strong>{analysis.security.missing_evidence.map((item:string)=><span key={item}>• {item}</span>)}</div>}
            </Panel>
            <Panel title="Market and quant features">
              <div className="metric-grid"><Metric label="RSI 14" value={analysis.features?.rsi14?.toFixed?.(1) ?? '—'}/><Metric label="ATR 14" value={analysis.features?.atr14?.toPrecision?.(5) ?? '—'}/><Metric label="Volume ratio" value={analysis.features?.volume_ratio?.toFixed?.(2) ?? '—'} note="vs prior 20 candles"/><Metric label="Trend" value={analysis.features?.trend || 'UNKNOWN'}/></div>
              <div className="fact-grid"><div><span>Lifecycle</span><b>{analysis.lifecycle}</b></div><div><span>DEX</span><b>{analysis.market?.dex_id || 'UNKNOWN'}</b></div><div><span>Buys / sells (1h)</span><b>{analysis.market?.buys_h1 ?? '—'} / {analysis.market?.sells_h1 ?? '—'}</b></div><div><span>Volume (24h)</span><b>{money(analysis.market?.volume_h24)}</b></div></div>
            </Panel>
            <Panel title="Adaptive trade plan" subtitle="Volatility-derived levels. A paper entry still requires a fresh route quote.">
              <div className="metric-grid"><Metric label="Entry reference" value={money(analysis.trade_plan?.entry)}/><Metric label="Stop-loss" value={money(analysis.trade_plan?.stop_loss)}/><Metric label="Target 1" value={money(analysis.trade_plan?.take_profit_1)}/><Metric label="Target 2" value={money(analysis.trade_plan?.take_profit_2)}/></div>
              <div className="button-row"><button className="primary" onClick={() => openPaper(analysis.mint)} disabled={busy || analysis.signal?.status !== 'BUY' || analysis.security?.status !== 'PASS' || analysis.lifecycle !== 'GRADUATED'}><CircleDollarSign size={15}/> Open paper position</button><span className="muted-copy">Enabled only for BUY signals with complete security evidence and an executable quote.</span></div>
            </Panel>
            <Panel title="Intelligence Council" subtitle="Independent analytical passes; missing evidence remains visible.">
              <div className="council-list">{(analysis.council || []).map((item:any)=><div className="council-row" key={item.role}><div><strong>{item.role}</strong><small>{item.finding}</small></div><Pill value={item.status}/><small>{pct((item.confidence || 0)*100)}</small></div>)}</div>
            </Panel>
            <Panel title="Evidence provenance"><div className="provider-grid">{(analysis.provenance || []).map((item:any)=><div className="provider-row" key={item.source}><span>{item.source}</span><Pill value={item.status}/><small>{stamp(item.fetched_at)}</small></div>)}</div></Panel>
          </div>}
        </div>}

        {page === 'Wallets' && <div className="page-stack">
          <Panel title="Wallet investigator" subtitle="Activity analysis is not realised profitability.">
            <div className="search-row"><input value={walletAddress} onChange={e=>setWalletAddress(e.target.value)} placeholder="Solana wallet address" spellCheck={false}/><button className="primary" onClick={analyseWallet} disabled={busy || !walletAddress.trim()}><Search size={15}/> Investigate</button></div>
          </Panel>
          {walletReport && <Panel title="Wallet evidence">
            <div className="analysis-title"><code>{walletReport.wallet}</code><Pill value={walletReport.performance_status}/></div>
            <div className="metric-grid"><Metric label="Recent transactions" value={walletReport.recent_transactions}/><Metric label="Creator launches" value={walletReport.creator_launches?.length || 0}/><Metric label="Realised P&L" value="UNKNOWN"/><Metric label="Sample coverage" value={walletReport.coverage?.transactions_sampled ?? 0}/></div>
            <p className="muted-copy">{walletReport.conclusion}</p>
            {walletReport.creator_launches?.length > 0 && <div className="table-wrap"><table><thead><tr><th>Created token</th><th>First observed</th></tr></thead><tbody>{walletReport.creator_launches.map((row:any)=><tr key={row.mint}><td>{row.symbol || shortMint(row.mint)}</td><td>{stamp(row.first_seen_at)}</td></tr>)}</tbody></table></div>}
          </Panel>}
        </div>}

        {page === 'Strategy Lab' && <div className="page-stack">
          <Panel title="Strategy laboratory" subtitle="Chronological 70/30 holdout, fees and slippage included.">
            <div className="search-row"><input value={backtestMint} onChange={e=>setBacktestMint(e.target.value)} placeholder="Solana mint address" spellCheck={false}/><button className="primary" onClick={runBacktest} disabled={busy || !backtestMint.trim()}><FlaskConical size={15}/> Run backtest</button></div>
            <p className="muted-copy">Baseline: 15-bar close breakout, 1.5× volume, 1.5 ATR stop, 2R target, 60-bar time exit. Optimisation is not run on the holdout.</p>
          </Panel>
          {backtest && <div className="page-stack">
            <div className="analysis-title"><div><h2>Research result</h2><code>Dataset {backtest.dataset_fingerprint?.slice(0,16)}</code></div><Pill value={backtest.strategy_validation || backtest.status}/></div>
            {backtest.status === 'INSUFFICIENT_DATA' ? <Empty title="Insufficient historical data" note={\`Observed ${backtest.bars} bars. At least ${backtest.required_bars} are required.\`}/> :
              <>
                <div className="metric-grid"><Metric label="Out-of-sample trades" value={backtest.out_of_sample?.trades ?? 0}/><Metric label="OOS expectancy" value={backtest.out_of_sample?.expectancy_r == null ? '—' : \`${backtest.out_of_sample.expectancy_r.toFixed(3)}R\`}/><Metric label="Profit factor" value={backtest.out_of_sample?.profit_factor?.toFixed?.(2) ?? '—'}/><Metric label="Max drawdown" value={backtest.out_of_sample?.max_drawdown_r?.toFixed?.(2) ?? '—'} note="R units"/></div>
                <div className="two-col">
                  <Panel title="In-sample"><div className="fact-grid"><div><span>Trades</span><b>{backtest.in_sample?.trades}</b></div><div><span>Win rate</span><b>{pct((backtest.in_sample?.win_rate || 0)*100)}</b></div><div><span>Expectancy</span><b>{backtest.in_sample?.expectancy_r?.toFixed?.(3) ?? '—'}R</b></div><div><span>Profit factor</span><b>{backtest.in_sample?.profit_factor?.toFixed?.(2) ?? '—'}</b></div></div></Panel>
                  <Panel title="Out-of-sample"><div className="fact-grid"><div><span>Trades</span><b>{backtest.out_of_sample?.trades}</b></div><div><span>Win rate</span><b>{pct((backtest.out_of_sample?.win_rate || 0)*100)}</b></div><div><span>Expectancy</span><b>{backtest.out_of_sample?.expectancy_r?.toFixed?.(3) ?? '—'}R</b></div><div><span>Profit factor</span><b>{backtest.out_of_sample?.profit_factor?.toFixed?.(2) ?? '—'}</b></div></div></Panel>
                </div>
                <Panel title="Uncertainty and risk"><div className="fact-grid"><div><span>Bootstrap 95% lower</span><b>{backtest.expectancy_ci_95?.lower?.toFixed?.(3) ?? '—'}R</b></div><div><span>Bootstrap 95% upper</span><b>{backtest.expectancy_ci_95?.upper?.toFixed?.(3) ?? '—'}R</b></div><div><span>Risk of 50% drawdown</span><b>{pct((backtest.risk_of_ruin?.probability_half || 0)*100)}</b></div><div><span>Bootstrap runs</span><b>{backtest.expectancy_ci_95?.runs ?? 0}</b></div></div><p className="muted-copy">{backtest.validation_rule}. This is a research gate, not a profitability promise.</p></Panel>
              </>}
          </div>}
        </div>}

        {page === 'Paper Trading' && <div className="page-stack">
          <div className="metric-grid"><Metric label="Virtual equity" value={money(account?.equity ?? account?.starting_balance)} note="Simulation only"/><Metric label="Available cash" value={money(account?.cash_balance)}/><Metric label="Open positions" value={positions.filter(p=>p.status==='OPEN').length}/><Metric label="Risk / trade" value={pct(account?.max_risk_per_trade_pct)}/></div>
          <Panel title="Open paper positions" subtitle="Quotes and fills are simulated; no transaction is signed or broadcast." action={<button className="secondary" onClick={loadPaper} disabled={busy}><RefreshCw size={14}/> Refresh</button>}>
            {positions.filter(p=>p.status==='OPEN').length === 0 ? <Empty title="No open paper positions" note="Investigate a graduated token with complete security evidence before opening a simulated position."/> :
              <div className="position-list">{positions.filter(p=>p.status==='OPEN').map(item=><div className="position-row" key={item.id}>
                <div className="position-main"><strong>{item.symbol || shortMint(item.mint)}</strong><small>{shortMint(item.mint)} · opened {stamp(item.opened_at)}</small></div>
                <div><span>Entry</span><b>{money(item.entry_price)}</b></div><div><span>Mark</span><b>{money(item.current_price)}</b></div><div><span>Stop</span><b>{money(item.stop_loss)}</b></div>
                <div><span>Unrealised</span><b className={(item.unrealised_pnl||0)>=0?'positive':'negative'}>{money(item.unrealised_pnl)}</b></div>
                <button className="secondary small-button" onClick={()=>closePaper(item.id)} disabled={busy}>Close</button>
              </div>)}</div>}
          </Panel>
          <Panel title="Execution constraints"><div className="fact-grid"><div><span>Daily loss cap</span><b>{pct(account?.max_daily_loss_pct)}</b></div><div><span>Max exposure</span><b>{pct(account?.max_total_exposure_pct)}</b></div><div><span>Max price impact</span><b>{pct(account?.max_slippage_pct)}</b></div><div><span>Max positions</span><b>{account?.max_open_positions ?? '—'}</b></div></div><p className="muted-copy">The Risk Manager enforces these controls server-side. Three consecutive losing exits and a 10% portfolio drawdown trigger a pause.</p></Panel>
        </div>}

        {page === 'Journal' && <div className="page-stack">
          <Panel title="Trade journal" subtitle="Realised results from simulated fills only." action={<button className="secondary" onClick={loadJournal} disabled={busy}><RefreshCw size={14}/> Refresh</button>}>
            {journal ? <>
              <div className="metric-grid"><Metric label="Closed trades" value={journal.closed_trades}/><Metric label="Realised P&L" value={money(journal.realised_pnl_usd)}/><Metric label="Win rate" value={pct((journal.win_rate || 0)*100)}/><Metric label="All records" value={journal.trades?.length || 0}/></div>
              {journal.trades?.length ? <div className="table-wrap"><table><thead><tr><th>Time</th><th>Token</th><th>Side</th><th>Price</th><th>Gross USD</th><th>Fees</th><th>P&L</th></tr></thead><tbody>{journal.trades.map((row:any)=><tr key={row.id}><td>{stamp(row.created_at)}</td><td>{row.symbol || shortMint(row.mint)}</td><td><Pill value={row.side}/></td><td>{money(row.price)}</td><td>{money(row.gross_usd)}</td><td>{money(row.fees_usd)}</td><td className={(row.pnl_usd||0)>=0?'positive':'negative'}>{row.pnl_usd == null?'—':money(row.pnl_usd)}</td></tr>)}</tbody></table></div> : <Empty title="Journal is empty" note="Paper trades will be recorded here with quote source, fees and timestamps."/>}
            </> : <Empty title="No journal loaded" note="Refresh to retrieve your persistent trade records."/>}
          </Panel>
          {alerts.length > 0 && <Panel title="Recent alerts"><div className="finding-list">{alerts.slice(0,20).map((item:any)=><div className="finding" key={item.id}><Bell size={14}/><span>{item.message}</span><Pill value={item.severity}/></div>)}</div></Panel>}
        </div>}

        {page === 'Settings' && <div className="page-stack">
          <Panel title="Paper risk controls" subtitle="These settings affect only the virtual portfolio.">
            <div className="settings-grid">
              <label>Virtual starting balance (USD)<input type="number" min="50" step="50" value={settings.paper_starting_balance} onChange={e=>setSettings({...settings,paper_starting_balance:Number(e.target.value)})}/><small>Locked after first paper trade.</small></label>
              <label>Maximum risk per trade (%)<input type="number" min="0.1" max="2" step="0.1" value={settings.max_risk_per_trade_pct} onChange={e=>setSettings({...settings,max_risk_per_trade_pct:Number(e.target.value)})}/></label>
              <label>Maximum daily loss (%)<input type="number" min="0.5" max="10" step="0.5" value={settings.max_daily_loss_pct} onChange={e=>setSettings({...settings,max_daily_loss_pct:Number(e.target.value)})}/></label>
              <label>Maximum open positions<input type="number" min="1" max="10" step="1" value={settings.max_open_positions} onChange={e=>setSettings({...settings,max_open_positions:Number(e.target.value)})}/></label>
              <label>Maximum total exposure (%)<input type="number" min="1" max="100" step="1" value={settings.max_total_exposure_pct} onChange={e=>setSettings({...settings,max_total_exposure_pct:Number(e.target.value)})}/></label>
              <label>Maximum quoted impact (%)<input type="number" min="0.1" max="10" step="0.1" value={settings.max_slippage_pct} onChange={e=>setSettings({...settings,max_slippage_pct:Number(e.target.value)})}/></label>
            </div>
            <div className="button-row"><button className="primary" onClick={saveSettings} disabled={busy}>Save risk controls</button>{authMessage && <span className="success-copy">{authMessage}</span>}</div>
          </Panel>
          <Panel title="Platform configuration">
            <div className="config-line"><span>API endpoint</span><b>{API_BASE || 'Not configured'}</b></div><div className="config-line"><span>Database</span><Pill value="Supabase"/></div><div className="config-line"><span>Execution</span><Pill value="PAPER ONLY"/></div><div className="config-line"><span>Wallet access</span><Pill value="DISABLED"/></div>
            <p className="muted-copy">Provider credentials are server-side only. No private keys, seed phrases or wallet permissions are requested by VERUM.</p>
          </Panel>
        </div>}
        <footer className="footer"><span>VERUM Meme Intelligence · 0.1.0</span><span>Evidence before signals · Risk before execution · Paper only</span></footer>
      </main>
    </div>
  </div>;
}
