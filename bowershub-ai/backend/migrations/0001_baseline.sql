-- 0001_baseline.sql — squashed schema baseline (project-review.md C2).
--
-- Generated from a schema-only pg_dump of the live 'finance' database (PG16).
-- Single source of truth for building the schema from an EMPTY database.
-- The migration-tracking table public.bh_migrations is intentionally EXCLUDED
-- (run_migrations() owns it). Pre-baseline granular migrations are preserved
-- under backend/migrations/_archive/ and are not re-run; databases that predate
-- the baseline adopt it without executing it (see backend/database.py).
-- Forward-only migrations follow as 0002_*.sql, 0003_*.sql, ...
--
-- NOTE: schema only — no seed/config data (tracked separately, see context-log).

--
-- PostgreSQL database dump
--


-- Dumped from database version 16.13
-- Dumped by pg_dump version 16.13

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: cook; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA cook;


--
-- Name: SCHEMA cook; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA cook IS 'Recipes, cook log, finished-dish photos.';


--
-- Name: files; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA files;


--
-- Name: SCHEMA files; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA files IS 'Canonical asset metadata. Every uploaded file lives here exactly once.';


--
-- Name: finance; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA finance;


--
-- Name: house; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA house;


--
-- Name: SCHEMA house; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA house IS 'Room photos, future 3D map seed data.';


--
-- Name: inventory; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA inventory;


--
-- Name: SCHEMA inventory; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA inventory IS 'Tools, saw blades, wood, albums, etc.';


--
-- Name: pgcrypto; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;


--
-- Name: EXTENSION pgcrypto; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION pgcrypto IS 'cryptographic functions';


