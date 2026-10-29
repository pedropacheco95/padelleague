-- Read-only database role for the chatbot (finding: the chatbot ran LLM-generated SQL
-- as the application user). Apply by hand on production as a superuser / the DB owner;
-- nothing in the app or CI runs this file.
--
--   psql -h <prod> -U postgres -d padel_league -v chatbot_password='<strong password>' -f chatbot_readonly_role.sql
--
-- Then set CHATBOT_DATABASE_URI=postgresql://ppl_chatbot:<password>@<host>:5432/padel_league
-- in the container's environment (.env.prod). The app falls back to its own connection
-- while the variable is unset, so the switch can be made whenever convenient.
--
-- What the role can do: SELECT on every current and future table in schema `public`
-- except `users` (credentials) and `chatbot_logs` (other visitors' questions).
-- What it cannot do: write anything, read `legacy` or `compat`, create objects,
-- hold a query longer than 5 s, or log in from more than 3 connections.

\set ON_ERROR_STOP on

BEGIN;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ppl_chatbot') THEN
        EXECUTE format('CREATE ROLE ppl_chatbot LOGIN PASSWORD %L NOINHERIT NOCREATEDB NOCREATEROLE NOSUPERUSER CONNECTION LIMIT 3',
                       :'chatbot_password');
    END IF;
END
$$;

-- Session defaults the application cannot override from inside a transaction.
ALTER ROLE ppl_chatbot SET default_transaction_read_only = on;
ALTER ROLE ppl_chatbot SET statement_timeout = '5s';
ALTER ROLE ppl_chatbot SET idle_in_transaction_session_timeout = '10s';
ALTER ROLE ppl_chatbot SET search_path = public;

GRANT CONNECT ON DATABASE padel_league TO ppl_chatbot;

-- Start from nothing: PUBLIC grants (schema public is world-usable by default on PG < 15).
REVOKE ALL ON SCHEMA public FROM ppl_chatbot;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM ppl_chatbot;
REVOKE ALL ON SCHEMA legacy FROM ppl_chatbot;
REVOKE ALL ON SCHEMA compat FROM ppl_chatbot;

GRANT USAGE ON SCHEMA public TO ppl_chatbot;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO ppl_chatbot;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO ppl_chatbot;
REVOKE ALL ON TABLE public.users FROM ppl_chatbot;
REVOKE ALL ON TABLE public.chatbot_logs FROM ppl_chatbot;

-- Tables created later by the application user (migrations) are readable too,
-- except that users/chatbot_logs stay revoked above (existing tables only).
ALTER DEFAULT PRIVILEGES FOR ROLE padel_user IN SCHEMA public GRANT SELECT ON TABLES TO ppl_chatbot;
ALTER DEFAULT PRIVILEGES FOR ROLE padel_user IN SCHEMA public GRANT SELECT ON SEQUENCES TO ppl_chatbot;

COMMIT;

-- Check (run as ppl_chatbot):
--   select count(*) from players;                 -- ok
--   select password from users;                   -- ERROR: permission denied for table users
--   update players set name = name where false;   -- ERROR: cannot execute UPDATE in a read-only transaction
--   select * from legacy.users;                   -- ERROR: permission denied for schema legacy
