"""Local MaaFramework OCR; no network calls and no game input actions."""
import re

from .config import ROOT, RUNTIME

# Full-resolution scroll-area bounds. Row positions are measured per image;
# partially clipped top cards are excluded from the five selected rows.
CONTENT_ROI = (24, 150, 584, 890)
PREVIEW_ROI = (24, 150, 584, 890)


class LocalOcr:
    def __init__(self):
        self._resource = None
        self._tasker = None

    def read_inventory(self, image_path, token, *, scrolling=False, prefer_last=False):
        from PIL import Image
        with Image.open(image_path) as source:
            size = source.size
        if size != (630, 1120):
            return [], {"rows": [], "status": "pending", "message": "当前网格仅验证630×1120，已保留截图"}
        header = self.read(image_path, token, roi=(24, 0, 584, 150))
        detected = self.read(image_path, token, roi=CONTENT_ROI)
        if not any(value["score"] >= .9 and value["text"].strip() == "背包" for value in header):
            return header + detected, {"rows": [], "status": "pending", "layout_valid": False,
                                       "message": "未确认背包页面，已保留截图；请返回背包后重试"}
        # Calibration uses several rows AND columns. Never promote the first row
        # with five OCR boxes to an anchor: adjacent labels may share one box.
        geometry = _grid_geometry(detected, scrolling=scrolling, prefer_last=prefer_last)
        if geometry is None:
            detail = parse_inventory(detected)
            if detail["status"] == "recognized" and len(detail["rows"]) <= 2:
                return header + detected, detail
            return header + detected, {"rows": [], "status": "pending", "layout_valid": False,
                              "message": "未能可靠定位本页5×5道具网格，已保留截图；请待画面静止后重试"}
        tokens = header + list(detected)
        rows = []
        for row, name_top in enumerate(geometry["row_name_tops"]):
            for col in range(5):
                token.check()
                name_roi = [24 + col * 116, name_top - 4, 116, 46]
                quantity_roi = [48 + col * 116, name_top - 39, 88, 34]
                # Detection + recognition supports a wrapped name. only_rec is
                # a single-line recognizer and silently loses a second line.
                name_tokens = self.read(image_path, token, roi=name_roi, scale=3)
                amount_tokens = self.read(image_path, token, roi=quantity_roi, only_rec=True)
                tokens.extend(name_tokens + amount_tokens)
                name = _cell_name(name_tokens, name_roi)
                detected_name = _cell_name(detected, name_roi)
                if name and detected_name and name != detected_name:
                    name = ""  # High confidence still does not prove correct spelling.
                amounts = _cell_amounts(amount_tokens, quantity_roi)
                corroborating = _cell_amounts(detected, quantity_roi)
                amounts |= corroborating
                rows.append({"slot": row * 5 + col + 1, "name": name,
                             "quantity": amounts.pop() if len(amounts) == 1 else ""})
        named = sum(bool(row["name"]) for row in rows)
        counted = sum(bool(row["quantity"]) for row in rows)
        return tokens, {"rows": rows, "layout": "bag_grid_5cols", "expected_cells": 25,
                        "layout_valid": True, "geometry": geometry,
                        "content_roi": list(CONTENT_ROI),
                        "status": "recognized" if named == counted == 25 else "pending",
                        "message": f"本页25格：{named}个名称、{counted}个数量已识别；已按本页位置对齐，仍需核对文字"}

    def read(self, image_path, token, *, roi=None, only_rec=False, scale=None):
        import numpy as np
        from PIL import Image
        from maa.controller import CustomController
        from maa.pipeline import JOCR
        from maa.resource import Resource
        from maa.tasker import Tasker
        from maa.toolkit import Toolkit

        model = ROOT / "assets/ocr/zh_cn"
        if not all((model / name).is_file() for name in ("det.onnx", "rec.onnx", "keys.txt")):
            raise RuntimeError("本地中文OCR模型不完整，截图已保留")
        if self._resource is None:
            Toolkit.init_option(RUNTIME / "framework")
            Tasker.set_save_draw(False)
            Tasker.set_save_on_error(False)
            Tasker.set_debug_mode(False)
            resource = token.dispatch(Resource)
            if not resource.use_cpu():
                raise RuntimeError("本地OCR CPU初始化失败")
            loaded = token.dispatch(lambda: resource.post_ocr_model(model))
            loaded.wait()
            token.check()
            if not loaded.succeeded:
                raise RuntimeError("本地OCR模型加载失败，截图已保留")
            self._resource = resource
        with Image.open(image_path) as source:
            scale = scale or (3 if only_rec else 1)
            if roi:
                x, y, width, height = roi
                source = source.crop((x, y, x + width, y + height)).resize((width * scale, height * scale))
            image = np.ascontiguousarray(np.asarray(source.convert("RGB"))[:, :, ::-1])

        class ImageController(CustomController):
            def connect(self):
                return True

            def request_uuid(self):
                return "m4b-local-ocr"

            def get_features(self):
                return 0

            def screencap(self):
                return image

            def _deny(self, *args):
                return False

            start_app = stop_app = click = swipe = touch_down = touch_move = touch_up = _deny
            click_key = input_text = key_down = key_up = _deny

        # Local image-only controller; all input operations return False.
        controller = token.dispatch(ImageController)
        connected = token.dispatch(controller.post_connection)
        connected.wait()
        token.check()
        if not connected.succeeded:
            raise RuntimeError("本地OCR图片加载失败")
        tasker = token.dispatch(Tasker)
        if not tasker.bind(self._resource, controller):
            raise RuntimeError("本地OCR任务初始化失败")
        self._tasker = tasker
        job = token.dispatch(lambda: tasker.post_recognition("OCR", JOCR(threshold=0.5, only_rec=only_rec), image))
        job.wait()
        token.check()
        detail = job.get()
        if not detail or not detail.nodes or not detail.nodes[0].recognition:
            raise RuntimeError("未取得OCR结果，截图已保留")
        recognition = detail.nodes[0].recognition
        def original_box(box):
            if not roi:
                return box
            return [roi[0] + round(box[0] / scale), roi[1] + round(box[1] / scale),
                    round(box[2] / scale), round(box[3] / scale)]
        return [{"text": result["text"], "score": float(result["score"]), "box": original_box(result["box"])}
                for result in recognition.raw_detail.get("all", [])]


