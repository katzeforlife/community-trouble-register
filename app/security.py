import hashlib, secrets
from passlib.context import CryptContext

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    return _pwd.hash(password)

def verify_password(password: str, hashed: str) -> bool:
    return _pwd.verify(password, hashed)

def new_api_key() -> str:
    return "ctr_" + secrets.token_urlsafe(36)

def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()
