-- 預測紀錄簿（prediction_log）
-- =============================
-- 「今天先把預測記下來，到期後用真實金價驗證」所需的資料表。
-- 和既有的成效驗證頁不同：那頁是挑歷史日期回頭驗證（答案已存在），
-- 這張表記的是「記錄當下還不知道答案」的預測，因此不可能事後挑選有利區間。
--
-- 在 Supabase 後台 SQL Editor 貼上整份執行即可（可重複執行）。

create table if not exists public.prediction_log (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references auth.users(id) on delete cascade,

  -- 記錄當下的狀態（全部來自記錄當天的 predictions.json，不可事後修改）
  logged_on     date not null,                       -- 預測所依據的資料截止日
  horizon       int  not null check (horizon > 0),   -- 預測幾個交易日之後
  due_on        date,                                -- 預估到期日（僅供顯示，實際驗證用 logged_on + horizon 個交易日）
  price_at_log  numeric(14,2) not null check (price_at_log > 0),
  pred_return   numeric(10,6),                       -- 模型預測的報酬率
  prob_down     numeric(6,4) check (prob_down between 0 and 1),
  hedge_ratio   numeric(6,4) check (hedge_ratio between 0 and 1),
  capital       numeric(16,2) check (capital > 0),
  risk_profile  text check (risk_profile in ('conservative','balanced','aggressive')),
  note          text,

  created_at    timestamptz not null default now()
);

create index if not exists idx_prediction_log_user
  on public.prediction_log(user_id, logged_on desc);

-- 同一個人同一天只留一筆，避免連按產生重複紀錄
create unique index if not exists uq_prediction_log_user_day
  on public.prediction_log(user_id, logged_on);

comment on table public.prediction_log is
  '使用者按下「記錄這次預測」時存下的當下預測，到期後以真實金價驗證';

-- Row Level Security：每個人只能讀寫自己的紀錄
alter table public.prediction_log enable row level security;

do $$
begin
  drop policy if exists "own_select" on public.prediction_log;
  create policy "own_select" on public.prediction_log
    for select using (auth.uid() = user_id);

  drop policy if exists "own_insert" on public.prediction_log;
  create policy "own_insert" on public.prediction_log
    for insert with check (auth.uid() = user_id);

  -- 刻意不開 update：預測紀錄一旦寫下就不該被改，否則「事後驗證」失去意義。
  drop policy if exists "own_update" on public.prediction_log;

  drop policy if exists "own_delete" on public.prediction_log;
  create policy "own_delete" on public.prediction_log
    for delete using (auth.uid() = user_id);
end $$;

-- 驗證用：
--   select relrowsecurity from pg_class where relname = 'prediction_log';        -- 應為 true
--   select policyname, cmd from pg_policies where tablename = 'prediction_log';  -- 應有 3 條
