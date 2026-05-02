from dataclasses import dataclass
from typing import Any, Dict, List

from PySide6.QtCore import QThread, Signal

from .quark_api import QuarkClient


@dataclass
class BatchJob:
    kind: str
    label: str
    payload: Dict[str, Any]


class TaskWorker(QThread):
    log = Signal(str)
    progress = Signal(int, int)
    result = Signal(dict)
    failed = Signal(str)
    finished_all = Signal()

    def __init__(self, client: QuarkClient, jobs: List[BatchJob], delay_min: int, delay_max: int) -> None:
        super().__init__()
        self.client = client
        self.jobs = jobs
        self.delay_min = delay_min
        self.delay_max = delay_max
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        total = len(self.jobs)
        for index, job in enumerate(self.jobs, start=1):
            if self._cancelled:
                self.log.emit("任务已停止")
                break

            self.progress.emit(index - 1, total)
            waited = self.client.random_delay(self.delay_min, self.delay_max, lambda: self._cancelled)
            if self._cancelled:
                break
            self.log.emit("等待 %.1f 秒后执行：%s" % (waited, job.label))

            try:
                data = self._execute(job)
                self.result.emit(
                    {
                        "ok": True,
                        "kind": job.kind,
                        "label": job.label,
                        "payload": job.payload,
                        "data": data,
                    }
                )
                self.log.emit("完成：%s" % job.label)
            except Exception as exc:
                self.result.emit(
                    {
                        "ok": False,
                        "kind": job.kind,
                        "label": job.label,
                        "payload": job.payload,
                        "error": str(exc),
                    }
                )
                self.failed.emit("%s：%s" % (job.label, exc))

            self.progress.emit(index, total)

        self.finished_all.emit()

    def _execute(self, job: BatchJob) -> Dict[str, Any]:
        payload = job.payload
        if job.kind == "share":
            return self.client.create_share(
                payload["fid"],
                payload.get("title") or "夸克分享",
                int(payload.get("expire_days") or 0),
                payload.get("password") or None,
            )
        if job.kind == "transfer":
            return self.client.transfer_share(
                payload["share_url"],
                payload.get("target_folder_id") or "root",
                payload.get("passcode") or "",
            )
        if job.kind == "transfer_share":
            return self.client.transfer_share_then_share(
                payload["share_url"],
                payload.get("target_folder_id") or "root",
                payload.get("passcode") or "",
                int(payload.get("expire_days") or 0),
                int(payload.get("share_delay_min") or 4),
                int(payload.get("share_delay_max") or 6),
                int(payload.get("share_retries") or 3),
                lambda: self._cancelled,
            )
        if job.kind == "copy":
            return self.client.copy_file_to_folder(payload["fid"], payload["target_folder_id"])
        if job.kind == "move":
            return self.client.move_files([payload["fid"]], payload["target_folder_id"])
        if job.kind == "rename":
            return self.client.rename_file(payload["fid"], payload["new_name"])
        if job.kind in ("delete", "delete_folder"):
            return self.client.delete_files([payload["fid"]])
        if job.kind == "create_folder":
            return self.client.create_folder(payload["name"], payload.get("parent_fid") or "root")
        if job.kind == "recycle_recover":
            return self.client.recover_recycle_records([payload["record_id"]])
        if job.kind == "recycle_remove":
            return self.client.remove_recycle_records([payload["record_id"]])
        raise ValueError("未知任务类型：%s" % job.kind)
