-- Migration for OAuth/RBAC/Audit features
-- Adds user management, role-based access, and audit logging tables

-- User table for authentication
CREATE TABLE IF NOT EXISTS user (
    id: record<user>,
    email: string UNIQUE,
    name: string,
    roles: array<string>,
    provider: string,          -- 'local', 'azure', 'google', 'github'
    external_id: string,       -- OAuth provider user ID
    is_active: bool DEFAULT true,
    created_at: datetime,
    updated_at: datetime,
    last_login: datetime
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_user_email ON user(email);
CREATE INDEX IF NOT EXISTS idx_user_provider ON user(provider);

-- Role table for RBAC
CREATE TABLE IF NOT EXISTS role (
    id: record<role>,
    name: string UNIQUE,
    description: string,
    permissions: array<string>,
    is_default: bool DEFAULT false,
    created_at: datetime,
    updated_at: datetime
);

-- Resource access control (for fine-grained permissions)
CREATE TABLE IF NOT EXISTS resource_access (
    id: record<resource_access>,
    user_id: record<user>,
    resource_type: string,     -- 'notebook', 'source', 'note'
    resource_id: string,
    permission: string,        -- 'read', 'write', 'delete', 'share'
    granted_by: record<user>,
    created_at: datetime
);

-- Audit log table for compliance
CREATE TABLE IF NOT EXISTS audit_log (
    id: record<audit_log>,
    timestamp: datetime,
    user_id: record<user>,
    action: string,            -- 'notebook_created', 'user_role_changed', etc.
    resource_type: string,     -- 'notebook', 'source', 'note', 'user', 'system'
    resource_id: string,
    resource_name: string,
    old_value: object,         -- Previous state
    new_value: object,         -- New state
    status: string,            -- 'success', 'failure'
    error_message: string,
    ip_address: string,
    user_agent: string,
    http_status: int,
    duration_ms: float,
    metadata: object           -- Custom data
);

-- Create indexes for audit log queries
CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_user_id ON audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_resource ON audit_log(resource_type, resource_id);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action);

-- Insert default roles
INSERT INTO role (name, description, permissions, is_default) VALUES
    ('admin', 'Full system access', [
        'notebook:create', 'notebook:read', 'notebook:update', 'notebook:delete', 'notebook:share',
        'source:create', 'source:read', 'source:update', 'source:delete',
        'note:create', 'note:read', 'note:update', 'note:delete',
        'user:create', 'user:read', 'user:update', 'user:delete', 'user:manage',
        'credential:create', 'credential:read', 'credential:delete',
        'audit:view', 'settings:manage'
    ], true),
    ('editor', 'Create and edit content', [
        'notebook:create', 'notebook:read', 'notebook:update', 'notebook:share',
        'source:create', 'source:read', 'source:update',
        'note:create', 'note:read', 'note:update'
    ], false),
    ('viewer', 'Read-only access', [
        'notebook:read',
        'source:read',
        'note:read'
    ], false);

-- Create default admin user if it doesn't exist
LET $admin_exists = (SELECT id FROM user WHERE email = 'admin@open-notebook.local');

IF $admin_exists THEN
    -- Admin user exists, log it
    RETURN 'Admin user already exists';
ELSE
    -- Create admin user
    CREATE user (
        email: 'admin@open-notebook.local',
        name: 'Administrator',
        roles: ['admin'],
        provider: 'local',
        is_active: true,
        created_at: now(),
        updated_at: now()
    );
    
    RETURN 'Admin user created successfully';
END;
