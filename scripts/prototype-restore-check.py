from pathlib import Path
import subprocess
import os
import time

root = Path(os.environ.get("PROTOTYPE_STATE_DIR", "/opt/mosprom-prototype"))
runtime = {}
for line in (root / "runtime.env").read_text().splitlines():
    if line and not line.startswith("#"):
        k, _, v = line.partition("=")
        runtime[k] = v
name = "mosprom-prototype-restore-check"
db = "mosprom_restore_verification"
q = subprocess.check_output(
    [
        "docker",
        "exec",
        "mosprom-prototype-db-1",
        "psql",
        "-U",
        "mosprom_admin",
        "-d",
        "mosprom",
        "-Atc",
        "SELECT count(*) FROM pg_database WHERE datname='mosprom_restore_verification'",
    ],
    text=True,
).strip()
assert q == "0", "Restore target already exists; stop"
dump = root / "acceptance-backup.dump"
with dump.open("wb") as f:
    subprocess.run(
        [
            "docker",
            "exec",
            "mosprom-prototype-db-1",
            "pg_dump",
            "-U",
            "mosprom_migrate",
            "-d",
            "mosprom",
            "-Fc",
            "--no-owner",
            "--no-acl",
        ],
        check=True,
        stdout=f,
    )
dump.chmod(0o600)
subprocess.run(
    [
        "docker",
        "exec",
        "mosprom-prototype-db-1",
        "createdb",
        "-U",
        "mosprom_admin",
        "-O",
        "mosprom_migrate",
        db,
    ],
    check=True,
)
checkenv = root / "restore-check.env"
started = False
try:
    with dump.open("rb") as f:
        subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                "mosprom-prototype-db-1",
                "pg_restore",
                "-U",
                "mosprom_migrate",
                "-d",
                db,
                "--no-owner",
                "--no-acl",
                "--clean",
                "--if-exists",
                "--exit-on-error",
            ],
            check=True,
            stdin=f,
        )
    subprocess.run(
        [
            "docker",
            "exec",
            "mosprom-prototype-db-1",
            "psql",
            "-U",
            "mosprom_migrate",
            "-d",
            db,
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            "GRANT USAGE ON SCHEMA public TO mosprom_app; GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO mosprom_app; GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO mosprom_app; ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO mosprom_app; ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO mosprom_app;",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    runtime.update(
        DATABASE_URL="postgresql+asyncpg://mosprom_app:"
        + runtime["POSTGRES_PASSWORD"]
        + "@db:5432/"
        + db,
        REDIS_URL="redis://redis:6379/14",
        SIM_URL="http://sim:8080",
        MEDIA_URL="",
        WEB_CONCURRENCY="1",
    )
    with os.fdopen(
        os.open(checkenv, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w"
    ) as f:
        f.write("".join(k + "=" + v + "\n" for k, v in runtime.items()))
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            name,
            "--network",
            "mosprom-prototype_default",
            "--memory",
            "384m",
            "--cpus",
            "0.5",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--tmpfs",
            "/tmp:rw,nosuid,noexec,size=32m",  # nosec B108: private container tmpfs, no host temporary file
            "--env-file",
            str(checkenv),
            runtime["API_IMAGE"],
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    started = True
    code = "import urllib.request,json; r=json.load(urllib.request.urlopen('http://127.0.0.1:8000/ready',timeout=4)); assert r['status']=='ready'; print('Restored application readiness verified')"
    for attempt in range(40):
        p = subprocess.run(
            ["docker", "exec", name, "python", "-c", code],
            capture_output=True,
            text=True,
        )
        if p.returncode == 0:
            print(p.stdout.strip())
            break
        time.sleep(1)
    else:
        raise RuntimeError("Restored API did not become ready")
    code2 = r"""import os,time,json,hmac,hashlib,urllib.request,urllib.parse
user=json.dumps({'id':1700000000099,'first_name':'Restore verification'},separators=(',',':'))
params={'auth_date':str(int(time.time())),'user':user}
check='\n'.join(k+'='+params[k] for k in sorted(params))
secret=hmac.new(b'WebAppData',os.environ['BOT_TOKEN'].encode(),hashlib.sha256).digest()
params['hash']=hmac.new(secret,check.encode(),hashlib.sha256).hexdigest()
headers={'X-Telegram-Init-Data':urllib.parse.urlencode(params),'X-Frontend-Revision':os.environ['FRONTEND_REVISION']}
r=urllib.request.Request('http://127.0.0.1:8000/api/bootstrap',headers=headers)
with urllib.request.urlopen(r,timeout=12) as response:
 assert response.status==200
 data=json.load(response); assert 'snapshot' in data
print('Authenticated game bootstrap on restored database verified')
"""
    subprocess.run(
        ["docker", "exec", "-i", name, "python", "-"],
        input=code2,
        text=True,
        check=True,
    )
    print(
        "Consistent backup restored into separate database; original application database unchanged"
    )
finally:
    if started:
        subprocess.run(
            ["docker", "rm", "-f", name], check=True, stdout=subprocess.DEVNULL
        )
    checkenv.unlink(missing_ok=True)
    subprocess.run(
        [
            "docker",
            "exec",
            "mosprom-prototype-db-1",
            "dropdb",
            "-U",
            "mosprom_admin",
            db,
        ],
        check=True,
    )
