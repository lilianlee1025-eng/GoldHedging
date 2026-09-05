/* Supabase 連線設定
   ==================
   到 https://supabase.com 開一個免費專案後，在
       Project Settings → API
   會看到兩個值，貼到下面：

     Project URL   → SUPABASE_URL
     anon public   → SUPABASE_ANON_KEY   ← 一定要挑 anon，不要挑 service_role

   ⚠️ service_role 金鑰可以繞過所有安全性規則，絕對不能放在前端或推上 GitHub。
      anon 金鑰則是「設計上就要公開」的，放在這裡、進版控都沒問題——
      真正的防線是資料庫的 Row Level Security 規則（見 supabase_setup.sql）。

   兩個值留空時，網站會自動退回「只用本機記憶」模式：
   登入按鈕不會出現，其他功能完全照常運作。
*/
window.SUPABASE_URL = "https://gsddywdegnhbpfvkoskr.supabase.co";
window.SUPABASE_ANON_KEY = "sb_publishable_vrAR1tlEe0N5zDGAbAbCvw_7tz-pdOo";
