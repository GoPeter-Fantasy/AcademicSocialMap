import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"

# Legacy plaintext key files live here. Override with the KEYS_DIR env var.
# Default is a home-directory path so a fresh clone never writes into the repo.
_DEFAULT_KEYS_DIR = Path.home() / ".academic-social-map" / "keys"
KEYS_DIR = Path(os.environ.get("KEYS_DIR", str(_DEFAULT_KEYS_DIR))).expanduser()

KEYRING_SERVICE = "academic-social-map"

# Optional. OpenAlex gives the "polite pool" a higher rate limit when the
# User-Agent carries a contact address. Leave unset and no mailto is sent.
MAILTO = os.environ.get("OPENALEX_MAILTO", "").strip()
USER_AGENT = (
    f"AcademicSocialMap/0.1 (mailto:{MAILTO})" if MAILTO else "AcademicSocialMap/0.1"
)


def load_key(filename: str, prefix: str | None = None) -> str:
    value = _optional_key(filename, prefix)
    if not value:
        raise FileNotFoundError(f"API key not found: {KEYS_DIR / filename}")
    return value


def _optional_key(filename: str, prefix: str | None = None) -> str:
    """Load a key if env/keyring/file has it; return '' otherwise.

    Lookup order: env > keyring > file. `prefix` is used to strip a labeled
    prefix from the file format (e.g. 'api_key: xxxx' → 'xxxx').
    """
    stem = os.path.splitext(filename)[0]
    env_var = _env_var_for(stem)
    env_val = os.environ.get(env_var, "").strip()
    if env_val:
        return env_val
    try:
        import keyring
        stored = keyring.get_password(KEYRING_SERVICE, stem)
        if stored:
            return stored.strip()
    except Exception:
        pass
    path = KEYS_DIR / filename
    if not path.exists():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        if prefix is not None:
            if line.lower().startswith(prefix.lower()):
                rest = line.split(":", 1)[1] if ":" in line else line[len(prefix) :]
                return rest.strip()
        else:
            if ":" not in line and "=" not in line:
                return line
    return ""


def _env_var_for(stem: str) -> str:
    """Map configuration stems to their historical env var names."""
    table = {
        "deepseek_api": "DEEPSEEK_API_KEY",
        "minimax": "MINIMAX_API_KEY",
        "openalex_api": "OPENALEX_API_KEY",
        "s2_api": "S2_API_KEY",
    }
    return table.get(stem, f"{stem.upper()}_API_KEY")


DEEPSEEK_API_KEY = _optional_key("deepseek_api.txt")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")

MINIMAX_API_KEY = _optional_key("minimax.txt", prefix="api_key")
MINIMAX_BASE_URL = "https://api.minimax.chat"
MINIMAX_MODEL = os.environ.get("MINIMAX_MODEL", "abab6.5s-chat")

OPENALEX_API_KEY = _optional_key("openalex_api.txt")

S2_API_KEY = _optional_key("s2_api.txt")

DATA_SOURCE = os.environ.get("DATASOURCE", "openalex").strip().lower()
if DATA_SOURCE not in ("s2", "openalex"):
    raise ValueError(f"Unknown DATA_SOURCE: {DATA_SOURCE} (use 's2' or 'openalex')")
