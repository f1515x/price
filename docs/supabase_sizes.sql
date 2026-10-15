-- 在 Supabase SQL Editor 中执行一次，为现有 orders 表添加 Sizes 字段。
-- 保留现有 id、created_at 和所有历史记录。
alter table public.orders
    add column if not exists contract text,
    add column if not exists activation_price numeric,
    add column if not exists side text,
    add column if not exists amount bigint,
    add column if not exists value numeric,
    add column if not exists timestamp bigint,
    add column if not exists quanto_multiplier text,
    add column if not exists order_price_round text;

-- 用 text 保留 Gate 返回的小数文本和尾随零，不经过浮点数。
comment on column public.orders.quanto_multiplier is '对应合约的乘数，原样保存 Gate 数字字符串';
comment on column public.orders.order_price_round is '对应合约的下单价格步长，原样保存 Gate 数字字符串';

comment on column public.orders.timestamp is 'Sizes 报告的 Unix 毫秒时间戳';