--
-- Name: update_updated_at(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.update_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: cook_log; Type: TABLE; Schema: cook; Owner: -
--

CREATE TABLE cook.cook_log (
    id bigint NOT NULL,
    recipe_id bigint NOT NULL,
    cooked_at date DEFAULT CURRENT_DATE NOT NULL,
    servings_made integer,
    adjustments text,
    rating smallint,
    notes text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: cook_log_id_seq; Type: SEQUENCE; Schema: cook; Owner: -
--

CREATE SEQUENCE cook.cook_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: cook_log_id_seq; Type: SEQUENCE OWNED BY; Schema: cook; Owner: -
--

ALTER SEQUENCE cook.cook_log_id_seq OWNED BY cook.cook_log.id;


--
-- Name: recipe_files; Type: TABLE; Schema: cook; Owner: -
--

CREATE TABLE cook.recipe_files (
    recipe_id bigint NOT NULL,
    asset_id uuid NOT NULL,
    file_role text,
    is_primary boolean DEFAULT false NOT NULL,
    linked_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: recipes; Type: TABLE; Schema: cook; Owner: -
--

CREATE TABLE cook.recipes (
    id bigint NOT NULL,
    title text NOT NULL,
    slug text,
    source text,
    servings integer,
    calories_each integer,
    notes text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: recipes_id_seq; Type: SEQUENCE; Schema: cook; Owner: -
--

CREATE SEQUENCE cook.recipes_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: recipes_id_seq; Type: SEQUENCE OWNED BY; Schema: cook; Owner: -
--

ALTER SEQUENCE cook.recipes_id_seq OWNED BY cook.recipes.id;


--
-- Name: assets; Type: TABLE; Schema: files; Owner: -
--

CREATE TABLE files.assets (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    path text NOT NULL,
    original_name text,
    mime text NOT NULL,
    size_bytes bigint NOT NULL,
    sha256 text NOT NULL,
    domain text,
    uploaded_at timestamp with time zone DEFAULT now() NOT NULL,
    uploaded_by text,
    ai_summary text,
    ai_extracted jsonb,
    ai_model text,
    processed_at timestamp with time zone
);


--
-- Name: TABLE assets; Type: COMMENT; Schema: files; Owner: -
--

COMMENT ON TABLE files.assets IS 'Canonical record for every uploaded file across all domains.';


--
-- Name: COLUMN assets.path; Type: COMMENT; Schema: files; Owner: -
--

COMMENT ON COLUMN files.assets.path IS 'Absolute host path today; may become object-store URI later.';


--
-- Name: COLUMN assets.domain; Type: COMMENT; Schema: files; Owner: -
--

COMMENT ON COLUMN files.assets.domain IS 'High-level bucket: receipt, tool, saw_blade, album, manual, house_room, cook_recipe, etc. NULL = unclassified/inbox.';


--
-- Name: COLUMN assets.ai_extracted; Type: COMMENT; Schema: files; Owner: -
--

COMMENT ON COLUMN files.assets.ai_extracted IS 'Domain-specific JSON from the vision pass. Shape varies by domain; consumers parse defensively.';


--
-- Name: accounts; Type: TABLE; Schema: finance; Owner: -
--

CREATE TABLE finance.accounts (
    id character varying(128) NOT NULL,
    org_name character varying(256),
    account_name character varying(256),
    currency character varying(8) DEFAULT 'USD'::character varying NOT NULL,
    last_balance numeric(12,2),
    last_balance_date date,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: alert_log; Type: TABLE; Schema: finance; Owner: -
--

CREATE TABLE finance.alert_log (
    id integer NOT NULL,
    category_id integer NOT NULL,
    alert_type character varying(16) NOT NULL,
    alert_date date DEFAULT CURRENT_DATE NOT NULL,
    amount_spent numeric(10,2),
    percentage_used integer,
    sent_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: alert_log_id_seq; Type: SEQUENCE; Schema: finance; Owner: -
--

CREATE SEQUENCE finance.alert_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: alert_log_id_seq; Type: SEQUENCE OWNED BY; Schema: finance; Owner: -
--

ALTER SEQUENCE finance.alert_log_id_seq OWNED BY finance.alert_log.id;


--
-- Name: budgets; Type: TABLE; Schema: finance; Owner: -
--

CREATE TABLE finance.budgets (
    id integer NOT NULL,
    category_id integer NOT NULL,
    month date NOT NULL,
    limit_amount numeric(10,2) NOT NULL
);


--
-- Name: budgets_id_seq; Type: SEQUENCE; Schema: finance; Owner: -
--

CREATE SEQUENCE finance.budgets_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: budgets_id_seq; Type: SEQUENCE OWNED BY; Schema: finance; Owner: -
--

ALTER SEQUENCE finance.budgets_id_seq OWNED BY finance.budgets.id;


--
-- Name: categories; Type: TABLE; Schema: finance; Owner: -
--

CREATE TABLE finance.categories (
    id integer NOT NULL,
    name character varying(64) NOT NULL,
    budget_monthly numeric(10,2),
    is_system boolean DEFAULT false NOT NULL,
    parent_id integer
);


--
-- Name: categories_id_seq; Type: SEQUENCE; Schema: finance; Owner: -
--

CREATE SEQUENCE finance.categories_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: categories_id_seq; Type: SEQUENCE OWNED BY; Schema: finance; Owner: -
--

ALTER SEQUENCE finance.categories_id_seq OWNED BY finance.categories.id;


--
-- Name: category_examples; Type: TABLE; Schema: finance; Owner: -
--

CREATE TABLE finance.category_examples (
    id integer NOT NULL,
    description_pattern text NOT NULL,
    category_id integer NOT NULL,
    source_transaction_id character varying(128),
    times_reinforced integer DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: category_examples_id_seq; Type: SEQUENCE; Schema: finance; Owner: -
--

CREATE SEQUENCE finance.category_examples_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: category_examples_id_seq; Type: SEQUENCE OWNED BY; Schema: finance; Owner: -
--

ALTER SEQUENCE finance.category_examples_id_seq OWNED BY finance.category_examples.id;


--
-- Name: email_classified; Type: TABLE; Schema: finance; Owner: -
--

CREATE TABLE finance.email_classified (
    message_id text NOT NULL,
    classified_at timestamp with time zone DEFAULT now() NOT NULL,
    labels text[] DEFAULT '{}'::text[] NOT NULL
);


--
-- Name: email_labels; Type: TABLE; Schema: finance; Owner: -
--

CREATE TABLE finance.email_labels (
    label text NOT NULL,
    times_used integer DEFAULT 1 NOT NULL,
    first_used timestamp with time zone DEFAULT now() NOT NULL,
    last_used timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: transaction_files; Type: TABLE; Schema: finance; Owner: -
--

CREATE TABLE finance.transaction_files (
    transaction_id text NOT NULL,
    asset_id uuid NOT NULL,
    is_primary boolean DEFAULT false NOT NULL,
    linked_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE transaction_files; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON TABLE finance.transaction_files IS 'Many-to-many between transactions and supporting receipt/photo files.';


--
-- Name: transactions; Type: TABLE; Schema: finance; Owner: -
--

CREATE TABLE finance.transactions (
    id character varying(128) NOT NULL,
    account_id character varying(128) NOT NULL,
    posted_date date NOT NULL,
    amount numeric(12,2) NOT NULL,
    description text,
    memo text,
    pending boolean DEFAULT false NOT NULL,
    category_id integer,
    user_category_override boolean DEFAULT false NOT NULL,
    is_transfer boolean DEFAULT false NOT NULL,
    is_transfer_manual boolean DEFAULT false NOT NULL,
    house_tag boolean DEFAULT false NOT NULL,
    house_tag_manual boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    source text DEFAULT 'simplefin'::text NOT NULL,
    is_investment boolean DEFAULT false NOT NULL
);


--
-- Name: COLUMN transactions.source; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.transactions.source IS 'Where this row originated: simplefin (default, bank sync), email (parsed from a receipt email), manual.';


--
-- Name: COLUMN transactions.is_investment; Type: COMMENT; Schema: finance; Owner: -
--

COMMENT ON COLUMN finance.transactions.is_investment IS 'True if this transaction represents a flow to/from an investment account (brokerage, fund purchase, dividend reinvestment). Not counted as real income or expense.';


--
-- Name: room_files; Type: TABLE; Schema: house; Owner: -
--

CREATE TABLE house.room_files (
    room_id bigint NOT NULL,
    asset_id uuid NOT NULL,
    orientation text,
    "position" text,
    is_primary boolean DEFAULT false NOT NULL,
    linked_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: rooms; Type: TABLE; Schema: house; Owner: -
--

CREATE TABLE house.rooms (
    id bigint NOT NULL,
    name text NOT NULL,
    floor integer,
    notes text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: rooms_id_seq; Type: SEQUENCE; Schema: house; Owner: -
--

CREATE SEQUENCE house.rooms_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: rooms_id_seq; Type: SEQUENCE OWNED BY; Schema: house; Owner: -
--

ALTER SEQUENCE house.rooms_id_seq OWNED BY house.rooms.id;


--
-- Name: album_files; Type: TABLE; Schema: inventory; Owner: -
--

CREATE TABLE inventory.album_files (
    album_id bigint NOT NULL,
    asset_id uuid NOT NULL,
    is_primary boolean DEFAULT false NOT NULL,
    linked_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: albums; Type: TABLE; Schema: inventory; Owner: -
--

CREATE TABLE inventory.albums (
    id bigint NOT NULL,
    title text NOT NULL,
    artist text,
    label text,
    catalog_number text,
    year integer,
    condition text,
    notes text,
    last_played_at date,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    archived_at timestamp with time zone
);


--
-- Name: albums_id_seq; Type: SEQUENCE; Schema: inventory; Owner: -
--

CREATE SEQUENCE inventory.albums_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: albums_id_seq; Type: SEQUENCE OWNED BY; Schema: inventory; Owner: -
--

ALTER SEQUENCE inventory.albums_id_seq OWNED BY inventory.albums.id;


--
-- Name: manual_files; Type: TABLE; Schema: inventory; Owner: -
--

CREATE TABLE inventory.manual_files (
    manual_id bigint NOT NULL,
    asset_id uuid NOT NULL,
    is_primary boolean DEFAULT false NOT NULL,
    linked_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: manuals; Type: TABLE; Schema: inventory; Owner: -
--

CREATE TABLE inventory.manuals (
    id bigint NOT NULL,
    title text NOT NULL,
    brand text,
    model text,
    doc_type text,
    notes text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    archived_at timestamp with time zone
);


--
-- Name: manuals_id_seq; Type: SEQUENCE; Schema: inventory; Owner: -
--

CREATE SEQUENCE inventory.manuals_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: manuals_id_seq; Type: SEQUENCE OWNED BY; Schema: inventory; Owner: -
--

ALTER SEQUENCE inventory.manuals_id_seq OWNED BY inventory.manuals.id;


--
-- Name: router_bit_files; Type: TABLE; Schema: inventory; Owner: -
--

CREATE TABLE inventory.router_bit_files (
    router_bit_id bigint NOT NULL,
    asset_id uuid NOT NULL,
    is_primary boolean DEFAULT false NOT NULL,
    linked_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE router_bit_files; Type: COMMENT; Schema: inventory; Owner: -
--

COMMENT ON TABLE inventory.router_bit_files IS 'Link table: router bits to files.assets (photos, manuals).';


--
-- Name: router_bits; Type: TABLE; Schema: inventory; Owner: -
--

CREATE TABLE inventory.router_bits (
    id bigint NOT NULL,
    brand text,
    profile text NOT NULL,
    shank_size_in numeric(4,3),
    cutting_diameter_in numeric(5,3),
    cutting_length_in numeric(5,3),
    has_bearing boolean,
    set_name text,
    notes text,
    condition text,
    purchase_price numeric(8,2),
    current_value_estimate numeric(8,2),
    value_estimated_at date,
    acquired_at date,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    archived_at timestamp with time zone,
    radius_in numeric(5,3),
    model_number text,
    angle_deg numeric(5,1),
    url text
);


--
-- Name: TABLE router_bits; Type: COMMENT; Schema: inventory; Owner: -
--

COMMENT ON TABLE inventory.router_bits IS 'Individual router bits — profile, dimensions, bearing, brand/model info.';


--
-- Name: router_bits_id_seq; Type: SEQUENCE; Schema: inventory; Owner: -
--

CREATE SEQUENCE inventory.router_bits_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: router_bits_id_seq; Type: SEQUENCE OWNED BY; Schema: inventory; Owner: -
--

ALTER SEQUENCE inventory.router_bits_id_seq OWNED BY inventory.router_bits.id;


--
-- Name: saw_blade_files; Type: TABLE; Schema: inventory; Owner: -
--

CREATE TABLE inventory.saw_blade_files (
    saw_blade_id bigint NOT NULL,
    asset_id uuid NOT NULL,
    is_primary boolean DEFAULT false NOT NULL,
    linked_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: saw_blades; Type: TABLE; Schema: inventory; Owner: -
--

CREATE TABLE inventory.saw_blades (
    id bigint NOT NULL,
    brand text,
    diameter_in numeric(5,3),
    teeth integer,
    kerf_in numeric(5,4),
    type text,
    notes text,
    acquired_at date,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    archived_at timestamp with time zone,
    condition text,
    purchase_price numeric(10,2),
    current_value_estimate numeric(10,2),
    value_estimated_at date,
    manufacturer text,
    model_number text
);


--
-- Name: saw_blades_id_seq; Type: SEQUENCE; Schema: inventory; Owner: -
--

CREATE SEQUENCE inventory.saw_blades_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: saw_blades_id_seq; Type: SEQUENCE OWNED BY; Schema: inventory; Owner: -
--

ALTER SEQUENCE inventory.saw_blades_id_seq OWNED BY inventory.saw_blades.id;


--
-- Name: tool_files; Type: TABLE; Schema: inventory; Owner: -
--

CREATE TABLE inventory.tool_files (
    tool_id bigint NOT NULL,
    asset_id uuid NOT NULL,
    is_primary boolean DEFAULT false NOT NULL,
    linked_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: tools; Type: TABLE; Schema: inventory; Owner: -
--

CREATE TABLE inventory.tools (
    id bigint NOT NULL,
    name text NOT NULL,
    brand text,
    model text,
    type text,
    notes text,
    acquired_at date,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    archived_at timestamp with time zone,
    motor_amps numeric,
    condition text,
    purchase_price numeric(10,2),
    current_value_estimate numeric(10,2),
    value_estimated_at date,
    manufacturer text
);


--
-- Name: tools_id_seq; Type: SEQUENCE; Schema: inventory; Owner: -
--

CREATE SEQUENCE inventory.tools_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: tools_id_seq; Type: SEQUENCE OWNED BY; Schema: inventory; Owner: -
--

ALTER SEQUENCE inventory.tools_id_seq OWNED BY inventory.tools.id;


--
-- Name: wood; Type: TABLE; Schema: inventory; Owner: -
--

CREATE TABLE inventory.wood (
    id bigint NOT NULL,
    species text,
    dimensions text,
    quantity numeric(6,2),
    unit text,
    notes text,
    acquired_at date,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    archived_at timestamp with time zone
);


--
-- Name: wood_files; Type: TABLE; Schema: inventory; Owner: -
--

CREATE TABLE inventory.wood_files (
    wood_id bigint NOT NULL,
    asset_id uuid NOT NULL,
    is_primary boolean DEFAULT false NOT NULL,
    linked_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: wood_id_seq; Type: SEQUENCE; Schema: inventory; Owner: -
--

CREATE SEQUENCE inventory.wood_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: wood_id_seq; Type: SEQUENCE OWNED BY; Schema: inventory; Owner: -
--

ALTER SEQUENCE inventory.wood_id_seq OWNED BY inventory.wood.id;


--
-- Name: accounts; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.accounts AS
 SELECT id,
    org_name,
    account_name,
    currency,
    last_balance,
    last_balance_date,
    created_at,
    updated_at
   FROM finance.accounts;


--
-- Name: alert_log; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.alert_log AS
 SELECT id,
    category_id,
    alert_type,
    alert_date,
    amount_spent,
    percentage_used,
    sent_at
   FROM finance.alert_log;


--
-- Name: api_usage_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.api_usage_log (
    id bigint NOT NULL,
    called_at timestamp with time zone DEFAULT now() NOT NULL,
    workflow_id text,
    workflow_name text,
    node_name text,
    model text NOT NULL,
    input_tokens integer DEFAULT 0 NOT NULL,
    output_tokens integer DEFAULT 0 NOT NULL,
    cache_read_tokens integer DEFAULT 0 NOT NULL,
    cache_write_tokens integer DEFAULT 0 NOT NULL,
    cost_usd numeric(10,6),
    duration_ms integer,
    metadata jsonb
);


--
-- Name: TABLE api_usage_log; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.api_usage_log IS 'Per-call Anthropic API token usage and cost tracking. Populated by n8n workflows after each LLM call.';


--
-- Name: api_usage_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.api_usage_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: api_usage_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.api_usage_log_id_seq OWNED BY public.api_usage_log.id;


--
-- Name: bh_api_registry; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.bh_api_registry (
    id integer NOT NULL,
    name text NOT NULL,
    base_url text NOT NULL,
    description text NOT NULL,
    auth_type text DEFAULT 'none'::text NOT NULL,
    auth_config jsonb,
    endpoints jsonb DEFAULT '[]'::jsonb NOT NULL,
    headers jsonb,
    is_active boolean DEFAULT true NOT NULL,
    usage_count integer DEFAULT 0 NOT NULL,
    last_used_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    notes text
);


--
-- Name: bh_api_registry_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.bh_api_registry_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: bh_api_registry_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.bh_api_registry_id_seq OWNED BY public.bh_api_registry.id;


--
-- Name: bh_api_usage_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.bh_api_usage_log (
    id integer NOT NULL,
    api_name text NOT NULL,
    url text NOT NULL,
    method text DEFAULT 'GET'::text NOT NULL,
    status_code integer,
    duration_ms integer,
    called_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE bh_api_usage_log; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.bh_api_usage_log IS 'External HTTP API call log from the universal toolbox. Tracks URL, status code, duration. Used for API usage pattern detection. NOT for Anthropic cost tracking (that is public.api_usage_log).';


--
-- Name: bh_api_usage_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.bh_api_usage_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: bh_api_usage_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.bh_api_usage_log_id_seq OWNED BY public.bh_api_usage_log.id;


--
-- Name: bh_artifacts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.bh_artifacts (
    id integer NOT NULL,
    conversation_id integer NOT NULL,
    message_id integer NOT NULL,
    artifact_type text NOT NULL,
    title text NOT NULL,
    content text NOT NULL,
    language text,
    version integer DEFAULT 1 NOT NULL,
    parent_id integer,
    file_path text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT bh_artifacts_artifact_type_check CHECK ((artifact_type = ANY (ARRAY['code'::text, 'html'::text, 'mermaid'::text, 'chart'::text, 'markdown'::text, 'table'::text])))
);


--
-- Name: bh_artifacts_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.bh_artifacts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: bh_artifacts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.bh_artifacts_id_seq OWNED BY public.bh_artifacts.id;


--
-- Name: bh_audit_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.bh_audit_log (
    id integer NOT NULL,
    user_id integer,
    action text NOT NULL,
    target_type text,
    target_id integer,
    details jsonb DEFAULT '{}'::jsonb,
    ip_address text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: bh_audit_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.bh_audit_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: bh_audit_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.bh_audit_log_id_seq OWNED BY public.bh_audit_log.id;


--
-- Name: bh_conversations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.bh_conversations (
    id integer NOT NULL,
    workspace_id integer NOT NULL,
    user_id integer NOT NULL,
    title text,
    parent_id integer,
    branch_point_msg integer,
    is_archived boolean DEFAULT false,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: bh_conversations_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.bh_conversations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: bh_conversations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.bh_conversations_id_seq OWNED BY public.bh_conversations.id;


--
-- Name: bh_dashboard_layouts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.bh_dashboard_layouts (
    id integer NOT NULL,
    user_id integer NOT NULL,
    page_key text NOT NULL,
    widgets jsonb DEFAULT '[]'::jsonb NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: bh_dashboard_layouts_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.bh_dashboard_layouts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: bh_dashboard_layouts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.bh_dashboard_layouts_id_seq OWNED BY public.bh_dashboard_layouts.id;


--
-- Name: bh_dashboard_widgets; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.bh_dashboard_widgets (
    id integer NOT NULL,
    widget_key text NOT NULL,
    display_name text NOT NULL,
    description text,
    category text DEFAULT 'general'::text NOT NULL,
    data_endpoint text NOT NULL,
    default_config jsonb DEFAULT '{}'::jsonb NOT NULL,
    default_pages jsonb DEFAULT '[]'::jsonb NOT NULL,
    sort_order integer DEFAULT 0 NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: bh_dashboard_widgets_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.bh_dashboard_widgets_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: bh_dashboard_widgets_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.bh_dashboard_widgets_id_seq OWNED BY public.bh_dashboard_widgets.id;


--
-- Name: bh_db_browser_layouts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.bh_db_browser_layouts (
    id integer NOT NULL,
    user_id integer NOT NULL,
    schema_name text NOT NULL,
    table_name text NOT NULL,
    list_config jsonb DEFAULT '{}'::jsonb NOT NULL,
    detail_config jsonb DEFAULT '{}'::jsonb NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: bh_db_browser_layouts_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.bh_db_browser_layouts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: bh_db_browser_layouts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.bh_db_browser_layouts_id_seq OWNED BY public.bh_db_browser_layouts.id;


--
-- Name: bh_db_browser_undo_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.bh_db_browser_undo_log (
    id bigint NOT NULL,
    session_id uuid NOT NULL,
    user_id integer NOT NULL,
    schema_name text NOT NULL,
    table_name text NOT NULL,
    row_id text NOT NULL,
    operation_type text NOT NULL,
    previous_values jsonb,
    new_values jsonb,
    is_undone boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT bh_db_browser_undo_log_operation_type_check CHECK ((operation_type = ANY (ARRAY['update'::text, 'insert'::text, 'delete'::text, 'bulk_update'::text])))
);


--
-- Name: bh_db_browser_undo_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.bh_db_browser_undo_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: bh_db_browser_undo_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.bh_db_browser_undo_log_id_seq OWNED BY public.bh_db_browser_undo_log.id;


--
-- Name: bh_db_browser_views; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.bh_db_browser_views (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id integer NOT NULL,
    schema_name text NOT NULL,
    table_name text NOT NULL,
    name text NOT NULL,
    config jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: bh_entities; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.bh_entities (
    id integer NOT NULL,
    name text NOT NULL,
    entity_type text NOT NULL,
    summary text,
    attributes jsonb DEFAULT '{}'::jsonb NOT NULL,
    source text,
    confidence numeric(3,2) DEFAULT 1.0,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_by integer
);


--
-- Name: bh_entities_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.bh_entities_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: bh_entities_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.bh_entities_id_seq OWNED BY public.bh_entities.id;


--
-- Name: bh_hook_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.bh_hook_log (
    id integer NOT NULL,
    hook_id integer NOT NULL,
    event_type text NOT NULL,
    trigger_data jsonb,
    action_result jsonb,
    success boolean NOT NULL,
    error_message text,
    executed_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: bh_hook_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.bh_hook_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: bh_hook_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.bh_hook_log_id_seq OWNED BY public.bh_hook_log.id;


--
-- Name: bh_hooks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.bh_hooks (
    id integer NOT NULL,
    workspace_id integer NOT NULL,
    name text NOT NULL,
    description text,
    event_type text NOT NULL,
    action_type text NOT NULL,
    action_config jsonb DEFAULT '{}'::jsonb NOT NULL,
    conditions jsonb DEFAULT '{}'::jsonb,
    cron_expression text,
    is_enabled boolean DEFAULT true,
    created_by integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT bh_hooks_action_type_check CHECK ((action_type = ANY (ARRAY['call_webhook'::text, 'call_ai'::text, 'capture_context'::text, 'notify'::text]))),
    CONSTRAINT bh_hooks_event_type_check CHECK ((event_type = ANY (ARRAY['message_sent'::text, 'message_received'::text, 'file_uploaded'::text, 'conversation_started'::text, 'conversation_ended'::text, 'schedule'::text, 'manual'::text])))
);


--
-- Name: bh_hooks_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.bh_hooks_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: bh_hooks_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.bh_hooks_id_seq OWNED BY public.bh_hooks.id;


--
-- Name: bh_invite_links; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.bh_invite_links (
    id integer NOT NULL,
    token text NOT NULL,
    created_by integer,
    role text DEFAULT 'member'::text NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    used_by integer,
    used_at timestamp with time zone
);


--
-- Name: bh_invite_links_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.bh_invite_links_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: bh_invite_links_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.bh_invite_links_id_seq OWNED BY public.bh_invite_links.id;


--
-- Name: bh_list_items; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.bh_list_items (
    id integer NOT NULL,
    list_id integer NOT NULL,
    text text NOT NULL,
    checked boolean DEFAULT false NOT NULL,
    quantity text,
    notes text,
    added_by text DEFAULT 'chat'::text,
    checked_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: bh_list_items_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.bh_list_items_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: bh_list_items_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.bh_list_items_id_seq OWNED BY public.bh_list_items.id;


--
-- Name: bh_lists; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.bh_lists (
    id integer NOT NULL,
    name text NOT NULL,
    user_id integer NOT NULL,
    description text,
    is_archived boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: bh_lists_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.bh_lists_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: bh_lists_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.bh_lists_id_seq OWNED BY public.bh_lists.id;


--
-- Name: bh_messages; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.bh_messages (
    id integer NOT NULL,
    conversation_id integer NOT NULL,
    role text NOT NULL,
    content text NOT NULL,
    attachments jsonb DEFAULT '[]'::jsonb,
    model_used text,
    routing_layer text,
    input_tokens integer,
    output_tokens integer,
    cost_usd numeric(10,6),
    metadata jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT bh_messages_role_check CHECK ((role = ANY (ARRAY['user'::text, 'assistant'::text, 'system'::text, 'tool_call'::text, 'tool_result'::text]))),
    CONSTRAINT bh_messages_routing_layer_check CHECK ((routing_layer = ANY (ARRAY['L1'::text, 'L2'::text, 'L3'::text])))
);


--
-- Name: bh_messages_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.bh_messages_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: bh_messages_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.bh_messages_id_seq OWNED BY public.bh_messages.id;


--
-- Name: bh_model_rates; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.bh_model_rates (
    id integer NOT NULL,
    provider text NOT NULL,
    model_id text NOT NULL,
    display_name text NOT NULL,
    input_cost_per_mtok numeric(10,4),
    output_cost_per_mtok numeric(10,4),
    supports_vision boolean DEFAULT false,
    supports_tools boolean DEFAULT false,
    max_output_tokens integer DEFAULT 4096,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: bh_model_rates_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.bh_model_rates_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: bh_model_rates_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.bh_model_rates_id_seq OWNED BY public.bh_model_rates.id;


--
-- Name: bh_notification_prefs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.bh_notification_prefs (
    user_id integer NOT NULL,
    event_type text NOT NULL,
    web_push boolean DEFAULT true,
    pushover boolean DEFAULT false,
    quiet_start time without time zone,
    quiet_end time without time zone
);


--
-- Name: bh_password_reset_tokens; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.bh_password_reset_tokens (
    id integer NOT NULL,
    user_id integer NOT NULL,
    token_hash text NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    consumed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: bh_password_reset_tokens_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.bh_password_reset_tokens_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: bh_password_reset_tokens_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.bh_password_reset_tokens_id_seq OWNED BY public.bh_password_reset_tokens.id;


--
-- Name: bh_patterns; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.bh_patterns (
    id integer NOT NULL,
    rule text NOT NULL,
    rule_type text DEFAULT 'regex'::text NOT NULL,
    skill_id integer NOT NULL,
    param_template jsonb DEFAULT '{}'::jsonb,
    description text,
    priority integer DEFAULT 100,
    workspace_id integer,
    is_active boolean DEFAULT true,
    CONSTRAINT bh_patterns_rule_type_check CHECK ((rule_type = ANY (ARRAY['regex'::text, 'keyword'::text])))
);


--
-- Name: bh_patterns_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.bh_patterns_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: bh_patterns_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.bh_patterns_id_seq OWNED BY public.bh_patterns.id;


--
-- Name: bh_pinned_context; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.bh_pinned_context (
    id integer NOT NULL,
    workspace_id integer NOT NULL,
    context_type text NOT NULL,
    title text NOT NULL,
    content text,
    query text,
    refresh_minutes integer DEFAULT 60,
    cached_result text,
    cached_at timestamp with time zone,
    priority integer DEFAULT 100,
    token_estimate integer DEFAULT 0,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT bh_pinned_context_context_type_check CHECK ((context_type = ANY (ARRAY['static'::text, 'dynamic'::text])))
);


--
-- Name: bh_pinned_context_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.bh_pinned_context_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: bh_pinned_context_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.bh_pinned_context_id_seq OWNED BY public.bh_pinned_context.id;


--
-- Name: bh_platform_settings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.bh_platform_settings (
    key text NOT NULL,
    value_json jsonb NOT NULL,
    updated_by integer,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: bh_push_subscriptions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.bh_push_subscriptions (
    id integer NOT NULL,
    user_id integer NOT NULL,
    subscription jsonb NOT NULL,
    user_agent text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: bh_push_subscriptions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.bh_push_subscriptions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: bh_push_subscriptions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.bh_push_subscriptions_id_seq OWNED BY public.bh_push_subscriptions.id;


--
-- Name: bh_refresh_tokens; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.bh_refresh_tokens (
    id integer NOT NULL,
    user_id integer NOT NULL,
    token_hash text NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    revoked_at timestamp with time zone
);


--
-- Name: bh_refresh_tokens_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.bh_refresh_tokens_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: bh_refresh_tokens_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.bh_refresh_tokens_id_seq OWNED BY public.bh_refresh_tokens.id;


--
-- Name: bh_relationships; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.bh_relationships (
    id integer NOT NULL,
    from_entity_id integer NOT NULL,
    to_entity_id integer NOT NULL,
    relationship text NOT NULL,
    attributes jsonb DEFAULT '{}'::jsonb,
    source text,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: bh_relationships_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.bh_relationships_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: bh_relationships_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.bh_relationships_id_seq OWNED BY public.bh_relationships.id;


--
-- Name: bh_reminders; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.bh_reminders (
    id integer NOT NULL,
    user_id integer NOT NULL,
    message text NOT NULL,
    deliver_at timestamp with time zone NOT NULL,
    delivered_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: bh_reminders_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.bh_reminders_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: bh_reminders_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.bh_reminders_id_seq OWNED BY public.bh_reminders.id;


--
-- Name: bh_skills; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.bh_skills (
    id integer NOT NULL,
    name text NOT NULL,
    description text NOT NULL,
    webhook_url text NOT NULL,
    http_method text DEFAULT 'POST'::text NOT NULL,
    param_schema jsonb DEFAULT '{}'::jsonb NOT NULL,
    response_hint text,
    is_active boolean DEFAULT true,
    restricted_users integer[] DEFAULT '{}'::integer[],
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    is_read_only boolean DEFAULT false NOT NULL
);


--
-- Name: COLUMN bh_skills.is_read_only; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.bh_skills.is_read_only IS 'Read-only/info skills get a lower L2 confidence threshold (0.65 vs 0.75). Set true for skills that only retrieve data and never modify state.';


--
-- Name: bh_skills_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.bh_skills_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: bh_skills_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.bh_skills_id_seq OWNED BY public.bh_skills.id;


--
-- Name: bh_slash_commands; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.bh_slash_commands (
    id integer NOT NULL,
    command text NOT NULL,
    description text NOT NULL,
    skill_id integer,
    param_template jsonb DEFAULT '{}'::jsonb,
    workspace_id integer,
    is_active boolean DEFAULT true,
    flags jsonb DEFAULT '[]'::jsonb
);


--
-- Name: COLUMN bh_slash_commands.flags; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.bh_slash_commands.flags IS 'Array of {flag, description} objects for --flag autocomplete. Empty array = no flags.';


--
-- Name: bh_slash_commands_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.bh_slash_commands_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: bh_slash_commands_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.bh_slash_commands_id_seq OWNED BY public.bh_slash_commands.id;


--
-- Name: bh_themes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.bh_themes (
    id integer NOT NULL,
    name text NOT NULL,
    slug text NOT NULL,
    is_preset boolean DEFAULT false NOT NULL,
    owner_id integer,
    tokens_json jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: bh_themes_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.bh_themes_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: bh_themes_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.bh_themes_id_seq OWNED BY public.bh_themes.id;


--
-- Name: bh_users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.bh_users (
    id integer NOT NULL,
    email text NOT NULL,
    password_hash text NOT NULL,
    display_name text NOT NULL,
    role text DEFAULT 'member'::text NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    last_login_at timestamp with time zone,
    settings_json jsonb DEFAULT '{}'::jsonb,
    CONSTRAINT bh_users_role_check CHECK ((role = ANY (ARRAY['admin'::text, 'member'::text, 'viewer'::text])))
);


--
-- Name: bh_users_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.bh_users_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: bh_users_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.bh_users_id_seq OWNED BY public.bh_users.id;


--
-- Name: bh_workspace_skills; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.bh_workspace_skills (
    workspace_id integer NOT NULL,
    skill_id integer NOT NULL
);


--
-- Name: bh_workspace_users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.bh_workspace_users (
    workspace_id integer NOT NULL,
    user_id integer NOT NULL,
    role text DEFAULT 'member'::text NOT NULL,
    added_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT bh_workspace_users_role_check CHECK ((role = ANY (ARRAY['owner'::text, 'member'::text, 'viewer'::text])))
);


--
-- Name: bh_workspaces; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.bh_workspaces (
    id integer NOT NULL,
    name text NOT NULL,
    description text,
    icon text,
    color text,
    system_prompt text DEFAULT ''::text NOT NULL,
    default_model text DEFAULT 'auto'::text,
    temperature numeric(3,2) DEFAULT 0.70,
    max_context_tokens integer DEFAULT 8000,
    auto_capture boolean DEFAULT true,
    permitted_schemas text[] DEFAULT '{}'::text[],
    settings_json jsonb DEFAULT '{}'::jsonb,
    created_by integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: bh_workspaces_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.bh_workspaces_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: bh_workspaces_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.bh_workspaces_id_seq OWNED BY public.bh_workspaces.id;


--
-- Name: budgets; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.budgets AS
 SELECT id,
    category_id,
    month,
    limit_amount
   FROM finance.budgets;


--
-- Name: categories; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.categories AS
 SELECT id,
    name,
    budget_monthly,
    is_system,
    parent_id
   FROM finance.categories;


--
-- Name: category_examples; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.category_examples AS
 SELECT id,
    description_pattern,
    category_id,
    source_transaction_id,
    times_reinforced,
    created_at,
    updated_at
   FROM finance.category_examples;


--
-- Name: db_admin_field_hints; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.db_admin_field_hints (
    column_name text NOT NULL,
    hint_type text DEFAULT 'text'::text NOT NULL,
    options jsonb,
    prefix text,
    suffix text,
    min_val numeric,
    max_val numeric,
    step_val numeric,
    placeholder text,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: TABLE db_admin_field_hints; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.db_admin_field_hints IS 'Per-column input type configuration for DB Admin forms. Overrides hardcoded FIELD_HINTS defaults.';


--
-- Name: email_classified; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.email_classified AS
 SELECT message_id,
    classified_at,
    labels
   FROM finance.email_classified;


--
-- Name: email_labels; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.email_labels AS
 SELECT label,
    times_used,
    first_used,
    last_used
   FROM finance.email_labels;


--
-- Name: transaction_files; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.transaction_files AS
 SELECT transaction_id,
    asset_id,
    is_primary,
    linked_at
   FROM finance.transaction_files;


--
-- Name: transactions; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.transactions AS
 SELECT id,
    account_id,
    posted_date,
    amount,
    description,
    memo,
    pending,
    category_id,
    user_category_override,
    is_transfer,
    is_transfer_manual,
    house_tag,
    house_tag_manual,
    created_at,
    updated_at,
    source,
    is_investment
   FROM finance.transactions;


--
-- Name: cook_log id; Type: DEFAULT; Schema: cook; Owner: -
--

ALTER TABLE ONLY cook.cook_log ALTER COLUMN id SET DEFAULT nextval('cook.cook_log_id_seq'::regclass);


--
-- Name: recipes id; Type: DEFAULT; Schema: cook; Owner: -
--

ALTER TABLE ONLY cook.recipes ALTER COLUMN id SET DEFAULT nextval('cook.recipes_id_seq'::regclass);


--
-- Name: alert_log id; Type: DEFAULT; Schema: finance; Owner: -
--

ALTER TABLE ONLY finance.alert_log ALTER COLUMN id SET DEFAULT nextval('finance.alert_log_id_seq'::regclass);


--
-- Name: budgets id; Type: DEFAULT; Schema: finance; Owner: -
--

ALTER TABLE ONLY finance.budgets ALTER COLUMN id SET DEFAULT nextval('finance.budgets_id_seq'::regclass);


--
-- Name: categories id; Type: DEFAULT; Schema: finance; Owner: -
--

ALTER TABLE ONLY finance.categories ALTER COLUMN id SET DEFAULT nextval('finance.categories_id_seq'::regclass);


--
-- Name: category_examples id; Type: DEFAULT; Schema: finance; Owner: -
--

ALTER TABLE ONLY finance.category_examples ALTER COLUMN id SET DEFAULT nextval('finance.category_examples_id_seq'::regclass);


--
-- Name: rooms id; Type: DEFAULT; Schema: house; Owner: -
--

ALTER TABLE ONLY house.rooms ALTER COLUMN id SET DEFAULT nextval('house.rooms_id_seq'::regclass);


--
-- Name: albums id; Type: DEFAULT; Schema: inventory; Owner: -
--

ALTER TABLE ONLY inventory.albums ALTER COLUMN id SET DEFAULT nextval('inventory.albums_id_seq'::regclass);


--
-- Name: manuals id; Type: DEFAULT; Schema: inventory; Owner: -
--

ALTER TABLE ONLY inventory.manuals ALTER COLUMN id SET DEFAULT nextval('inventory.manuals_id_seq'::regclass);


--
-- Name: router_bits id; Type: DEFAULT; Schema: inventory; Owner: -
--

ALTER TABLE ONLY inventory.router_bits ALTER COLUMN id SET DEFAULT nextval('inventory.router_bits_id_seq'::regclass);


--
-- Name: saw_blades id; Type: DEFAULT; Schema: inventory; Owner: -
--

ALTER TABLE ONLY inventory.saw_blades ALTER COLUMN id SET DEFAULT nextval('inventory.saw_blades_id_seq'::regclass);


--
-- Name: tools id; Type: DEFAULT; Schema: inventory; Owner: -
--

ALTER TABLE ONLY inventory.tools ALTER COLUMN id SET DEFAULT nextval('inventory.tools_id_seq'::regclass);


--
-- Name: wood id; Type: DEFAULT; Schema: inventory; Owner: -
--

ALTER TABLE ONLY inventory.wood ALTER COLUMN id SET DEFAULT nextval('inventory.wood_id_seq'::regclass);


--
-- Name: api_usage_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_usage_log ALTER COLUMN id SET DEFAULT nextval('public.api_usage_log_id_seq'::regclass);


--
-- Name: bh_api_registry id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_api_registry ALTER COLUMN id SET DEFAULT nextval('public.bh_api_registry_id_seq'::regclass);


--
-- Name: bh_api_usage_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_api_usage_log ALTER COLUMN id SET DEFAULT nextval('public.bh_api_usage_log_id_seq'::regclass);


--
-- Name: bh_artifacts id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_artifacts ALTER COLUMN id SET DEFAULT nextval('public.bh_artifacts_id_seq'::regclass);


--
-- Name: bh_audit_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_audit_log ALTER COLUMN id SET DEFAULT nextval('public.bh_audit_log_id_seq'::regclass);


--
-- Name: bh_conversations id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_conversations ALTER COLUMN id SET DEFAULT nextval('public.bh_conversations_id_seq'::regclass);


--
-- Name: bh_dashboard_layouts id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_dashboard_layouts ALTER COLUMN id SET DEFAULT nextval('public.bh_dashboard_layouts_id_seq'::regclass);


--
-- Name: bh_dashboard_widgets id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_dashboard_widgets ALTER COLUMN id SET DEFAULT nextval('public.bh_dashboard_widgets_id_seq'::regclass);


--
-- Name: bh_db_browser_layouts id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_db_browser_layouts ALTER COLUMN id SET DEFAULT nextval('public.bh_db_browser_layouts_id_seq'::regclass);


--
-- Name: bh_db_browser_undo_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_db_browser_undo_log ALTER COLUMN id SET DEFAULT nextval('public.bh_db_browser_undo_log_id_seq'::regclass);


--
-- Name: bh_entities id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_entities ALTER COLUMN id SET DEFAULT nextval('public.bh_entities_id_seq'::regclass);


--
-- Name: bh_hook_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_hook_log ALTER COLUMN id SET DEFAULT nextval('public.bh_hook_log_id_seq'::regclass);


--
-- Name: bh_hooks id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_hooks ALTER COLUMN id SET DEFAULT nextval('public.bh_hooks_id_seq'::regclass);


--
-- Name: bh_invite_links id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_invite_links ALTER COLUMN id SET DEFAULT nextval('public.bh_invite_links_id_seq'::regclass);


--
-- Name: bh_list_items id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_list_items ALTER COLUMN id SET DEFAULT nextval('public.bh_list_items_id_seq'::regclass);


--
-- Name: bh_lists id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_lists ALTER COLUMN id SET DEFAULT nextval('public.bh_lists_id_seq'::regclass);


--
-- Name: bh_messages id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_messages ALTER COLUMN id SET DEFAULT nextval('public.bh_messages_id_seq'::regclass);


--
-- Name: bh_model_rates id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_model_rates ALTER COLUMN id SET DEFAULT nextval('public.bh_model_rates_id_seq'::regclass);


--
-- Name: bh_password_reset_tokens id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_password_reset_tokens ALTER COLUMN id SET DEFAULT nextval('public.bh_password_reset_tokens_id_seq'::regclass);


--
-- Name: bh_patterns id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_patterns ALTER COLUMN id SET DEFAULT nextval('public.bh_patterns_id_seq'::regclass);


--
-- Name: bh_pinned_context id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_pinned_context ALTER COLUMN id SET DEFAULT nextval('public.bh_pinned_context_id_seq'::regclass);


--
-- Name: bh_push_subscriptions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_push_subscriptions ALTER COLUMN id SET DEFAULT nextval('public.bh_push_subscriptions_id_seq'::regclass);


--
-- Name: bh_refresh_tokens id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_refresh_tokens ALTER COLUMN id SET DEFAULT nextval('public.bh_refresh_tokens_id_seq'::regclass);


--
-- Name: bh_relationships id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_relationships ALTER COLUMN id SET DEFAULT nextval('public.bh_relationships_id_seq'::regclass);


--
-- Name: bh_reminders id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_reminders ALTER COLUMN id SET DEFAULT nextval('public.bh_reminders_id_seq'::regclass);


--
-- Name: bh_skills id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_skills ALTER COLUMN id SET DEFAULT nextval('public.bh_skills_id_seq'::regclass);


--
-- Name: bh_slash_commands id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_slash_commands ALTER COLUMN id SET DEFAULT nextval('public.bh_slash_commands_id_seq'::regclass);


--
-- Name: bh_themes id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_themes ALTER COLUMN id SET DEFAULT nextval('public.bh_themes_id_seq'::regclass);


--
-- Name: bh_users id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_users ALTER COLUMN id SET DEFAULT nextval('public.bh_users_id_seq'::regclass);


--
-- Name: bh_workspaces id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_workspaces ALTER COLUMN id SET DEFAULT nextval('public.bh_workspaces_id_seq'::regclass);


--
-- Name: cook_log cook_log_pkey; Type: CONSTRAINT; Schema: cook; Owner: -
--

ALTER TABLE ONLY cook.cook_log
    ADD CONSTRAINT cook_log_pkey PRIMARY KEY (id);


--
-- Name: recipe_files recipe_files_pkey; Type: CONSTRAINT; Schema: cook; Owner: -
--

ALTER TABLE ONLY cook.recipe_files
    ADD CONSTRAINT recipe_files_pkey PRIMARY KEY (recipe_id, asset_id);


--
-- Name: recipes recipes_pkey; Type: CONSTRAINT; Schema: cook; Owner: -
--

ALTER TABLE ONLY cook.recipes
    ADD CONSTRAINT recipes_pkey PRIMARY KEY (id);


--
-- Name: recipes recipes_slug_key; Type: CONSTRAINT; Schema: cook; Owner: -
--

ALTER TABLE ONLY cook.recipes
    ADD CONSTRAINT recipes_slug_key UNIQUE (slug);


--
-- Name: assets assets_path_key; Type: CONSTRAINT; Schema: files; Owner: -
--

ALTER TABLE ONLY files.assets
    ADD CONSTRAINT assets_path_key UNIQUE (path);


--
-- Name: assets assets_pkey; Type: CONSTRAINT; Schema: files; Owner: -
--

ALTER TABLE ONLY files.assets
    ADD CONSTRAINT assets_pkey PRIMARY KEY (id);


--
-- Name: assets assets_sha256_key; Type: CONSTRAINT; Schema: files; Owner: -
--

ALTER TABLE ONLY files.assets
    ADD CONSTRAINT assets_sha256_key UNIQUE (sha256);


--
-- Name: accounts accounts_pkey; Type: CONSTRAINT; Schema: finance; Owner: -
--

ALTER TABLE ONLY finance.accounts
    ADD CONSTRAINT accounts_pkey PRIMARY KEY (id);


--
-- Name: alert_log alert_log_category_id_alert_type_alert_date_key; Type: CONSTRAINT; Schema: finance; Owner: -
--

ALTER TABLE ONLY finance.alert_log
    ADD CONSTRAINT alert_log_category_id_alert_type_alert_date_key UNIQUE (category_id, alert_type, alert_date);


--
-- Name: alert_log alert_log_pkey; Type: CONSTRAINT; Schema: finance; Owner: -
--

ALTER TABLE ONLY finance.alert_log
    ADD CONSTRAINT alert_log_pkey PRIMARY KEY (id);


--
-- Name: budgets budgets_category_id_month_key; Type: CONSTRAINT; Schema: finance; Owner: -
--

ALTER TABLE ONLY finance.budgets
    ADD CONSTRAINT budgets_category_id_month_key UNIQUE (category_id, month);


--
-- Name: budgets budgets_pkey; Type: CONSTRAINT; Schema: finance; Owner: -
--

ALTER TABLE ONLY finance.budgets
    ADD CONSTRAINT budgets_pkey PRIMARY KEY (id);


--
-- Name: categories categories_name_key; Type: CONSTRAINT; Schema: finance; Owner: -
--

ALTER TABLE ONLY finance.categories
    ADD CONSTRAINT categories_name_key UNIQUE (name);


--
-- Name: categories categories_pkey; Type: CONSTRAINT; Schema: finance; Owner: -
--

ALTER TABLE ONLY finance.categories
    ADD CONSTRAINT categories_pkey PRIMARY KEY (id);


--
-- Name: category_examples category_examples_pkey; Type: CONSTRAINT; Schema: finance; Owner: -
--

ALTER TABLE ONLY finance.category_examples
    ADD CONSTRAINT category_examples_pkey PRIMARY KEY (id);


--
-- Name: email_classified email_classified_pkey; Type: CONSTRAINT; Schema: finance; Owner: -
--

ALTER TABLE ONLY finance.email_classified
    ADD CONSTRAINT email_classified_pkey PRIMARY KEY (message_id);


--
-- Name: email_labels email_labels_pkey; Type: CONSTRAINT; Schema: finance; Owner: -
--

ALTER TABLE ONLY finance.email_labels
    ADD CONSTRAINT email_labels_pkey PRIMARY KEY (label);


--
-- Name: transaction_files transaction_files_pkey; Type: CONSTRAINT; Schema: finance; Owner: -
--

ALTER TABLE ONLY finance.transaction_files
    ADD CONSTRAINT transaction_files_pkey PRIMARY KEY (transaction_id, asset_id);


--
-- Name: transactions transactions_pkey; Type: CONSTRAINT; Schema: finance; Owner: -
--

ALTER TABLE ONLY finance.transactions
    ADD CONSTRAINT transactions_pkey PRIMARY KEY (id);


--
-- Name: room_files room_files_pkey; Type: CONSTRAINT; Schema: house; Owner: -
--

ALTER TABLE ONLY house.room_files
    ADD CONSTRAINT room_files_pkey PRIMARY KEY (room_id, asset_id);


--
-- Name: rooms rooms_name_key; Type: CONSTRAINT; Schema: house; Owner: -
--

ALTER TABLE ONLY house.rooms
    ADD CONSTRAINT rooms_name_key UNIQUE (name);


--
-- Name: rooms rooms_pkey; Type: CONSTRAINT; Schema: house; Owner: -
--

ALTER TABLE ONLY house.rooms
    ADD CONSTRAINT rooms_pkey PRIMARY KEY (id);


--
-- Name: album_files album_files_pkey; Type: CONSTRAINT; Schema: inventory; Owner: -
--

ALTER TABLE ONLY inventory.album_files
    ADD CONSTRAINT album_files_pkey PRIMARY KEY (album_id, asset_id);


--
-- Name: albums albums_pkey; Type: CONSTRAINT; Schema: inventory; Owner: -
--

ALTER TABLE ONLY inventory.albums
    ADD CONSTRAINT albums_pkey PRIMARY KEY (id);


--
-- Name: manual_files manual_files_pkey; Type: CONSTRAINT; Schema: inventory; Owner: -
--

ALTER TABLE ONLY inventory.manual_files
    ADD CONSTRAINT manual_files_pkey PRIMARY KEY (manual_id, asset_id);


--
-- Name: manuals manuals_pkey; Type: CONSTRAINT; Schema: inventory; Owner: -
--

ALTER TABLE ONLY inventory.manuals
    ADD CONSTRAINT manuals_pkey PRIMARY KEY (id);


--
-- Name: router_bit_files router_bit_files_pkey; Type: CONSTRAINT; Schema: inventory; Owner: -
--

ALTER TABLE ONLY inventory.router_bit_files
    ADD CONSTRAINT router_bit_files_pkey PRIMARY KEY (router_bit_id, asset_id);


--
-- Name: router_bits router_bits_pkey; Type: CONSTRAINT; Schema: inventory; Owner: -
--

ALTER TABLE ONLY inventory.router_bits
    ADD CONSTRAINT router_bits_pkey PRIMARY KEY (id);


--
-- Name: saw_blade_files saw_blade_files_pkey; Type: CONSTRAINT; Schema: inventory; Owner: -
--

ALTER TABLE ONLY inventory.saw_blade_files
    ADD CONSTRAINT saw_blade_files_pkey PRIMARY KEY (saw_blade_id, asset_id);


--
-- Name: saw_blades saw_blades_pkey; Type: CONSTRAINT; Schema: inventory; Owner: -
--

ALTER TABLE ONLY inventory.saw_blades
    ADD CONSTRAINT saw_blades_pkey PRIMARY KEY (id);


--
-- Name: tool_files tool_files_pkey; Type: CONSTRAINT; Schema: inventory; Owner: -
--

ALTER TABLE ONLY inventory.tool_files
    ADD CONSTRAINT tool_files_pkey PRIMARY KEY (tool_id, asset_id);


--
-- Name: tools tools_pkey; Type: CONSTRAINT; Schema: inventory; Owner: -
--

ALTER TABLE ONLY inventory.tools
    ADD CONSTRAINT tools_pkey PRIMARY KEY (id);


--
-- Name: wood_files wood_files_pkey; Type: CONSTRAINT; Schema: inventory; Owner: -
--

ALTER TABLE ONLY inventory.wood_files
    ADD CONSTRAINT wood_files_pkey PRIMARY KEY (wood_id, asset_id);


--
-- Name: wood wood_pkey; Type: CONSTRAINT; Schema: inventory; Owner: -
--

ALTER TABLE ONLY inventory.wood
    ADD CONSTRAINT wood_pkey PRIMARY KEY (id);


--
-- Name: api_usage_log api_usage_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_usage_log
    ADD CONSTRAINT api_usage_log_pkey PRIMARY KEY (id);


--
-- Name: bh_api_registry bh_api_registry_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_api_registry
    ADD CONSTRAINT bh_api_registry_name_key UNIQUE (name);


--
-- Name: bh_api_registry bh_api_registry_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_api_registry
    ADD CONSTRAINT bh_api_registry_pkey PRIMARY KEY (id);


--
-- Name: bh_api_usage_log bh_api_usage_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_api_usage_log
    ADD CONSTRAINT bh_api_usage_log_pkey PRIMARY KEY (id);


--
-- Name: bh_artifacts bh_artifacts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_artifacts
    ADD CONSTRAINT bh_artifacts_pkey PRIMARY KEY (id);


--
-- Name: bh_audit_log bh_audit_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_audit_log
    ADD CONSTRAINT bh_audit_log_pkey PRIMARY KEY (id);


--
-- Name: bh_conversations bh_conversations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_conversations
    ADD CONSTRAINT bh_conversations_pkey PRIMARY KEY (id);


--
-- Name: bh_dashboard_layouts bh_dashboard_layouts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_dashboard_layouts
    ADD CONSTRAINT bh_dashboard_layouts_pkey PRIMARY KEY (id);


--
-- Name: bh_dashboard_layouts bh_dashboard_layouts_user_id_page_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_dashboard_layouts
    ADD CONSTRAINT bh_dashboard_layouts_user_id_page_key_key UNIQUE (user_id, page_key);


--
-- Name: bh_dashboard_widgets bh_dashboard_widgets_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_dashboard_widgets
    ADD CONSTRAINT bh_dashboard_widgets_pkey PRIMARY KEY (id);


--
-- Name: bh_dashboard_widgets bh_dashboard_widgets_widget_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_dashboard_widgets
    ADD CONSTRAINT bh_dashboard_widgets_widget_key_key UNIQUE (widget_key);


--
-- Name: bh_db_browser_layouts bh_db_browser_layouts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_db_browser_layouts
    ADD CONSTRAINT bh_db_browser_layouts_pkey PRIMARY KEY (id);


--
-- Name: bh_db_browser_layouts bh_db_browser_layouts_user_id_schema_name_table_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_db_browser_layouts
    ADD CONSTRAINT bh_db_browser_layouts_user_id_schema_name_table_name_key UNIQUE (user_id, schema_name, table_name);


--
-- Name: bh_db_browser_undo_log bh_db_browser_undo_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_db_browser_undo_log
    ADD CONSTRAINT bh_db_browser_undo_log_pkey PRIMARY KEY (id);


--
-- Name: bh_db_browser_views bh_db_browser_views_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_db_browser_views
    ADD CONSTRAINT bh_db_browser_views_pkey PRIMARY KEY (id);


--
-- Name: bh_entities bh_entities_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_entities
    ADD CONSTRAINT bh_entities_pkey PRIMARY KEY (id);


--
-- Name: bh_hook_log bh_hook_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_hook_log
    ADD CONSTRAINT bh_hook_log_pkey PRIMARY KEY (id);


--
-- Name: bh_hooks bh_hooks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_hooks
    ADD CONSTRAINT bh_hooks_pkey PRIMARY KEY (id);


--
-- Name: bh_invite_links bh_invite_links_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_invite_links
    ADD CONSTRAINT bh_invite_links_pkey PRIMARY KEY (id);


--
-- Name: bh_invite_links bh_invite_links_token_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_invite_links
    ADD CONSTRAINT bh_invite_links_token_key UNIQUE (token);


--
-- Name: bh_list_items bh_list_items_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_list_items
    ADD CONSTRAINT bh_list_items_pkey PRIMARY KEY (id);


--
-- Name: bh_lists bh_lists_name_user_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_lists
    ADD CONSTRAINT bh_lists_name_user_id_key UNIQUE (name, user_id);


--
-- Name: bh_lists bh_lists_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_lists
    ADD CONSTRAINT bh_lists_pkey PRIMARY KEY (id);


--
-- Name: bh_messages bh_messages_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_messages
    ADD CONSTRAINT bh_messages_pkey PRIMARY KEY (id);


--
-- Name: bh_model_rates bh_model_rates_model_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_model_rates
    ADD CONSTRAINT bh_model_rates_model_id_key UNIQUE (model_id);


--
-- Name: bh_model_rates bh_model_rates_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_model_rates
    ADD CONSTRAINT bh_model_rates_pkey PRIMARY KEY (id);


--
-- Name: bh_notification_prefs bh_notification_prefs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_notification_prefs
    ADD CONSTRAINT bh_notification_prefs_pkey PRIMARY KEY (user_id, event_type);


--
-- Name: bh_password_reset_tokens bh_password_reset_tokens_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_password_reset_tokens
    ADD CONSTRAINT bh_password_reset_tokens_pkey PRIMARY KEY (id);


--
-- Name: bh_password_reset_tokens bh_password_reset_tokens_token_hash_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_password_reset_tokens
    ADD CONSTRAINT bh_password_reset_tokens_token_hash_key UNIQUE (token_hash);


--
-- Name: bh_patterns bh_patterns_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_patterns
    ADD CONSTRAINT bh_patterns_pkey PRIMARY KEY (id);


--
-- Name: bh_pinned_context bh_pinned_context_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_pinned_context
    ADD CONSTRAINT bh_pinned_context_pkey PRIMARY KEY (id);


--
-- Name: bh_platform_settings bh_platform_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_platform_settings
    ADD CONSTRAINT bh_platform_settings_pkey PRIMARY KEY (key);


--
-- Name: bh_push_subscriptions bh_push_subscriptions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_push_subscriptions
    ADD CONSTRAINT bh_push_subscriptions_pkey PRIMARY KEY (id);


--
-- Name: bh_refresh_tokens bh_refresh_tokens_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_refresh_tokens
    ADD CONSTRAINT bh_refresh_tokens_pkey PRIMARY KEY (id);


--
-- Name: bh_refresh_tokens bh_refresh_tokens_token_hash_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_refresh_tokens
    ADD CONSTRAINT bh_refresh_tokens_token_hash_key UNIQUE (token_hash);


--
-- Name: bh_relationships bh_relationships_from_entity_id_to_entity_id_relationship_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_relationships
    ADD CONSTRAINT bh_relationships_from_entity_id_to_entity_id_relationship_key UNIQUE (from_entity_id, to_entity_id, relationship);


--
-- Name: bh_relationships bh_relationships_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_relationships
    ADD CONSTRAINT bh_relationships_pkey PRIMARY KEY (id);


--
-- Name: bh_reminders bh_reminders_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_reminders
    ADD CONSTRAINT bh_reminders_pkey PRIMARY KEY (id);


--
-- Name: bh_skills bh_skills_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_skills
    ADD CONSTRAINT bh_skills_name_key UNIQUE (name);


--
-- Name: bh_skills bh_skills_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_skills
    ADD CONSTRAINT bh_skills_pkey PRIMARY KEY (id);


--
-- Name: bh_slash_commands bh_slash_commands_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_slash_commands
    ADD CONSTRAINT bh_slash_commands_pkey PRIMARY KEY (id);


--
-- Name: bh_themes bh_themes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_themes
    ADD CONSTRAINT bh_themes_pkey PRIMARY KEY (id);


--
-- Name: bh_themes bh_themes_slug_owner_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_themes
    ADD CONSTRAINT bh_themes_slug_owner_id_key UNIQUE (slug, owner_id);


--
-- Name: bh_users bh_users_email_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_users
    ADD CONSTRAINT bh_users_email_key UNIQUE (email);


--
-- Name: bh_users bh_users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_users
    ADD CONSTRAINT bh_users_pkey PRIMARY KEY (id);


--
-- Name: bh_workspace_skills bh_workspace_skills_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_workspace_skills
    ADD CONSTRAINT bh_workspace_skills_pkey PRIMARY KEY (workspace_id, skill_id);


--
-- Name: bh_workspace_users bh_workspace_users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_workspace_users
    ADD CONSTRAINT bh_workspace_users_pkey PRIMARY KEY (workspace_id, user_id);


--
-- Name: bh_workspaces bh_workspaces_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_workspaces
    ADD CONSTRAINT bh_workspaces_pkey PRIMARY KEY (id);


--
-- Name: db_admin_field_hints db_admin_field_hints_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.db_admin_field_hints
    ADD CONSTRAINT db_admin_field_hints_pkey PRIMARY KEY (column_name);


--
-- Name: recipe_files_asset_idx; Type: INDEX; Schema: cook; Owner: -
--

CREATE INDEX recipe_files_asset_idx ON cook.recipe_files USING btree (asset_id);


--
-- Name: assets_ai_extracted_idx; Type: INDEX; Schema: files; Owner: -
--

CREATE INDEX assets_ai_extracted_idx ON files.assets USING gin (ai_extracted);


--
-- Name: assets_domain_idx; Type: INDEX; Schema: files; Owner: -
--

CREATE INDEX assets_domain_idx ON files.assets USING btree (domain);


--
-- Name: assets_uploaded_at_idx; Type: INDEX; Schema: files; Owner: -
--

CREATE INDEX assets_uploaded_at_idx ON files.assets USING btree (uploaded_at DESC);


--
-- Name: idx_categories_parent_id; Type: INDEX; Schema: finance; Owner: -
--

CREATE INDEX idx_categories_parent_id ON finance.categories USING btree (parent_id);


--
-- Name: idx_category_examples_category_id; Type: INDEX; Schema: finance; Owner: -
--

CREATE INDEX idx_category_examples_category_id ON finance.category_examples USING btree (category_id);


--
-- Name: idx_category_examples_unique_pattern; Type: INDEX; Schema: finance; Owner: -
--

CREATE UNIQUE INDEX idx_category_examples_unique_pattern ON finance.category_examples USING btree (lower(description_pattern), category_id);


--
-- Name: idx_email_classified_at; Type: INDEX; Schema: finance; Owner: -
--

CREATE INDEX idx_email_classified_at ON finance.email_classified USING btree (classified_at DESC);


--
-- Name: idx_transactions_account_id; Type: INDEX; Schema: finance; Owner: -
--

CREATE INDEX idx_transactions_account_id ON finance.transactions USING btree (account_id);


--
-- Name: idx_transactions_category_id; Type: INDEX; Schema: finance; Owner: -
--

CREATE INDEX idx_transactions_category_id ON finance.transactions USING btree (category_id);


--
-- Name: idx_transactions_house_tag; Type: INDEX; Schema: finance; Owner: -
--

CREATE INDEX idx_transactions_house_tag ON finance.transactions USING btree (house_tag);


--
-- Name: idx_transactions_is_investment; Type: INDEX; Schema: finance; Owner: -
--

CREATE INDEX idx_transactions_is_investment ON finance.transactions USING btree (is_investment) WHERE (is_investment = true);


--
-- Name: idx_transactions_is_transfer; Type: INDEX; Schema: finance; Owner: -
--

CREATE INDEX idx_transactions_is_transfer ON finance.transactions USING btree (is_transfer);


--
-- Name: idx_transactions_posted_date; Type: INDEX; Schema: finance; Owner: -
--

CREATE INDEX idx_transactions_posted_date ON finance.transactions USING btree (posted_date);


--
-- Name: idx_transactions_posted_date_category; Type: INDEX; Schema: finance; Owner: -
--

CREATE INDEX idx_transactions_posted_date_category ON finance.transactions USING btree (posted_date, category_id);


--
-- Name: idx_transactions_source; Type: INDEX; Schema: finance; Owner: -
--

CREATE INDEX idx_transactions_source ON finance.transactions USING btree (source);


--
-- Name: transaction_files_asset_idx; Type: INDEX; Schema: finance; Owner: -
--

CREATE INDEX transaction_files_asset_idx ON finance.transaction_files USING btree (asset_id);


--
-- Name: room_files_asset_idx; Type: INDEX; Schema: house; Owner: -
--

CREATE INDEX room_files_asset_idx ON house.room_files USING btree (asset_id);


--
-- Name: album_files_asset_idx; Type: INDEX; Schema: inventory; Owner: -
--

CREATE INDEX album_files_asset_idx ON inventory.album_files USING btree (asset_id);


--
-- Name: manual_files_asset_idx; Type: INDEX; Schema: inventory; Owner: -
--

CREATE INDEX manual_files_asset_idx ON inventory.manual_files USING btree (asset_id);


--
-- Name: router_bit_files_asset_idx; Type: INDEX; Schema: inventory; Owner: -
--

CREATE INDEX router_bit_files_asset_idx ON inventory.router_bit_files USING btree (asset_id);


--
-- Name: saw_blade_files_asset_idx; Type: INDEX; Schema: inventory; Owner: -
--

CREATE INDEX saw_blade_files_asset_idx ON inventory.saw_blade_files USING btree (asset_id);


--
-- Name: tool_files_asset_idx; Type: INDEX; Schema: inventory; Owner: -
--

CREATE INDEX tool_files_asset_idx ON inventory.tool_files USING btree (asset_id);


--
-- Name: wood_files_asset_idx; Type: INDEX; Schema: inventory; Owner: -
--

CREATE INDEX wood_files_asset_idx ON inventory.wood_files USING btree (asset_id);


--
-- Name: api_usage_log_called_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX api_usage_log_called_at_idx ON public.api_usage_log USING btree (called_at DESC);


--
-- Name: api_usage_log_model_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX api_usage_log_model_idx ON public.api_usage_log USING btree (model);


--
-- Name: api_usage_log_workflow_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX api_usage_log_workflow_idx ON public.api_usage_log USING btree (workflow_name);


--
-- Name: idx_api_usage_log_api_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_api_usage_log_api_name ON public.bh_api_usage_log USING btree (api_name);


--
-- Name: idx_api_usage_log_called_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_api_usage_log_called_at ON public.bh_api_usage_log USING btree (called_at DESC);


--
-- Name: idx_bh_audit_log_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_bh_audit_log_user ON public.bh_audit_log USING btree (user_id, created_at DESC);


--
-- Name: idx_bh_conversations_workspace_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_bh_conversations_workspace_user ON public.bh_conversations USING btree (workspace_id, user_id, updated_at DESC);


--
-- Name: idx_bh_messages_conversation; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_bh_messages_conversation ON public.bh_messages USING btree (conversation_id, created_at);


--
-- Name: idx_bh_messages_fts; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_bh_messages_fts ON public.bh_messages USING gin (to_tsvector('english'::regconfig, content));


--
-- Name: idx_bh_reminders_due; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_bh_reminders_due ON public.bh_reminders USING btree (deliver_at) WHERE (delivered_at IS NULL);


--
-- Name: idx_bh_themes_owner; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_bh_themes_owner ON public.bh_themes USING btree (owner_id);


--
-- Name: idx_bh_themes_preset; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_bh_themes_preset ON public.bh_themes USING btree (is_preset);


--
-- Name: idx_dashboard_layouts_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dashboard_layouts_user ON public.bh_dashboard_layouts USING btree (user_id);


--
-- Name: idx_db_browser_layouts_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_db_browser_layouts_user_id ON public.bh_db_browser_layouts USING btree (user_id);


--
-- Name: idx_db_browser_undo_log_session_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_db_browser_undo_log_session_created ON public.bh_db_browser_undo_log USING btree (session_id, created_at DESC);


--
-- Name: idx_db_browser_undo_log_session_undone; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_db_browser_undo_log_session_undone ON public.bh_db_browser_undo_log USING btree (session_id, is_undone);


--
-- Name: idx_db_browser_views_user_schema_table; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_db_browser_views_user_schema_table ON public.bh_db_browser_views USING btree (user_id, schema_name, table_name);


--
-- Name: idx_entities_attributes; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_entities_attributes ON public.bh_entities USING gin (attributes);


--
-- Name: idx_entities_fts; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_entities_fts ON public.bh_entities USING gin (to_tsvector('english'::regconfig, ((name || ' '::text) || COALESCE(summary, ''::text))));


--
-- Name: idx_entities_name_lower; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_entities_name_lower ON public.bh_entities USING btree (lower(name));


--
-- Name: idx_entities_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_entities_type ON public.bh_entities USING btree (entity_type);


--
-- Name: idx_list_items_list; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_list_items_list ON public.bh_list_items USING btree (list_id);


--
-- Name: idx_lists_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_lists_user ON public.bh_lists USING btree (user_id);


--
-- Name: idx_password_reset_tokens_expires; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_password_reset_tokens_expires ON public.bh_password_reset_tokens USING btree (expires_at);


--
-- Name: idx_password_reset_tokens_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_password_reset_tokens_user ON public.bh_password_reset_tokens USING btree (user_id);


--
-- Name: idx_relationships_from; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_relationships_from ON public.bh_relationships USING btree (from_entity_id);


--
-- Name: idx_relationships_to; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_relationships_to ON public.bh_relationships USING btree (to_entity_id);


--
-- Name: idx_relationships_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_relationships_type ON public.bh_relationships USING btree (relationship);


--
-- Name: accounts trg_accounts_updated_at; Type: TRIGGER; Schema: finance; Owner: -
--

CREATE TRIGGER trg_accounts_updated_at BEFORE UPDATE ON finance.accounts FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();


--
-- Name: transactions trg_transactions_updated_at; Type: TRIGGER; Schema: finance; Owner: -
--

CREATE TRIGGER trg_transactions_updated_at BEFORE UPDATE ON finance.transactions FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();


--
-- Name: cook_log cook_log_recipe_id_fkey; Type: FK CONSTRAINT; Schema: cook; Owner: -
--

ALTER TABLE ONLY cook.cook_log
    ADD CONSTRAINT cook_log_recipe_id_fkey FOREIGN KEY (recipe_id) REFERENCES cook.recipes(id) ON DELETE CASCADE;


--
-- Name: recipe_files recipe_files_asset_id_fkey; Type: FK CONSTRAINT; Schema: cook; Owner: -
--

ALTER TABLE ONLY cook.recipe_files
    ADD CONSTRAINT recipe_files_asset_id_fkey FOREIGN KEY (asset_id) REFERENCES files.assets(id) ON DELETE CASCADE;


--
-- Name: recipe_files recipe_files_recipe_id_fkey; Type: FK CONSTRAINT; Schema: cook; Owner: -
--

ALTER TABLE ONLY cook.recipe_files
    ADD CONSTRAINT recipe_files_recipe_id_fkey FOREIGN KEY (recipe_id) REFERENCES cook.recipes(id) ON DELETE CASCADE;


--
-- Name: alert_log alert_log_category_id_fkey; Type: FK CONSTRAINT; Schema: finance; Owner: -
--

ALTER TABLE ONLY finance.alert_log
    ADD CONSTRAINT alert_log_category_id_fkey FOREIGN KEY (category_id) REFERENCES finance.categories(id);


--
-- Name: budgets budgets_category_id_fkey; Type: FK CONSTRAINT; Schema: finance; Owner: -
--

ALTER TABLE ONLY finance.budgets
    ADD CONSTRAINT budgets_category_id_fkey FOREIGN KEY (category_id) REFERENCES finance.categories(id);


--
-- Name: categories categories_parent_id_fkey; Type: FK CONSTRAINT; Schema: finance; Owner: -
--

ALTER TABLE ONLY finance.categories
    ADD CONSTRAINT categories_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES finance.categories(id);


--
-- Name: category_examples category_examples_category_id_fkey; Type: FK CONSTRAINT; Schema: finance; Owner: -
--

ALTER TABLE ONLY finance.category_examples
    ADD CONSTRAINT category_examples_category_id_fkey FOREIGN KEY (category_id) REFERENCES finance.categories(id);


--
-- Name: category_examples category_examples_source_transaction_id_fkey; Type: FK CONSTRAINT; Schema: finance; Owner: -
--

ALTER TABLE ONLY finance.category_examples
    ADD CONSTRAINT category_examples_source_transaction_id_fkey FOREIGN KEY (source_transaction_id) REFERENCES finance.transactions(id) ON DELETE SET NULL;


--
-- Name: transaction_files transaction_files_asset_id_fkey; Type: FK CONSTRAINT; Schema: finance; Owner: -
--

ALTER TABLE ONLY finance.transaction_files
    ADD CONSTRAINT transaction_files_asset_id_fkey FOREIGN KEY (asset_id) REFERENCES files.assets(id) ON DELETE CASCADE;


--
-- Name: transaction_files transaction_files_transaction_id_fkey; Type: FK CONSTRAINT; Schema: finance; Owner: -
--

ALTER TABLE ONLY finance.transaction_files
    ADD CONSTRAINT transaction_files_transaction_id_fkey FOREIGN KEY (transaction_id) REFERENCES finance.transactions(id) ON DELETE CASCADE;


--
-- Name: transactions transactions_account_id_fkey; Type: FK CONSTRAINT; Schema: finance; Owner: -
--

ALTER TABLE ONLY finance.transactions
    ADD CONSTRAINT transactions_account_id_fkey FOREIGN KEY (account_id) REFERENCES finance.accounts(id);


--
-- Name: transactions transactions_category_id_fkey; Type: FK CONSTRAINT; Schema: finance; Owner: -
--

ALTER TABLE ONLY finance.transactions
    ADD CONSTRAINT transactions_category_id_fkey FOREIGN KEY (category_id) REFERENCES finance.categories(id);


--
-- Name: room_files room_files_asset_id_fkey; Type: FK CONSTRAINT; Schema: house; Owner: -
--

ALTER TABLE ONLY house.room_files
    ADD CONSTRAINT room_files_asset_id_fkey FOREIGN KEY (asset_id) REFERENCES files.assets(id) ON DELETE CASCADE;


--
-- Name: room_files room_files_room_id_fkey; Type: FK CONSTRAINT; Schema: house; Owner: -
--

ALTER TABLE ONLY house.room_files
    ADD CONSTRAINT room_files_room_id_fkey FOREIGN KEY (room_id) REFERENCES house.rooms(id) ON DELETE CASCADE;


--
-- Name: album_files album_files_album_id_fkey; Type: FK CONSTRAINT; Schema: inventory; Owner: -
--

ALTER TABLE ONLY inventory.album_files
    ADD CONSTRAINT album_files_album_id_fkey FOREIGN KEY (album_id) REFERENCES inventory.albums(id) ON DELETE CASCADE;


--
-- Name: album_files album_files_asset_id_fkey; Type: FK CONSTRAINT; Schema: inventory; Owner: -
--

ALTER TABLE ONLY inventory.album_files
    ADD CONSTRAINT album_files_asset_id_fkey FOREIGN KEY (asset_id) REFERENCES files.assets(id) ON DELETE CASCADE;


--
-- Name: manual_files manual_files_asset_id_fkey; Type: FK CONSTRAINT; Schema: inventory; Owner: -
--

ALTER TABLE ONLY inventory.manual_files
    ADD CONSTRAINT manual_files_asset_id_fkey FOREIGN KEY (asset_id) REFERENCES files.assets(id) ON DELETE CASCADE;


--
-- Name: manual_files manual_files_manual_id_fkey; Type: FK CONSTRAINT; Schema: inventory; Owner: -
--

ALTER TABLE ONLY inventory.manual_files
    ADD CONSTRAINT manual_files_manual_id_fkey FOREIGN KEY (manual_id) REFERENCES inventory.manuals(id) ON DELETE CASCADE;


--
-- Name: router_bit_files router_bit_files_asset_id_fkey; Type: FK CONSTRAINT; Schema: inventory; Owner: -
--

ALTER TABLE ONLY inventory.router_bit_files
    ADD CONSTRAINT router_bit_files_asset_id_fkey FOREIGN KEY (asset_id) REFERENCES files.assets(id) ON DELETE CASCADE;


--
-- Name: router_bit_files router_bit_files_router_bit_id_fkey; Type: FK CONSTRAINT; Schema: inventory; Owner: -
--

ALTER TABLE ONLY inventory.router_bit_files
    ADD CONSTRAINT router_bit_files_router_bit_id_fkey FOREIGN KEY (router_bit_id) REFERENCES inventory.router_bits(id) ON DELETE CASCADE;


--
-- Name: saw_blade_files saw_blade_files_asset_id_fkey; Type: FK CONSTRAINT; Schema: inventory; Owner: -
--

ALTER TABLE ONLY inventory.saw_blade_files
    ADD CONSTRAINT saw_blade_files_asset_id_fkey FOREIGN KEY (asset_id) REFERENCES files.assets(id) ON DELETE CASCADE;


--
-- Name: saw_blade_files saw_blade_files_saw_blade_id_fkey; Type: FK CONSTRAINT; Schema: inventory; Owner: -
--

ALTER TABLE ONLY inventory.saw_blade_files
    ADD CONSTRAINT saw_blade_files_saw_blade_id_fkey FOREIGN KEY (saw_blade_id) REFERENCES inventory.saw_blades(id) ON DELETE CASCADE;


--
-- Name: tool_files tool_files_asset_id_fkey; Type: FK CONSTRAINT; Schema: inventory; Owner: -
--

ALTER TABLE ONLY inventory.tool_files
    ADD CONSTRAINT tool_files_asset_id_fkey FOREIGN KEY (asset_id) REFERENCES files.assets(id) ON DELETE CASCADE;


--
-- Name: tool_files tool_files_tool_id_fkey; Type: FK CONSTRAINT; Schema: inventory; Owner: -
--

ALTER TABLE ONLY inventory.tool_files
    ADD CONSTRAINT tool_files_tool_id_fkey FOREIGN KEY (tool_id) REFERENCES inventory.tools(id) ON DELETE CASCADE;


--
-- Name: wood_files wood_files_asset_id_fkey; Type: FK CONSTRAINT; Schema: inventory; Owner: -
--

ALTER TABLE ONLY inventory.wood_files
    ADD CONSTRAINT wood_files_asset_id_fkey FOREIGN KEY (asset_id) REFERENCES files.assets(id) ON DELETE CASCADE;


--
-- Name: wood_files wood_files_wood_id_fkey; Type: FK CONSTRAINT; Schema: inventory; Owner: -
--

ALTER TABLE ONLY inventory.wood_files
    ADD CONSTRAINT wood_files_wood_id_fkey FOREIGN KEY (wood_id) REFERENCES inventory.wood(id) ON DELETE CASCADE;


--
-- Name: bh_artifacts bh_artifacts_conversation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_artifacts
    ADD CONSTRAINT bh_artifacts_conversation_id_fkey FOREIGN KEY (conversation_id) REFERENCES public.bh_conversations(id) ON DELETE CASCADE;


--
-- Name: bh_artifacts bh_artifacts_message_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_artifacts
    ADD CONSTRAINT bh_artifacts_message_id_fkey FOREIGN KEY (message_id) REFERENCES public.bh_messages(id) ON DELETE CASCADE;


--
-- Name: bh_artifacts bh_artifacts_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_artifacts
    ADD CONSTRAINT bh_artifacts_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.bh_artifacts(id);


--
-- Name: bh_audit_log bh_audit_log_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_audit_log
    ADD CONSTRAINT bh_audit_log_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.bh_users(id);


--
-- Name: bh_conversations bh_conversations_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_conversations
    ADD CONSTRAINT bh_conversations_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.bh_conversations(id);


--
-- Name: bh_conversations bh_conversations_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_conversations
    ADD CONSTRAINT bh_conversations_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.bh_users(id) ON DELETE CASCADE;


--
-- Name: bh_conversations bh_conversations_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_conversations
    ADD CONSTRAINT bh_conversations_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.bh_workspaces(id) ON DELETE CASCADE;


--
-- Name: bh_dashboard_layouts bh_dashboard_layouts_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_dashboard_layouts
    ADD CONSTRAINT bh_dashboard_layouts_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.bh_users(id) ON DELETE CASCADE;


--
-- Name: bh_db_browser_layouts bh_db_browser_layouts_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_db_browser_layouts
    ADD CONSTRAINT bh_db_browser_layouts_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.bh_users(id) ON DELETE CASCADE;


--
-- Name: bh_db_browser_undo_log bh_db_browser_undo_log_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_db_browser_undo_log
    ADD CONSTRAINT bh_db_browser_undo_log_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.bh_users(id) ON DELETE CASCADE;


--
-- Name: bh_db_browser_views bh_db_browser_views_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_db_browser_views
    ADD CONSTRAINT bh_db_browser_views_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.bh_users(id) ON DELETE CASCADE;


--
-- Name: bh_entities bh_entities_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_entities
    ADD CONSTRAINT bh_entities_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.bh_users(id);


--
-- Name: bh_hook_log bh_hook_log_hook_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_hook_log
    ADD CONSTRAINT bh_hook_log_hook_id_fkey FOREIGN KEY (hook_id) REFERENCES public.bh_hooks(id) ON DELETE CASCADE;


--
-- Name: bh_hooks bh_hooks_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_hooks
    ADD CONSTRAINT bh_hooks_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.bh_users(id);


--
-- Name: bh_hooks bh_hooks_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_hooks
    ADD CONSTRAINT bh_hooks_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.bh_workspaces(id) ON DELETE CASCADE;


--
-- Name: bh_invite_links bh_invite_links_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_invite_links
    ADD CONSTRAINT bh_invite_links_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.bh_users(id);


--
-- Name: bh_invite_links bh_invite_links_used_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_invite_links
    ADD CONSTRAINT bh_invite_links_used_by_fkey FOREIGN KEY (used_by) REFERENCES public.bh_users(id);


--
-- Name: bh_list_items bh_list_items_list_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_list_items
    ADD CONSTRAINT bh_list_items_list_id_fkey FOREIGN KEY (list_id) REFERENCES public.bh_lists(id) ON DELETE CASCADE;


--
-- Name: bh_lists bh_lists_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_lists
    ADD CONSTRAINT bh_lists_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.bh_users(id) ON DELETE CASCADE;


--
-- Name: bh_messages bh_messages_conversation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_messages
    ADD CONSTRAINT bh_messages_conversation_id_fkey FOREIGN KEY (conversation_id) REFERENCES public.bh_conversations(id) ON DELETE CASCADE;


--
-- Name: bh_notification_prefs bh_notification_prefs_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_notification_prefs
    ADD CONSTRAINT bh_notification_prefs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.bh_users(id) ON DELETE CASCADE;


--
-- Name: bh_password_reset_tokens bh_password_reset_tokens_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_password_reset_tokens
    ADD CONSTRAINT bh_password_reset_tokens_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.bh_users(id) ON DELETE CASCADE;


--
-- Name: bh_patterns bh_patterns_skill_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_patterns
    ADD CONSTRAINT bh_patterns_skill_id_fkey FOREIGN KEY (skill_id) REFERENCES public.bh_skills(id);


--
-- Name: bh_patterns bh_patterns_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_patterns
    ADD CONSTRAINT bh_patterns_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.bh_workspaces(id);


--
-- Name: bh_pinned_context bh_pinned_context_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_pinned_context
    ADD CONSTRAINT bh_pinned_context_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.bh_workspaces(id) ON DELETE CASCADE;


--
-- Name: bh_platform_settings bh_platform_settings_updated_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_platform_settings
    ADD CONSTRAINT bh_platform_settings_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES public.bh_users(id);


--
-- Name: bh_push_subscriptions bh_push_subscriptions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_push_subscriptions
    ADD CONSTRAINT bh_push_subscriptions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.bh_users(id) ON DELETE CASCADE;


--
-- Name: bh_refresh_tokens bh_refresh_tokens_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_refresh_tokens
    ADD CONSTRAINT bh_refresh_tokens_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.bh_users(id) ON DELETE CASCADE;


--
-- Name: bh_relationships bh_relationships_from_entity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_relationships
    ADD CONSTRAINT bh_relationships_from_entity_id_fkey FOREIGN KEY (from_entity_id) REFERENCES public.bh_entities(id) ON DELETE CASCADE;


--
-- Name: bh_relationships bh_relationships_to_entity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_relationships
    ADD CONSTRAINT bh_relationships_to_entity_id_fkey FOREIGN KEY (to_entity_id) REFERENCES public.bh_entities(id) ON DELETE CASCADE;


--
-- Name: bh_reminders bh_reminders_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_reminders
    ADD CONSTRAINT bh_reminders_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.bh_users(id) ON DELETE CASCADE;


--
-- Name: bh_slash_commands bh_slash_commands_skill_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_slash_commands
    ADD CONSTRAINT bh_slash_commands_skill_id_fkey FOREIGN KEY (skill_id) REFERENCES public.bh_skills(id);


--
-- Name: bh_slash_commands bh_slash_commands_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_slash_commands
    ADD CONSTRAINT bh_slash_commands_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.bh_workspaces(id);


--
-- Name: bh_themes bh_themes_owner_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_themes
    ADD CONSTRAINT bh_themes_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES public.bh_users(id) ON DELETE CASCADE;


--
-- Name: bh_workspace_skills bh_workspace_skills_skill_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_workspace_skills
    ADD CONSTRAINT bh_workspace_skills_skill_id_fkey FOREIGN KEY (skill_id) REFERENCES public.bh_skills(id) ON DELETE CASCADE;


--
-- Name: bh_workspace_skills bh_workspace_skills_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_workspace_skills
    ADD CONSTRAINT bh_workspace_skills_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.bh_workspaces(id) ON DELETE CASCADE;


--
-- Name: bh_workspace_users bh_workspace_users_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_workspace_users
    ADD CONSTRAINT bh_workspace_users_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.bh_users(id) ON DELETE CASCADE;


--
-- Name: bh_workspace_users bh_workspace_users_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_workspace_users
    ADD CONSTRAINT bh_workspace_users_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.bh_workspaces(id) ON DELETE CASCADE;


--
-- Name: bh_workspaces bh_workspaces_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.bh_workspaces
    ADD CONSTRAINT bh_workspaces_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.bh_users(id);


--
-- PostgreSQL database dump complete
--



-- ============================================================================
-- SEED / CONFIG DATA (app configuration tables only — no user/private data).
-- Tables: bh_skills, bh_workspaces, bh_workspace_skills, bh_slash_commands,
-- bh_model_rates, bh_themes (presets), bh_platform_settings, bh_patterns,
-- bh_dashboard_widgets, bh_api_registry, finance.email_labels.
-- Lets a fresh database boot a working app. On databases that predate the
-- baseline this whole file is adopted, not executed (see run_migrations).
-- ============================================================================

--
--


-- Dumped from database version 16.13
-- Dumped by pg_dump version 16.13

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Data for Name: email_labels; Type: TABLE DATA; Schema: finance; Owner: -
--

INSERT INTO finance.email_labels (label, times_used, first_used, last_used) VALUES ('AI-Tags/Receipts', 0, '2026-05-19 01:56:19.503791+00', '2026-05-19 01:56:19.503791+00');
INSERT INTO finance.email_labels (label, times_used, first_used, last_used) VALUES ('AI-Tags/Bills', 0, '2026-05-19 01:56:19.503791+00', '2026-05-19 01:56:19.503791+00');
INSERT INTO finance.email_labels (label, times_used, first_used, last_used) VALUES ('AI-Tags/Shipping', 0, '2026-05-19 01:56:19.503791+00', '2026-05-19 01:56:19.503791+00');
INSERT INTO finance.email_labels (label, times_used, first_used, last_used) VALUES ('AI-Tags/Pets', 0, '2026-05-19 01:56:19.503791+00', '2026-05-19 01:56:19.503791+00');
INSERT INTO finance.email_labels (label, times_used, first_used, last_used) VALUES ('AI-Tags/House', 0, '2026-05-19 01:56:19.503791+00', '2026-05-19 01:56:19.503791+00');
INSERT INTO finance.email_labels (label, times_used, first_used, last_used) VALUES ('AI-Tags/Action-Required', 1, '2026-05-19 01:56:19.503791+00', '2026-05-19 02:40:28.427823+00');
INSERT INTO finance.email_labels (label, times_used, first_used, last_used) VALUES ('AI-Tags/Subscriptions', 2, '2026-05-19 01:56:19.503791+00', '2026-05-19 02:45:31.417165+00');
INSERT INTO finance.email_labels (label, times_used, first_used, last_used) VALUES ('AI-Tags/Travel', 1, '2026-05-19 01:56:19.503791+00', '2026-05-19 02:52:00.460988+00');
INSERT INTO finance.email_labels (label, times_used, first_used, last_used) VALUES ('AI-Tags/Finance', 2, '2026-05-19 01:56:19.503791+00', '2026-05-19 02:55:29.263311+00');
INSERT INTO finance.email_labels (label, times_used, first_used, last_used) VALUES ('AI-Tags/Spam-ish', 4, '2026-05-19 01:56:19.503791+00', '2026-05-19 03:00:30.589689+00');
INSERT INTO finance.email_labels (label, times_used, first_used, last_used) VALUES ('AI-Tags/Social', 2, '2026-05-19 01:56:19.503791+00', '2026-05-19 03:05:32.700259+00');
INSERT INTO finance.email_labels (label, times_used, first_used, last_used) VALUES ('AI-Tags/Newsletters', 5, '2026-05-19 01:56:19.503791+00', '2026-05-19 03:05:32.700259+00');


--
-- Data for Name: bh_api_registry; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.bh_api_registry (id, name, base_url, description, auth_type, auth_config, endpoints, headers, is_active, usage_count, last_used_at, created_at, notes) VALUES (1, 'espn', 'https://site.api.espn.com/apis/site/v2/sports', 'ESPN Sports API — live scores, box scores, standings, schedules, news for MLB, NFL, NBA, NHL, MLS, UFC, F1, Golf, Tennis, College sports. No auth required.', 'none', NULL, '[{"name": "scoreboard", "path": "/{sport}/{league}/scoreboard", "method": "GET", "params": {"dates": "YYYYMMDD", "sport": "baseball|football|basketball|hockey|soccer|mma|racing|golf|tennis", "league": "mlb|nfl|nba|nhl|usa.1|ufc|f1|pga|atp|eng.1|esp.1"}, "description": "Live/recent scores. Params: dates (YYYYMMDD)"}, {"name": "summary", "path": "/{sport}/{league}/summary", "method": "GET", "params": {"event": "game ID number"}, "description": "Full game detail with box score, play-by-play, stats. Params: event (game ID from scoreboard)"}, {"name": "standings", "path": "/{sport}/{league}/standings", "method": "GET", "description": "Current league standings"}, {"name": "teams", "path": "/{sport}/{league}/teams", "method": "GET", "description": "All teams in a league"}, {"name": "team_detail", "path": "/{sport}/{league}/teams/{team_id}", "method": "GET", "description": "Specific team info, roster, stats"}, {"name": "news", "path": "/{sport}/{league}/news", "method": "GET", "description": "Latest news/headlines for a sport. Params: limit (number)"}]', NULL, true, 0, NULL, '2026-06-07 20:14:29.805917+00', NULL);
INSERT INTO public.bh_api_registry (id, name, base_url, description, auth_type, auth_config, endpoints, headers, is_active, usage_count, last_used_at, created_at, notes) VALUES (2, 'wttr', 'https://wttr.in', 'Weather API — current conditions and forecast for any location worldwide. No auth required. Supports cities, zip codes, airports, landmarks.', 'none', NULL, '[{"name": "forecast", "path": "/{location}", "method": "GET", "params": {"format": "j1", "location": "city name, zip code, or airport code"}, "description": "Weather forecast. Use format=j1 for JSON."}]', NULL, true, 0, NULL, '2026-06-07 20:14:29.805917+00', NULL);
INSERT INTO public.bh_api_registry (id, name, base_url, description, auth_type, auth_config, endpoints, headers, is_active, usage_count, last_used_at, created_at, notes) VALUES (3, 'npr_rss', 'https://feeds.npr.org', 'NPR News RSS — top stories, world news, business, science, technology. No auth required.', 'none', NULL, '[{"name": "top_stories", "path": "/1001/rss.xml", "method": "GET", "description": "Top news stories"}, {"name": "world", "path": "/1004/rss.xml", "method": "GET", "description": "World news"}, {"name": "business", "path": "/1006/rss.xml", "method": "GET", "description": "Business/economy news"}, {"name": "science", "path": "/1007/rss.xml", "method": "GET", "description": "Science news"}, {"name": "technology", "path": "/1019/rss.xml", "method": "GET", "description": "Technology news"}]', NULL, true, 0, NULL, '2026-06-07 20:14:29.805917+00', NULL);
INSERT INTO public.bh_api_registry (id, name, base_url, description, auth_type, auth_config, endpoints, headers, is_active, usage_count, last_used_at, created_at, notes) VALUES (4, 'ars_technica', 'https://feeds.arstechnica.com', 'Ars Technica RSS — technology, science, gaming, policy news. No auth required.', 'none', NULL, '[{"name": "all", "path": "/arstechnica/index", "method": "GET", "description": "All Ars Technica articles"}]', NULL, true, 0, NULL, '2026-06-07 20:14:29.805917+00', NULL);
INSERT INTO public.bh_api_registry (id, name, base_url, description, auth_type, auth_config, endpoints, headers, is_active, usage_count, last_used_at, created_at, notes) VALUES (5, 'open_meteo', 'https://api.open-meteo.com/v1', 'Open-Meteo Weather API — detailed weather forecasts, historical data, air quality. Free, no auth, high resolution.', 'none', NULL, '[{"name": "forecast", "path": "/forecast", "method": "GET", "params": {"daily": "temperature_2m_max,temperature_2m_min,precipitation_sum", "latitude": "decimal", "longitude": "decimal", "current_weather": "true"}, "description": "Weather forecast by coordinates"}, {"name": "geocoding", "path": "/geocoding/v1/search", "method": "GET", "params": {"name": "city name", "count": "1"}, "description": "Convert city name to lat/lng"}]', NULL, true, 0, NULL, '2026-06-07 20:14:29.805917+00', NULL);
INSERT INTO public.bh_api_registry (id, name, base_url, description, auth_type, auth_config, endpoints, headers, is_active, usage_count, last_used_at, created_at, notes) VALUES (6, 'tmdb', 'https://api.themoviedb.org/3', 'The Movie Database API — movies, TV shows, ratings, cast, streaming availability. Requires free API key (set TMDB_API_KEY env var).', 'api_key', NULL, '[{"name": "search_movie", "path": "/search/movie", "method": "GET", "params": {"query": "movie title"}, "description": "Search for movies by title"}, {"name": "search_tv", "path": "/search/tv", "method": "GET", "params": {"query": "show title"}, "description": "Search for TV shows"}, {"name": "trending", "path": "/trending/all/week", "method": "GET", "description": "Trending movies and TV this week"}, {"name": "movie_detail", "path": "/movie/{id}", "method": "GET", "description": "Full movie details, cast, ratings"}]', NULL, true, 0, NULL, '2026-06-07 20:14:29.805917+00', NULL);
INSERT INTO public.bh_api_registry (id, name, base_url, description, auth_type, auth_config, endpoints, headers, is_active, usage_count, last_used_at, created_at, notes) VALUES (7, 'exchangerate', 'https://open.er-api.com/v6', 'Exchange Rate API — free currency conversion. No auth, 1500 requests/month.', 'none', NULL, '[{"name": "latest", "path": "/latest/{base}", "method": "GET", "description": "Latest exchange rates. Base is 3-letter currency code (USD, EUR, GBP, etc)"}]', NULL, true, 0, NULL, '2026-06-07 20:14:29.805917+00', NULL);
INSERT INTO public.bh_api_registry (id, name, base_url, description, auth_type, auth_config, endpoints, headers, is_active, usage_count, last_used_at, created_at, notes) VALUES (8, 'wikipedia', 'https://en.wikipedia.org/api/rest_v1', 'Wikipedia API — article summaries, random articles, page content. No auth.', 'none', NULL, '[{"name": "summary", "path": "/page/summary/{title}", "method": "GET", "description": "Get a summary of a Wikipedia article"}, {"name": "random", "path": "/page/random/summary", "method": "GET", "description": "Get a random Wikipedia article summary"}]', NULL, true, 0, NULL, '2026-06-07 20:14:29.805917+00', NULL);
INSERT INTO public.bh_api_registry (id, name, base_url, description, auth_type, auth_config, endpoints, headers, is_active, usage_count, last_used_at, created_at, notes) VALUES (9, 'numbersapi', 'http://numbersapi.com', 'Numbers API — fun facts about numbers, dates, math. No auth.', 'none', NULL, '[{"name": "number_fact", "path": "/{number}", "method": "GET", "description": "Fun fact about a number"}, {"name": "date_fact", "path": "/{month}/{day}/date", "method": "GET", "description": "Historical fact about a date"}, {"name": "math_fact", "path": "/{number}/math", "method": "GET", "description": "Math fact about a number"}]', NULL, true, 0, NULL, '2026-06-07 20:14:29.805917+00', NULL);


--
-- Data for Name: bh_dashboard_widgets; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.bh_dashboard_widgets (id, widget_key, display_name, description, category, data_endpoint, default_config, default_pages, sort_order, is_active, created_at) VALUES (1, 'weather', 'Weather', 'Current conditions and 3-day forecast', 'general', '/api/dashboard/weather', '{"location": "Clawson,MI", "polling_interval_ms": 300000}', '["overview"]', 1, true, '2026-06-07 21:41:17.938219+00');
INSERT INTO public.bh_dashboard_widgets (id, widget_key, display_name, description, category, data_endpoint, default_config, default_pages, sort_order, is_active, created_at) VALUES (2, 'finance_summary', 'Finance Summary', 'MTD spending, top categories, and net change', 'finance', '/api/dashboard/finance/summary', '{"polling_interval_ms": 60000}', '["overview", "finance"]', 2, true, '2026-06-07 21:41:17.938219+00');
INSERT INTO public.bh_dashboard_widgets (id, widget_key, display_name, description, category, data_endpoint, default_config, default_pages, sort_order, is_active, created_at) VALUES (3, 'finance_balances', 'Balances', 'Account balances grouped by type with net worth', 'finance', '/api/dashboard/finance/balances', '{"polling_interval_ms": 60000}', '["finance"]', 3, true, '2026-06-07 21:41:17.938219+00');
INSERT INTO public.bh_dashboard_widgets (id, widget_key, display_name, description, category, data_endpoint, default_config, default_pages, sort_order, is_active, created_at) VALUES (4, 'recent_transactions', 'Recent Transactions', 'Last 10 transactions with details', 'finance', '/api/dashboard/finance/recent-transactions', '{"polling_interval_ms": 60000}', '["finance"]', 4, true, '2026-06-07 21:41:17.938219+00');
INSERT INTO public.bh_dashboard_widgets (id, widget_key, display_name, description, category, data_endpoint, default_config, default_pages, sort_order, is_active, created_at) VALUES (5, 'system_health', 'System Health', 'CPU, memory, disk usage, and uptime', 'system', '/api/dashboard/system-health', '{"polling_interval_ms": 30000}', '["system"]', 5, true, '2026-06-07 21:41:17.938219+00');
INSERT INTO public.bh_dashboard_widgets (id, widget_key, display_name, description, category, data_endpoint, default_config, default_pages, sort_order, is_active, created_at) VALUES (6, 'containers', 'Containers', 'Docker container status and quick links', 'system', '/api/dashboard/containers', '{"links": {"n8n": "http://100.106.180.101:5678", "bowershub-ai": "https://595bowershub.tailc4d58a.ts.net"}, "polling_interval_ms": 30000}', '["overview", "system"]', 6, true, '2026-06-07 21:41:17.938219+00');
INSERT INTO public.bh_dashboard_widgets (id, widget_key, display_name, description, category, data_endpoint, default_config, default_pages, sort_order, is_active, created_at) VALUES (7, 'inventory', 'Inventory', 'Item counts per inventory table', 'general', '/api/dashboard/inventory', '{"polling_interval_ms": 300000}', '["system"]', 7, true, '2026-06-07 21:41:17.938219+00');
INSERT INTO public.bh_dashboard_widgets (id, widget_key, display_name, description, category, data_endpoint, default_config, default_pages, sort_order, is_active, created_at) VALUES (8, 'knowledge_base', 'Knowledge Base', 'Knowledge base file and topic counts', 'general', '/api/dashboard/knowledge', '{"polling_interval_ms": 300000}', '["system"]', 8, true, '2026-06-07 21:41:17.938219+00');
INSERT INTO public.bh_dashboard_widgets (id, widget_key, display_name, description, category, data_endpoint, default_config, default_pages, sort_order, is_active, created_at) VALUES (9, 'recent_emails', 'Recent Emails', 'Unread count and last 5 subject lines', 'general', '/api/dashboard/emails', '{"polling_interval_ms": 120000}', '["overview"]', 9, true, '2026-06-07 21:41:17.938219+00');
INSERT INTO public.bh_dashboard_widgets (id, widget_key, display_name, description, category, data_endpoint, default_config, default_pages, sort_order, is_active, created_at) VALUES (10, 'tailscale_devices', 'Tailscale Devices', 'Device list with online/offline status', 'system', '/api/dashboard/tailscale', '{"polling_interval_ms": 60000}', '["system"]', 10, true, '2026-06-07 21:41:17.938219+00');
INSERT INTO public.bh_dashboard_widgets (id, widget_key, display_name, description, category, data_endpoint, default_config, default_pages, sort_order, is_active, created_at) VALUES (11, 'api_spend', 'API Spend', '7-day Anthropic API usage and cost breakdown', 'system', '/api/dashboard/api-spend', '{"polling_interval_ms": 300000}', '["finance"]', 11, true, '2026-06-07 21:41:17.938219+00');
INSERT INTO public.bh_dashboard_widgets (id, widget_key, display_name, description, category, data_endpoint, default_config, default_pages, sort_order, is_active, created_at) VALUES (12, 'sports_scores', 'Sports Scores', 'Recent scores for tracked teams', 'general', '/api/dashboard/sports-scores', '{"polling_interval_ms": 300000}', '["overview"]', 12, true, '2026-06-07 21:41:17.938219+00');
INSERT INTO public.bh_dashboard_widgets (id, widget_key, display_name, description, category, data_endpoint, default_config, default_pages, sort_order, is_active, created_at) VALUES (13, 'news', 'Top Stories', 'Latest headlines', 'general', '/api/dashboard/news', '{"polling_interval_ms": 600000}', '["overview"]', 13, true, '2026-06-07 23:37:28.155471+00');


--
-- Data for Name: bh_model_rates; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.bh_model_rates (id, provider, model_id, display_name, input_cost_per_mtok, output_cost_per_mtok, supports_vision, supports_tools, max_output_tokens, updated_at) VALUES (1, 'anthropic', 'claude-haiku-4-5-20251001', 'Claude Haiku 4.5', 0.8000, 4.0000, true, true, 8192, '2026-05-27 02:09:37.859117+00');
INSERT INTO public.bh_model_rates (id, provider, model_id, display_name, input_cost_per_mtok, output_cost_per_mtok, supports_vision, supports_tools, max_output_tokens, updated_at) VALUES (5, 'bedrock', 'us.anthropic.claude-haiku-4-5-20251001-v1:0', 'Haiku 4.5 (Bedrock)', 0.8000, 4.0000, true, true, 8192, '2026-05-27 02:09:37.859117+00');
INSERT INTO public.bh_model_rates (id, provider, model_id, display_name, input_cost_per_mtok, output_cost_per_mtok, supports_vision, supports_tools, max_output_tokens, updated_at) VALUES (9, 'ollama', 'hermes3:8b', 'Hermes 3 8B (Local)', 0.0000, 0.0000, false, true, 4096, '2026-05-27 02:09:37.859117+00');
INSERT INTO public.bh_model_rates (id, provider, model_id, display_name, input_cost_per_mtok, output_cost_per_mtok, supports_vision, supports_tools, max_output_tokens, updated_at) VALUES (10, 'ollama', 'llama3.2:3b', 'Llama 3.2 3B (Local)', 0.0000, 0.0000, false, false, 4096, '2026-05-27 02:09:37.859117+00');
INSERT INTO public.bh_model_rates (id, provider, model_id, display_name, input_cost_per_mtok, output_cost_per_mtok, supports_vision, supports_tools, max_output_tokens, updated_at) VALUES (11, 'ollama', 'qwen2.5:7b', 'Qwen 2.5 7B (Local)', 0.0000, 0.0000, false, true, 4096, '2026-05-27 02:09:37.859117+00');
INSERT INTO public.bh_model_rates (id, provider, model_id, display_name, input_cost_per_mtok, output_cost_per_mtok, supports_vision, supports_tools, max_output_tokens, updated_at) VALUES (12, 'anthropic', 'claude-sonnet-4-5', 'Claude Sonnet 4.5', 3.0000, 15.0000, true, true, 8192, '2026-05-27 02:47:08.418472+00');
INSERT INTO public.bh_model_rates (id, provider, model_id, display_name, input_cost_per_mtok, output_cost_per_mtok, supports_vision, supports_tools, max_output_tokens, updated_at) VALUES (13, 'anthropic', 'claude-opus-4-5', 'Claude Opus 4.5', 15.0000, 75.0000, true, true, 8192, '2026-05-27 02:47:08.418472+00');
INSERT INTO public.bh_model_rates (id, provider, model_id, display_name, input_cost_per_mtok, output_cost_per_mtok, supports_vision, supports_tools, max_output_tokens, updated_at) VALUES (14, 'bedrock', 'us.anthropic.claude-sonnet-4-5-v1:0', 'Sonnet 4.5 (Bedrock)', 3.0000, 15.0000, true, true, 8192, '2026-05-27 02:47:08.418472+00');


--
-- Data for Name: bh_skills; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.bh_skills (id, name, description, webhook_url, http_method, param_schema, response_hint, is_active, restricted_users, created_at, is_read_only) VALUES (6, 'override-category', 'Re-categorize a transaction. Triggers learning loop for future auto-categorization.', '/webhook/update-category', 'POST', '{"type": "object", "required": ["transaction_id", "category"], "properties": {"category": {"type": "string"}, "transaction_id": {"type": "integer"}, "confirm_retroactive": {"type": "boolean"}}}', 'single', true, '{1}', '2026-05-27 02:09:37.85225+00', false);
INSERT INTO public.bh_skills (id, name, description, webhook_url, http_method, param_schema, response_hint, is_active, restricted_users, created_at, is_read_only) VALUES (7, 'smart-capture-extract', 'Extract structured data from text and/or images. Returns draft intents for confirmation.', '/webhook/smart-capture/extract', 'POST', '{"type": "object", "properties": {"text": {"type": "string"}, "image_path": {"type": "string"}, "domain_hint": {"type": "string"}}}', 'json', true, '{}', '2026-05-27 02:09:37.85225+00', false);
INSERT INTO public.bh_skills (id, name, description, webhook_url, http_method, param_schema, response_hint, is_active, restricted_users, created_at, is_read_only) VALUES (8, 'smart-capture-commit', 'Commit an accepted capture intent to the database or knowledge base.', '/webhook/smart-capture/commit', 'POST', '{"type": "object", "required": ["domain", "payload", "extract_token"], "properties": {"domain": {"type": "string"}, "payload": {"type": "object"}, "asset_id": {"type": "string"}, "extract_token": {"type": "string"}}}', 'single', true, '{}', '2026-05-27 02:09:37.85225+00', false);
INSERT INTO public.bh_skills (id, name, description, webhook_url, http_method, param_schema, response_hint, is_active, restricted_users, created_at, is_read_only) VALUES (9, 'inventory-admin', 'Manage inventory records: update fields, archive, unarchive, delete, or merge duplicates.', '/webhook/inventory-admin', 'POST', '{"type": "object", "required": ["action", "table", "id"], "properties": {"id": {"type": "integer"}, "table": {"type": "string"}, "action": {"enum": ["update", "archive", "unarchive", "delete", "merge"], "type": "string"}, "fields": {"type": "object"}}}', 'single', true, '{1}', '2026-05-27 02:09:37.85225+00', false);
INSERT INTO public.bh_skills (id, name, description, webhook_url, http_method, param_schema, response_hint, is_active, restricted_users, created_at, is_read_only) VALUES (12, 'send-email', 'Send an email via Gmail SMTP.', '/webhook/send-email', 'POST', '{"type": "object", "required": ["to", "subject", "body"], "properties": {"to": {"type": "string"}, "body": {"type": "string"}, "html": {"type": "string"}, "subject": {"type": "string"}}}', 'single', true, '{1}', '2026-05-27 02:09:37.85225+00', false);
INSERT INTO public.bh_skills (id, name, description, webhook_url, http_method, param_schema, response_hint, is_active, restricted_users, created_at, is_read_only) VALUES (13, 'process-asset', 'Process a file through the vision pipeline: dedup, classify, extract metadata, move to permanent storage.', '/webhook/process-asset', 'POST', '{"type": "object", "required": ["path"], "properties": {"path": {"type": "string", "description": "File path relative to /files"}, "domain_hint": {"type": "string"}, "uploaded_by": {"type": "string"}}}', 'json', true, '{}', '2026-05-27 02:09:37.85225+00', false);
INSERT INTO public.bh_skills (id, name, description, webhook_url, http_method, param_schema, response_hint, is_active, restricted_users, created_at, is_read_only) VALUES (4, 'filter-transactions', 'Search transactions by account, category, amount, or description.', '/webhook/filter', 'POST', '{"type": "object", "properties": {"account": {"type": "string"}, "category": {"type": "string"}, "max_amount": {"type": "number"}, "min_amount": {"type": "number"}, "description": {"type": "string"}}}', 'table', true, '{1}', '2026-05-27 02:09:37.85225+00', true);
INSERT INTO public.bh_skills (id, name, description, webhook_url, http_method, param_schema, response_hint, is_active, restricted_users, created_at, is_read_only) VALUES (2, 'balances', 'Get current balances for all bank accounts and net worth.', '/webhook/balances', 'POST', '{"type": "object", "properties": {}}', 'table', true, '{1}', '2026-05-27 02:09:37.85225+00', true);
INSERT INTO public.bh_skills (id, name, description, webhook_url, http_method, param_schema, response_hint, is_active, restricted_users, created_at, is_read_only) VALUES (3, 'transactions', 'Get transactions by date range with category breakdown.', '/webhook/transactions', 'POST', '{"type": "object", "required": ["start_date", "end_date"], "properties": {"end_date": {"type": "string", "description": "End date YYYY-MM-DD"}, "start_date": {"type": "string", "description": "Start date YYYY-MM-DD"}}}', 'table', true, '{1}', '2026-05-27 02:09:37.85225+00', true);
INSERT INTO public.bh_skills (id, name, description, webhook_url, http_method, param_schema, response_hint, is_active, restricted_users, created_at, is_read_only) VALUES (10, 'remember', 'Save a fact to the knowledge base for long-term memory.', 'native://remember', 'POST', '{"type": "object", "required": ["topic", "fact"], "properties": {"fact": {"type": "string", "description": "The fact to remember"}, "topic": {"type": "string", "description": "Topic slug e.g. finance/accounts"}}}', 'text', true, '{}', '2026-05-27 02:09:37.85225+00', false);
INSERT INTO public.bh_skills (id, name, description, webhook_url, http_method, param_schema, response_hint, is_active, restricted_users, created_at, is_read_only) VALUES (5, 'spending-summary', 'Monthly spending breakdown by category with top purchases.', '/webhook/transactions', 'POST', '{"type": "object", "properties": {"month": {"type": "string", "description": "Month in YYYY-MM format (optional, defaults to current)"}}}', 'table', true, '{1}', '2026-05-27 02:09:37.85225+00', true);
INSERT INTO public.bh_skills (id, name, description, webhook_url, http_method, param_schema, response_hint, is_active, restricted_users, created_at, is_read_only) VALUES (14, 'list-files', 'List files in a directory (inbox, inventory, etc).', '/webhook/list-files', 'POST', '{"type": "object", "required": ["path"], "properties": {"path": {"type": "string", "description": "Directory to list, e.g. inbox"}}}', 'table', true, '{}', '2026-05-27 02:09:37.85225+00', true);
INSERT INTO public.bh_skills (id, name, description, webhook_url, http_method, param_schema, response_hint, is_active, restricted_users, created_at, is_read_only) VALUES (1, 'ask-db', 'Ask any question about your stored data in natural language. Translates to SQL and queries the database. Covers transactions, accounts, balances, inventory (tools, router bits, saw blades, wood), files, recipes, house data — every schema you have access to. Use this for any "how many", "show me", "what did I", "list my X" question.', '/webhook/finance-query', 'POST', '{"type": "object", "required": ["question"], "properties": {"question": {"type": "string", "description": "Natural language question about financial data"}}}', 'table', true, '{1}', '2026-05-27 02:09:37.85225+00', true);
INSERT INTO public.bh_skills (id, name, description, webhook_url, http_method, param_schema, response_hint, is_active, restricted_users, created_at, is_read_only) VALUES (15, 'weather', 'Get current weather and 3-day forecast for any location. Accepts city names, zip codes, airport codes, or landmarks. Defaults to Detroit if no location specified.', 'native://weather', 'GET', '{"type": "object", "properties": {"location": {"type": "string", "description": "City, zip, airport code, or landmark (e.g., New Orleans, 10001, LAX, Eiffel Tower). Omit for default location."}}}', 'text', true, '{}', '2026-05-27 02:09:37.85225+00', true);
INSERT INTO public.bh_skills (id, name, description, webhook_url, http_method, param_schema, response_hint, is_active, restricted_users, created_at, is_read_only) VALUES (11, 'recall', 'Search the knowledge base for previously saved facts.', 'native://recall', 'POST', '{"type": "object", "required": ["query"], "properties": {"query": {"type": "string", "description": "Search term"}}}', 'text', true, '{}', '2026-05-27 02:09:37.85225+00', true);
INSERT INTO public.bh_skills (id, name, description, webhook_url, http_method, param_schema, response_hint, is_active, restricted_users, created_at, is_read_only) VALUES (16, 'sports-score', 'Get live sports scores, pitching matchups, game details for MLB, NHL, NBA, NFL, soccer, and more. Handles: scores, who is pitching, starting pitchers, game status, current pitcher. Provide a team name (e.g., "Tigers", "Red Wings") or ask for all scores in a sport.', 'native://sports-score', 'POST', '{"type": "object", "properties": {"team": {"type": "string", "description": "Team name (e.g., Tigers, Red Wings, Lions, Inter Miami, Fever)"}, "sport": {"type": "string", "description": "League/sport: mlb, nfl, nba, nhl, wnba, mls, premier league, champions league, la liga, ncaaf, ncaab, ufc, f1, golf, tennis, world cup"}}}', NULL, true, '{}', '2026-06-06 02:53:09.969395+00', true);
INSERT INTO public.bh_skills (id, name, description, webhook_url, http_method, param_schema, response_hint, is_active, restricted_users, created_at, is_read_only) VALUES (26, 'news', 'Get current news headlines. Categories: top (general), sports, tech, world, business. Returns latest headlines from free RSS sources.', 'native://news', 'POST', '{"type": "object", "properties": {"limit": {"type": "integer", "description": "Number of headlines (default 10, max 20)"}, "category": {"type": "string", "description": "News category: top, sports, tech, world, business"}}}', NULL, true, '{}', '2026-06-07 19:48:27.812921+00', true);
INSERT INTO public.bh_skills (id, name, description, webhook_url, http_method, param_schema, response_hint, is_active, restricted_users, created_at, is_read_only) VALUES (27, 'calendar', 'Read and create Google Calendar events. Can show today''s schedule, upcoming events for any date range, or add new events.', 'native://calendar', 'POST', '{"type": "object", "properties": {"days": {"type": "integer", "description": "How many days ahead to look (0=today, 1=tomorrow, 7=week). Default 7."}, "query": {"type": "string", "description": "Range shorthand: today, tomorrow, week, next week, or a number of days."}}}', NULL, true, '{}', '2026-06-07 20:51:16.736198+00', false);
INSERT INTO public.bh_skills (id, name, description, webhook_url, http_method, param_schema, response_hint, is_active, restricted_users, created_at, is_read_only) VALUES (28, 'calendar-create', 'Create a new Google Calendar event. Requires a title and start time. End time defaults to 1 hour after start.', 'native://calendar-create', 'POST', '{"type": "object", "properties": {"end": {"type": "string", "description": "End datetime: YYYY-MM-DD HH:MM (optional, defaults to 1 hour after start)"}, "start": {"type": "string", "description": "Start datetime: YYYY-MM-DD HH:MM or YYYY-MM-DDTHH:MM (required)"}, "all_day": {"type": "boolean", "description": "Set to true to create an all-day event (optional)"}, "summary": {"type": "string", "description": "Event title (required)"}, "location": {"type": "string", "description": "Event location (optional)"}, "description": {"type": "string", "description": "Event notes or details (optional)"}}}', NULL, true, '{}', '2026-06-07 20:51:16.736198+00', false);


--
-- Data for Name: bh_workspaces; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.bh_workspaces (id, name, description, icon, color, system_prompt, default_model, temperature, max_context_tokens, auto_capture, permitted_schemas, settings_json, created_by, created_at) VALUES (3, 'Woodshop', 'Woodworking assistant with tool inventory, router bits, and project tracking.', '🪚', '#f59e0b', 'You are BowersHub AI acting as a woodshop assistant. You have access to the tool inventory (inventory.tools, inventory.router_bits, inventory.saw_blades) and can help catalog new tools, look up specifications, and track projects. When photos are shared, offer to process them into the inventory via smart-capture.', 'auto', 0.70, 8000, true, '{inventory,files}', '{}', NULL, '2026-05-27 02:09:37.854289+00');
INSERT INTO public.bh_workspaces (id, name, description, icon, color, system_prompt, default_model, temperature, max_context_tokens, auto_capture, permitted_schemas, settings_json, created_by, created_at) VALUES (4, 'Cooking', 'Recipe assistant for Michael and Manon. Track recipes, cook logs, and shopping lists.', '🍳', '#ef4444', 'You are BowersHub AI acting as a cooking assistant for Michael and Manon. You can help find recipes, track what was cooked and when, manage shopping lists, and remember cooking preferences. Be friendly and suggest ideas when asked.', 'auto', 0.70, 8000, true, '{cook,files}', '{}', NULL, '2026-05-27 02:09:37.854289+00');
INSERT INTO public.bh_workspaces (id, name, description, icon, color, system_prompt, default_model, temperature, max_context_tokens, auto_capture, permitted_schemas, settings_json, created_by, created_at) VALUES (5, 'House', 'Home management — rooms, maintenance, improvements, and shared tasks.', '🏡', '#8b5cf6', 'You are BowersHub AI acting as a home management assistant. You can help track rooms, maintenance tasks, home improvements, and shared household information. Both Michael and Manon have access to this workspace.', 'auto', 0.70, 8000, true, '{house,files}', '{}', NULL, '2026-05-27 02:09:37.854289+00');
INSERT INTO public.bh_workspaces (id, name, description, icon, color, system_prompt, default_model, temperature, max_context_tokens, auto_capture, permitted_schemas, settings_json, created_by, created_at) VALUES (2, 'Finance', 'Financial advisor with access to all bank accounts, transactions, and spending data.', '💰', '#10b981', 'You are BowersHub AI acting as a personal financial advisor. You have access to all bank accounts, transactions, and spending data. For complex questions, use the ask-db skill (natural-language SQL across all your data). For common lookups, use balances, transactions, or spending-summary. Format monetary amounts with $ and two decimal places. Negative amounts are spending, positive are income. Exclude transfers from spending analysis unless specifically asked.', 'auto', 0.70, 8000, true, '{public,files,finance}', '{}', NULL, '2026-05-27 02:09:37.854289+00');
INSERT INTO public.bh_workspaces (id, name, description, icon, color, system_prompt, default_model, temperature, max_context_tokens, auto_capture, permitted_schemas, settings_json, created_by, created_at) VALUES (1, 'General', 'General-purpose assistant. Ask anything, save facts, send emails.', '🏠', '#6366f1', 'You are BowersHub AI, a helpful personal assistant for Michael. You can search the knowledge base, remember facts, check the weather, send emails, and answer general questions. Be conversational, helpful, and concise.', 'auto', 0.70, 8000, true, '{public,finance}', '{}', NULL, '2026-05-27 02:09:37.854289+00');


--
-- Data for Name: bh_patterns; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.bh_patterns (id, rule, rule_type, skill_id, param_template, description, priority, workspace_id, is_active) VALUES (1, '(?i)\b(weather|forecast|temperature|temp)\b', 'regex', 15, '{}', 'Weather queries (weather, forecast, temp)', 50, NULL, true);
INSERT INTO public.bh_patterns (id, rule, rule_type, skill_id, param_template, description, priority, workspace_id, is_active) VALUES (2, '(?i)(?:how|what).*(?:cold|hot|warm|rain|snow|sunny)', 'regex', 15, '{}', 'Weather via condition words (cold, hot, rain, snow)', 80, NULL, true);
INSERT INTO public.bh_patterns (id, rule, rule_type, skill_id, param_template, description, priority, workspace_id, is_active) VALUES (3, '(?i)\b(tigers?|lions?|pistons?|red wings?|wolverines?)\b.*\b(score|game|play|win|lose|lost|won|pitch)', 'regex', 16, '{"team": "$1"}', 'Detroit teams + game words → sports-score', 40, NULL, true);
INSERT INTO public.bh_patterns (id, rule, rule_type, skill_id, param_template, description, priority, workspace_id, is_active) VALUES (4, '(?i)\b(score|box\s*score|scoreboard|standings)\b.*\b(tigers?|lions?|pistons?|red wings?|mlb|nfl|nba|nhl)', 'regex', 16, '{}', 'Score/standings + team/league', 45, NULL, true);
INSERT INTO public.bh_patterns (id, rule, rule_type, skill_id, param_template, description, priority, workspace_id, is_active) VALUES (5, '(?i)who.*(pitch|start|playing|throwing)', 'regex', 16, '{}', 'Who is pitching/starting/playing', 50, NULL, true);
INSERT INTO public.bh_patterns (id, rule, rule_type, skill_id, param_template, description, priority, workspace_id, is_active) VALUES (6, '(?i)(?:what.s|show|check).*\b(balance|balances|accounts?)\b', 'regex', 2, '{}', 'Balance/account queries', 50, NULL, true);
INSERT INTO public.bh_patterns (id, rule, rule_type, skill_id, param_template, description, priority, workspace_id, is_active) VALUES (7, '(?i)how much.*(?:spend|spent|cost|paid)', 'regex', 1, '{"question": "$0"}', 'Spending questions → ask-db', 60, NULL, true);
INSERT INTO public.bh_patterns (id, rule, rule_type, skill_id, param_template, description, priority, workspace_id, is_active) VALUES (8, '(?i)\b(spending|expenses?)\b.*\b(summary|breakdown|this month|last month)\b', 'regex', 5, '{}', 'Spending summary/breakdown', 55, NULL, true);
INSERT INTO public.bh_patterns (id, rule, rule_type, skill_id, param_template, description, priority, workspace_id, is_active) VALUES (9, '(?i)(?:what do I|do I)\s+know\s+about\s+(.+)', 'regex', 11, '{"query": "$1"}', 'What do I know about X → recall', 40, NULL, true);
INSERT INTO public.bh_patterns (id, rule, rule_type, skill_id, param_template, description, priority, workspace_id, is_active) VALUES (10, '(?i)^recall\s+(.+)', 'regex', 11, '{"query": "$1"}', 'Bare "recall X" → recall skill', 30, NULL, true);
INSERT INTO public.bh_patterns (id, rule, rule_type, skill_id, param_template, description, priority, workspace_id, is_active) VALUES (11, '(?i)^remember\s+(.+)', 'regex', 10, '{"topic": "$1"}', 'Bare "remember X" → remember skill', 30, NULL, true);
INSERT INTO public.bh_patterns (id, rule, rule_type, skill_id, param_template, description, priority, workspace_id, is_active) VALUES (12, '(?i)(?:what.s|any|show|get).*\b(news|headlines)\b', 'regex', 26, '{}', 'News/headlines queries', 50, NULL, true);


--
-- Data for Name: bh_platform_settings; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.bh_platform_settings (key, value_json, updated_by, updated_at) VALUES ('default_theme_id', '{"theme_id": 1}', NULL, '2026-05-28 04:19:06.483708+00');
INSERT INTO public.bh_platform_settings (key, value_json, updated_by, updated_at) VALUES ('app_icon_version', '{"version": "1779941946"}', NULL, '2026-05-28 04:19:06.483708+00');
INSERT INTO public.bh_platform_settings (key, value_json, updated_by, updated_at) VALUES ('app_icon_active_filename', '{"filename": "icon-set-default"}', NULL, '2026-05-28 04:19:06.483708+00');
INSERT INTO public.bh_platform_settings (key, value_json, updated_by, updated_at) VALUES ('app_icon_previous_filename', '{"filename": null}', NULL, '2026-05-28 04:19:06.483708+00');


--
-- Data for Name: bh_slash_commands; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.bh_slash_commands (id, command, description, skill_id, param_template, workspace_id, is_active, flags) VALUES (4, '/help', 'List available commands', NULL, '{}', NULL, true, '[]');
INSERT INTO public.bh_slash_commands (id, command, description, skill_id, param_template, workspace_id, is_active, flags) VALUES (5, '/new', 'Start a new conversation', NULL, '{}', NULL, true, '[]');
INSERT INTO public.bh_slash_commands (id, command, description, skill_id, param_template, workspace_id, is_active, flags) VALUES (7, '/balance', 'Show all account balances', 2, '{}', 2, true, '[]');
INSERT INTO public.bh_slash_commands (id, command, description, skill_id, param_template, workspace_id, is_active, flags) VALUES (8, '/spend', 'Monthly spending breakdown', 5, '{}', 2, true, '[]');
INSERT INTO public.bh_slash_commands (id, command, description, skill_id, param_template, workspace_id, is_active, flags) VALUES (3, '/files', 'List inbox files', NULL, '{}', NULL, true, '[]');
INSERT INTO public.bh_slash_commands (id, command, description, skill_id, param_template, workspace_id, is_active, flags) VALUES (11, '/remember', 'Save a fact (e.g., /remember woodshop/tools bought a new chisel)', 10, '{"fact": "$args_rest", "topic": "$args_first"}', NULL, true, '[]');
INSERT INTO public.bh_slash_commands (id, command, description, skill_id, param_template, workspace_id, is_active, flags) VALUES (16, '/email', 'Email digest (clean, preview, all)', NULL, '{}', NULL, true, '[{"flag": "--clean", "description": "Classify and archive junk/newsletters"}, {"flag": "--preview", "description": "Dry-run — show what clean would do"}, {"flag": "--all", "description": "Show all emails with categories"}, {"flag": "--important", "description": "Show only important/priority emails"}, {"flag": "--unsubscribe", "description": "Find senders to unsubscribe from"}, {"flag": "--help", "description": "Show all /email flags"}]');
INSERT INTO public.bh_slash_commands (id, command, description, skill_id, param_template, workspace_id, is_active, flags) VALUES (12, '/transactions', 'Recent transactions (or: last week, groceries)', NULL, NULL, NULL, true, '[{"flag": "--sync", "description": "Pull latest transactions from SimpleFin now"}, {"flag": "--today", "description": "Today only"}, {"flag": "--week", "description": "Last 7 days"}, {"flag": "--month", "description": "This month"}, {"flag": "--large", "description": "Transactions over $100"}, {"flag": "--recurring", "description": "Likely recurring charges"}, {"flag": "--uncategorized", "description": "No category assigned"}, {"flag": "--help", "description": "Show all /transactions flags"}]');
INSERT INTO public.bh_slash_commands (id, command, description, skill_id, param_template, workspace_id, is_active, flags) VALUES (13, '/inventory', 'Browse inventory (or: /inventory tools)', NULL, NULL, NULL, true, '[{"flag": "--tools", "description": "Browse tools"}, {"flag": "--bits", "description": "Browse router bits"}, {"flag": "--blades", "description": "Browse saw blades"}, {"flag": "--help", "description": "Show all /inventory flags"}]');
INSERT INTO public.bh_slash_commands (id, command, description, skill_id, param_template, workspace_id, is_active, flags) VALUES (2, '/recall', 'Search knowledge base', NULL, '{"query": "$args"}', NULL, true, '[{"flag": "--list", "description": "Show all knowledge topics/files"}, {"flag": "--recent", "description": "Show last 10 facts saved"}]');
INSERT INTO public.bh_slash_commands (id, command, description, skill_id, param_template, workspace_id, is_active, flags) VALUES (6, '/cost', 'Show today''s AI spend breakdown', NULL, '{}', NULL, true, '[{"flag": "--week", "description": "AI spend for the last 7 days"}, {"flag": "--breakdown", "description": "Cost by model"}]');
INSERT INTO public.bh_slash_commands (id, command, description, skill_id, param_template, workspace_id, is_active, flags) VALUES (19, '/health', 'Check all service connections', NULL, '{}', NULL, true, '[{"flag": "--postgres", "description": "Check database connection"}, {"flag": "--ollama", "description": "Check local AI model"}, {"flag": "--simplefin", "description": "Check bank sync"}, {"flag": "--anthropic", "description": "Check Claude API key"}, {"flag": "--imap", "description": "Check Gmail/email connection"}, {"flag": "--n8n", "description": "Check workflow engine"}, {"flag": "--pushover", "description": "Check push notifications"}, {"flag": "--filewriter", "description": "Check file service"}]');
INSERT INTO public.bh_slash_commands (id, command, description, skill_id, param_template, workspace_id, is_active, flags) VALUES (14, '/remind', 'Set a timed reminder', NULL, '{}', NULL, true, '[{"flag": "--list", "description": "Show pending reminders"}, {"flag": "--clear", "description": "Cancel all pending reminders"}]');
INSERT INTO public.bh_slash_commands (id, command, description, skill_id, param_template, workspace_id, is_active, flags) VALUES (15, '/briefing', 'Show or configure morning briefing', NULL, '{}', NULL, true, '[{"flag": "--short", "description": "Just weather + important emails"}]');
INSERT INTO public.bh_slash_commands (id, command, description, skill_id, param_template, workspace_id, is_active, flags) VALUES (18, '/local', 'Chat with local AI (free, no API cost)', NULL, '{}', NULL, true, '[{"flag": "--help", "description": "Show usage info"}]');
INSERT INTO public.bh_slash_commands (id, command, description, skill_id, param_template, workspace_id, is_active, flags) VALUES (10, '/sports', 'Sports scores & schedules (--scores, --schedule)', NULL, '{"team": "$args"}', NULL, true, '[{"flag": "--scores", "description": "Latest scores (your teams or specify a team after)"}, {"flag": "--schedule", "description": "Upcoming games (your teams or specify a team after)"}, {"flag": "--help", "description": "Show usage"}]');
INSERT INTO public.bh_slash_commands (id, command, description, skill_id, param_template, workspace_id, is_active, flags) VALUES (23, '/news', 'Get current news headlines', NULL, '{}', NULL, true, '[{"flag": "sports", "description": "Sports headlines (ESPN)"}, {"flag": "tech", "description": "Tech news (Ars Technica)"}, {"flag": "world", "description": "World news"}, {"flag": "business", "description": "Business news"}]');
INSERT INTO public.bh_slash_commands (id, command, description, skill_id, param_template, workspace_id, is_active, flags) VALUES (25, '/score', 'Get live sports scores', NULL, '{}', NULL, true, '[{"flag": "--tigers", "description": "Detroit Tigers"}, {"flag": "--lions", "description": "Detroit Lions"}, {"flag": "--pistons", "description": "Detroit Pistons"}, {"flag": "--wings", "description": "Detroit Red Wings"}, {"flag": "--michigan", "description": "Michigan Wolverines"}, {"flag": "--all", "description": "All tracked teams"}]');
INSERT INTO public.bh_slash_commands (id, command, description, skill_id, param_template, workspace_id, is_active, flags) VALUES (24, '/schedule', 'Show your calendar — today, tomorrow, this week, or any date range', NULL, '{}', NULL, true, '[{"flag": "--today", "description": "Today only"}, {"flag": "--tomorrow", "description": "Tomorrow only"}, {"flag": "--week", "description": "Next 7 days"}]');
INSERT INTO public.bh_slash_commands (id, command, description, skill_id, param_template, workspace_id, is_active, flags) VALUES (26, '/schedule', 'Show your calendar — today, tomorrow, this week, or any date range', NULL, '{}', NULL, true, '[{"flag": "--today", "description": "Today only"}, {"flag": "--tomorrow", "description": "Tomorrow only"}, {"flag": "--week", "description": "Next 7 days"}]');
INSERT INTO public.bh_slash_commands (id, command, description, skill_id, param_template, workspace_id, is_active, flags) VALUES (1, '/weather', 'Get current weather', NULL, '{}', NULL, true, '[{"flag": "--tomorrow", "description": "Just tomorrows forecast"}, {"flag": "--week", "description": "5-day forecast"}]');


--
-- Data for Name: bh_themes; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.bh_themes (id, name, slug, is_preset, owner_id, tokens_json, created_at, updated_at) VALUES (1, 'Dark Navy', 'dark-navy', true, NULL, '{"text": "#e5e7eb", "accent": "#818cf8", "border": "#374151", "danger": "#ef4444", "primary": "#6366f1", "success": "#22c55e", "surface": "#1a1a2e", "background": "#0f0f1a", "text_muted": "#94a3b8"}', '2026-05-28 04:19:06.483708+00', '2026-05-28 04:19:06.483708+00');
INSERT INTO public.bh_themes (id, name, slug, is_preset, owner_id, tokens_json, created_at, updated_at) VALUES (2, 'Light Stone', 'light-stone', true, NULL, '{"text": "#1f2937", "accent": "#6366f1", "border": "#e5e7eb", "danger": "#dc2626", "primary": "#4f46e5", "success": "#16a34a", "surface": "#ffffff", "background": "#f8f7f4", "text_muted": "#6b7280"}', '2026-05-28 04:19:06.483708+00', '2026-05-28 04:19:06.483708+00');
INSERT INTO public.bh_themes (id, name, slug, is_preset, owner_id, tokens_json, created_at, updated_at) VALUES (3, 'Forest', 'forest', true, NULL, '{"text": "#e5f7ec", "accent": "#4ade80", "border": "#2d3f33", "danger": "#ef4444", "primary": "#22c55e", "success": "#22c55e", "surface": "#1a2e22", "background": "#0f1f17", "text_muted": "#94a3b8"}', '2026-05-28 04:19:06.483708+00', '2026-05-28 04:19:06.483708+00');
INSERT INTO public.bh_themes (id, name, slug, is_preset, owner_id, tokens_json, created_at, updated_at) VALUES (5, 'Michigan', 'michigan', true, NULL, '{"text": "#f8f0d8", "accent": "#ffd75e", "border": "#1b3a66", "danger": "#ef4444", "primary": "#ffcb05", "success": "#4ade80", "surface": "#00274c", "background": "#00132e", "text_muted": "#a3b1c7"}', '2026-06-07 04:01:17.987306+00', '2026-06-07 04:01:17.987306+00');
INSERT INTO public.bh_themes (id, name, slug, is_preset, owner_id, tokens_json, created_at, updated_at) VALUES (6, 'OLED Black', 'oled-black', true, NULL, '{"text": "#fafafa", "accent": "#818cf8", "border": "#18181b", "danger": "#ef4444", "primary": "#6366f1", "success": "#22c55e", "surface": "#0a0a0a", "background": "#000000", "text_muted": "#a1a1aa"}', '2026-06-07 04:01:17.987306+00', '2026-06-07 04:01:17.987306+00');
INSERT INTO public.bh_themes (id, name, slug, is_preset, owner_id, tokens_json, created_at, updated_at) VALUES (7, 'Dracula', 'dracula', true, NULL, '{"text": "#f8f8f2", "accent": "#ff79c6", "border": "#44475a", "danger": "#ff5555", "primary": "#bd93f9", "success": "#50fa7b", "surface": "#343746", "background": "#282a36", "text_muted": "#6272a4"}', '2026-06-07 04:01:17.987306+00', '2026-06-07 04:01:17.987306+00');
INSERT INTO public.bh_themes (id, name, slug, is_preset, owner_id, tokens_json, created_at, updated_at) VALUES (8, 'Nord', 'nord', true, NULL, '{"text": "#eceff4", "accent": "#81a1c1", "border": "#4c566a", "danger": "#bf616a", "primary": "#88c0d0", "success": "#a3be8c", "surface": "#3b4252", "background": "#2e3440", "text_muted": "#d8dee9"}', '2026-06-07 04:01:17.987306+00', '2026-06-07 04:01:17.987306+00');
INSERT INTO public.bh_themes (id, name, slug, is_preset, owner_id, tokens_json, created_at, updated_at) VALUES (9, 'Solarized Dark', 'solarized-dark', true, NULL, '{"text": "#93a1a1", "accent": "#2aa198", "border": "#094352", "danger": "#dc322f", "primary": "#268bd2", "success": "#859900", "surface": "#073642", "background": "#002b36", "text_muted": "#586e75"}', '2026-06-07 04:01:17.987306+00', '2026-06-07 04:01:17.987306+00');
INSERT INTO public.bh_themes (id, name, slug, is_preset, owner_id, tokens_json, created_at, updated_at) VALUES (10, 'Sunset', 'sunset', true, NULL, '{"text": "#fef3e2", "accent": "#ec4899", "border": "#4a2c54", "danger": "#ef4444", "primary": "#f97316", "success": "#facc15", "surface": "#2a1830", "background": "#1a0e1f", "text_muted": "#c4a3b0"}', '2026-06-07 04:01:17.987306+00', '2026-06-07 04:01:17.987306+00');
INSERT INTO public.bh_themes (id, name, slug, is_preset, owner_id, tokens_json, created_at, updated_at) VALUES (4, 'Mono', 'mono', true, NULL, '{"text": "#e5e7eb", "accent": "#d1d5db", "border": "#374151", "danger": "#ef4444", "primary": "#ffffff", "success": "#22c55e", "surface": "#1a1a1a", "background": "#000000", "text_muted": "#9ca3af"}', '2026-05-28 04:19:06.483708+00', '2026-06-07 04:09:53.880639+00');


--
-- Data for Name: bh_workspace_skills; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (2, 1);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (2, 2);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (2, 3);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (2, 4);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (2, 5);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (2, 6);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (2, 10);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (2, 11);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (3, 7);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (3, 8);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (3, 9);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (3, 10);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (3, 11);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (3, 13);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (3, 14);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (4, 7);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (4, 8);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (4, 10);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (4, 11);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (4, 14);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (5, 7);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (5, 8);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (5, 10);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (5, 11);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (5, 14);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (2, 14);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (2, 15);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (3, 1);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (3, 15);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (4, 1);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (4, 15);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (5, 1);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (5, 15);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (1, 1);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (1, 14);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (1, 11);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (1, 10);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (1, 12);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (1, 15);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (1, 9);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (1, 4);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (1, 2);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (1, 6);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (1, 13);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (1, 8);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (1, 7);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (1, 5);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (1, 3);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (1, 16);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (1, 26);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (1, 27);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (1, 28);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (3, 27);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (3, 28);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (4, 27);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (4, 28);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (5, 27);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (5, 28);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (2, 27);
INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES (2, 28);


--
-- Name: bh_api_registry_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.bh_api_registry_id_seq', 9, true);


--
-- Name: bh_dashboard_widgets_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.bh_dashboard_widgets_id_seq', 13, true);


--
-- Name: bh_model_rates_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.bh_model_rates_id_seq', 14, true);


--
-- Name: bh_patterns_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.bh_patterns_id_seq', 12, true);


--
-- Name: bh_skills_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.bh_skills_id_seq', 30, true);


--
-- Name: bh_slash_commands_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.bh_slash_commands_id_seq', 26, true);


--
-- Name: bh_themes_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.bh_themes_id_seq', 10, true);


--
-- Name: bh_workspaces_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.bh_workspaces_id_seq', 5, true);


--
--


