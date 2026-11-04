"""通知：PushPlus / Server酱（微信）+ Gmail（邮件）。没配置的渠道自动跳过。"""
from __future__ import annotations

import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

import requests


def _pushplus(title: str, md: str) -> str:
    tok = os.environ.get("PUSHPLUS_TOKEN")
    if not tok:
        return ""
    r = requests.post(
        "https://www.pushplus.plus/send",
        json={"token": tok, "title": title[:100], "content": md, "template": "markdown"},
        timeout=20,
    )
    ok = r.ok and r.json().get("code") == 200
    return "PushPlus 成功" if ok else f"PushPlus 失败：{r.text[:120]}"


def _serverchan(title: str, md: str) -> str:
    key = os.environ.get("SERVERCHAN_KEY")
    if not key:
        return ""
    m = re.match(r"sctp(\d+)t", key)
    host = f"https://{m.group(1)}.push.ft07.com/send/{key}.send" if m else f"https://sctapi.ftqq.com/{key}.send"
    r = requests.post(host, data={"title": title[:32], "desp": md}, timeout=20)
    try:
        ok = r.ok and r.json().get("code") == 0
    except ValueError:
        ok = False
    return "Server酱 成功" if ok else f"Server酱 失败：{r.text[:120]}"


def _email(title: str, md: str, html: str | None = None) -> str:
    user, pw, to = os.environ.get("SMTP_USER"), os.environ.get("SMTP_PASS"), os.environ.get("MAIL_TO")
    if not (user and pw and to):
        return ""
    if html:
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(md, "plain", "utf-8"))
        msg.attach(MIMEText(html, "html", "utf-8"))
    else:
        msg = MIMEText(md, "plain", "utf-8")
    msg["Subject"] = title
    msg["From"] = formataddr(("鞋子监控", user))
    msg["To"] = to
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    with smtplib.SMTP_SSL(host, int(os.environ.get("SMTP_PORT", "465")), timeout=30) as s:
        s.login(user, pw)
        s.sendmail(user, [a.strip() for a in to.split(",")], msg.as_string())
    return "邮件 成功"


def md_to_html(md: str) -> str:
    """把推送用的简单 Markdown（### 标题、- **键**：值、---、链接）转成邮件 HTML，手机上也好读。"""
    import html as _h

    out = ["<div style='font-family:-apple-system,Helvetica,Arial,sans-serif;font-size:15px;line-height:1.6;color:#222'>"]
    in_list = False
    for line in md.splitlines():
        t = _h.escape(line.strip())
        t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
        t = re.sub(r"(https?://[^\s<]+)", r"<a href='\1'>\1</a>", t)
        if t.startswith("- "):
            if not in_list:
                out.append("<ul style='padding-left:18px;margin:6px 0'>")
                in_list = True
            out.append(f"<li style='margin:3px 0'>{t[2:]}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        if t.startswith("### "):
            out.append(f"<h3 style='margin:14px 0 6px;font-size:17px'>{t[4:]}</h3>")
        elif t == "---":
            out.append("<hr style='border:none;border-top:1px solid #ddd;margin:14px 0'>")
        elif t:
            out.append(f"<p style='margin:6px 0'>{t}</p>")
    if in_list:
        out.append("</ul>")
    out.append("</div>")
    return "".join(out)


def send(title: str, md: str, *, wechat: bool = True, email: bool = True, dry: bool = False, html: str | None = None) -> list[str]:
    if dry:
        print("\n======== [演练，不发送] " + title + "\n" + md + "\n========")
        return ["演练"]
    out = []
    html = html or md_to_html(md)  # 邮件一律发 HTML，不再露出 ### 和 ** 符号
    chans = ([_pushplus, _serverchan] if wechat else []) + ([_email] if email else [])
    for fn in chans:
        try:
            r = fn(title, md, html) if fn is _email else fn(title, md)
        except Exception as e:  # 通知失败不能让监控本身崩掉
            r = f"{fn.__name__} 异常：{e}"
        if r:
            out.append(r)
    if not out:
        print("[未配置任何通知渠道] " + title + "\n" + md)
    else:
        print(title, "->", "；".join(out))
    return out


def delivered(results) -> bool:
    """至少一个渠道发送成功（演练也算）。"""
    return any(r == "演练" or str(r).endswith("成功") for r in (results or []))


def failures(results) -> list[str]:
    return [str(r) for r in (results or []) if not (r == "演练" or str(r).endswith("成功"))]
