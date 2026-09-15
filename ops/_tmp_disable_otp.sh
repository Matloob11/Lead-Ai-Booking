#!/usr/bin/env bash
set -euo pipefail
AWS_KEY="C:/Users/Matloob/.ssh/aws_codex"
AWS_KH="${HOME}/.ssh/known_hosts"
ssh.exe -i "$AWS_KEY" -o BatchMode=yes -o ConnectTimeout=20 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$AWS_KH" ec2-user@13.203.81.218 python3 - <<'PY'
import re, subprocess, os
settings = subprocess.check_output(["sudo", "cat", "/home/bitrix/www/bitrix/.settings.php"], text=True)

def grab(key):
    m = re.search(r"['\"]%s['\"]\s*=>\s*['\"]([^'\"]*)" % key, settings)
    return m.group(1) if m else ""

env=os.environ.copy(); env["MYSQL_PWD"]=grab("password")
args=["mysql","-N","-h",grab("host") or "localhost","-u",grab("login"),grab("database")]

def mysql(sql):
    r=subprocess.run(args+["-e",sql],env=env,capture_output=True,text=True)
    if r.returncode:
        print("ERR", r.stderr[:400])
    return r.stdout.strip()

like = r"%khurram162%OR SESSION_DATA LIKE %\"USER_ID\";i:1;%"
# two predicates
q = """DELETE FROM {t} WHERE SESSION_DATA LIKE '%khurram162%'
   OR SESSION_DATA LIKE '%s:7:\\\"USER_ID\\\";i:1;%'
   OR SESSION_DATA LIKE '%\"USER_ID\";i:1;%'"""
for t in ("b_user_session","b_sec_session"):
    before = mysql("SELECT COUNT(*) FROM %s" % t)
    mysql(q.format(t=t))
    after = mysql("SELECT COUNT(*) FROM %s" % t)
    print(t, "rows", before, "->", after)
print("otp flags", mysql("SELECT CONCAT(ACTIVE,', skip=',SKIP_MANDATORY) FROM b_sec_user WHERE USER_ID=1"))
PY
