CREATE DATABASE hwdb;

CREATE USER hwdb_admin WITH PASSWORD 'password';

GRANT ALL PRIVILEGES ON DATABASE hwdb TO hwdb_admin;

-- Connect to the database and grant schema permissions
\c hwdb

-- Grant permissions on the public schema
GRANT ALL ON SCHEMA public TO hwdb_admin;
GRANT CREATE ON SCHEMA public TO hwdb_admin;