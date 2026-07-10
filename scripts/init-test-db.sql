-- Creates the test database alongside the main one.
-- Executed by PostgreSQL during container initialisation.
SELECT 'CREATE DATABASE forgeai_test OWNER forgeai'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'forgeai_test')
\gexec
