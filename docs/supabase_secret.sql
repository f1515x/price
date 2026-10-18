-- Historical schema only: Gate credentials now come exclusively from Infisical.
-- Do not run for new price-monitor deployments. Existing Orders3 rows are preserved.
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

commit;
notify pgrst, 'reload schema';
