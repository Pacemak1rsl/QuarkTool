import base64
import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


SERVICE_NAME = "QuarkBatchTool"


@dataclass
class Account:
    account_id: str
    name: str
    created_at: float
    active: bool = False


class SessionStore:
    def __init__(self) -> None:
        appdata = os.environ.get("APPDATA") or str(Path.home())
        self.base_dir = Path(appdata) / "QuarkBatchTool"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.accounts_path = self.base_dir / "accounts.json"
        self.fallback_cookie_path = self.base_dir / "cookies.json"
        self._keyring = self._load_keyring()

    def _load_keyring(self):
        try:
            import keyring  # type: ignore

            return keyring
        except Exception:
            return None

    def list_accounts(self) -> List[Account]:
        payload = self._read_json(self.accounts_path, {"accounts": []})
        accounts = []
        for item in payload.get("accounts", []):
            accounts.append(
                Account(
                    account_id=item["account_id"],
                    name=item.get("name") or "夸克账号",
                    created_at=float(item.get("created_at") or time.time()),
                    active=bool(item.get("active")),
                )
            )
        return accounts

    def add_or_update_account(self, name: str, cookie_header: str) -> Account:
        accounts = self.list_accounts()
        existing = next((item for item in accounts if item.name == name), None)
        account = existing or Account(str(uuid.uuid4()), name, time.time(), True)

        for item in accounts:
            item.active = False
        account.active = True
        if existing is None:
            accounts.append(account)

        self._save_accounts(accounts)
        self._save_cookie(account.account_id, cookie_header)
        return account

    def delete_account(self, account_id: str) -> None:
        accounts = [item for item in self.list_accounts() if item.account_id != account_id]
        if accounts and not any(item.active for item in accounts):
            accounts[0].active = True
        self._save_accounts(accounts)

        if self._keyring:
            try:
                self._keyring.delete_password(SERVICE_NAME, account_id)
            except Exception:
                pass
        fallback = self._read_json(self.fallback_cookie_path, {})
        fallback.pop(account_id, None)
        self._write_json(self.fallback_cookie_path, fallback)

    def rename_account(self, account_id: str, new_name: str) -> None:
        cleaned = str(new_name or "").strip()
        if not cleaned:
            raise ValueError("账号名称不能为空")
        accounts = self.list_accounts()
        for item in accounts:
            if item.account_id != account_id and item.name == cleaned:
                raise ValueError("账号名称已存在")
        updated = False
        for item in accounts:
            if item.account_id == account_id:
                item.name = cleaned
                updated = True
                break
        if not updated:
            raise ValueError("未找到要重命名的账号")
        self._save_accounts(accounts)

    def set_active(self, account_id: str) -> None:
        accounts = self.list_accounts()
        for item in accounts:
            item.active = item.account_id == account_id
        self._save_accounts(accounts)

    def active_account(self) -> Optional[Account]:
        accounts = self.list_accounts()
        return next((item for item in accounts if item.active), accounts[0] if accounts else None)

    def get_cookie(self, account_id: str) -> Optional[str]:
        if self._keyring:
            try:
                cookie = self._keyring.get_password(SERVICE_NAME, account_id)
                if cookie:
                    return cookie
            except Exception:
                pass

        fallback = self._read_json(self.fallback_cookie_path, {})
        encoded = fallback.get(account_id)
        if not encoded:
            return None
        try:
            return base64.b64decode(encoded.encode("utf-8")).decode("utf-8")
        except Exception:
            return None

    def _save_cookie(self, account_id: str, cookie_header: str) -> None:
        if self._keyring:
            try:
                self._keyring.set_password(SERVICE_NAME, account_id, cookie_header)
                return
            except Exception:
                pass

        fallback = self._read_json(self.fallback_cookie_path, {})
        fallback[account_id] = base64.b64encode(cookie_header.encode("utf-8")).decode("utf-8")
        self._write_json(self.fallback_cookie_path, fallback)

    def _save_accounts(self, accounts: List[Account]) -> None:
        payload = {
            "accounts": [
                {
                    "account_id": item.account_id,
                    "name": item.name,
                    "created_at": item.created_at,
                    "active": item.active,
                }
                for item in accounts
            ]
        }
        self._write_json(self.accounts_path, payload)

    def _read_json(self, path: Path, default: Dict) -> Dict:
        if not path.exists():
            return default
        try:
            with path.open("r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return default

    def _write_json(self, path: Path, payload: Dict) -> None:
        with path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
