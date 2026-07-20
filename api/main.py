# Load environment variables
from dotenv import load_dotenv

load_dotenv()

import os
from contextlib import asynccontextmanager

import secrets

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.middleware.jwt_auth import JWTAuthMiddleware
from api.middleware.rbac import RBACMiddleware
from api.audit_service import AuditLoggingMiddleware

from api.auth import PasswordAuthMiddleware
from open_notebook.exceptions import (
    AuthenticationError,
    ConfigurationError,
    ExternalServiceError,
    InvalidInputError,
    NetworkError,
    NotFoundError,
    OpenNotebookError,
    RateLimitError,
)
from api.routers import (
    auth,
    audit,
    capabilities,
    chat,
    chat_agents,
    charts,
    citations,
    collaboration,
    config,
    context,
    credentials,
    embedding,
    embedding_rebuild,
    episode_profiles,
    flags,
    global_chat,
    health,
    insights,
    languages,
    models,
    navigation,
    navy_docs,
    notebooks,
    notes,
    opensearch,
    permissions,
    podcasts,
    prompt_improvement,
    research,
    vision,
    search,
    settings,
    source_chat,
    sources,
    speaker_profiles,
    transcription,
    transformations,
    users,
)
from api.routers import commands as commands_router
from open_notebook.database.async_migrate import AsyncMigrationManager
from open_notebook.utils.encryption import get_secret_from_env

# Import commands to register them in the API process
try:
    logger.info("Commands imported in API process")