QUANTITY = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:万|亿|[kKwWmM])?"
COUNT = re.compile(r"^(?:(?:拥有|持有|数量|已拥有|拥有数量|持有数量|当前拥有)(?:数量)?[：:]?\s*[xX×]?\s*)(" + QUANTITY + r")(?:个|件|份|枚|张)?$")
NAME = re.compile(r"^[\u3400-\u9fffA-Za-z][\u3400-\u9fffA-Za-z0-9·（）()\-]{1,29}$")
EXCLUDED = re.compile(r"^(?:道具类型|道具分类|类型|分类)[：:](?:活动道具|待合成|合成道具|合成材料)$")
UI_WORDS = {"背包", "道具", "道具详情", "详情", "使用", "出售", "合成", "数量", "拥有", "获得途径", "获取途径", "前往", "确定", "取消", "普通道具", "资源", "材料", "选择数量", "活动道具", "待合成", "合成道具"}


def _grid_geometry(tokens, *, scrolling=False, prefer_last=False):
    """Find the visible five-row lattice without depending on complete OCR rows.

    The supported screen has a 155 px card pitch. A human swipe changes its
    phase, so the label tops must be measured anew for each image. The whole
    card (about 117 px above its label) must clear the fixed top UI. At least
    four rows and four columns must corroborate it; sparse text is not a grid.
    """
    from statistics import median
    candidates = []
    for value in tokens:
        text, box = value["text"].strip(), value["box"]
        x, y, width, height = box
        if (value["score"] >= .9 and NAME.fullmatch(text) and text not in UI_WORDS
                and len(re.findall(r"[\u3400-\u9fff]", text)) >= 2
                and 12 <= height <= 34 and 20 <= width <= 245 and 180 <= y <= 1008):
            # Merged adjacent names do not vote for either cell. The other
            # rows/columns still establish phase, then cell OCR separates them.
            if width <= 140:
                column = min(range(5), key=lambda col: abs(x + width / 2 - (82 + col * 116)))
                if abs(x + width / 2 - (82 + column * 116)) <= 34:
                    candidates.append((y, column))
    origins = {y - row * 155 for y, _ in candidates for row in range(5)
               if (189 if scrolling else 267) <= y - row * 155 <= 373}
    choices = []
    for origin in origins:
        hits = [[] for _ in range(5)]
        for y, col in candidates:
            row = round((y - origin) / 155)
            if 0 <= row < 5 and abs(y - (origin + row * 155)) <= 9:
                hits[row].append((y, col))
        counts = [len({col for _, col in values}) for values in hits]
        columns = {col for values in hits for _, col in values}
        # Do not silently shift down because the first row has fewer OCR boxes.
        # If it has no usable evidence at all, leave the page pending.
        if counts[0] < 2 or sum(count >= 3 for count in counts) < 4 or len(columns) < 4:
            continue
        phase = median(y - row * 155 for row, values in enumerate(hits) for y, _ in values)
        positions = [round(median(y for y, _ in values)) if values else round(phase + row * 155)
                     for row, values in enumerate(hits)]
        if any(top - (39 if scrolling else 117) < 150 or top + 42 > 1040 for top in positions):
            continue
        deviation = sum(abs(y - (phase + row * 155)) for row, values in enumerate(hits) for y, _ in values)
        choices.append((sum(counts), -deviation, phase, hits, counts, columns))
    if not choices:
        return None
    if prefer_last:
        _, _, phase, hits, counts, columns = max(choices, key=lambda value: (value[2], value[0], value[1]))
    else:
        _, _, phase, hits, counts, columns = max(choices, key=lambda value: (value[0], value[1], -value[2]))
    tops = [round(median(y for y, _ in values)) if values else round(phase + row * 155)
            for row, values in enumerate(hits)]
    if any(top - (39 if scrolling else 117) < 150 or top + 42 > 1040 for top in tops):
        return None
    return {"row_name_tops": tops, "pitch": 155, "support_columns": sorted(columns),
            "row_support": counts, "method": "multi_row_column_consensus"}


