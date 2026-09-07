"""Authentication package.

Contains every piece of the JWT + refresh-token + RBAC authentication system:

- keys.py        - loading and managing the RS256 signing keys.
- security.py    - password verification and login rate limiting.
- jwt_service.py - creating and verifying short-lived access tokens.
- refresh_service.py - managing long-lived, revocable refresh sessions.
- rbac.py        - roles-to-permissions mapping and authorization checks.
- dependencies.py- FastAPI dependencies that protect routes.
- routes.py      - the /auth endpoints (login, refresh, logout, me, sessions).
"""
