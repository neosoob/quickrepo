# quickrepo

一个基于 Flask 的小工具页，用来一键完成这些事情：

- 在 GitHub 上创建同名仓库
- 在本地指定目录下创建同名文件夹
- 自动执行 `git init`、首次提交、绑定 `origin` 和 `git push -u origin main`
- 记住你自定义的默认基础路径、仓库可见性和 GitHub Token

## 运行

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

浏览器打开：`http://127.0.0.1:5000`

## GitHub 授权

创建远程仓库需要 GitHub Token。

- 最简单的方式：页面里直接填写 Personal Access Token
- 更方便的方式：先设置环境变量 `GITHUB_TOKEN`，页面里就可以留空
- 如果你点了“保存默认设置”，页面里的 Token 会保存到本地 `instance/settings.json`

Classic Personal Access Token 至少需要：

- `repo`

如果你使用 fine-grained token，需要确保它有创建仓库和推送内容的权限。

## 默认设置保存位置

默认基础路径、仓库可见性和 GitHub Token 会保存到本地的 `instance/settings.json`，这个目录已经加入 `.gitignore`，不会默认提交到仓库。

注意：当前实现里，Token 是以本地明文形式保存到这个文件中的，只适合你自己的开发机使用。

## 约束

项目名称会同时用作 Windows 文件夹名和 GitHub 仓库名，所以当前限制为：

- 只能使用字母、数字、点、下划线、短横线
- 必须以字母或数字开头
- 不能以 `.git` 结尾
