from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from flask import Flask, flash, redirect, render_template, request, session, url_for


APP_ROOT = Path(__file__).resolve().parent
DEFAULT_BASE_PATH = Path(r"D:\VSCode")
SETTINGS_FILE = APP_ROOT / "instance" / "settings.json"
DEFAULT_SETTINGS = {
    "base_path": str(DEFAULT_BASE_PATH),
    "visibility": "private",
    "github_token": "",
}
SAFE_PROJECT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    "COM1",
    "COM2",
    "COM3",
    "COM4",
    "COM5",
    "COM6",
    "COM7",
    "COM8",
    "COM9",
    "LPT1",
    "LPT2",
    "LPT3",
    "LPT4",
    "LPT5",
    "LPT6",
    "LPT7",
    "LPT8",
    "LPT9",
}
VALID_VISIBILITIES = {"private", "public"}

app = Flask(__name__, instance_relative_config=True)
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY", "quickrepo-dev-secret")


def load_settings() -> dict[str, str]:
    settings = DEFAULT_SETTINGS.copy()
    if SETTINGS_FILE.exists():
        try:
            payload = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            payload = {}
        if isinstance(payload, dict):
            for key in settings:
                value = payload.get(key)
                if isinstance(value, str):
                    settings[key] = value
    if settings["visibility"] not in VALID_VISIBILITIES:
        settings["visibility"] = DEFAULT_SETTINGS["visibility"]
    return settings


