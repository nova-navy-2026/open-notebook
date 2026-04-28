# Load environment variables
from dotenv import load_dotenv

load_dotenv()

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.middleware.jwt_auth import JWTAuthMiddleware
from api.middleware.rbac import RBACMiddleware
from api.audit_service import AuditLoggingMiddleware
from api.routers import auth

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
    chat,
    config,
    context,
    credentials,
    embedding,
    embedding_rebuild,
    episode_profiles,
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
    research,
    vision,
    search,
    settings,
    source_chat,
    sources,
    speaker_profiles,
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

    logger.success("API initialization completed successfully")

    # Yield control to the application
    yield

    # Shutdown: cleanup if needed
    logger.info("API shutdown complete")


app = FastAPI(
    title="Open Notebook API",
    description="API for Open Notebook - Research Assistant",
    lifespan=lifespan,
)

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
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific origins
    allow_credentials=True,
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
app.include_router(source_chat.router, prefix="/api", tags=["source-chat"])
app.include_router(credentials.router, prefix="/api", tags=["credentials"])
app.include_router(research.router, prefix="/api", tags=["research"])
app.include_router(languages.router, prefix="/api", tags=["languages"])
app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(users.router, prefix="/api", tags=["users"])
app.include_router(permissions.router, prefix="/api", tags=["permissions"])
app.include_router(audit.router, prefix="/api", tags=["audit"])
app.include_router(
    opensearch.router, prefix="/api/opensearch", tags=["opensearch"]
)
app.include_router(navy_docs.router, prefix="/api", tags=["navy-docs"])
app.include_router(global_chat.router, prefix="/api", tags=["global-chat"])
app.include_router(vision.router, prefix="/api", tags=["vision"])
app.include_router(navigation.router, prefix="/api", tags=["navigation"])


@app.get("/")
async def root():
    return {"message": "Open Notebook API is running"}


@app.get("/health")
async def health():
    return {"status": "healthy"}
