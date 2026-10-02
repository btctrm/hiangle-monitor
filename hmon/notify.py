"""通知：PushPlus / Server酱（微信）+ Gmail（邮件）。没配置的渠道自动跳过。"""
from __future__ import annotations

import os
import re
import smtplib
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
    return "Server酱 成功" if r.ok else f"Server酱 失败：{r.text[:120]}"


def _email(title: str, md: str) -> str:
    user, pw, to = os.environ.get("SMTP_USER"), os.environ.get("SMTP_PASS"), os.environ.get("MAIL_TO")
    if not (user and pw and to):
        return ""
    msg = MIMEText(md, "plain", "utf-8")
    msg["Subject"] = title
    msg["From"] = formataddr(("鞋子监控", user))
    msg["To"] = to
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    with smtplib.SMTP_SSL(host, int(os.environ.get("SMTP_PORT", "465")), timeout=30) as s:
        s.login(user, pw)
        s.sendmail(user, [a.strip() for a in to.split(",")], msg.as_string())
    return "邮件 成功"


def send(title: str, md: str, *, wechat: bool = True, email: bool = True, dry: bool = False) -> list[str]:
    if dry:
        print("\n======== [演练，不发送] " + title + "\n" + md + "\n========")
        return ["演练"]
    out = []
    chans = ([_pushplus, _serverchan] if wechat else []) + ([_email] if email else [])
    for fn in chans:
        try:
            r = fn(title, md)
        except Exception as e:  # 通知失败不能让监控本身崩掉
            r = f"{fn.__name__} 异常：{e}"
        if r:
            out.append(r)
    if not out:
        print("[未配置任何通知渠道] " + title + "\n" + md)
    else:
        print(title, "->", "；".join(out))
    return out
