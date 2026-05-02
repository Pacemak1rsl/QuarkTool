import random
import re
import time
from typing import Any, Callable, Dict, Iterable, List, Optional

import requests


LogFn = Optional[Callable[[str], None]]


class QuarkApiError(RuntimeError):
    pass


class QuarkClient:
    def __init__(self, cookie: str, logger: LogFn = None) -> None:
        self.cookie = cookie.strip()
        self.log = logger or (lambda message: None)
        self.session = requests.Session()
        self.session.trust_env = False
        self.base_params = {"pr": "ucpro", "fr": "pc", "uc_param_str": ""}

    def list_files(self, folder_id: str = "root", page_size: int = 80) -> List[Dict[str, Any]]:
        url = "https://drive-pc.quark.cn/1/clouddrive/file/sort"
        folder = self._api_folder_id(folder_id)
        page = 1
        total = None
        files: List[Dict[str, Any]] = []

        while True:
            params = self._params(
                pdir_fid=folder,
                _page=str(page),
                _size=str(page_size),
                _fetch_total="1",
                _fetch_sub_dirs="0",
                _sort="file_type:asc,updated_at:desc",
            )
            data = self._request("GET", url, params=params)
            chunk = data.get("list") or []
            files.extend(chunk)
            metadata = data.get("metadata") or {}
            total = total if total is not None else metadata.get("_total")

            if not chunk:
                break
            if total is not None and len(files) >= int(total):
                break
            page += 1

        return files

    def search_files(self, keyword: str, folder_id: str = "root", page_size: int = 100) -> List[Dict[str, Any]]:
        url = "https://drive-pc.quark.cn/1/clouddrive/file/search"
        folder = self._api_folder_id(folder_id)
        terms: List[str] = []
        for part in str(keyword or "").split("|"):
            term = part.strip()
            if term and term not in terms:
                terms.append(term)
        if not terms:
            return []

        results: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for term in terms:
            page = 1
            while True:
                params = self._params(
                    pdir_fid=folder,
                    q=term,
                    _page=str(page),
                    _size=str(page_size),
                )
                data = self._request("GET", url, params=params)
                chunk = data.get("list") or []
                if not chunk:
                    break
                for item in chunk:
                    key = str(item.get("fid") or "") or "%s::%s" % (
                        item.get("file_name") or "",
                        item.get("pdir_fid") or "",
                    )
                    if key and key not in seen:
                        seen.add(key)
                        results.append(item)
                if len(chunk) < page_size:
                    break
                page += 1

        lowered_terms = [term.lower() for term in terms]

        def rank(item: Dict[str, Any]) -> tuple:
            name = str(item.get("file_name") or "")
            lowered = name.lower()
            exact = any(lowered == term for term in lowered_terms)
            prefix = any(lowered.startswith(term) for term in lowered_terms)
            contains = any(term in lowered for term in lowered_terms)
            file_type = int(item.get("file_type") or 1)
            updated = str(item.get("updated_at") or "")
            return (
                0 if exact else 1 if prefix else 2 if contains else 3,
                file_type,
                -len(name),
                updated,
            )

        return sorted(results, key=rank)

    def get_file_info(self, fid: str) -> Dict[str, Any]:
        url = "https://drive-pc.quark.cn/1/clouddrive/file/info"
        return self._request("GET", url, params=self._params(fid=fid))

    def rename_file(self, fid: str, new_name: str) -> Dict[str, Any]:
        url = "https://drive-pc.quark.cn/1/clouddrive/file/rename"
        return self._request("POST", url, params=self._params(), json={"fid": fid, "file_name": new_name})

    def create_folder(self, name: str, parent_fid: str = "root") -> Dict[str, Any]:
        url = "https://drive-pc.quark.cn/1/clouddrive/file"
        body = {
            "pdir_fid": self._api_folder_id(parent_fid),
            "file_name": name,
            "dir_path": "",
            "dir_init_lock": False,
        }
        return self._request("POST", url, params=self._params(), json=body)

    def create_share(
        self,
        fid: str,
        title: str,
        expire_days: int = 0,
        password: Optional[str] = None,
    ) -> Dict[str, Any]:
        url = "https://drive-pc.quark.cn/1/clouddrive/share"
        body: Dict[str, Any] = {
            "fid_list": [fid],
            "title": title or "夸克分享",
            "url_type": 1,
            "expired_type": 1,
            "expire_time": 0,
        }
        if expire_days > 0:
            body["expired_type"] = 2
            body["expire_time"] = expire_days * 86400
        if password:
            body["password"] = password

        result = self._raw_request("POST", url, params=self._params(), json=body)
        task_data = result.get("data") or {}
        share_id = self._extract_task_value(task_data, "share_id")
        if not share_id:
            raise QuarkApiError("创建分享成功响应中没有 share_id")
        detail = self.get_share_password(share_id)
        detail["share_id"] = share_id
        return detail

    def get_share_password(self, share_id: str) -> Dict[str, Any]:
        url = "https://drive-pc.quark.cn/1/clouddrive/share/password"
        return self._request("POST", url, params=self._params(), json={"share_id": share_id})

    def get_share_list(self) -> List[Dict[str, Any]]:
        url = "https://drive-pc.quark.cn/1/clouddrive/share/list"
        data = self._request("GET", url, params=self._params())
        return data.get("list") or []

    def list_recycle_files(self, page_size: int = 80) -> List[Dict[str, Any]]:
        url = "https://drive-pc.quark.cn/1/clouddrive/file/recycle/list"
        page = 1
        total = None
        items: List[Dict[str, Any]] = []

        while True:
            data = self._request("GET", url, params=self._params(_page=str(page), _size=str(page_size)))
            chunk = data.get("list") or []
            items.extend(chunk)
            total = total if total is not None else data.get("total")
            if not chunk:
                break
            if total is not None and len(items) >= int(total):
                break
            page += 1
        return items

    def transfer_share(self, share_url: str, target_folder_id: str = "root", passcode: str = "") -> Dict[str, Any]:
        pwd_id = self.extract_pwd_id(share_url)
        if not pwd_id:
            raise QuarkApiError("分享链接格式不正确")

        stoken = self.get_share_token(pwd_id, passcode)
        detail = self.get_share_detail(pwd_id, stoken)
        items = detail.get("list") or []
        if not items:
            raise QuarkApiError("分享内没有可转存文件，或分享已失效")

        fid_list = [item.get("fid") for item in items if item.get("fid")]
        token_list = [item.get("share_fid_token") for item in items if item.get("share_fid_token")]
        if not fid_list or len(fid_list) != len(token_list):
            raise QuarkApiError("分享文件 token 不完整，无法转存")

        url = "https://drive-pc.quark.cn/1/clouddrive/share/sharepage/save"
        body = {
            "fid_list": fid_list,
            "fid_token_list": token_list,
            "pdir_fid": "0",
            "pwd_id": pwd_id,
            "scene": "link",
            "stoken": stoken,
            "to_pdir_fid": self._api_folder_id(target_folder_id),
        }
        result = self._raw_request(
            "POST",
            url,
            params=self._time_params(),
            json=body,
            referer="https://pan.quark.cn/s/%s" % pwd_id,
        )
        data = result.get("data") or {}
        task_data = self._resolve_task(data)
        share_info = detail.get("share") or {}
        item_names = [item.get("file_name") for item in items if item.get("file_name")]
        return {
            "success": True,
            "title": share_info.get("title") or "",
            "item_names": item_names,
            "pwd_id": pwd_id,
            "task": task_data,
            "count": len(fid_list),
        }

    def transfer_share_then_share(
        self,
        share_url: str,
        target_folder_id: str = "root",
        passcode: str = "",
        expire_days: int = 0,
        share_delay_min: int = 4,
        share_delay_max: int = 6,
        share_retries: int = 3,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, Any]:
        transfer = self.transfer_share(share_url, target_folder_id, passcode)
        title = transfer.get("title") or "转存资源"
        candidates = [title] + list(transfer.get("item_names") or [])
        attempts = max(1, int(share_retries or 1))
        last_error = ""
        for attempt in range(1, attempts + 1):
            waited = self.random_delay(share_delay_min, max(share_delay_max, share_delay_min), cancel_check)
            self.log("转存完成，第 %d/%d 次分享前等待 %.1f 秒：%s" % (attempt, attempts, waited, title))
            if cancel_check and cancel_check():
                raise QuarkApiError("任务已取消")

            found = self.find_child_by_names(target_folder_id, candidates)
            if not found:
                last_error = "第 %d 次分享前没有自动定位到转存文件" % attempt
                self.log(last_error)
                continue

            try:
                share = self.create_share(found["fid"], found.get("file_name") or title, expire_days)
                link = self._find_nested_value(share, ["share_url", "url", "link"])
                if link:
                    transfer["share"] = share
                    transfer["share_created"] = True
                    transfer["share_attempts"] = attempt
                    return transfer
                last_error = "第 %d 次分享接口返回成功，但没有分享链接" % attempt
                self.log(last_error)
            except Exception as exc:
                last_error = "第 %d 次分享失败：%s" % (attempt, exc)
                self.log(last_error)

        transfer["share_created"] = False
        transfer["share_attempts"] = attempts
        transfer["share_error"] = last_error or "转存成功，但多次重试后仍未生成分享链接"
        transfer["share"] = {"message": transfer["share_error"]}
        return transfer

    def find_child_by_name(self, folder_id: str, name: str) -> Optional[Dict[str, Any]]:
        for item in self.list_files(folder_id):
            if item.get("file_name") == name:
                return item
        return None

    def find_child_by_names(self, folder_id: str, names: Iterable[str]) -> Optional[Dict[str, Any]]:
        wanted = []
        for name in names:
            value = str(name or "").strip()
            if value and value not in wanted:
                wanted.append(value)
        if not wanted:
            return None
        for item in self.list_files(folder_id):
            if item.get("file_name") in wanted:
                return item
        return None

    def _find_nested_value(self, data: Any, keys: Iterable[str]) -> str:
        wanted = set(keys)
        if isinstance(data, dict):
            for key in wanted:
                value = data.get(key)
                if value:
                    return str(value)
            for value in data.values():
                found = self._find_nested_value(value, wanted)
                if found:
                    return found
        elif isinstance(data, list):
            for item in data:
                found = self._find_nested_value(item, wanted)
                if found:
                    return found
        return ""

    def copy_file_to_folder(self, fid: str, target_folder_id: str) -> Dict[str, Any]:
        url = "https://drive-pc.quark.cn/1/clouddrive/file/copy"
        body = {
            "action_type": 1,
            "filelist": [fid],
            "to_pdir_fid": self._api_folder_id(target_folder_id),
            "exclude_fids": [],
        }
        result = self._raw_request("POST", url, params=self._params(), json=body)
        data = result.get("data") or {}
        task = self._resolve_task(data)
        return {"success": True, "target_folder_id": target_folder_id, "task": task}

    def move_files(self, fids: Iterable[str], target_folder_id: str) -> Dict[str, Any]:
        url = "https://drive-pc.quark.cn/1/clouddrive/file/move"
        body = {
            "action_type": 1,
            "filelist": list(fids),
            "to_pdir_fid": self._api_folder_id(target_folder_id),
            "exclude_fids": [],
        }
        result = self._raw_request("POST", url, params=self._params(), json=body)
        return {"success": True, "task": self._resolve_task(result.get("data") or {})}

    def delete_files(self, fids: Iterable[str]) -> Dict[str, Any]:
        filelist = [fid for fid in fids if fid]
        if not filelist:
            raise QuarkApiError("没有可删除的 FID")
        url = "https://drive-pc.quark.cn/1/clouddrive/file/delete"
        body = {
            "action_type": 2,
            "filelist": filelist,
            "exclude_fids": [],
        }
        result = self._raw_request("POST", url, params=self._params(), json=body)
        return {"success": True, "filelist": filelist, "task": self._resolve_task(result.get("data") or {})}

    def recover_recycle_records(self, record_ids: Iterable[str]) -> Dict[str, Any]:
        record_list = [record_id for record_id in record_ids if record_id]
        if not record_list:
            raise QuarkApiError("没有可恢复的回收站记录")
        url = "https://drive-pc.quark.cn/1/clouddrive/file/recycle/recover"
        body = {"select_mode": 1, "record_list": record_list}
        result = self._raw_request("POST", url, params=self._params(), json=body)
        return {"success": True, "record_list": record_list, "task": self._resolve_task(result.get("data") or {})}

    def remove_recycle_records(self, record_ids: Iterable[str]) -> Dict[str, Any]:
        record_list = [record_id for record_id in record_ids if record_id]
        if not record_list:
            raise QuarkApiError("没有可彻底删除的回收站记录")
        url = "https://drive-pc.quark.cn/1/clouddrive/file/recycle/remove"
        body = {"select_mode": 1, "record_list": record_list}
        result = self._raw_request("POST", url, params=self._params(), json=body)
        return {"success": True, "record_list": record_list, "task": self._resolve_task(result.get("data") or {})}

    def extract_pwd_id(self, share_url: str) -> Optional[str]:
        match = re.search(r"(?:https?://)?pan\.quark\.cn/s/([a-zA-Z0-9]+)", share_url)
        return match.group(1) if match else None

    def get_share_token(self, pwd_id: str, passcode: str = "") -> str:
        url = "https://drive-h.quark.cn/1/clouddrive/share/sharepage/token"
        data = self._request(
            "POST",
            url,
            params=self._time_params(),
            json={"pwd_id": pwd_id, "passcode": passcode or ""},
            referer="https://pan.quark.cn/s/%s" % pwd_id,
        )
        stoken = data.get("stoken")
        if not stoken:
            raise QuarkApiError("获取分享 stoken 失败，可能是提取码错误或链接失效")
        return stoken

    def get_share_detail(self, pwd_id: str, stoken: str, pdir_fid: str = "0") -> Dict[str, Any]:
        url = "https://drive-h.quark.cn/1/clouddrive/share/sharepage/detail"
        params = self._time_params(
            pwd_id=pwd_id,
            pdir_fid=pdir_fid,
            force="0",
            _page="1",
            _size="100",
            _fetch_banner="1",
            _fetch_share="1",
            _fetch_total="1",
            _sort="file_type:asc,file_name:asc",
            stoken=stoken,
        )
        return self._request("GET", url, params=params, referer="https://pan.quark.cn/s/%s" % pwd_id)

    def random_delay(self, min_seconds: int = 5, max_seconds: int = 10, cancel_check: Optional[Callable[[], bool]] = None) -> float:
        seconds = random.uniform(min_seconds, max_seconds)
        end_at = time.time() + seconds
        while time.time() < end_at:
            if cancel_check and cancel_check():
                break
            time.sleep(min(0.25, end_at - time.time()))
        return seconds

    def _poll_task(self, task_id: str, retries: int = 20) -> Dict[str, Any]:
        url = "https://drive-pc.quark.cn/1/clouddrive/task"
        last_data: Dict[str, Any] = {}
        delay = 1.0
        for index in range(retries):
            params = self._params(task_id=task_id, retry_index=str(index))
            data = self._request("GET", url, params=params)
            last_data = data
            status = data.get("status")
            if status == 2:
                return data
            if status == 3:
                raise QuarkApiError(data.get("message") or "任务失败")
            gap = (data.get("metadata") or {}).get("tq_gap")
            if gap:
                delay = max(float(gap) / 1000.0, 1.0)
            time.sleep(delay)
        return last_data

    def _extract_task_value(self, data: Dict[str, Any], key: str) -> Optional[Any]:
        task_data = self._resolve_task(data)
        return task_data.get(key) or (task_data.get("data") or {}).get(key)

    def _resolve_task(self, data: Dict[str, Any]) -> Dict[str, Any]:
        if data.get("task_sync"):
            task_resp = data.get("task_resp") or {}
            if task_resp.get("code", 0) != 0:
                raise QuarkApiError(task_resp.get("message") or "同步任务失败")
            return task_resp.get("data") or task_resp

        task_id = data.get("task_id")
        if task_id:
            self.log("任务已提交：%s，等待完成..." % task_id)
            return self._poll_task(task_id)
        return data

    def _request(self, method: str, url: str, **kwargs: Any) -> Dict[str, Any]:
        result = self._raw_request(method, url, **kwargs)
        return result.get("data") or {}

    def _raw_request(self, method: str, url: str, referer: Optional[str] = None, **kwargs: Any) -> Dict[str, Any]:
        headers = self._headers(referer=referer)
        response = self.session.request(method, url, headers=headers, timeout=45, **kwargs)
        try:
            payload = response.json()
        except ValueError:
            if response.status_code >= 400:
                raise QuarkApiError("HTTP %s：%s" % (response.status_code, response.text[:240]))
            raise QuarkApiError("接口没有返回 JSON：%s" % response.text[:120])

        if response.status_code >= 400:
            message = payload.get("message") or payload.get("msg") or response.reason
            raise QuarkApiError("HTTP %s：%s（code=%s）" % (response.status_code, message, payload.get("code")))

        if payload.get("code") != 0:
            message = payload.get("message") or payload.get("msg") or "接口返回失败"
            raise QuarkApiError("%s：%s" % (message, payload.get("code")))
        return payload

    def _headers(self, referer: Optional[str] = None) -> Dict[str, str]:
        return {
            "Cookie": self.cookie,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Content-Type": "application/json",
            "Origin": "https://pan.quark.cn",
            "Referer": referer or "https://pan.quark.cn/",
            "Sec-Fetch-Site": "same-site",
        }

    def _params(self, **extra: Any) -> Dict[str, Any]:
        params = dict(self.base_params)
        params.update(extra)
        return params

    def _time_params(self, **extra: Any) -> Dict[str, Any]:
        now = int(time.time() * 1000)
        params = self._params(__dt=str(now % 1000), __t=str(now))
        params.update(extra)
        return params

    def _api_folder_id(self, folder_id: str) -> str:
        return "0" if not folder_id or folder_id == "root" else folder_id
