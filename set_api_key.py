"""Set, inspect, or remove an API key for a data source.

Keys are stored in OS-provided secure storage (Windows Credential Manager /
macOS Keychain / Secret Service) via the `keyring` library. For backwards
compatibility, keys that already exist as plaintext files under KEYS_DIR are
read as a fallback. See config.py for the lookup order.

Usage:
  python set_api_key.py openalex YOUR_OPENALEX_KEY
  python set_api_key.py s2 YOUR_S2_KEY
  python set_api_key.py deepseek YOUR_DEEPSEEK_KEY
  python set_api_key.py --check
  python set_api_key.py --remove openalex
"""
import sys
from pathlib import Path

import config

FILES = {"openalex": "openalex_api.txt", "s2": "s2_api.txt", "deepseek": "deepseek_api.txt", "minimax": "minimax.txt"}
MINIMAX_FILE_VALUE = "minimax"  # used as the keyring account name


def _set_keyring(account: str, value: str) -> bool:
    import keyring
    keyring.set_password(config.KEYRING_SERVICE, account, value)
    return True


def _delete_keyring(account: str) -> bool:
    try:
        import keyring
        keyring.delete_password(config.KEYRING_SERVICE, account)
        return True
    except Exception:
        return False


def _read_keyring(account: str) -> str:
    try:
        import keyring
        v = keyring.get_password(config.KEYRING_SERVICE, account)
        return v or ""
    except Exception:
        return ""


def _check(name: str) -> str:
    if name == "s2":
        account = "s2_api"
    elif name == "openalex":
        account = "openalex_api"
    elif name == "deepseek":
        account = "deepseek_api"
    elif name == "minimax":
        account = "minimax"
    else:
        return f"{name}: 未知来源"
    from_keyring = _read_keyring(account)
    if from_keyring:
        return f"{name}: keyring 已配置 {from_keyring[:4]}...{from_keyring[-4:]}"
    filename = FILES.get(name, "")
    if not filename:
        return f"{name}: 未配置"
    from_file = config._optional_key(filename, prefix=("api_key" if name == "minimax" else None))
    if from_file:
        return f"{name}: 文件已配置 {from_file[:4]}...{from_file[-4:]}"
    return f"{name}: 未配置"


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        return
    if sys.argv[1] == "--check":
        for name in ("s2", "openalex", "deepseek", "minimax"):
            print(_check(name))
        return
    if sys.argv[1] == "--remove":
        if len(sys.argv) < 3:
            print("用法: set_api_key.py --remove <s2|openalex|minimax>")
            return
        name = sys.argv[2].strip().lower()
        if name not in ("s2", "openalex", "minimax"):
            print(f"未知数据源: {name}")
            return
        account = "minimax" if name == "minimax" else f"{name}_api"
        removed = _delete_keyring(account)
        print(f"keyring {'已删除' if removed else '未找到'}: {name}")
        # Also remove the legacy file if present.
        fname = FILES.get(name)
        if fname:
            fpath = config.KEYS_DIR / fname
            if fpath.exists():
                try:
                    fpath.unlink()
                    print(f"  - 遗留文件已删除: {fpath}")
                except Exception as e:
                    print(f"  - 遗留文件删除失败: {e}")
        return
    name = sys.argv[1].strip().lower()
    key = (sys.argv[2] if len(sys.argv) > 2 else "").strip()
    if name not in FILES and name != "minimax":
        print(f"未知数据源: {name}（可选: {', '.join(list(FILES) + ['minimax'])}）")
        return
    if not key:
        print("key 不能为空")
        return
    account = "minimax" if name == "minimax" else f"{name}_api"
    try:
        _set_keyring(account, key)
        print(f"已保存 {name} key 到 keyring (service={config.KEYRING_SERVICE})")
    except Exception as e:
        print(f"keyring 写入失败: {e}")
        # Fall back to writing the plaintext file so the key is never lost.
        fname = FILES.get(name)
        if not fname:
            print("  - 无可用的文件回退路径")
            return
        config.KEYS_DIR.mkdir(parents=True, exist_ok=True)
        if name == "minimax":
            (config.KEYS_DIR / fname).write_text(f"api_key: {key}\n", encoding="utf-8")
        else:
            (config.KEYS_DIR / fname).write_text(key + "\n", encoding="utf-8")
        print(f"  - 回退写入明文文件: {config.KEYS_DIR / fname}")
    print("重启服务器后生效: 重新运行 start_ui.py")


if __name__ == "__main__":
    main()
