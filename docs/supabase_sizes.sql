-- 在 Supabase SQL Editor 中执行一次，为现有 orders 表添加 Sizes 字段。
-- 保留现有 id、created_at 和所有历史记录。
alter table public.orders
    add column if not exists contract text,
    add column if not exists activation_price numeric,
    add column if not exists side text,
    add column if not exists amount bigint,
    add column if not exists value numeric,
    add column if not exists timestamp bigint;

comment on column public.orders.timestamp is 'Sizes 报告的 Unix 毫秒时间戳';
