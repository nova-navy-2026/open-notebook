# OpenNotebook Customization - Complete Setup & Run Guide

**Status**: ✅ All TODOs Implemented  
**Date**: March 23, 2026

---

## 🚀 Quick Start: Run the App Locally

Follow these exact steps to get OpenNotebook running with OAuth, RBAC, and Audit logging.

### Prerequisites

- Python 3.11+
- Node.js 18+
- Docker (for SurrealDB)
- Git

---

## Step 1: Clone & Setup

```bash
# Clone the repository
git clone https://github.com/lfnovo/open-notebook.git
cd open-notebook

# Create Python virtual environment
python -m venv venv

# Activate virtual environment
# On Windows:
venv\Scripts\activate
# On macOS/Linux:
source venv/bin/activate

# Install Python dependencies
pip install -e .
pip install authlib python-jose elasticsearch PyJWT

# Install frontend dependencies
cd frontend
npm install
cd ..
```

---

## Step 2: Start SurrealDB

```bash
# Start SurrealDB in Docker
docker run -d \
  --name surrealdb \
  -p 8000:8000 \
  surrealdb/surrealdb:latest \
  start --log debug -u root -p root

# Wait for SurrealDB to start
sleep 5

# Verify it's running
curl http://localhost:8000/health
# Should return: {"status":"OK"}
```

---

## Step 3: Setup Environment Variables

**.env file is already created** in the project root with all required settings pre-configured for local development.

**File location**: `.env` (in project root)

**Pre-configured values**:

```bash
JWT_SECRET=dev-jwt-secret-key-change-in-production
ADMIN_EMAIL=admin@open-notebook.local
ADMIN_PASSWORD=admin
SURREALDB_URL=ws://localhost:8000
RBAC_ENABLED=true
AUDIT_LOGGING_ENABLED=true
```

**For production** or custom settings:

- Edit `.env` file directly
- Change JWT_SECRET to something secure
- Change ADMIN_PASSWORD
- Update database URL if needed

**Optional OAuth setup** (advanced):

- Uncomment OAuth sections in `.env` if using Azure/Google/GitHub
- Add your client IDs and secrets

---

## Step 4: Run Database Migrations

The API will run migrations automatically on startup, but you can verify manually:

```bash
# Check migrations will run by checking logs when API starts:
python run_api.py

# Watch for: "Running migrations..." and "Migrations completed"
```

---

## Step 5: Start the API Server

```bash
# In a terminal window, run:
cd open-notebook
python run_api.py

# You should see:
# INFO:     Uvicorn running on http://0.0.0.0:5055
# ✅ API Started successfully at http://localhost:5055
```

**API is now running at**: `http://localhost:5055`

---

## Step 6: Start the Frontend

```bash
# In a NEW terminal window:
cd open-notebook/frontend
npm run dev

# You should see:
# - ready started server on 0.0.0.0:3000, url: http://localhost:3000
```

**Frontend is now running at**: `http://localhost:3000`

---

## Step 7: Login to the App

### Option A: Local Admin Login (Recommended for Development)

1. Go to `http://localhost:3000`
2. Click "Sign In"
3. Select "Local Login"
4. Enter credentials:
   - Email: `admin@open-notebook.local`
   - Password: `admin`
5. Click "Sign In"

### Option B: Test via API (curl)

```bash
# Login to get JWT token
curl -X POST http://localhost:5055/auth/login/local \
  -H "Content-Type: application/json" \
  -d '{
    "email": "admin@open-notebook.local",
    "password": "admin"
  }'

# Response should include:
# {
#   "access_token": "eyJ0eXAi...",
#   "token_type": "bearer",
#   "expires_in": 3600,
#   "user": {
#     "id": "admin-user-001",
#     "email": "admin@open-notebook.local",
#     "roles": ["admin"]
#   }
# }
```

---

## Step 8: Test Features

### 🔐 Test Authentication

```bash
# Get current user
TOKEN="your-token-from-login"
curl -X GET http://localhost:5055/auth/me \
  -H "Authorization: Bearer $TOKEN"

# Refresh token
curl -X POST http://localhost:5055/auth/token/refresh \
  -H "Authorization: Bearer $TOKEN"
```

### 👥 Test RBAC (Role-Based Access)

```bash
TOKEN="your-admin-token"

# Admin can create notebooks (should work)
curl -X POST http://localhost:5055/notebooks \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Test Notebook",
    "description": "Testing RBAC"
  }'
# Expected: 200 OK

# If you create a viewer account and try to delete:
# curl -X DELETE http://localhost:5055/notebooks/123 \
#   -H "Authorization: Bearer viewer_token"
# Expected: 403 Forbidden (permission denied)
```

### 📊 Test Audit Logging

```bash
TOKEN="your-admin-token"

# View audit logs
curl -X GET "http://localhost:5055/api/audit/logs?limit=10" \
  -H "Authorization: Bearer $TOKEN"

# Search audit logs
curl -X GET "http://localhost:5055/api/audit/search?q=notebook" \
  -H "Authorization: Bearer $TOKEN"

# Get user activity
curl -X GET "http://localhost:5055/api/audit/user/admin-user-001/activity" \
  -H "Authorization: Bearer $TOKEN"
```

### 🔍 Test Search

