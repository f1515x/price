-- Run once before enabling the migrated workflow. Existing Orders3 secret rows are preserved.
begin;

-- Do not change permissions on an existing Orders3 credential table.
do $$
begin
    if to_regclass('public.secret') is null then
        create table public.secret (
            "API_KEY=" text not null,
            "API_SECRET=" text not null
        );
        alter table public.secret enable row level security;
        revoke all on public.secret from anon, authenticated;
        grant select on public.secret to service_role;
    end if;
end;
$$;

-- Text keeps the exact decimal representation, including trailing zeroes.
create table if not exists public.contracts (
    contract text primary key check (contract ~ '^[A-Z0-9_]+_USDT$'),
    quanto_multiplier text not null,
    order_price_round text not null,
    leverage_max text not null,
    updated_at timestamptz not null default now(),
    check (quanto_multiplier ~ '^[+]?[0-9]+([.][0-9]+)?([eE][+-]?[0-9]+)?$'
           and quanto_multiplier::numeric > 0),
    check (order_price_round ~ '^[+]?[0-9]+([.][0-9]+)?([eE][+-]?[0-9]+)?$'
           and order_price_round::numeric > 0),
    check (leverage_max ~ '^[0-9]+([.]0+)?$' and leverage_max::numeric > 0)
);

create or replace function public.price_contract_updated_at()
returns trigger language plpgsql set search_path = public as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists price_contract_updated_at on public.contracts;
create trigger price_contract_updated_at before update on public.contracts
for each row execute function public.price_contract_updated_at();

alter table public.contracts enable row level security;
revoke all on public.contracts from anon, authenticated;
grant select, insert, update on public.contracts to service_role;

commit;
notify pgrst, 'reload schema';
