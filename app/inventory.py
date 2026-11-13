"""Local manual inventory; never calls the device or an external service."""
import base64
import copy
import csv
import hashlib
import io
import json
import re
from pathlib import Path
from uuid import uuid4

from PIL import Image

from .config import ROOT


def active_inventory_paths(root=ROOT):
    root = Path(root).resolve()
    pointer = root / "runtime/manual-inventory/active.json"
    if not pointer.exists():
        return {}
    state = json.loads(pointer.read_text(encoding="utf-8"))
    directory = (root / state["directory"]).resolve()
    output = (root / state["output"]).resolve()
    if not directory.is_relative_to(root / "runtime/auto-inventory") or output.parent != directory:
        raise ValueError("自动采集会话路径异常，已停止加载")
    return {"directory": directory, "output": output}


class ManualInventory:
    def __init__(self, root=ROOT, *, directory=None, output=None):
        self.root = Path(root).resolve()
        self.directory = Path(directory).resolve() if directory else self.root / "runtime/manual-inventory/step56"
        if not self.directory.is_relative_to(self.root):
            raise ValueError("会话必须保存在项目内")
        self.images = self.directory / "screenshots"
        self.session = self.directory / "session.json"
        self.output = Path(output).resolve() if output else self.root / "data/inventory.csv"
        if not self.output.is_relative_to(self.root):
            raise ValueError("CSV必须保存在项目内")
        self.rows = []
        self.shots = []
        self.phase = "draft"
        self.ocr_reports = {}
        self.groups = []
        self.export_intent = None
        self.capture_files = []
        self.capture_mode = "manual"
        if self.session.exists():
            try:
                state = json.loads(self.session.read_text(encoding="utf-8"))
            except (ValueError, OSError) as error:
                raise ValueError("本轮草稿无法读取，已停止；请保留session.json及.tmp文件排查，不会另建空记录") from error
            self.rows, self.shots, self.phase = state["rows"], state["screenshots"], state["phase"]
            self.ocr_reports = state.get("ocr_reports", {})
            self.groups = state.get("groups") or self._legacy_groups()
            self.export_intent = state.get("export_intent")
            self.capture_files = state.get("capture_files", [])
            self.capture_mode = state.get("capture_mode", "automatic" if (self.directory / "progress.json").exists() else "manual")
            if output is None and state.get("csv_path"):
                previous_output = (self.root / state["csv_path"]).resolve()
                if not previous_output.is_relative_to(self.root):
                    raise ValueError("会话中的CSV路径超出项目，已停止加载")
                self.output = previous_output
        elif self.session.with_suffix(".tmp").exists():
            raise ValueError("发现未完成保存的草稿.tmp，已停止以防覆盖；请先恢复核查")
        # Existing default CSV remains protected; never rename or import it.
        legacy_output = self.root / "data/背包道具统计.csv"
        if output is None and (not self.session.exists() or not state.get("csv_path")) and legacy_output.exists():
            self.output = legacy_output
        self._persisted = self.snapshot()

    def _legacy_groups(self):
        groups = []
        for filename in self.shots:
            report = self.ocr_reports.get(filename, {})
            if report.get("status") == "superseded" and groups:
                groups[-1]["images"].append(filename)
            else:
                groups.append({"id": filename[:-4], "images": [filename], "selected": filename})
        return groups

    def create_group(self):
        self._editable()
        group = {"id": uuid4().hex, "images": [], "selected": ""}
        self.groups.append(group)
        self._save()
        return group["id"]

    def select_group(self, group_id, filename):
        self._editable()
        group = next((value for value in self.groups if value["id"] == group_id), None)
        if not group or filename not in group["images"]:
            raise ValueError("图片不属于当前识别组")
        group["selected"] = filename
        self._save()

    def snapshot(self):
        return copy.deepcopy({"rows": self.rows, "screenshots": self.shots,
                "phase": self.phase, "csv_path": self.output.relative_to(self.root).as_posix(),
                "groups": self.groups, "ocr_reports": self.ocr_reports,
                "capture_files": self.capture_files,
                "capture_mode": self.capture_mode,
                "export_intent": self.export_intent})

    def apply_ocr(self, filename, tokens, result):
        self._editable()
        if filename not in self.shots:
            raise ValueError("截图不属于本次记录")
        if any(row.get("grid_page") == filename for row in self.rows):
            raise ValueError("该页已入表，请在原记录核对；不会重复导入或覆盖人工更改")
        grid = result.get("layout") == "bag_grid_5cols"
        incoming = copy.deepcopy(result["rows"])
        missing_slots = []
        if grid:
            slots = [row.get("slot") for row in incoming]
            if any(type(slot) is not int or not 1 <= slot <= 25 for slot in slots) or len(set(slots)) != len(slots):
                raise ValueError("OCR格号无效或重复，已保留截图，未录入半页")
            by_slot = {row["slot"]: row for row in incoming}
            missing_slots = [slot for slot in range(1, 26) if slot not in by_slot]
            incoming = [by_slot.get(slot, {"name": "", "quantity": "", "slot": slot}) for slot in range(1, 26)]
        # Validate the entire result before changing any existing inventory row.
        for row in incoming:
            fields = self._validate_fields(row.get("name") or "待识别名称", row.get("quantity") or "待核对")
            row["name"] = fields["name"] if row.get("name") else ""
            row["quantity"] = fields["quantity"] if row.get("quantity") else ""
        pending_rows = copy.deepcopy(self.rows)
        added, repeated, conflicts = 0, 0, 0
        for row in incoming:
            prior_index = next((index for index, value in enumerate(pending_rows)
                                if not value.get("invalid") and row["name"] and value["name"] == row["name"]), None)
            prior = pending_rows[prior_index] if prior_index is not None else None
            if prior:
                if row["quantity"] and prior["quantity"] == row["quantity"]:
                    repeated += 1
                else:
                    conflicts += 1
                if not grid:
                    continue
            record = self._validate_fields(row["name"] or "待识别名称", row["quantity"] or "待核对")
            if not row["name"]:
                record["name"] = ""
            if not row["quantity"]:
                record["quantity"] = ""
            if grid:
                record.update(grid_page=filename, grid_slot=row["slot"])
                if prior and row["quantity"] and prior["quantity"] == row["quantity"] and prior.get("grid_page") != filename:
                    record.update(invalid=True, invalid_reason="duplicate", duplicate_of=prior_index)
            pending_rows.append(record)
            added += 1
        report = {**copy.deepcopy(result), "rows": incoming, "tokens": copy.deepcopy(tokens), "added": added, "repeated": repeated, "conflicts": conflicts}
        if conflicts:
            report.update(status="pending", message="同名道具数量与已有记录不同，已保留原值，需核对")
        elif grid and repeated:
            report.update(status="pending", message="发现重复道具，保留原格并标记重复排除，请核对是否翻页重叠或错字")
        if grid and (missing_slots or any(not row["name"] or not row["quantity"] for row in incoming)):
            report.update(status="pending", message="本页25格存在缺项，已保留全部格号，请核对或标记无效")
        self.rows = pending_rows
        self.ocr_reports[filename] = report
        self._save()
        return report

    def review(self, filename):
        self._editable()
        if filename not in self.ocr_reports:
            raise ValueError("该图没有待核对的OCR记录")
        if any(not row.get("invalid") and row.get("grid_page") == filename and (not row["name"] or not row["quantity"]) for row in self.rows):
            raise ValueError("本页25格仍有名称或数量缺失，不能确认整页完成")
        self._validate_records([row for row in self.rows if not row.get("invalid")], allow_missing=True)
        self.ocr_reports[filename]["status"] = "reviewed"
        self.ocr_reports[filename]["message"] = "本图已人工核对"
        self._save()

    def _save(self):
        temporary = self.session.with_suffix(".tmp")
        state = self.snapshot()
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self.session)
        except OSError:
            saved = copy.deepcopy(self._persisted)
            self.rows, self.shots, self.phase = saved["rows"], saved["screenshots"], saved["phase"]
            self.groups, self.ocr_reports = saved["groups"], saved["ocr_reports"]
            self.export_intent = saved.get("export_intent")
            self.capture_files = saved.get("capture_files", [])
            self.capture_mode = saved.get("capture_mode", "manual")
            raise
        self._persisted = state

    def _editable(self):
        if self.phase != "draft":
            raise ValueError("本次CSV已保存，不能继续更改；如清理未完成，请重试完成按钮")

    def _image_path(self, filename):
        if not re.fullmatch(r"[0-9a-f]{32}\.png", filename):
            raise ValueError("无效的本次临时截图名称")
        path = (self.images / filename).resolve()
        if path.parent != self.images.resolve() or not path.is_relative_to(self.root):
            raise ValueError("临时截图路径超出本次目录")
        return path

    def _capture_path(self, filename):
        if not re.fullmatch(r"frame-\d{3,5}-(?:initial|settling|stable|ocr-retry)\.png", filename):
            raise ValueError("无效的本轮采集证据名称")
        path = (self.directory / filename).resolve()
        if path.parent != self.directory.resolve() or not path.is_relative_to(self.root):
            raise ValueError("采集证据路径超出本轮目录")
        return path

    def import_image(self, data, *, group_id=None):
        self._editable()
        group = next((group for group in self.groups if group["id"] == group_id), None) if group_id else None
        if group_id is not None and group is None:
            raise ValueError("识别组不存在")
        if not isinstance(data, str) or len(data) > 20_000_000:
            raise ValueError("请选择小于15MB的PNG/JPEG截图")
        try:
            raw = base64.b64decode(data.split(",", 1)[1], validate=True)
            with Image.open(io.BytesIO(raw)) as source:
                if source.format not in ("PNG", "JPEG") or source.width * source.height > 20_000_000:
                    raise ValueError("图片格式或尺寸不支持")
                image = source.convert("RGB")
        except Exception as error:
            raise ValueError("无法读取截图，请选择有效的PNG/JPEG图片") from error
        filename = uuid4().hex + ".png"
        self.images.mkdir(parents=True, exist_ok=True)
        path = self._image_path(filename)
        try:
            image.save(path, format="PNG")
        except OSError:
            path.unlink(missing_ok=True)
            raise
        if group is None:
            group = {"id": uuid4().hex, "images": [], "selected": ""}
            self.groups.append(group)
        self.shots.append(filename)
        group["images"].append(filename)
        group["selected"] = filename
        try:
            self._save()
        except OSError:
            self._image_path(filename).unlink(missing_ok=True)
            raise
        return self.preview(filename)

    def preview(self, filename):
        if filename not in self.shots:
            raise ValueError("截图不属于本次记录")
        with Image.open(self._image_path(filename)) as source:
            if source.size == (630, 1120):
                from .ocr import PREVIEW_ROI
                x, y, width, height = PREVIEW_ROI
                source = source.crop((x, y, x + width, y + height))
            buffer = io.BytesIO()
            source.save(buffer, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")

    @staticmethod
    def _validate_fields(name, quantity):
        name, quantity = str(name).strip(), str(quantity).strip()
        if not name or not quantity or len(name) > 100 or len(quantity) > 40:
            raise ValueError("请填写道具名称和画面中显示的数量")
        if any(c in name + quantity for c in "\r\n\x00") or name[0] in "=+-@" or quantity[0] in "=+-@":
            raise ValueError("名称或数量含不支持的字符")
        return {"name": name, "quantity": quantity}

    def _row(self, name, quantity, excluding=None):
        fields = self._validate_fields(name, quantity)
        if any(row["name"] == fields["name"] for i, row in enumerate(self.rows) if i != excluding and not row.get("invalid")):
            raise ValueError("该名称已记录，请先核对是否为翻页重复；不会累加数量")
        return fields

    def _validate_records(self, records, *, allow_missing=False):
        names = set()
        for row in records:
            fields = self._validate_fields(row["name"] or ("待识别名称" if allow_missing else ""),
                                           row["quantity"] or ("待核对" if allow_missing else ""))
            if row["name"] and fields["name"] in names:
                raise ValueError("有效记录中存在同名道具，请核对重复或错字并排除重复格")
            if row["name"]:
                names.add(fields["name"])

    def add(self, name, quantity):
        self._editable()
        self.rows.append(self._row(name, quantity))
        self._save()

    def update(self, index, name, quantity):
        self._editable()
        if type(index) is not int or not 0 <= index < len(self.rows):
            raise ValueError("无效的道具行")
        self.rows[index] = {**self.rows[index], **self._row(name, quantity, excluding=index)}
        self._save()

    def update_cell(self, index, field, value):
        self._editable()
        if type(index) is not int or not 0 <= index < len(self.rows) or field not in ("name", "quantity"):
            raise ValueError("无效的道具单元格")
        current = self.rows[index]
        if field == "name":
            changed = self._row(value, current["quantity"] or "待核对", excluding=index)["name"]
        else:
            changed = self._row(current["name"] or "待识别名称", value, excluding=index)["quantity"]
        current[field] = changed
        self._save()

    def remove(self, index):
        self.set_invalid_many([index], True)

    def restore(self, index):
        self.set_invalid_many([index], False)

    def set_invalid_many(self, indexes, invalid):
        self._editable()
        if not isinstance(indexes, list) or not indexes or type(invalid) is not bool:
            raise ValueError("请选择需要标记的道具行")
        if any(type(index) is not int or not 0 <= index < len(self.rows) for index in indexes):
            raise ValueError("无效的道具行；本次批量操作未执行")
        changed = copy.deepcopy(self.rows)
        for index in set(indexes):
            changed[index]["invalid"] = invalid
            changed[index]["invalid_reason"] = "manual" if invalid else ""
            changed[index].pop("duplicate_of", None)
        if not invalid:
            self._validate_records([row for row in changed if not row.get("invalid")], allow_missing=True)
        self.rows = changed
        self._save()

    def reset(self):
        # Enumerate and validate every target before deleting; never recurse.
        targets = {self._image_path(name) for name in self.shots}
        targets.update(self._capture_path(name) for name in self.capture_files)
        if self.images.exists():
            targets.update(self._image_path(path.name) for path in self.images.iterdir()
                           if re.fullmatch(r"[0-9a-f]{32}\.png", path.name))
        for path in targets:
            if path.exists() and not path.is_file():
                raise ValueError("临时截图目录含非文件目标，已停止重置")
        counts = {"cleared_rows": len(self.rows), "cleared_screenshots": sum(path.exists() for path in targets)}
        self.rows, self.shots, self.groups, self.ocr_reports, self.phase = [], [], [], {}, "draft"
        self.export_intent = None
        self.capture_files = []
        self.capture_mode = "manual"
        # Persist the requested reset before deleting files. A failed session
        # write must never destroy screenshots required by the previous draft.
        self._save()
        for path in targets:
            path.unlink(missing_ok=True)
        progress = self.directory / "progress.json"
        if progress.exists():
            temporary = progress.with_suffix(".tmp")
            temporary.write_text(json.dumps({"phase": "idle", "pages": 0, "capture_complete": False,
                                             "message": "本轮已重置，等待重新开始"}, ensure_ascii=False), encoding="utf-8")
            temporary.replace(progress)
        return counts

    def finish(self, confirmed):
        if self.capture_mode == "automatic":
            progress = self.directory / "progress.json"
            if not progress.exists() or not json.loads(progress.read_text(encoding="utf-8")).get("capture_complete"):
                raise ValueError("本轮自动采集未完整到达底部或已中断作废，不能导出；请重新自动采集")
        records = [row for row in self.rows if not row.get("invalid")]
        if confirmed is not True or not records:
            raise ValueError("请先录入道具，并确认顺序、数量及排除范围均已核对")
        if any(not row["name"].strip() or not row["quantity"].strip() for row in records):
            raise ValueError("仍有格子名称或数量未识别，请补记或核对后再完成；不会按0或1猜测")
        self._validate_records(records)
        if any(report["status"] == "pending" for report in self.ocr_reports.values()):
            raise ValueError("仍有截图识别不完整或数量冲突，请先核对，临时截图保留")
        if self.phase == "draft":
            self.output.parent.mkdir(parents=True, exist_ok=True)
            buffer = io.StringIO(newline="")
            writer = csv.writer(buffer)
            writer.writerow(["道具名称", "数量"])
            writer.writerows((row["name"], row["quantity"]) for row in records)
            content = buffer.getvalue()
            digest = hashlib.sha256(content.encode("utf-8-sig")).hexdigest()
            # A persisted intent permits recovery after CSV creation succeeded
            # but the exported-phase session update failed. Unrelated files
            # remain protected, even if their content happens to be identical.
            recovering = self.export_intent == digest and self.output.exists()
            if self.output.exists() and not recovering:
                raise ValueError("目标CSV已存在，已停止以防覆盖；请先核对已有文件")
            if recovering and hashlib.sha256(self.output.read_bytes()).hexdigest() != digest:
                raise ValueError("上次CSV写入不完整或已被更改，已保留截图，请先核查")
            temporary = self.directory / "inventory-export.tmp"
            self.directory.mkdir(parents=True, exist_ok=True)
            temporary.write_text(content, encoding="utf-8-sig", newline="")
            with temporary.open(encoding="utf-8-sig", newline="") as stream:
                if list(csv.reader(stream)) != [["道具名称", "数量"]] + [[r["name"], r["quantity"]] for r in records]:
                    raise ValueError("CSV核查失败，已保留临时截图")
            # Exclusive creation avoids overwriting an existing inventory.
            if not recovering:
                self.export_intent = digest
                self._save()
                with self.output.open("x", encoding="utf-8-sig", newline="") as stream:
                    stream.write(content)
            self.phase = "exported"
            self._save()
            temporary.unlink()
        if self.phase == "exported":
            with self.output.open(encoding="utf-8-sig", newline="") as stream:
                if list(csv.reader(stream)) != [["道具名称", "数量"]] + [[r["name"], r["quantity"]] for r in records]:
                    raise ValueError("已保存CSV与记录不符，保留临时截图，请先核查")
            targets = [self._image_path(filename) for filename in self.shots]
            targets += [self._capture_path(filename) for filename in self.capture_files]
            if any(path.exists() and not path.is_file() for path in targets):
                raise ValueError("临时截图清理目标不是文件，已停止清理")
            for path in targets:
                path.unlink(missing_ok=True)
            self.shots = []
            self.groups = []
            self.capture_files = []
            self.phase = "completed"
            self._save()
        return self.snapshot()
