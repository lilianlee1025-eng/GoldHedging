-- ===========================================================================
-- 黃金避險系統：Supabase 資料庫設定
-- ===========================================================================
-- 用法：Supabase 後台 → 左側 SQL Editor → New query → 整段貼上 → Run
-- 只需要跑這一次。
-- ===========================================================================

-- 1. 使用者設定表：一位使用者一列
-- ---------------------------------------------------------------------------
-- user_id 直接參照 Supabase 內建的 auth.users，不必自己管帳號密碼。
-- on delete cascade：使用者刪除帳號時，他的資料跟著刪掉（GDPR 友善）。
create table if not exists public.user_prefs (
  user_id    uuid primary key references auth.users(id) on delete cascade,
  prefs      jsonb       not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

comment on table  public.user_prefs is '每位使用者的部位設定與介面偏好';
comment on column public.user_prefs.prefs is
  '前端 localStorage 的同一份結構：{sim:{...}, prin:{...}, unit, tf, ctype, touched}';

-- 2. 啟用 Row Level Security（最重要的一步）
-- ---------------------------------------------------------------------------
-- 不開這個，任何拿到 anon 金鑰的人（金鑰本來就公開在前端）
-- 就能讀寫所有人的持倉資料。開了之後，預設是「全部拒絕」，
-- 再由下面的政策逐條開放。
alter table public.user_prefs enable row level security;

-- 3. 存取政策：每個人只能碰自己那一列
-- ---------------------------------------------------------------------------
-- auth.uid() 是 Supabase 從 JWT 解出來的登入者 ID，前端偽造不了。
drop policy if exists "讀自己的設定" on public.user_prefs;
create policy "讀自己的設定" on public.user_prefs
  for select using (auth.uid() = user_id);

drop policy if exists "建立自己的設定" on public.user_prefs;
create policy "建立自己的設定" on public.user_prefs
  for insert with check (auth.uid() = user_id);

-- update 要同時寫 using 和 with check：
--   using      → 決定「可以改哪些現有的列」
--   with check → 決定「改完之後的內容是否合法」
-- 少了 with check，使用者可以把自己的列的 user_id 改成別人的。
drop policy if exists "更新自己的設定" on public.user_prefs;
create policy "更新自己的設定" on public.user_prefs
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop policy if exists "刪除自己的設定" on public.user_prefs;
create policy "刪除自己的設定" on public.user_prefs
  for delete using (auth.uid() = user_id);

-- 4. 自動更新 updated_at
-- ---------------------------------------------------------------------------
-- 前端用這個欄位跟本機的時間戳比較，決定「雲端比較新還是本機比較新」。
-- 交給資料庫寫，比讓前端自己填時間可靠（不受使用者電腦時鐘影響）。
create or replace function public.touch_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end $$;

drop trigger if exists trg_user_prefs_touch on public.user_prefs;
create trigger trg_user_prefs_touch
  before update on public.user_prefs
  for each row execute function public.touch_updated_at();

-- ===========================================================================
-- 驗證：跑完後執行下面這句，應該看到 rowsecurity = true 與 4 條政策
-- ===========================================================================
--   select relrowsecurity from pg_class where relname = 'user_prefs';
--   select policyname, cmd from pg_policies where tablename = 'user_prefs';