def save_settings(base_path: Path, visibility: str, github_token: str) -> None:
    try:
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(
            json.dumps(
                {
                    "base_path": str(base_path),
                    "visibility": visibility,
                    "github_token": github_token,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError as exc:
        raise RuntimeError(f"默认设置保存失败：{exc}") from exc


def normalize_base_path(raw_path: str) -> Path:
    candidate = (raw_path or str(DEFAULT_BASE_PATH)).strip()
    base_path = Path(candidate).expanduser()
    if not base_path.is_absolute():
        raise ValueError(r"目录路径必须是绝对路径，例如 D:\VSCode")
    return base_path.resolve(strict=False)


def normalize_visibility(raw_visibility: str) -> str:
    visibility = (raw_visibility or DEFAULT_SETTINGS["visibility"]).strip().lower()
    if visibility not in VALID_VISIBILITIES:
        raise ValueError("仓库可见性只能是 private 或 public。")
    return visibility


def validate_project_name(project_name: str) -> str:
    name = project_name.strip()
    if not name:
        raise ValueError("项目名称不能为空。")
    if not SAFE_PROJECT_NAME.fullmatch(name):
        raise ValueError("项目名称只支持字母、数字、点、下划线和短横线，且必须以字母或数字开头。")
    if name.upper() in WINDOWS_RESERVED_NAMES:
        raise ValueError("项目名称不能使用 Windows 保留名称。")
    if name.endswith(".git"):
        raise ValueError("项目名称不要以 .git 结尾。")
    return name


def render_home(
    *,
    form_data: dict[str, str] | None = None,
    result: dict[str, str] | None = None,
    status_code: int = 200,
):
    settings = load_settings()
    defaults = {
        "project_name": "",
        "base_path": settings["base_path"],
        "visibility": settings["visibility"],
        "github_token": settings["github_token"],
        "save_defaults": "on",
    }
    if form_data:
        defaults.update(form_data)
    return (
        render_template(
            "index.html",
            form_data=defaults,
            result=result,
            environment_token=bool(os.environ.get("GITHUB_TOKEN")),
            local_token=bool(settings["github_token"]),
            settings_file=str(SETTINGS_FILE),
        ),
        status_code,
    )


def ensure_project_folder(base_path: Path, project_name: str) -> Path:
    try:
        if base_path.exists() and not base_path.is_dir():
            raise RuntimeError("目标基础路径已存在，但不是文件夹。")

        base_path.mkdir(parents=True, exist_ok=True)
        project_dir = base_path / project_name

        if project_dir.exists():
            if not project_dir.is_dir():
                raise RuntimeError("目标项目路径已存在，但不是文件夹。")
            if any(project_dir.iterdir()):
                raise RuntimeError("目标项目文件夹已存在且非空，请换一个名称或清空目录后再试。")
        else:
            project_dir.mkdir(parents=True, exist_ok=True)

        readme_path = project_dir / "README.md"
        if not readme_path.exists():
            readme_path.write_text(f"# {project_name}\n", encoding="utf-8")

        return project_dir
    except OSError as exc:
        raise RuntimeError(f"无法创建本地项目目录：{exc}") from exc


def run_git_command(args: list[str], cwd: Path) -> None:
    completed = subprocess.run(
        args,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode == 0:
        return

    detail = (completed.stderr or completed.stdout).strip() or "未知 git 错误。"
    if "Author identity unknown" in detail or "unable to auto-detect email address" in detail:
        detail = (
            "git 提交失败，请先配置用户名和邮箱："
            'git config --global user.name "你的名字" '
            '和 git config --global user.email "you@example.com"'
        )
    raise RuntimeError(detail)


def initialize_local_repository(project_dir: Path) -> None:
    run_git_command(["git", "init"], cwd=project_dir)
    run_git_command(["git", "add", "README.md"], cwd=project_dir)
    run_git_command(["git", "commit", "-m", "first commit"], cwd=project_dir)
    run_git_command(["git", "branch", "-M", "main"], cwd=project_dir)


def github_error_message(body_text: str) -> str:
    try:
        payload = json.loads(body_text)
    except json.JSONDecodeError:
        return body_text.strip() or "未知错误"

    message = payload.get("message", "未知错误")
    errors = payload.get("errors")
    if isinstance(errors, list) and errors:
        parts = []
        for item in errors:
            if isinstance(item, dict):
                parts.append(item.get("message") or item.get("code") or json.dumps(item, ensure_ascii=False))
            else:
                parts.append(str(item))
        return f"{message} ({'; '.join(parts)})"
    return message


def create_github_repository(project_name: str, token: str, private: bool) -> dict[str, str]:
    payload = json.dumps(
        {
            "name": project_name,
            "private": private,
            "auto_init": False,
        }
    ).encode("utf-8")
    request_obj = urllib.request.Request(
        "https://api.github.com/user/repos",
        data=payload,
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "quickrepo-flask-app",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )

    try:
        with urllib.request.urlopen(request_obj, timeout=20) as response:
            response_body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        error_message = github_error_message(error_body)
        if exc.code == 401:
            raise RuntimeError("GitHub Token 无效或已过期。") from exc
        if exc.code == 403:
            raise RuntimeError(f"GitHub 拒绝了请求：{error_message}。请确认 Token 权限足够。") from exc
        if exc.code == 422:
            raise RuntimeError(f"GitHub 仓库创建失败：{error_message}。通常是同名仓库已存在。") from exc
        raise RuntimeError(f"GitHub API 调用失败（HTTP {exc.code}）：{error_message}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"无法连接 GitHub API：{exc.reason}") from exc

    payload_data = json.loads(response_body)
    return {
        "clone_url": payload_data["clone_url"],
        "html_url": payload_data["html_url"],
        "full_name": payload_data["full_name"],
    }


def push_to_remote(project_dir: Path, remote_url: str, token: str) -> None:
    run_git_command(["git", "remote", "add", "origin", remote_url], cwd=project_dir)
    auth = base64.b64encode(f"x-access-token:{token}".encode("utf-8")).decode("ascii")
    run_git_command(
        [
            "git",
            "-c",
            f"http.extraheader=Authorization: Basic {auth}",
            "push",
            "-u",
            "origin",
            "main",
        ],
        cwd=project_dir,
    )


@app.get("/")
def index():
    last_result = session.pop("last_result", None)
    return render_home(result=last_result)


@app.post("/save-settings")
def save_settings_route():
    base_path_raw = request.form.get("base_path", "")
    visibility_raw = request.form.get("visibility", DEFAULT_SETTINGS["visibility"])
    github_token = request.form.get("github_token", "").strip()
    form_data = {
        "base_path": base_path_raw,
        "visibility": visibility_raw,
        "github_token": github_token,
        "save_defaults": request.form.get("save_defaults", "on"),
    }

    try:
        base_path = normalize_base_path(base_path_raw)
        visibility = normalize_visibility(visibility_raw)
        save_settings(base_path, visibility, github_token)
    except (ValueError, RuntimeError) as exc:
        flash(str(exc), "error")
        return render_home(form_data=form_data, status_code=400)

    flash("默认设置已保存：基础路径、仓库可见性和 GitHub Token。", "success")
    return redirect(url_for("index"))


@app.post("/create-project")
def create_project():
    project_name_raw = request.form.get("project_name", "")
    base_path_raw = request.form.get("base_path", "")
    visibility_raw = request.form.get("visibility", DEFAULT_SETTINGS["visibility"])
    github_token = request.form.get("github_token", "").strip()
    save_defaults_flag = request.form.get("save_defaults") == "on"
    token = github_token or os.environ.get("GITHUB_TOKEN", "").strip()

    form_data = {
        "project_name": project_name_raw,
        "base_path": base_path_raw,
        "visibility": visibility_raw,
        "github_token": github_token,
        "save_defaults": "on" if save_defaults_flag else "",
    }

    if not token:
        flash("请填写 GitHub Token，或先设置环境变量 GITHUB_TOKEN。", "error")
        return render_home(form_data=form_data, status_code=400)

    local_ready = False
    remote_ready = False

    try:
        project_name = validate_project_name(project_name_raw)
        base_path = normalize_base_path(base_path_raw)
        visibility = normalize_visibility(visibility_raw)

        if save_defaults_flag:
            save_settings(base_path, visibility, github_token)

        project_dir = ensure_project_folder(base_path, project_name)
        initialize_local_repository(project_dir)
        local_ready = True

        repository = create_github_repository(
            project_name=project_name,
            token=token,
            private=(visibility != "public"),
        )
        remote_ready = True
        push_to_remote(project_dir, repository["clone_url"], token)

        session["last_result"] = {
            "project_name": project_name,
            "project_dir": str(project_dir),
            "remote_url": repository["clone_url"],
            "html_url": repository["html_url"],
            "full_name": repository["full_name"],
        }
        flash("项目已创建完成，本地仓库和 GitHub 远程仓库都已经初始化。", "success")
        return redirect(url_for("index"))
    except (ValueError, RuntimeError) as exc:
        if remote_ready:
            flash(f"GitHub 仓库已经创建，但推送失败：{exc}", "error")
        elif local_ready:
            flash(f"本地仓库已经初始化，但 GitHub 仓库创建失败：{exc}", "error")
        else:
            flash(str(exc), "error")
        return render_home(form_data=form_data, status_code=400)


if __name__ == "__main__":
    app.run(debug=True)