def _inside(value, roi):
    x, y, width, height = value["box"]
    return (roi[0] <= x and x + width <= roi[0] + roi[2]
            and roi[1] <= y and y + height <= roi[1] + roi[3])


def _cell_name(tokens, roi):
    values = [value for value in tokens if value["score"] >= .9 and _inside(value, roi)
              and re.fullmatch(r"[\u3400-\u9fffA-Za-z][\u3400-\u9fffA-Za-z0-9·（）()\-]{0,29}", value["text"].strip())
              and value["text"].strip() not in UI_WORDS]
    if not values:
        return ""
    lines = []
    for value in sorted(values, key=lambda item: (item["box"][1], item["box"][0])):
        if not lines or abs(value["box"][1] - lines[-1][0]["box"][1]) > 9:
            lines.append([value])
        else:
            lines[-1].append(value)
    if len(lines) > 2:
        return ""
    pieces = []
    for line in lines:
        ordered = sorted(line, key=lambda item: item["box"][0])
        # Overlapping alternatives are competing recognitions, not word parts.
        if any(left["box"][0] + left["box"][2] > right["box"][0] + 2
               for left, right in zip(ordered, ordered[1:])):
            return ""
        pieces.extend(item["text"].strip() for item in ordered)
    name = "".join(pieces)
    return name if NAME.fullmatch(name) else ""