except Exception as e:
    logger.error(f"Failed to import commands in API process: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan event handler for the FastAPI application.
    Runs database migrations automatically on startup.
    """
    import os

    # Startup: Security checks
    logger.info("Starting API initialization...")

    # Security check: Encryption key
    if not get_secret_from_env("OPEN_NOTEBOOK_ENCRYPTION_KEY"):
        logger.warning(
            "OPEN_NOTEBOOK_ENCRYPTION_KEY not set. "
            "API key encryption will fail until this is configured. "
            "Set OPEN_NOTEBOOK_ENCRYPTION_KEY to any secret string."
        )

    # Production-readiness security checks. Loud warnings (or hard failure in
    # strict mode) when insecure defaults are detected. Set APP_ENV=production
    # and STRICT_SECURITY=1 to refuse to boot with insecure config.
    _strict = os.environ.get("STRICT_SECURITY", "").lower() in ("1", "true", "yes")
    _problems: list[str] = []
    _jwt = os.environ.get("JWT_SECRET", "")
    if not _jwt or "change-me" in _jwt.lower():
        _problems.append(
            "JWT_SECRET is unset or still the default — anyone can forge login "
            "tokens. Set it to a long random secret (e.g. `openssl rand -hex 32`)."
        )
    _admin_pw = os.environ.get("ADMIN_PASSWORD", "")
    if _admin_pw and _admin_pw.lower() in ("admin", "password", "changeme", "open-notebook"):
        _problems.append(
            "ADMIN_PASSWORD is a trivial/default value — set a strong admin password."
        )
    if not get_secret_from_env("OPEN_NOTEBOOK_PASSWORD") and not _admin_pw:
        _problems.append(
            "No OPEN_NOTEBOOK_PASSWORD and no ADMIN_PASSWORD set — the API may "
            "accept unauthenticated (anonymous) requests."
        )
    for _p in _problems:
        logger.warning(f"[SECURITY] {_p}")
    if _problems and _strict:
        raise RuntimeError(
            "STRICT_SECURITY is on and insecure configuration was detected: "
            + " | ".join(_problems)
        )

    # Run database migrations

    try:
        migration_manager = AsyncMigrationManager()
        current_version = await migration_manager.get_current_version()
        logger.info(f"Current database version: {current_version}")

        if await migration_manager.needs_migration():
            logger.warning("Database migrations are pending. Running migrations...")
            await migration_manager.run_migration_up()
            new_version = await migration_manager.get_current_version()
            logger.success(
                f"Migrations completed successfully. Database is now at version {new_version}"
            )
        else:
            logger.info(
                "Database is already at the latest version. No migrations needed."
            )
    except Exception as e:
        logger.error(f"CRITICAL: Database migration failed: {str(e)}")
        logger.exception(e)
        # Fail fast - don't start the API with an outdated database schema
        raise RuntimeError(f"Failed to run database migrations: {str(e)}") from e

    # Run podcast profile data migration (legacy strings -> Model registry)
    try:
        from open_notebook.podcasts.migration import migrate_podcast_profiles

        await migrate_podcast_profiles()
    except Exception as e:
        logger.warning(f"Podcast profile migration encountered errors: {e}")
        # Non-fatal: profiles can be migrated manually via UI

    # Ensure Amália (always-available provider) has a credential and models
    try:
        from open_notebook.domain.credential import Credential as CredentialModel
        from api.credentials_service import create_credential_from_env
        from open_notebook.ai.key_provider import provision_provider_keys
        from open_notebook.ai.model_discovery import sync_provider_models

        existing_amalia = await CredentialModel.get_by_provider("amalia")
        if not existing_amalia:
            logger.info("Auto-creating Amália credential (always-available provider)")
            cred = create_credential_from_env("amalia")
            await cred.save()
            logger.info(f"Amália credential created (id={cred.id})")
        else:
            # Refresh api_key / base_url from env vars if they differ (handles
            # the case where a previous startup seeded the credential with the
            # default 'dummy' key before AMALIA_API_KEY was set).
            env_cred = create_credential_from_env("amalia")
            env_key = env_cred.api_key.get_secret_value() if env_cred.api_key else None
            for cred in existing_amalia:
                current_key = cred.api_key.get_secret_value() if cred.api_key else None
                if (env_key and current_key != env_key) or (
                    env_cred.base_url and cred.base_url != env_cred.base_url
                ):
                    logger.info(
                        f"Refreshing Amália credential {cred.id} from env vars "
                        f"(api_key changed={current_key != env_key}, "
                        f"base_url changed={cred.base_url != env_cred.base_url})"
                    )
                    cred.api_key = env_cred.api_key
                    cred.base_url = env_cred.base_url
                    await cred.save()

        await provision_provider_keys("amalia")
        discovered, new, existing = await sync_provider_models("amalia", auto_register=True)
        if new > 0:
            logger.info(f"Registered {new} new Amália model(s)")

        # Link any unlinked Amália models to the credential
        from open_notebook.database.repository import repo_query as _rq
        from open_notebook.ai.models import Model as ModelRecord
        amalia_creds = await CredentialModel.get_by_provider("amalia")
        if amalia_creds:
            cred_id = amalia_creds[0].id
            unlinked = await _rq(
                "SELECT * FROM model WHERE string::lowercase(provider) = 'amalia' AND credential IS NONE",
                {},
            )
            for m in unlinked:
                model = ModelRecord(**m)
                model.credential = cred_id
                await model.save()
            if unlinked:
                logger.info(f"Linked {len(unlinked)} Amália model(s) to credential {cred_id}")
    except Exception as e:
        logger.warning(f"Amália auto-provisioning encountered an error: {e}")

    # Ensure Gemma (always-available provider) has a credential and models
    try:
        from open_notebook.domain.credential import Credential as CredentialModel
        from api.credentials_service import create_credential_from_env
        from open_notebook.ai.key_provider import provision_provider_keys
        from open_notebook.ai.model_discovery import sync_provider_models

        existing_gemma = await CredentialModel.get_by_provider("gemma")
        if not existing_gemma:
            logger.info("Auto-creating Gemma credential (always-available provider)")
            cred = create_credential_from_env("gemma")
            await cred.save()
            logger.info(f"Gemma credential created (id={cred.id})")

        await provision_provider_keys("gemma")
        discovered, new, existing = await sync_provider_models("gemma", auto_register=True)
        if new > 0:
            logger.info(f"Registered {new} new Gemma model(s)")

        # Link any unlinked Gemma models to the credential
        from open_notebook.database.repository import repo_query as _rq
        from open_notebook.ai.models import Model as ModelRecord
        gemma_creds = await CredentialModel.get_by_provider("gemma")
        if gemma_creds:
            cred_id = gemma_creds[0].id
            unlinked = await _rq(
                "SELECT * FROM model WHERE string::lowercase(provider) = 'gemma' AND credential IS NONE",
                {},
            )
            for m in unlinked:
                model = ModelRecord(**m)
                model.credential = cred_id
                await model.save()
            if unlinked:
                logger.info(f"Linked {len(unlinked)} Gemma model(s) to credential {cred_id}")
    except Exception as e:
        logger.warning(f"Gemma auto-provisioning encountered an error: {e}")

    # Seed transformers (HuggingFace local) models — no API key required
    try:
        from open_notebook.ai.model_discovery import sync_provider_models as _sync

        discovered, new, existing = await _sync("transformers", auto_register=True)
        if new > 0:
            logger.info(f"Registered {new} new transformers embedding model(s)")
        else:
            logger.info(f"Transformers models already present ({existing} existing)")
    except Exception as e:
        logger.warning(f"Transformers model seeding encountered an error: {e}")

    # Seed local OpenAI-compatible embedding servers (Nomic, CLIP) — no API key
    # required. Models are auto-registered so they show up in the embedding
    # dropdown without any user configuration.
    for _local_provider in ("nomic", "clip"):
        try:
            from open_notebook.ai.model_discovery import sync_provider_models as _sync

            discovered, new, existing = await _sync(_local_provider, auto_register=True)
            if new > 0:
                logger.info(f"Registered {new} new {_local_provider} embedding model(s)")
            else:
                logger.info(
                    f"{_local_provider} models already present ({existing} existing)"
                )
        except Exception as e:
            logger.warning(f"{_local_provider} model seeding encountered an error: {e}")

    # Seed the local Whisper speech-to-text server (NOVA-Researcher
    # whisper_server, default port 4805). No API key required — the
    # server is reachable over the shared Docker network. Registering
    # makes the Whisper model appear in the Models screen so the user
    # can pick it as the default speech-to-text engine.
    try:
        from open_notebook.ai.model_discovery import sync_provider_models as _sync

        discovered, new, existing = await _sync("whisper", auto_register=True)
        if new > 0:
            logger.info(f"Registered {new} new whisper speech-to-text model(s)")
        else:
            logger.info(f"whisper models already present ({existing} existing)")
    except Exception as e:
        logger.warning(f"whisper model seeding encountered an error: {e}")

    # Background task: expire the per-user navy documents listing cache on a
    # fixed interval. The listing is ACL-filtered, so it cannot be safely or
    # usefully warmed without a concrete navy user id.
    import asyncio as _asyncio

    from open_notebook.search import navy_docs as _navy_docs_mod

    _NAVY_REFRESH_INTERVAL = float(os.environ.get("NAVY_DOCS_REFRESH_SECONDS", "300"))

    async def _refresh_navy_docs_loop():
        logger.info("Navy docs per-user cache expiration task started")

        while True:
            try:
                await _asyncio.sleep(_NAVY_REFRESH_INTERVAL)
                _navy_docs_mod.invalidate_navy_documents_cache()
                logger.debug(
                    "Navy docs per-user cache expired in background"
                )
            except _asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"Background navy docs refresh failed: {e}")

    navy_refresh_task = _asyncio.create_task(_refresh_navy_docs_loop())

    # Auto-assign default models if none are configured yet.
    # This runs after all provider models have been seeded above, so AMALIA
    # (highest priority) will be selected as the default chat model on a
    # fresh install — no UI interaction required.
    try:
        from open_notebook.ai.models import DefaultModels as _DefaultModels

        _defaults = await _DefaultModels.get_instance()
        if not _defaults.default_chat_model:
            logger.info("No default chat model set — running auto-assign…")
            from api.routers.models import auto_assign_defaults as _auto_assign
            result = await _auto_assign()
            assigned = getattr(result, "assigned", {})
            missing = getattr(result, "missing", [])
            if assigned:
                logger.success(f"Auto-assigned default models: {list(assigned.keys())}")
            if missing:
                logger.warning(f"No models available for slots: {missing}")
        else:
            logger.info(f"Default chat model already set: {_defaults.default_chat_model}")
    except Exception as e:
        logger.warning(f"Auto-assign default models failed (non-fatal): {e}")

    # Sweep cited_document records leaked by crashed sessions (the citation
    # viewer normally deletes them when the panel closes; there is no TTL).
    try:
        from api.citations_service import sweep_stale_cited_documents

        await sweep_stale_cited_documents(max_age="2h")
    except Exception as e:
        logger.warning(f"cited_document startup sweep failed (non-fatal): {e}")

    logger.success("API initialization completed successfully")

    # Yield control to the application
    yield

    # Shutdown: cleanup if needed
    navy_refresh_task.cancel()
    try:
        await navy_refresh_task
    except (Exception, BaseException):
        pass
    logger.info("API shutdown complete")


app = FastAPI(
    title="Open Notebook API",
    description="API for Open Notebook - Research Assistant",
    lifespan=lifespan,
    # Disable the public auto-generated docs. Custom admin-protected routes for
    # /docs, /redoc and /openapi.json are registered below so the full API
    # surface is not exposed to anonymous users in production.
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

# ── Admin-only API docs ────────────────────────────────────────────────────
# Swagger/ReDoc/OpenAPI are gated behind HTTP Basic auth using the admin
# account (ADMIN_EMAIL / ADMIN_PASSWORD). The browser prompts for credentials
# and reuses them for the /openapi.json fetch. These paths are exempt from the
# JWT/password middleware (see EXEMPT_PATHS), so this Basic check is the gate.
_docs_basic = HTTPBasic(auto_error=True)


def _require_docs_admin(credentials: HTTPBasicCredentials = Depends(_docs_basic)) -> bool:
    admin_email = os.environ.get("ADMIN_EMAIL", "admin@open-notebook.local")
    admin_pw = os.environ.get("ADMIN_PASSWORD", "")
    user_ok = secrets.compare_digest(credentials.username, admin_email)
    pw_ok = bool(admin_pw) and secrets.compare_digest(credentials.password, admin_pw)
    if not (user_ok and pw_ok):
        raise HTTPException(
            status_code=401,
            detail="Admin authentication required",
            headers={"WWW-Authenticate": "Basic"},
        )
    return True


@app.get("/openapi.json", include_in_schema=False)
async def _protected_openapi(_: bool = Depends(_require_docs_admin)):
    return app.openapi()


@app.get("/docs", include_in_schema=False)
async def _protected_swagger(_: bool = Depends(_require_docs_admin)):
    return get_swagger_ui_html(openapi_url="/openapi.json", title="Open Notebook API — Docs")


@app.get("/redoc", include_in_schema=False)
async def _protected_redoc(_: bool = Depends(_require_docs_admin)):
    return get_redoc_html(openapi_url="/openapi.json", title="Open Notebook API — ReDoc")

# Middleware execution order: last-added = outermost = runs first.
# Desired request flow: AuditLogging → CORS → JWT → RBAC → PasswordAuth → App
#
# Add innermost first, outermost last:
app.add_middleware(
    PasswordAuthMiddleware,
    excluded_paths=[
        "/",
        "/health",
        "/docs",
        "/openapi.json",
        "/redoc",
        "/api/",  # Exclude all /api/* endpoints - JWT middleware handles auth
        "/api/config",
    ],
)
app.add_middleware(RBACMiddleware)
app.add_middleware(JWTAuthMiddleware)
# CORS origins are configurable for production. Set CORS_ALLOW_ORIGINS to a
# comma-separated allowlist (e.g. "https://marinha.novasearch.org"); leave unset
# (or "*") for open access in development.
_cors_raw = os.environ.get("CORS_ALLOW_ORIGINS", "*").strip()
_cors_origins = (
    ["*"]
    if _cors_raw in ("", "*")
    else [o.strip() for o in _cors_raw.split(",") if o.strip()]
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    # Wildcard origin + credentials is invalid per the CORS spec and rejected by
    # browsers; only enable credentials when an explicit allowlist is set.
    allow_credentials=_cors_origins != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AuditLoggingMiddleware)

app.include_router(auth.router, prefix="/auth", tags=["auth"])

# Custom exception handler to ensure CORS headers are included in error responses
# This helps when errors occur before the CORS middleware can process them
@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):
    """
    Custom exception handler that ensures CORS headers are included in error responses.
    This is particularly important for 413 (Payload Too Large) errors during file uploads.

    Note: If a reverse proxy (nginx, traefik) returns 413 before the request reaches
    FastAPI, this handler won't be called. In that case, configure your reverse proxy
    to add CORS headers to error responses.
    """
    # Get the origin from the request
    origin = request.headers.get("origin", "*")

    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers={
            **(exc.headers or {}), "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Credentials": "true",
            "Access-Control-Allow-Methods": "*",
            "Access-Control-Allow-Headers": "*",
        },
    )


def _cors_headers(request: Request) -> dict[str, str]:
    origin = request.headers.get("origin", "*")
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Allow-Methods": "*",
        "Access-Control-Allow-Headers": "*",
    }


@app.exception_handler(NotFoundError)
async def not_found_error_handler(request: Request, exc: NotFoundError):
    return JSONResponse(
        status_code=404,
        content={"detail": str(exc)},
        headers=_cors_headers(request),
    )


@app.exception_handler(InvalidInputError)
async def invalid_input_error_handler(request: Request, exc: InvalidInputError):
    return JSONResponse(
        status_code=400,
        content={"detail": str(exc)},
        headers=_cors_headers(request),
    )


@app.exception_handler(AuthenticationError)
async def authentication_error_handler(request: Request, exc: AuthenticationError):
    return JSONResponse(
        status_code=401,
        content={"detail": str(exc)},
        headers=_cors_headers(request),
    )


@app.exception_handler(RateLimitError)
async def rate_limit_error_handler(request: Request, exc: RateLimitError):
    return JSONResponse(
        status_code=429,
        content={"detail": str(exc)},
        headers=_cors_headers(request),
    )


@app.exception_handler(ConfigurationError)
async def configuration_error_handler(request: Request, exc: ConfigurationError):
    return JSONResponse(
        status_code=422,
        content={"detail": str(exc)},
        headers=_cors_headers(request),
    )


@app.exception_handler(NetworkError)
async def network_error_handler(request: Request, exc: NetworkError):
    return JSONResponse(
        status_code=502,
        content={"detail": str(exc)},
        headers=_cors_headers(request),
    )


@app.exception_handler(ExternalServiceError)
async def external_service_error_handler(request: Request, exc: ExternalServiceError):
    return JSONResponse(
        status_code=502,
        content={"detail": str(exc)},
        headers=_cors_headers(request),
    )


@app.exception_handler(OpenNotebookError)
async def open_notebook_error_handler(request: Request, exc: OpenNotebookError):
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc)},
        headers=_cors_headers(request),
    )


# Include routers
app.include_router(auth.router, prefix="/api", tags=["auth"])
app.include_router(config.router, prefix="/api", tags=["config"])
app.include_router(notebooks.router, prefix="/api", tags=["notebooks"])
app.include_router(collaboration.router, prefix="/api", tags=["collaboration"])
app.include_router(search.router, prefix="/api", tags=["search"])
app.include_router(models.router, prefix="/api", tags=["models"])
app.include_router(transformations.router, prefix="/api", tags=["transformations"])
app.include_router(notes.router, prefix="/api", tags=["notes"])
app.include_router(embedding.router, prefix="/api", tags=["embedding"])
app.include_router(
    embedding_rebuild.router, prefix="/api/embeddings", tags=["embeddings"]
)
app.include_router(settings.router, prefix="/api", tags=["settings"])
app.include_router(context.router, prefix="/api", tags=["context"])
app.include_router(sources.router, prefix="/api", tags=["sources"])
app.include_router(insights.router, prefix="/api", tags=["insights"])
app.include_router(commands_router.router, prefix="/api", tags=["commands"])
app.include_router(podcasts.router, prefix="/api", tags=["podcasts"])
app.include_router(episode_profiles.router, prefix="/api", tags=["episode-profiles"])
app.include_router(speaker_profiles.router, prefix="/api", tags=["speaker-profiles"])
app.include_router(chat.router, prefix="/api", tags=["chat"])
app.include_router(chat_agents.router, prefix="/api", tags=["chat-agents"])
app.include_router(citations.router, prefix="/api", tags=["citations"])
app.include_router(charts.router, prefix="/api", tags=["charts"])
app.include_router(source_chat.router, prefix="/api", tags=["source-chat"])
app.include_router(credentials.router, prefix="/api", tags=["credentials"])
app.include_router(research.router, prefix="/api", tags=["research"])
app.include_router(languages.router, prefix="/api", tags=["languages"])
app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(users.router, prefix="/api", tags=["users"])
app.include_router(permissions.router, prefix="/api", tags=["permissions"])
app.include_router(audit.router, prefix="/api", tags=["audit"])
app.include_router(flags.router, prefix="/api", tags=["flags"])
app.include_router(capabilities.router, prefix="/api", tags=["capabilities"])
app.include_router(
    opensearch.router, prefix="/api/opensearch", tags=["opensearch"]
)
app.include_router(navy_docs.router, prefix="/api", tags=["navy-docs"])
app.include_router(global_chat.router, prefix="/api", tags=["global-chat"])
app.include_router(vision.router, prefix="/api", tags=["vision"])
app.include_router(navigation.router, prefix="/api", tags=["navigation"])
app.include_router(transcription.router, prefix="/api", tags=["transcription"])
app.include_router(prompt_improvement.router, prefix="/api", tags=["prompt-improvement"])


@app.get("/")
async def root():
    return {"message": "Open Notebook API is running"}


@app.get("/health")
async def health():
    return {"status": "healthy"}
