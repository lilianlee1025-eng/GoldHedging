-- ===========================================================================
-- 黃金避險系統：在 profiles 加一欄「避險工具」
-- ===========================================================================
-- 用法：Supabase 後台 → SQL Editor → New query → 整段貼上 → Run
--
-- 為什麼需要這一欄：
--   避險成本原本是全站寫死 0.3%（COMEX 期貨），但實際上差很多——
--   台銀黃金存摺年化 2%、保護性賣權 5%。用不同工具的人，
--   看到的「這套避險划不划算」本來就該是不同的答案。
--
-- 這段可以重複執行，不會重複新增欄位、也不會動到既有資料。
-- ===========================================================================

alter table public.profiles
  add column if not exists hedge_tool text not null default 'comex';

-- 限制只能存我們認得的那幾個 key。
-- 先丟掉舊的同名約束，這樣以後新增工具時整段重跑即可。
alter table public.profiles drop constraint if exists profiles_hedge_tool_check;
alter table public.profiles
  add constraint profiles_hedge_tool_check
  check (hedge_tool in ('none','comex','gld','passbook','put'));

comment on column public.profiles.hedge_tool is
  '使用者選用的避險工具，對應 config.HEDGE_COST_SCENARIOS 的 key';

-- Row Level Security 不必再設：
-- profiles 的政策是針對整張表（auth.uid() = user_id），新增欄位自動受同一條政策保護。
-- 驗證：下面這行應該要列出 hedge_tool
select column_name, data_type, column_default
from information_schema.columns
where table_schema = 'public' and table_name = 'profiles'
order by ordinal_position;
