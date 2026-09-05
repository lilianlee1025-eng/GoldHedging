-- ===========================================================================
-- 黃金避險系統 v2：正規化結構
-- ===========================================================================
-- 用法：Supabase 後台 → SQL Editor → New query → 整段貼上 → Run
-- 這份會建立三張新表，並把 user_prefs 裡的舊資料自動搬過來（不會刪掉舊表）。
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- 1. profiles：使用者的風險偏好與避險假設（1:1）
-- ---------------------------------------------------------------------------
create table if not exists public.profiles (
  user_id       uuid primary key references auth.users(id) on delete cascade,
  risk_profile  text not null default 'balanced'
                check (risk_profile in ('conservative','balanced','aggressive')),
  hedge_months  numeric(5,2)  not null default 3   check (hedge_months  > 0),
  hedge_vol     numeric(5,2)  not null default 18  check (hedge_vol     > 0),
  hedge_rate    numeric(5,2)  not null default 4.2 check (hedge_rate   >= 0),
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
comment on table public.profiles is '每位使用者的風險偏好與避險試算參數（一對一）';

-- ---------------------------------------------------------------------------
-- 2. positions：持有部位（1:N）—— 這張是整個正規化的重點
-- ---------------------------------------------------------------------------
-- 台灣人常同時持有多種形式：金條算台錢、黃金存摺算公克、ETF 算股。
-- 每一筆各自有數量、單位、成本，所以必須是獨立的列，不能塞成一包 JSON。
-- id 用 uuid 由前端產生，這樣同步時可以直接 upsert，不必先問資料庫要編號。
create table if not exists public.positions (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null references auth.users(id) on delete cascade,
  label        text,
  kind         text not null default 'bar'
               check (kind in ('bar','passbook','etf','coin','other')),
  qty          numeric(18,4) not null check (qty > 0),
  unit         text not null default 'oz'
               check (unit in ('oz','g','tqian','gld')),
  cost_per_oz  numeric(14,2) check (cost_per_oz >= 0),
  bought_at    date,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);
create index if not exists idx_positions_user on public.positions(user_id);
comment on table public.positions is '使用者持有的黃金部位，一位使用者可有多筆（一對多）';

-- ---------------------------------------------------------------------------
-- 3. ui_prefs：介面偏好（1:1）
-- ---------------------------------------------------------------------------
create table if not exists public.ui_prefs (
  user_id     uuid primary key references auth.users(id) on delete cascade,
  price_unit  text not null default 'spot' check (price_unit in ('spot','twd','gld')),
  timeframe   text not null default 'D'    check (timeframe  in ('D','W','M','Q')),
  chart_type  text not null default 'line' check (chart_type in ('line','candle')),
  qty_unit    text not null default 'oz'   check (qty_unit   in ('oz','g','tqian','gld')),
  updated_at  timestamptz not null default now()
);
comment on table public.ui_prefs is '每位使用者的介面顯示偏好（一對一）';

-- ---------------------------------------------------------------------------
-- 4. Row Level Security：三張表都只能碰自己的資料
-- ---------------------------------------------------------------------------
alter table public.profiles  enable row level security;
alter table public.positions enable row level security;
alter table public.ui_prefs  enable row level security;

do $$
declare t text;
begin
  foreach t in array array['profiles','positions','ui_prefs'] loop
    execute format('drop policy if exists "own_select" on public.%I', t);
    execute format('create policy "own_select" on public.%I for select using (auth.uid() = user_id)', t);
    execute format('drop policy if exists "own_insert" on public.%I', t);
    execute format('create policy "own_insert" on public.%I for insert with check (auth.uid() = user_id)', t);
    execute format('drop policy if exists "own_update" on public.%I', t);
    execute format('create policy "own_update" on public.%I for update using (auth.uid() = user_id) with check (auth.uid() = user_id)', t);
    execute format('drop policy if exists "own_delete" on public.%I', t);
    execute format('create policy "own_delete" on public.%I for delete using (auth.uid() = user_id)', t);
  end loop;
end $$;

-- ---------------------------------------------------------------------------
-- 5. 自動維護 updated_at
-- ---------------------------------------------------------------------------
create or replace function public.touch_updated_at()
returns trigger language plpgsql as $$
begin new.updated_at = now(); return new; end $$;

do $$
declare t text;
begin
  foreach t in array array['profiles','positions','ui_prefs'] loop
    execute format('drop trigger if exists trg_%s_touch on public.%I', t, t);
    execute format('create trigger trg_%s_touch before update on public.%I
                    for each row execute function public.touch_updated_at()', t, t);
  end loop;
end $$;

-- ---------------------------------------------------------------------------
-- 6. 把 user_prefs 的舊資料搬過來（安全：重跑不會重複）
-- ---------------------------------------------------------------------------
insert into public.profiles (user_id, risk_profile, hedge_months, hedge_vol, hedge_rate)
select user_id,
       coalesce(nullif(prefs->>'profile',''), 'balanced'),
       coalesce((prefs->'sim'->>'months')::numeric, 3),
       coalesce((prefs->'sim'->>'vol')::numeric,   18),
       coalesce((prefs->'sim'->>'rate')::numeric,  4.2)
from public.user_prefs
on conflict (user_id) do nothing;

insert into public.ui_prefs (user_id, price_unit, timeframe, chart_type, qty_unit)
select user_id,
       coalesce(nullif(prefs->>'unit',''),    'spot'),
       coalesce(nullif(prefs->>'tf',''),      'D'),
       coalesce(nullif(prefs->>'ctype',''),   'line'),
       coalesce(nullif(prefs->>'qtyUnit',''), 'oz')
from public.user_prefs
on conflict (user_id) do nothing;

-- 舊的單一部位 → 變成 positions 的第一筆。只搬有填數量的，且只搬一次。
insert into public.positions (user_id, label, kind, qty, unit, cost_per_oz)
select up.user_id, '原有部位', 'bar',
       (up.prefs->'sim'->>'ounces')::numeric,
       coalesce(nullif(up.prefs->>'qtyUnit',''), 'oz'),
       nullif(up.prefs->'sim'->>'entry','')::numeric
from public.user_prefs up
where (up.prefs->'sim'->>'ounces') is not null
  and (up.prefs->'sim'->>'ounces')::numeric > 0
  and not exists (select 1 from public.positions p where p.user_id = up.user_id);

-- ===========================================================================
-- 驗證
-- ===========================================================================
--   select tablename from pg_tables where schemaname='public';
--   select tablename, count(*) from pg_policies
--     where tablename in ('profiles','positions','ui_prefs') group by tablename;
--   select * from public.positions;
--
-- 確認新表資料都對之後，才執行下面這句移除舊表（可選，不急）：
--   drop table public.user_prefs;
