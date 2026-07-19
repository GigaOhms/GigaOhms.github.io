from __future__ import annotations

import json
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request, send_from_directory
from PIL import Image, ImageOps, UnidentifiedImageError
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
IMG_DIR = BASE_DIR / "img"
DB_FILE = BASE_DIR / "projects.json"
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}

app = Flask(__name__, template_folder="templates")
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024
IMG_DIR.mkdir(exist_ok=True)


def load_projects() -> list[dict[str, Any]]:
    """
    Read all existing projects from projects.json and normalize their fields.

    Existing records are preserved. Missing IDs and invalid order values are
    repaired automatically so the admin page can always detect old projects.
    """
    if not DB_FILE.exists():
        DB_FILE.write_text("[]", encoding="utf-8")
        return []

    try:
        data = json.loads(DB_FILE.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"projects.json bị lỗi tại dòng {exc.lineno}, cột {exc.colno}: {exc.msg}"
        ) from exc
    except OSError as exc:
        raise RuntimeError(f"Không thể đọc projects.json: {exc}") from exc

    if not isinstance(data, list):
        raise RuntimeError("projects.json phải chứa một danh sách JSON [...]")

    projects: list[dict[str, Any]] = []
    changed = False

    for fallback_order, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            changed = True
            continue

        project = dict(item)

        if not str(project.get("id") or "").strip():
            project["id"] = uuid.uuid4().hex
            changed = True
        else:
            project["id"] = str(project["id"]).strip()

        try:
            order = int(project.get("order", fallback_order))
        except (TypeError, ValueError):
            order = fallback_order
            changed = True

        project["order"] = max(1, order)
        project["title"] = str(project.get("title") or "").strip()
        project["description"] = str(project.get("description") or "").strip()
        project["link"] = str(project.get("link") or "").strip()

        hashtags = project.get("hashtags", [])
        if isinstance(hashtags, str):
            hashtags = hashtags.split(",")
            changed = True
        elif not isinstance(hashtags, list):
            hashtags = []
            changed = True

        project["hashtags"] = [
            str(tag).strip().lstrip("#")
            for tag in hashtags
            if str(tag).strip().lstrip("#")
        ]

        projects.append(project)

    projects.sort(key=lambda project: int(project["order"]))

    # Keep order values continuous because image filenames depend on them.
    for order, project in enumerate(projects, start=1):
        if project["order"] != order:
            project["order"] = order
            changed = True

    if changed:
        DB_FILE.write_text(
            json.dumps(projects, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    return projects





def embed_projects_in_index(projects: list[dict[str, Any]]) -> None:
    index_file = BASE_DIR / "index.html"
    if not index_file.exists():
        return

    html = index_file.read_text(encoding="utf-8")
    json_text = json.dumps(projects, ensure_ascii=False).replace("</", "<\\/")
    block = (
        '<script id="projects-data" type="application/json">'
        + json_text
        + "</script>"
    )

    pattern = re.compile(
        r'<script id="projects-data" type="application/json">.*?</script>',
        re.DOTALL,
    )

    if pattern.search(html):
        html = pattern.sub(block, html, count=1)
    else:
        html = html.replace("<script>", block + "\n<script>", 1)

    index_file.write_text(html, encoding="utf-8")

def save_projects(projects: list[dict[str, Any]]) -> None:
    for index, project in enumerate(projects, start=1):
        project["order"] = index
    DB_FILE.write_text(
        json.dumps(projects, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    embed_projects_in_index(projects)


def image_paths_for_order(order: int) -> list[Path]:
    pattern = re.compile(rf"^img{order}(?:_(\d+))?\.png$", re.IGNORECASE)

    def sort_key(path: Path) -> tuple[int, int]:
        match = pattern.match(path.name)
        if not match:
            return (99, 99)
        child = match.group(1)
        return (0 if child is None else 1, int(child or 0))

    return sorted(
        [path for path in IMG_DIR.iterdir() if path.is_file() and pattern.match(path.name)],
        key=sort_key,
    )


def final_name(order: int, image_index: int) -> str:
    return f"img{order}.png" if image_index == 0 else f"img{order}_{image_index}.png"


def renumber_all_images(projects: list[dict[str, Any]]) -> None:
    """Rename every managed image in two phases to avoid filename collisions."""
    temp_root = IMG_DIR / f".rename_{uuid.uuid4().hex}"
    temp_root.mkdir()

    try:
        staged: dict[str, list[Path]] = {}

        for project in projects:
            project_id = project["id"]
            old_order = int(project.get("order", 0))
            files = image_paths_for_order(old_order)
            staged[project_id] = []

            project_temp = temp_root / project_id
            project_temp.mkdir()

            for index, source in enumerate(files):
                target = project_temp / f"{index}.png"
                shutil.move(str(source), str(target))
                staged[project_id].append(target)

        for new_order, project in enumerate(projects, start=1):
            for image_index, source in enumerate(staged.get(project["id"], [])):
                shutil.move(str(source), str(IMG_DIR / final_name(new_order, image_index)))
            project["order"] = new_order
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def public_project(project: dict[str, Any]) -> dict[str, Any]:
    order = int(project["order"])
    files = image_paths_for_order(order)
    images = [f"/img/{path.name}" for path in files]
    return {
        **project,
        "hashtags": project.get("hashtags", []),
        "main_image": images[0] if images else "",
        "images": images,
    }


def convert_to_png(source, destination: Path) -> None:
    """
    Preserve the original file exactly when the upload is already PNG.

    JPEG and WEBP files must be decoded because the portfolio naming convention
    requires every saved image to use the .png extension. They are converted at
    their original pixel dimensions without resizing or quality reduction.
    """
    extension = Path(source.filename or "").suffix.lower()

    try:
        # Validate the image first.
        source.stream.seek(0)
        with Image.open(source.stream) as image:
            image.verify()

        source.stream.seek(0)

        # A PNG upload is copied byte-for-byte. No re-encoding, optimization,
        # resizing, metadata stripping, or color conversion is performed.
        if extension == ".png":
            with destination.open("wb") as output:
                shutil.copyfileobj(source.stream, output)
            return

        # Other supported formats must be converted because the generated
        # filenames are required to end in .png.
        with Image.open(source.stream) as image:
            image = ImageOps.exif_transpose(image)

            save_options = {}
            icc_profile = image.info.get("icc_profile")
            if icc_profile:
                save_options["icc_profile"] = icc_profile

            if image.mode not in ("RGB", "RGBA", "L", "LA", "P"):
                image = image.convert("RGBA")

            # PNG compression is lossless. No resize or lossy quality setting.
            image.save(destination, format="PNG", **save_options)

    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValueError(
            f"File {secure_filename(source.filename)} không phải ảnh hợp lệ."
        ) from exc


@app.get("/")
def portfolio():
    """
    Synchronize projects.json into index.html whenever the user opens portfolio.

    This preserves any manual edits elsewhere in index.html and only replaces
    the embedded project-data block.
    """
    try:
        projects = load_projects()
        embed_projects_in_index(projects)
    except RuntimeError as exc:
        app.logger.error("Cannot synchronize portfolio: %s", exc)

    return send_from_directory(BASE_DIR, "index.html")


@app.get("/admin")
def admin():
    return render_template("admin.html")


@app.get("/img/<path:filename>")
def images(filename: str):
    return send_from_directory(IMG_DIR, filename)


@app.get("/<path:filename>")
def local_files(filename: str):
    """Serve local assets such as avatar and CV HTML."""
    return send_from_directory(BASE_DIR, filename)


@app.get("/api/projects")
def get_projects():
    try:
        projects = load_projects()
        return jsonify([public_project(project) for project in projects])
    except RuntimeError as exc:
        return jsonify(error=str(exc)), 500


@app.post("/api/sync-portfolio")
def sync_portfolio():
    try:
        projects = load_projects()
        embed_projects_in_index(projects)
        return jsonify(
            success=True,
            project_count=len(projects),
            message="Đã đồng bộ projects.json vào index.html.",
        )
    except RuntimeError as exc:
        return jsonify(error=str(exc)), 500


@app.post("/api/projects")
def create_project():
    projects = load_projects()
    files = request.files.getlist("images")

    if not files or not any(file.filename for file in files):
        return jsonify(error="Cần chọn ít nhất một ảnh."), 400

    for file in files:
        extension = Path(file.filename).suffix.lower()
        if extension not in ALLOWED_EXTENSIONS:
            return jsonify(error=f"Định dạng {extension or 'không xác định'} không được hỗ trợ."), 400

    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    link = request.form.get("link", "").strip()
    hashtags = [
        tag.strip().lstrip("#")
        for tag in request.form.get("hashtags", "").split(",")
        if tag.strip().lstrip("#")
    ]

    if not title or not description:
        return jsonify(error="Tên project và mô tả là bắt buộc."), 400

    try:
        requested_order = int(request.form.get("order", len(projects) + 1))
    except ValueError:
        return jsonify(error="Số thứ tự project không hợp lệ."), 400

    requested_order = max(1, min(requested_order, len(projects) + 1))

    # Preserve current images in a temporary area, insert metadata, then renumber.
    temp_upload = IMG_DIR / f".upload_{uuid.uuid4().hex}"
    temp_upload.mkdir()
    try:
        uploaded_paths = []
        for index, file in enumerate(files):
            target = temp_upload / f"{index}.png"
            convert_to_png(file, target)
            uploaded_paths.append(target)

        new_project = {
            "id": uuid.uuid4().hex,
            "order": requested_order,
            "title": title,
            "hashtags": hashtags,
            "description": description,
            "link": link,
        }

        # First stage every existing project by current order.
        staging = IMG_DIR / f".insert_{uuid.uuid4().hex}"
        staging.mkdir()
        staged_existing: dict[str, list[Path]] = {}
        try:
            for project in projects:
                project_dir = staging / project["id"]
                project_dir.mkdir()
                staged_existing[project["id"]] = []
                for index, source in enumerate(image_paths_for_order(int(project["order"]))):
                    target = project_dir / f"{index}.png"
                    shutil.move(str(source), str(target))
                    staged_existing[project["id"]].append(target)

            projects.insert(requested_order - 1, new_project)

            for order, project in enumerate(projects, start=1):
                sources = uploaded_paths if project["id"] == new_project["id"] else staged_existing[project["id"]]
                for image_index, source in enumerate(sources):
                    shutil.move(str(source), str(IMG_DIR / final_name(order, image_index)))
                project["order"] = order
        finally:
            shutil.rmtree(staging, ignore_errors=True)

        save_projects(projects)
        return jsonify(public_project(new_project)), 201
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except Exception as exc:
        return jsonify(error=f"Không thể lưu project: {exc}"), 500
    finally:
        shutil.rmtree(temp_upload, ignore_errors=True)


@app.post("/api/projects/reorder")
def reorder_projects():
    projects = load_projects()

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error="Dữ liệu kéo thả không hợp lệ."), 400

    ordered_ids = payload.get("ordered_ids")
    if not isinstance(ordered_ids, list):
        return jsonify(error="Danh sách thứ tự project không hợp lệ."), 400

    normalized_ids = [
        str(project_id).strip()
        for project_id in ordered_ids
        if str(project_id).strip()
    ]

    if len(normalized_ids) != len(set(normalized_ids)):
        return jsonify(error="Danh sách kéo thả có project bị trùng."), 400

    by_id = {
        str(project["id"]).strip(): project
        for project in projects
        if str(project.get("id", "")).strip()
    }

    if set(normalized_ids) != set(by_id):
        return jsonify(
            error="Danh sách project trên giao diện không khớp projects.json. "
                  "Hãy tải lại trang rồi thử lại."
        ), 400

    reordered = [by_id[project_id] for project_id in normalized_ids]

    try:
        renumber_all_images(reordered)
        save_projects(reordered)
        return jsonify([public_project(project) for project in reordered])
    except Exception as exc:
        app.logger.exception("Project reorder failed")
        return jsonify(error=f"Không thể đổi thứ tự: {exc}"), 500


@app.delete("/api/projects/<project_id>")
def delete_project(project_id: str):
    projects = load_projects()
    target = next((project for project in projects if project["id"] == project_id), None)
    if not target:
        return jsonify(error="Không tìm thấy project."), 404

    for path in image_paths_for_order(int(target["order"])):
        path.unlink(missing_ok=True)

    remaining = [project for project in projects if project["id"] != project_id]
    try:
        renumber_all_images(remaining)
        save_projects(remaining)
        return jsonify(success=True)
    except Exception as exc:
        return jsonify(error=f"Không thể xóa project: {exc}"), 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