```bash
TOKEN="your-token"

# Basic search
curl -X POST http://localhost:5055/search \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "test search query",
    "search_type": "semantic",
    "limit": 20
  }'
```

---

## 📋 Next Steps

### Create More Users (Admin Only)

```bash
# List all users
curl -X GET http://localhost:5055/api/admin/users \
  -H "Authorization: Bearer admin_token"

# View user roles
curl -X GET http://localhost:5055/api/admin/roles \
  -H "Authorization: Bearer admin_token"

# Change user role
curl -X PUT http://localhost:5055/api/admin/users/user-123/roles \
  -H "Authorization: Bearer admin_token" \
  -H "Content-Type: application/json" \
  -d '{"roles": ["editor"]}'
```

### Check API Documentation

Visit `http://localhost:5055/docs` for interactive API documentation (Swagger UI)

### View Audit Logs Dashboard

Access `http://localhost:3000/admin/audit` (when implemented)

---

## 🔧 Troubleshooting

### SurrealDB Connection Error

```bash
# Check if SurrealDB is running
curl http://localhost:8000/health

# If not, restart it
docker stop surrealdb
docker remove surrealdb
docker run -d \
  --name surrealdb \
  -p 8000:8000 \
  surrealdb/surrealdb:latest \
  start -u root -p root
```

### JWT Secret Error

```
JWT Error: Secret key not set
```

Solution: Add `JWT_SECRET` to `.env` file

### Migration Failed

```bash
# Check SurrealDB is running and accessible
curl http://localhost:8000/health

# Check logs in API startup
python run_api.py
```

### Port Already in Use

```bash
# Change port in run_api.py or use:
uvicorn api.main:app --host 0.0.0.0 --port 5056

# Or kill the process using the port:
# Windows:
netstat -ano | findstr :5055
taskkill /PID <PID> /F

# macOS/Linux:
lsof -i :5055
kill -9 <PID>
```

---

## 📝 Default Credentials

**For Development Only:**

| Field    | Value                     |
| -------- | ------------------------- |
| Email    | admin@open-notebook.local |
| Password | admin                     |
| Role     | admin                     |

⚠️ **Change these in production!**

Set in `.env`:

```bash
ADMIN_EMAIL=your-email@company.com
ADMIN_PASSWORD=your-secure-password
```

---

## 🚀 Production Deployment

See [REQUIREMENTS_SETUP.md](REQUIREMENTS_SETUP.md) for production deployment guide including:

- Docker setup
- Reverse proxy configuration
- SSL/TLS configuration
- Scalable database setup
- Monitoring and logging

---

## 📚 Documentation Reference

| Document                                                 | Purpose                               |
| -------------------------------------------------------- | ------------------------------------- |
| [CUSTOMIZATION_TASKS.md](CUSTOMIZATION_TASKS.md)         | Detailed architecture for all 4 tasks |
| [REQUIREMENTS_SETUP.md](REQUIREMENTS_SETUP.md)           | Dependencies, env vars, deployment    |
| [SEARCH_RAG_UI_TEMPLATES.md](SEARCH_RAG_UI_TEMPLATES.md) | React templates for search UI         |
| [api/CLAUDE.md](api/CLAUDE.md)                           | FastAPI architecture                  |
| [frontend/CLAUDE.md](frontend/CLAUDE.md)                 | React/Next.js architecture            |

---

## ✅ Verification Checklist

After setup, verify everything works:

- [ ] SurrealDB running (`http://localhost:8000/health` returns OK)
- [ ] API running (`http://localhost:5055/health` returns OK)
- [ ] Frontend running (`http://localhost:3000` loads)
- [ ] Login works with admin@open-notebook.local
- [ ] Can create notebooks (RBAC working)
- [ ] Audit logs appear in database
- [ ] Search API responds

---

## 💡 Development Tips

### Hot Reload

Both API and Frontend support hot reload:

- **API**: Automatically reloads on file changes
- **Frontend**: Automatically reloads on file changes

### Debug Logging

Set in `.env`:

```bash
DEBUG=true
LOG_LEVEL=debug
```

### Test OAuth (Optional)

To test OAuth providers locally, use ngrok to expose your local server:

```bash
# Install ngrok
brew install ngrok

# Start ngrok
ngrok http 5055

# Set in .env:
AZURE_REDIRECT_URI=https://your-ngrok-id.ngrok.io/auth/oauth/azure/callback
GOOGLE_REDIRECT_URI=https://your-ngrok-id.ngrok.io/auth/oauth/google/callback
```

---

## 🎓 Next: Implement Custom Features

With OAuth, RBAC, and Audit logging ready, you can now:

1. **Add custom roles** in `/api/admin/roles`
2. **Build search UI** using components in [SEARCH_RAG_UI_TEMPLATES.md](SEARCH_RAG_UI_TEMPLATES.md)
3. **Configure OAuth providers** (Azure, Google, GitHub)
4. **Setup log aggregation** with ELK stack
5. **Deploy to production** following [REQUIREMENTS_SETUP.md](REQUIREMENTS_SETUP.md)

---

## 📞 Support

- API Docs: `http://localhost:5055/docs`
- Issue Tracker: https://github.com/lfnovo/open-notebook/issues
- Discord: https://discord.gg/37XJPXfz2w

---

**You're all set! 🎉 OpenNotebook is ready with OAuth, RBAC, and Audit logging!**
