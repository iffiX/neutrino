"""The shared voice of the client's commands, in the client's own language.

The resident answers with typed ``{"code", "params"}`` refusals and state
tokens; every surface words them itself, and this file is where the
terminal surface keeps its tables, one per language the client offers. The
language is the one the client keeps in its store, else the machine's own.
The one way these commands ask the resident lives here too: over the
control socket, as whoever ran them, with ``client_not_running`` when
nothing answers.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import getpass
import os
import re
import sys
import time

from neutrino_client.constants import (
    CLIENT_DEFAULT_LANGUAGE,
    CLIENT_HOLD_TIMEOUT_S,
    CLIENT_LANGUAGES,
    CLIENT_STATE_FILE_NAME,
)
from neutrino_client.control import client
from neutrino_client.control.easytier_socket import ask_easytier_daemon
from neutrino_client.core.client_hold import VERB_HOLD, VERB_HOLDER
from neutrino_client.exceptions import PlatformUnsupportedError
from neutrino_client.platforms.detect import detect_platform
from neutrino_client.services.store import ClientServiceStore

CLIENT_LANGUAGE_CHINESE = "zh-CN"
# How often a command looks again at a job it started, and how long it
# waits for one.
CLIENT_JOB_POLL_S = 0.2
CLIENT_JOB_WAIT_S = 300

# What each typed refusal or failure code says on this surface, by language.
CLIENT_CODE_WORDS = {
    "en": {
        "client_not_running": ("The client is not running; start it with nclient gui."),
        "resident_not_running": (
            "The client is not running; start it with nclient gui."
        ),
        "busy": "the client is still handling the last request",
        "crashed": "the last request failed on this machine",
        "root_refused": "nclient runs as a person, never as root",
        "bundle_missing": "this install carries no {binary}; reinstall the client",
        "unknown_terminal": "the hub offers no terminal on {device_id}",
        "permission_denied": "the hub gives this client no {kind} permission",
        "agent_offline": "{device} is offline",
        "connect_failed": "the hub could not reach that service ({reason})",
        "connect_limit": (
            "this client has too many connections open through the hub ({limit})"
        ),
        "port_not_published": "that machine does not publish port {port} now",
        "admission_paused": (
            "the hub has paused new joins; this client tries again in "
            "{retry_after_s} s"
        ),
        "control_unavailable": "The hub is busy and did not answer; try again.",
        "shell_unknown": "the hub no longer has that terminal open",
        "terminal_input_failed": (
            "the client ended this terminal: its keys could not be read ({detail})"
        ),
        "terminal_account_missing": (
            "No account is enabled for this machine's terminal; enable one on its "
            "machine page."
        ),
        "account_not_enabled": (
            "{account} is not enabled for this machine's terminal."
        ),
        "key_missing": (
            "The SSH server of {account} has no key from the hub; apply the module "
            "again."
        ),
        "op_unknown": "This agent cannot do {op} on files.",
        "session_not_owned": "this session belongs to someone else and is not shared",
        "session_unknown": "the machine no longer keeps this session",
        "account_unknown": "that machine has no account {account}",
        "shell_program_unusable": "that machine cannot run {path}",
        "kind_unknown": "the hub is too old to open this; update the hub",
        "overlay_daemon_down": (
            "the virtual network service is not running on this machine; "
            "reinstall the client"
        ),
        "overlay_not_authorized": (
            "joining the virtual network was not authorized on this machine"
        ),
        "overlay_other_network": (
            "this machine is on another virtual network; leave it first to join "
            "{network}"
        ),
        "overlay_join_failed": "joining the virtual network failed: {detail}",
        "overlay_leave_failed": "leaving the virtual network failed: {detail}",
        "overlay_network_invalid": (
            "the hub named a virtual network this client cannot use"
        ),
        "overlay_peer_invalid": (
            "the hub named an address this client cannot connect to"
        ),
        "overlay_secret_missing": (
            "the virtual network's secret did not arrive; try again"
        ),
        "overlay_restart_failed": (
            "the virtual network service could not be restarted"
        ),
        "overlay_console_invalid": (
            "the hub named an EasyTier console this client cannot use"
        ),
        "overlay_request_invalid": (
            "the virtual network service did not understand the request; update "
            "the client"
        ),
        "overlay_missing": "this hub publishes no virtual network",
        "overlay_no_address": (
            "the virtual network gave this machine no address in time"
        ),
        "overlay_hub_unreachable": (
            "the hub did not answer through the virtual network in time"
        ),
        "overlay_engine_stopped": "the virtual network stopped",
        "overlay_withdrawn": "the hub no longer offers {network}",
        "clipboard_unreadable": "the clipboard could not be read: {detail}",
        "clipboard_unwritable": "the clipboard could not be written: {detail}",
        "web_token_missing": "the hub sent no token for this page; try again",
        "port_taken": (
            "local port {port} is in use; give this entry another with nclient "
            "app set"
        ),
        "local_port_invalid": "give a port from 1024 to 65535, not {port}",
        "app_in_use": "stop the app first: nclient app stop",
        "unknown_app": "this client has no such app",
        "setting_value_unknown": (
            "{name} does not take {value}; see nclient settings show"
        ),
        "ticket_spent": (
            "the hub refused this link; it was used already or has expired, "
            "so leave this hub and join with a fresh link"
        ),
        "mount_not_authorized": "mounting was not authorized on this machine",
        "mount_timed_out": (
            "the system did not finish the mount in ten minutes; mount again"
        ),
        "mount_tooling_missing": "the mount tooling is missing on this machine",
        "pkexec_missing": (
            "this machine has no pkexec, which a mount goes through; install pkexec "
            "and mount again"
        ),
        "control_peer_refused": "the running client belongs to another account",
        "control_socket_unavailable": (
            "this session has no place for the client's socket"
        ),
        "control_channel_closed": "the client stopped answering; open it again",
        "client_internal": "the client hit an unexpected error; check its log",
        "client_disabled": "the hub has switched this client off",
        "link_missing": "paste the link from the hub's Clients page",
        "link_unreadable": (
            "that is not an enrollment link; copy the whole line from the hub"
        ),
        "link_incomplete": "that link carries no hub address and token",
        "link_not_for_client": "that link is for a device agent, not for a client",
        "enroll_refused": (
            "the hub refused this link; it may have expired, so generate a fresh one"
        ),
        "enroll_no_token": "the hub sent no token back",
        "hub_refused": "the hub refused this client's token",
        "hub_untrusted": (
            "The hub's key does not match; if it was reset, join it again."
        ),
        "hub_key_missing": (
            "This binding is from 0.5 and the hub no longer moves it; join the hub "
            "again with a new link."
        ),
        "binding_unknown": (
            "this hub no longer knows this client; join it again with a new link"
        ),
        "role_mismatch": "the hub says this binding is not a client's",
        "hello_invalid": (
            "the hub could not read this client's hello; update the client"
        ),
        "unknown_hub": "this client has not joined that hub",
        "ambiguous_hub": (
            "this client has joined several hubs; name one with --hub: {hubs}"
        ),
        "no_exit_hub": "the AI tools can only point at a connected hub",
        "hub_unreachable": "the hub cannot be reached",
        "hub_reply_unreadable": "the hub sent a reply this client could not read",
        "protocol_too_old": (
            "this client speaks protocol {peer}; the hub accepts {min} and up, "
            "so update the client"
        ),
        "protocol_too_new": (
            "this client speaks protocol {peer}; the hub speaks {hub}, "
            "so update the hub first"
        ),
        "no_endpoint": "the hub has not granted this client a key yet",
        "ai_tools_managed": (
            "This is a managed device: set its AI tools on the hub's panel, "
            "on its machine page."
        ),
        "mountpoint_not_empty": "that folder is not empty",
        "share_login_rejected": (
            "the share rejected the user name or password; mount it again and "
            "enter them again"
        ),
        "share_access_denied": (
            "the share refused this login: the password is wrong, or this "
            "account may not use the share"
        ),
        "share_not_found": "the host has no share by this name",
        "share_unreachable": (
            "the host cannot be reached; mounting is tried again shortly"
        ),
        "share_session_conflict": (
            "Windows already holds a connection to this server under another "
            "login; disconnect it first"
        ),
        "mountpoint_in_use": "another share is already set to mount at {path}",
        "credentials_missing": (
            "the saved login is gone; mount the share again and enter it"
        ),
        "fs_refused": "this account may not use that folder",
        "client_held": (
            "{account}'s client is running on this machine; one person's client "
            "runs at a time"
        ),
        "files_adapter_in_use": (
            "the files adapter is in use by another account on this machine; the "
            "mount is tried again once that account's client has quit"
        ),
        "files_adapter_unavailable": (
            "the files adapter could not start: {detail}; check the "
            "NeutrinoClientFiles service"
        ),
        "mountpoint_invalid": "give a folder under your home, like ~/remote/share",
        "mountpoint_not_drive_letter": "give an unused drive letter, like N:",
        "service_unknown": "the hub no longer publishes that service",
        "rdp_not_shared": "that desktop is not shared any more",
        "vault_locked": (
            "the hub's vault is locked, so it cannot open this client's key"
        ),
        "rdp_no_desktop": "this session has no screen to open a viewer on",
        "rdp_launch_failed": "the RustDesk viewer could not be started: {detail}",
        "rdp_no_address": "that machine published no address to connect to",
        "rdp_viewer_open": ("a viewer is already open on this desktop; close it first"),
        "unsupported_platform": "this machine cannot do this",
        "gui_webkitgtk_missing": (
            "the window needs WebKitGTK; install it: sudo apt install {packages}"
        ),
        "gui_webview2_missing": (
            "the window needs {runtime}; install it and try again"
        ),
        "gui_wkwebview_missing": (
            "the window needs pyobjc; install it: pip install {packages}"
        ),
        "ssh_entry_unknown": "{machine} offers no SSH for {account}",
        "ssh_key_unwritable": "the SSH key for {machine} could not be written: {detail}",
        "transport_missing": (
            "this install carries no neutrino_transport; reinstall the client"
        ),
        "transport_unavailable": (
            "the client's transport is not running; quit the client and start it "
            "again"
        ),
        "rdp_nobody_seated": "nobody is at that machine's screen",
        "rdp_screen_not_allowed": "that machine does not let its screen be shared yet",
        "unknown_request": "the client does not know this request",
    },
    CLIENT_LANGUAGE_CHINESE: {
        "client_not_running": "客户端没有运行，先 nclient gui。",
        "resident_not_running": "客户端没有运行，先 nclient gui。",
        "busy": "仍在处理上一个请求",
        "crashed": "上一个请求在这台机器上失败了",
        "root_refused": "nclient 以你自己的身份运行，不能用 root",
        "bundle_missing": "此安装未包含 {binary}，请重新安装客户端",
        "unknown_terminal": "中枢没有提供 {device_id} 的终端",
        "permission_denied": "中枢没有给这个客户端 {kind} 权限",
        "agent_offline": "{device} 不在线",
        "connect_failed": "中枢连不上那个服务（{reason}）",
        "connect_limit": "这个客户端经中枢开着的连接太多了（{limit}）",
        "port_not_published": "那台机器现在没有发布 {port} 端口",
        "admission_paused": "中枢暂停了新的加入；本客户端 {retry_after_s} 秒后再试",
        "control_unavailable": "中枢正忙，没有应答，稍后再试。",
        "shell_unknown": "中枢那边已经没有这个终端了",
        "terminal_input_failed": "客户端结束了这个终端：读不到它的按键（{detail}）",
        "terminal_account_missing": (
            "这台机器的终端没有启用的账户，到它的机器页上启用一个。"
        ),
        "account_not_enabled": "这台机器的终端没有启用 {account}。",
        "key_missing": "{account} 的 SSH 服务器没有中枢发的钥匙，重新应用这个模块。",
        "op_unknown": "这个被控端不能对文件做 {op}。",
        "session_not_owned": "这个会话属于别人，且没有共享",
        "session_unknown": "那台机器已不再保留这个会话",
        "account_unknown": "那台机器上没有账户 {account}",
        "shell_program_unusable": "那台机器无法运行 {path}",
        "kind_unknown": "中枢版本太旧，打不开这个；请先更新中枢",
        "overlay_daemon_down": "本机的虚拟网服务没有运行；请重新安装客户端",
        "overlay_not_authorized": "本机没有授权加入虚拟网",
        "overlay_other_network": "本机已在另一个虚拟网里；先离开它再加入 {network}",
        "overlay_join_failed": "加入虚拟网失败：{detail}",
        "overlay_leave_failed": "离开虚拟网失败：{detail}",
        "overlay_network_invalid": "非法虚拟网名称：中枢给出的名称本客户端不能使用",
        "overlay_peer_invalid": "非法碰头点：中枢给出的地址本客户端连不上",
        "overlay_secret_missing": "虚拟网的密钥没有送到；请再试一次",
        "overlay_restart_failed": "虚拟网服务无法重启",
        "overlay_console_invalid": (
            "非法控制台地址：中枢给出的 EasyTier 控制台本客户端用不了"
        ),
        "overlay_request_invalid": ("非法请求：虚拟网服务看不懂这个请求；请更新客户端"),
        "overlay_missing": "这台中枢没有发布虚拟网",
        "overlay_no_address": "虚拟网没有及时给本机分配地址",
        "overlay_hub_unreachable": "中枢没有及时经虚拟网应答",
        "overlay_engine_stopped": "虚拟网停了",
        "overlay_withdrawn": "中枢不再提供 {network}",
        "clipboard_unreadable": "读不到剪贴板：{detail}",
        "clipboard_unwritable": "写不进剪贴板：{detail}",
        "web_token_missing": "中枢没有给出这个网页的令牌；请再试一次",
        "port_taken": "本机端口 {port} 已被占用，用 nclient app set 给这个入口换一个",
        "local_port_invalid": "端口要在 1024 到 65535 之间，{port} 不行",
        "app_in_use": "先停止这个应用：nclient app stop",
        "unknown_app": "这个客户端没有这个应用",
        "setting_value_unknown": "{name} 不能设成 {value}，看 nclient settings show",
        "ticket_spent": (
            "中枢拒绝了这个链接：它已被用过或已过期；请离开这台中枢，用新链接重新加入"
        ),
        "mount_not_authorized": "这台机器上的挂载未获授权",
        "mount_timed_out": "系统十分钟内没有完成挂载，再挂载一次",
        "mount_tooling_missing": "这台机器上缺少挂载工具",
        "pkexec_missing": "这台电脑没有 pkexec，挂载要经过它；请安装 pkexec 后再挂载",
        "control_peer_refused": "正在运行的客户端属于另一个账户",
        "control_socket_unavailable": "客户端在这个会话里启动不了",
        "control_channel_closed": "客户端不再应答，请重新打开它",
        "client_internal": "客户端遇到意外错误，请查看它的日志",
        "client_disabled": "中枢已关闭此客户端",
        "link_missing": "粘贴中枢客户端页面上的链接",
        "link_unreadable": "这不是加入链接，请从中枢复制整行",
        "link_incomplete": "此链接不带中枢地址和令牌",
        "link_not_for_client": "这是设备被控端的链接",
        "enroll_refused": "中枢拒绝了这个链接，它可能已过期，请重新生成一个",
        "enroll_no_token": "中枢没有返回令牌",
        "hub_refused": "中枢拒绝了此客户端的令牌",
        "hub_untrusted": "中枢的密钥对不上；中枢重置过的话就重新加入。",
        "hub_key_missing": "这份绑定来自 0.5，中枢已不再迁移；用新链接重新加入中枢。",
        "binding_unknown": "这台中枢已不再认识这个客户端，请用新链接重新加入",
        "role_mismatch": "中枢说这不是客户端的链接",
        "hello_invalid": "非法握手：中枢读不懂这个客户端，请更新客户端",
        "unknown_hub": "此客户端没有加入那台中枢",
        "ambiguous_hub": "已加入多台中枢，用 --hub 指明其中一台：{hubs}",
        "no_exit_hub": "AI 工具只能指向已连接的中枢",
        "hub_unreachable": "连接不上中枢",
        "hub_reply_unreadable": "客户端读不懂中枢的应答",
        "protocol_too_old": (
            "此客户端使用协议 {peer}，中枢接受 {min} 及以上，请升级客户端"
        ),
        "protocol_too_new": "此客户端使用协议 {peer}，中枢使用 {hub}，请先升级中枢",
        "no_endpoint": "中枢还没有给你密钥",
        "ai_tools_managed": (
            "这是已管理的设备，请到中枢面板它的机器页上设置它的 AI 工具。"
        ),
        "mountpoint_not_empty": "那个文件夹不是空的",
        "share_login_rejected": "用户名或密码不对，重新挂载并重新填写。",
        "share_access_denied": "登录被拒绝：密码不对，或者这个账号不能用这个共享。",
        "share_not_found": "主机上没有这个共享。",
        "share_unreachable": "连不上主机，稍后会再试挂载。",
        "share_session_conflict": (
            "Windows 已经用另一个账号连着这台服务器，先断开那个连接。"
        ),
        "mountpoint_in_use": "另一个共享已设为挂载到 {path}",
        "credentials_missing": "保存的登录信息已丢失，重新挂载并重新填写",
        "fs_refused": "此账户不能使用那个文件夹",
        "client_held": (
            "{account} 的客户端正在这台电脑上运行；一台电脑同一时间只运行一个人的客户端"
        ),
        "files_adapter_in_use": (
            "文件适配器正被这台电脑上的另一个账户使用；那个账户的客户端退出后会再试挂载"
        ),
        "files_adapter_unavailable": (
            "文件适配器无法启动：{detail}；检查 NeutrinoClientFiles 服务"
        ),
        "mountpoint_invalid": (
            "非法挂载路径：请填家目录下的文件夹，例如 ~/remote/share"
        ),
        "mountpoint_not_drive_letter": "请填一个空闲盘符，例如 N:",
        "service_unknown": "中枢已不再发布那个服务",
        "rdp_not_shared": "那个桌面已不再共享",
        "vault_locked": "中枢的保险库已锁定，取不到此客户端的密钥",
        "rdp_no_desktop": "此会话没有可供查看器打开的屏幕",
        "rdp_launch_failed": "RustDesk 查看器启动不了：{detail}",
        "rdp_no_address": "那台机器没有发布可连接的地址",
        "rdp_viewer_open": "这台桌面已经开着一个查看器，请先关掉它",
        "unsupported_platform": "这台机器不支持此操作",
        "gui_webkitgtk_missing": (
            "窗口需要 WebKitGTK，请安装：sudo apt install {packages}"
        ),
        "gui_webview2_missing": "窗口需要 {runtime}，请安装后再试",
        "gui_wkwebview_missing": "窗口需要 pyobjc，请安装：pip install {packages}",
        "ssh_entry_unknown": "{machine} 没有给 {account} 开 SSH",
        "ssh_key_unwritable": "{machine} 的 SSH 钥匙写不进去：{detail}",
        "transport_missing": "这份安装缺少 neutrino_transport，重新安装客户端",
        "transport_unavailable": "客户端的传输进程没有运行，退出客户端再重新打开",
        "rdp_nobody_seated": "那台机器的屏幕前没有人",
        "rdp_screen_not_allowed": "那台机器还不允许共享屏幕",
        "unknown_request": "客户端不认识这个请求",
    },
}

# Codes worded through their params' own detail text when they carry one.
CLIENT_DETAIL_CODES = (
    "switch_failed",
    "reconcile_failed",
    "mount_failed",
    "unmount_failed",
    "forward_failed",
)

# The state tokens a row reports, by language.
CLIENT_STATE_WORDS = {
    "en": {
        "installed": "ready",
        "absent": "not installed",
        "failed": "failed",
        "unknown": "waiting for the client",
        "replaced": "another client took this connection",
        "on": "on",
        "joining": "joining",
        "leaving": "leaving",
    },
    CLIENT_LANGUAGE_CHINESE: {
        "installed": "就绪",
        "absent": "未安装",
        "failed": "失败",
        "unknown": "正在等待客户端",
        "replaced": "已被另一个客户端取代",
        "on": "已加入",
        "joining": "加入中",
        "leaving": "离开中",
    },
}

# Where a mount record stands, by language; a failed record is worded by
# its code.
CLIENT_MOUNT_STATE_WORDS = {
    "en": {
        "queued": "waiting for the client",
        "mounting": "mounting",
        "pending": "waiting to mount",
        "mounted": "mounted",
        "unmounting": "unmounting",
        "detached": "not mounted",
        "failed": "failed",
    },
    CLIENT_LANGUAGE_CHINESE: {
        "queued": "正在等待客户端",
        "mounting": "挂载中",
        "pending": "等待挂载",
        "mounted": "已挂载",
        "unmounting": "卸载中",
        "detached": "未挂载",
        "failed": "失败",
    },
}

# Every other line a command prints, by language.
CLIENT_LINES = {
    "en": {
        "not_joined": "this client has joined no hub",
        "quit_asked": "asked the client to quit",
        "nothing_changed": "nothing changed",
        "no_terminal": (
            "error: no terminal to answer on; run it again with --yes to go "
            "ahead without asking"
        ),
        "exec_command_missing": (
            "name the command after --, like: nclient terminal exec <machine> -- "
            "uptime"
        ),
        "session_ambiguous": (
            "several sessions on {machine} start with {prefix}; give more of the id:"
        ),
        "joined": "joined {url}; connecting",
        "link_prompt": "paste the enrollment link: ",
        "leave_question": "leave {hub}? Its forwards, mounts and viewers end [y/N] ",
        "left": "left {hub}",
        "panel_opening": "opening the panel of {hub}",
        "unknown_name": "no {what} named {name}; there are: {names}",
        "unknown_name_none": "no {what} named {name}; there are none",
        "ambiguous_name": "{name} names more than one {what}; say which: {names}",
        "what_machine": "machine",
        "what_hub": "hub",
        "what_app": "app",
        "what_share": "share",
        "what_entry": "entry",
        "what_account": "account",
        "what_setting": "setting",
        "opening": "opening {address}",
        "stopped": "stopped {app}",
        "port_value_invalid": "give --port as <entry>=<port>, not {value}",
        "port_missing": "name at least one --port <entry>=<port>",
        "in_use": "in use",
        "not_in_use": "not in use",
        "yes": "yes",
        "no": "no",
        "none": "-",
        "source_module": "module",
        "source_declared": "declared",
        "source_manual": "manual",
        "kind_web": "web",
        "kind_port": "port",
        "kind_ssh": "ssh",
        "kind_file": "file",
        "unhealthy": "not reachable now",
        "ask_user": "User name for {share}: ",
        "ask_password": "Password for {share}: ",  # scan: allow
        "user_missing": "a declared share needs a user name",
        "ai_hub": "the hub's",
        "ai_own": "its own",
        "ai_switching": "switching the tools",
        "ai_none": "no hub publishes an AI gateway to this client",
        "ai_set": "the tools point at {address}",
        "rdp_open": "viewer open",
        "rdp_opening": "opening the viewer on {machine}",
        "rdp_nobody": "nobody at the screen",
        "on": "on",
        "off": "off",
        "ssh_config_absent": "{path} is not written yet",
        "ssh_installed": "added Include ~/.ssh/neutrino_config to ~/.ssh/config",
        "ssh_uninstalled": ("took Include ~/.ssh/neutrino_config out of ~/.ssh/config"),
        "session_flags_missing": "name --persist on|off, --share on|off, or both",
        "terminal_none": "{machine} keeps no session",
        "terminal_session": "SESSION",
        "terminal_account": "ACCOUNT",
        "terminal_open_for": "OPEN",
        "terminal_persistent": "PERSISTENT",
        "terminal_shared": "SHARED",
        "terminal_attached": "ATTACHED",
        "see_help": "see {command} -h",
    },
    CLIENT_LANGUAGE_CHINESE: {
        "not_joined": "这个客户端还没有加入中枢",
        "quit_asked": "已请客户端退出",
        "nothing_changed": "没有改动",
        "no_terminal": "错误：没有终端可以回答；加上 --yes 再运行一次就不再确认",
        "exec_command_missing": (
            "在 -- 后面写命令，例如：nclient terminal exec <机器> -- uptime"
        ),
        "session_ambiguous": "{machine} 上有几个会话都以 {prefix} 开头；多写几位：",
        "joined": "已加入 {url}，正在连接",
        "link_prompt": "粘贴加入链接：",
        "leave_question": "离开 {hub}？它的转发、挂载和查看器都会结束 [y/N] ",
        "left": "已离开 {hub}",
        "panel_opening": "正在打开 {hub} 的面板",
        "unknown_name": "没有叫 {name} 的{what}，有这些：{names}",
        "unknown_name_none": "没有叫 {name} 的{what}，一个也没有",
        "ambiguous_name": "{name} 对得上不止一个{what}，指明是哪个：{names}",
        "what_machine": "机器",
        "what_hub": "中枢",
        "what_app": "应用",
        "what_share": "共享",
        "what_entry": "入口",
        "what_account": "账户",
        "what_setting": "设置项",
        "opening": "正在打开 {address}",
        "stopped": "已停止 {app}",
        "port_value_invalid": "--port 要写成 <入口>=<端口>，不是 {value}",
        "port_missing": "至少写一个 --port <入口>=<端口>",
        "in_use": "在用",
        "not_in_use": "未用",
        "yes": "是",
        "no": "否",
        "none": "-",
        "source_module": "模块",
        "source_declared": "声明",
        "source_manual": "手动",
        "kind_web": "网页",
        "kind_port": "端口",
        "kind_ssh": "ssh",
        "kind_file": "文件",
        "unhealthy": "现在连不上",
        "ask_user": "{share} 的用户名：",
        "ask_password": "{share} 的密码：",
        "user_missing": "声明的共享要填用户名",
        "ai_hub": "中枢的",
        "ai_own": "它自己的",
        "ai_switching": "切换工具中",
        "ai_none": "没有中枢给这个客户端发布 AI 网关",
        "ai_set": "工具已指向 {address}",
        "rdp_open": "查看器开着",
        "rdp_opening": "正在打开 {machine} 的查看器",
        "rdp_nobody": "屏幕前没有人",
        "on": "on",
        "off": "off",
        "ssh_config_absent": "{path} 还没有写出来",
        "ssh_installed": "已在 ~/.ssh/config 里加上 Include ~/.ssh/neutrino_config",
        "ssh_uninstalled": "已从 ~/.ssh/config 里拿掉 Include ~/.ssh/neutrino_config",
        "session_flags_missing": "写 --persist on|off、--share on|off，或者两个都写",
        "terminal_none": "{machine} 上没有会话",
        "terminal_session": "会话",
        "terminal_account": "账户",
        "terminal_open_for": "开了多久",
        "terminal_persistent": "持久",
        "terminal_shared": "共享",
        "terminal_attached": "在看",
        "see_help": "看 {command} -h",
    },
}

# Whether the commands print to a Windows console, and what they print there
# in place of two characters of the window's words, which a console reading
# in code page 437 garbles.
CLIENT_IS_WINDOWS_CONSOLE = os.name == "nt"
CLIENT_WINDOWS_CONSOLE_TEXT = str.maketrans({"·": "-", "…": "..."})

# The language a caller fixed for this process; empty reads the store.
_FIXED_LANGUAGE = {"value": ""}


def language() -> str:
    """The language this client's commands speak.

    Returns:
        The language the client's store keeps, else the machine's own, one
        of ``CLIENT_LANGUAGES``; English when neither can be read.
    """
    if _FIXED_LANGUAGE["value"]:
        return _FIXED_LANGUAGE["value"]
    try:
        platform = detect_platform()
        store = ClientServiceStore(
            path=os.path.join(platform.config_dir(), CLIENT_STATE_FILE_NAME)
        )
        chosen = store.language() or platform.system_language()
    except (OSError, ValueError, PlatformUnsupportedError):
        return CLIENT_DEFAULT_LANGUAGE
    return chosen if chosen in CLIENT_LANGUAGES else CLIENT_DEFAULT_LANGUAGE


def fix_language(chosen: str) -> None:
    """Speak one language from now on in this process, whatever the store keeps.

    Args:
        chosen: One of ``CLIENT_LANGUAGES``; empty reads the store again.
    """
    _FIXED_LANGUAGE["value"] = chosen if chosen in CLIENT_LANGUAGES else ""


def console_text(text: str) -> str:
    """A line as this system's console shows it.

    Args:
        text: The line.

    Returns:
        The line; on Windows with ``-`` for ``·`` and ``...`` for ``…``.
    """
    if not CLIENT_IS_WINDOWS_CONSOLE:
        return text
    return text.translate(CLIENT_WINDOWS_CONSOLE_TEXT)


def word_code(code: str, params: "dict | None" = None) -> str:
    """One typed code's wording on this surface, in the client's language.

    Args:
        code: The code the resident or the channel answered with.
        params: The code's own parameters.

    Returns:
        The words to print; a code with no entry prints as itself.
    """
    if not code:
        return ""
    values = dict(params or {})
    if code in CLIENT_DETAIL_CODES:
        return str(values.get("detail", "")) or word_state("failed")
    if code == "hub_unreachable" and values.get("detail"):
        return str(values["detail"])
    word = _table(CLIENT_CODE_WORDS).get(code) or CLIENT_CODE_WORDS["en"].get(code)
    return _fill(word, values) if word else code


def word_state(state: str) -> str:
    """One state token's wording; a token outside the table reads as unknown.

    Args:
        state: The token a row reported.

    Returns:
        The words to print.
    """
    table = _table(CLIENT_STATE_WORDS)
    return table.get(state, table["unknown"])


def word_mount_state(state: str) -> str:
    """One mount record state's wording; empty for a state outside the table.

    Args:
        state: The record's state.

    Returns:
        The words to print.
    """
    return _table(CLIENT_MOUNT_STATE_WORDS).get(state, "")


def line(key: str, **params) -> str:
    """One of the commands' own lines, in the client's language.

    Args:
        key: The line's key in ``CLIENT_LINES``.
        **params: What its ``{name}`` holes take.

    Returns:
        The filled line; a key no table carries reads as itself.
    """
    word = _table(CLIENT_LINES).get(key) or CLIENT_LINES["en"].get(key)
    return _fill(word, params) if word else key


def say(text: str, *, is_error: bool = False) -> None:
    """Print one line as this system's console shows it.

    Args:
        text: The line.
        is_error: Whether it goes to stderr.
    """
    print(console_text(text), file=sys.stderr if is_error else sys.stdout)


def refuse(code: str, params: "dict | None" = None) -> None:
    """Print one refusal's words on stderr.

    Args:
        code: The refusal's code.
        params: Its parameters.
    """
    say(word_code(code, params), is_error=True)


def refusal_of(reply) -> "dict | None":
    """The refusal one answer carries, when it carries one.

    Args:
        reply: What the resident answered.

    Returns:
        ``{"code", "params"}``, or None when the answer is no refusal.
    """
    if not isinstance(reply, dict):
        return None
    nested = reply.get("error")
    if isinstance(nested, dict) and nested.get("code"):
        reply = nested
    code = str(reply.get("code", "") or "")
    if not code:
        return None
    params = reply.get("params")
    return {"code": code, "params": params if isinstance(params, dict) else {}}


def hub_name(row: dict) -> str:
    """What one hub is called on this surface.

    Args:
        row: A hub of the resident's state.

    Returns:
        The hub's name, or its address while it has not said one.
    """
    return str(row.get("hub_name") or row.get("gateway_url") or "")


def choose_hub(rows: list, needle: str) -> "dict | None":
    """The one hub a command acts on.

    Args:
        rows: The hubs joined, as the resident's state lists them.
        needle: The hub's name, its id, its binding's id or its ordinal in
            ``hub list``; empty names the one hub joined.

    Returns:
        The hub, or None after the refusal was printed: no hub joined,
        several joined and none named, or a name nobody joined.
    """
    if not rows:
        say(line("not_joined"), is_error=True)
        return None
    if not needle:
        if len(rows) == 1:
            return rows[0]
        refuse("ambiguous_hub", {"hubs": ", ".join(hub_name(row) for row in rows)})
        return None
    if needle.isdigit() and 1 <= int(needle) <= len(rows):
        return rows[int(needle) - 1]
    for row in rows:
        if needle in (
            row.get("hub_name"),
            row.get("hub_id"),
            row.get("binding_id"),
            row.get("id"),
        ):
            return row
    unknown_name("what_hub", needle, [hub_name(row) for row in rows])
    return None


def unknown_name(what: str, name: str, names: list) -> None:
    """Say on stderr that a name matches nothing, with the names there are.

    Args:
        what: The line key of what was named, such as ``what_machine``.
        name: What the person typed.
        names: The names there are.
    """
    if names:
        say(
            line("unknown_name", what=line(what), name=name, names=", ".join(names)),
            is_error=True,
        )
    else:
        say(line("unknown_name_none", what=line(what), name=name), is_error=True)


def ambiguous_name(what: str, name: str, names: list) -> None:
    """Say on stderr that a name matches several, with the ones it matches.

    Args:
        what: The line key of what was named, such as ``what_app``.
        name: What the person typed.
        names: The full names it matches.
    """
    say(
        line("ambiguous_name", what=line(what), name=name, names=", ".join(names)),
        is_error=True,
    )


def ask_hold(verb: str) -> dict:
    """One ``hold`` or ``holder`` asked of the EasyTier daemon.

    Args:
        verb: ``hold`` or ``holder``.

    Returns:
        The daemon's answer; empty when this platform runs no daemon or
        none answers.
    """
    try:
        address = detect_platform().easytier_daemon_address()
    except PlatformUnsupportedError:
        return {}
    try:
        return ask_easytier_daemon(
            address, {"verb": verb}, timeout_s=CLIENT_HOLD_TIMEOUT_S
        )
    except (OSError, ValueError):
        return {}


def other_holder() -> str:
    """The account whose client holds this machine, when it is another's.

    Returns:
        That account; empty when this account holds it, nobody does, or no
        daemon answers.
    """
    answer = ask_hold(VERB_HOLDER)
    if answer.get("is_holder"):
        return ""
    return str(answer.get("holder", "") or "")


def hold_machine() -> str:
    """Ask the EasyTier daemon to hold this machine for this process.

    Returns:
        The account whose client holds it instead; empty when this process
        holds it, or no daemon answers.
    """
    answer = ask_hold(VERB_HOLD)
    if answer.get("code") != "client_held":
        return ""
    return str((answer.get("params") or {}).get("account", "") or "")


def read_state() -> "dict | None":
    """The running client's state, as this person.

    Returns:
        The state payload, or None after the refusal was printed.
    """
    answer = request("GET", "/api/state")
    if answer is None:
        return None
    status, state = answer
    if status != 200:
        refusal = refusal_of(state) or {"code": "unknown_request", "params": {}}
        refuse(refusal["code"], refusal["params"])
        return None
    return state


def request(method: str, path: str, body: "dict | None" = None):
    """One request to the running client over its control socket.

    Args:
        method: The HTTP method.
        path: The request path.
        body: Sent as JSON when given.

    Returns:
        ``(status, reply)``, or None after the refusal was printed: no
        platform socket, or nothing answering on it.
    """
    try:
        socket_path = detect_platform().control_socket_path()
    except PlatformUnsupportedError as error:
        refuse(error.code)
        return None
    try:
        return client.request(
            socket_path=socket_path, method=method, path=path, body=body
        )
    except (OSError, ValueError):
        refuse("client_not_running")
        return None


def post(path: str, body: dict) -> "dict | None":
    """One POST to the running client, its refusal printed here.

    Args:
        path: The request path.
        body: The JSON body.

    Returns:
        The answer, or None after the refusal was printed.
    """
    answer = request("POST", path, body)
    if answer is None:
        return None
    _status, reply = answer
    refusal = refusal_of(reply)
    if refusal is not None:
        refuse(refusal["code"], refusal["params"])
        return None
    return reply


def settled_state(is_settled, timeout_s: float = CLIENT_JOB_WAIT_S) -> "dict | None":
    """The running client's state once a job it runs has ended.

    Args:
        is_settled: ``is_settled(state)`` says whether the job has ended.
        timeout_s: How long to wait; the last state read is returned then.

    Returns:
        The state payload, or None after the refusal was printed.
    """
    deadline = time.monotonic() + timeout_s
    while True:
        state = read_state()
        if state is None or is_settled(state) or time.monotonic() >= deadline:
            return state
        time.sleep(CLIENT_JOB_POLL_S)


def ask_secret(prompt: str) -> str:
    """A password from the person, never from the command line.

    At a terminal it is asked without echo. From a pipe it is one line of
    stdin.

    Args:
        prompt: What to ask at a terminal.

    Returns:
        The secret, without its line ending.
    """
    stream = sys.stdin
    if stream is None or not stream.isatty():
        return (stream.readline() if stream is not None else "").rstrip("\r\n")
    return getpass.getpass(prompt)


def ask_text(prompt: str) -> str:
    """One line from the person: at a terminal with the prompt, else from stdin.

    Args:
        prompt: What to ask at a terminal.

    Returns:
        The line, stripped; empty at the end of the input.
    """
    stream = sys.stdin
    if stream is None or not stream.isatty():
        return (stream.readline() if stream is not None else "").strip()
    try:
        return input(prompt).strip()
    except EOFError:
        return ""


def is_confirmed(question: str) -> bool:
    """Ask one yes-or-no question on the terminal.

    With no terminal on stdin nothing is asked: one line on stderr says that
    ``--yes`` goes ahead without asking.

    Args:
        question: The question, ending in ``[y/N]``.

    Returns:
        True only for ``y`` or ``yes``; no input and no terminal are a no.
    """
    if sys.stdin is None or not sys.stdin.isatty():
        say(line("no_terminal"), is_error=True)
        return False
    try:
        answer = input(question)
    except EOFError:
        print()
        return False
    return answer.strip().lower() in ("y", "yes")


def _table(tables: dict) -> dict:
    """The client's language's table among one set of tables."""
    return tables.get(language()) or tables["en"]


def _fill(template: str, params: dict) -> str:
    """A template with its ``{name}`` holes filled from the params.

    Args:
        template: The wording, with ``{name}`` holes.
        params: The code's parameters; a missing name fills as empty.

    Returns:
        The filled wording.
    """

    def _value(match) -> str:
        return str(params.get(match.group(1), ""))

    return re.sub(r"\{(\w+)\}", _value, template)