def _cell_amounts(tokens, roi):
    return {value["text"].strip() for value in tokens if value["score"] >= .9
            and re.fullmatch(QUANTITY, value["text"].strip()) and _inside(value, roi)}


def _parse_grid(tokens, image_size):
    if tuple(image_size or ()) != (630, 1120) or not any(value["text"] == "背包" for value in tokens):
        return None
    geometry = _grid_geometry(tokens)
    if geometry is None:
        return {"rows": [], "status": "pending", "layout_valid": False,
                "message": "网格位置证据不足，已保留截图待核对"}
    rows = []
    for row, top in enumerate(geometry["row_name_tops"]):
        for col in range(5):
            amounts = _cell_amounts(tokens, [48 + col * 116, top - 39, 88, 34])
            rows.append({"slot": row * 5 + col + 1,
                         "name": _cell_name(tokens, [24 + col * 116, top - 4, 116, 46]),
                         "quantity": amounts.pop() if len(amounts) == 1 else ""})
    named = sum(bool(row["name"]) for row in rows)
    counted = sum(bool(row["quantity"]) for row in rows)
    return {"rows": rows, "layout": "bag_grid_5cols", "expected_cells": 25,
            "layout_valid": True, "geometry": geometry,
            "status": "recognized" if named == counted == 25 else "pending",
            "message": f"本页25格：{named}个名称、{counted}个数量已识别，位置按本页网格保留"}


def parse_inventory(tokens, *, image_size=None):
    """Conservative labeled name/count rows; ambiguous screens stay pending."""
    ordered = sorted(tokens, key=lambda value: (value["box"][1], value["box"][0]))
    # Merely visible tab labels do not establish the active category.
    if any(EXCLUDED.fullmatch(re.sub(r"\s+", "", value["text"])) for value in ordered):
        return {"rows": [], "status": "excluded", "message": "识别到活动/合成类别，本图暂不统计"}
    grid = _parse_grid(ordered, image_size)
    if grid:
        return grid
    rows = []
    used_names = set()
    counts = [value for value in ordered if COUNT.fullmatch(re.sub(r"\s+", "", value["text"]))]
    for index, value in enumerate(ordered):
        text = re.sub(r"\s+", "", value["text"])
        count = COUNT.fullmatch(text)
        if not count or value["score"] < 0.9:
            continue
        # Only explicitly labeled names are safe before a game layout is calibrated.
        candidates = []
        for previous in ordered:
            name_match = re.fullmatch(r"(?:道具名称|名称)[：:](.+)", re.sub(r"\s+", "", previous["text"]))
            if name_match and NAME.fullmatch(name_match[1]) and previous["score"] >= 0.9:
                distance = value["box"][1] - previous["box"][1]
                if -10 <= distance <= 180:
                    candidates.append((distance, name_match[1]))
        # A detail panel can have an unlabeled title plus an explicitly labeled count.
        # Accept only a unique short title; multiple possible names stay pending.
        if not candidates and len(counts) == 1:
            titles = []
            for previous in ordered:
                name = re.sub(r"\s+", "", previous["text"])
                distance = value["box"][1] - previous["box"][1]
                if (15 <= distance <= 300 and NAME.fullmatch(name) and name not in UI_WORDS
                        and not re.search(r"使用后|可获得|用于|点击|选择|解锁|等级|战力|钻石|金币", name)
                        and previous["score"] >= 0.95):
                    titles.append((distance, name))
            if len(titles) == 1:
                candidates = titles
        if not candidates:
            continue
        candidates.sort()
        if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
            continue
        name = candidates[0][1]
        if name not in used_names:
            rows.append({"name": name, "quantity": count[1]})
            used_names.add(name)
    complete = bool(rows) and len(rows) == len(counts)
    return {"rows": rows, "status": "recognized" if complete else "pending",
            "message": "OCR已提取，请核对名称和数量" if complete else "OCR已运行，名称/数量无法完整可靠配对，截图保留待核对"}
