"""Dépendances FastAPI partagées entre les routers."""
from fastapi import Depends
from src.core.security import verify_api_key

# Dépendance réutilisable pour les routes protégées
AuthDep = Depends(verify_api_key)
