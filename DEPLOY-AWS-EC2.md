# Deploy the Andon Tool on AWS EC2 (Beginner Guide, Free-Tier)

A complete, from-scratch guide to run the Andon tool on a single small AWS EC2
instance, using only **free-tier-eligible** resources. Written for someone new to AWS.

---

## Read this first — cost & data notes

**Cost / no future charges:**
- Use a **`t2.micro` or `t3.micro`** instance — these are **free-tier eligible**.
- Use the **default 8 GB disk**, one instance, and **no** extra paid services
  (no RDS, no load balancer, no Elastic IP left unattached).
- **Terminate the instance when the demo is done** (Step 9). Terminating stops all
  charges. On a burner account that auto-expires, everything is also torn down at expiry.
- Confirm with whoever gave you the account that **billing goes to the team cost
  center**, not you. On internal/burner accounts you do not attach a personal card.
- The single biggest way people get surprise charges is leaving things running.
  This guide uses one tiny instance and tells you to terminate it — follow that and
  cost stays at/near zero.

**Data note:**
- Before storing **real** associate logins / production images, confirm with your
  manager or security contact that it's permitted in this account. If unsure, use
  sample data. (The steps are identical either way.)
- Data lives on the instance (SQLite). **Export the CSV from the dashboard before the
  account expires** if you want to keep records — everything is wiped when the burner ends.

---

## What you'll end up with

A running, **password-protected** server reachable at
`http://<your-server-ip>:8900/login.html`. After signing in, users reach the
associate, SME, and dashboard pages. Your remote managers open the link and enter
the password you set.

---

## Step 1 — Log in to the AWS Console

1. Open the AWS Console for your burner account (however your org gives you access).
2. Top-right, set the **Region** (e.g. "US East (N. Virginia) us-east-1"). Remember
   which region you pick — everything must be created in the same region.

---

## Step 2 — Launch an EC2 instance

1. In the search bar type **EC2**, open it.
2. Click **Launch instance**.
3. **Name:** `andon-demo`
4. **Application and OS Image (AMI):** choose **Amazon Linux 2023** (free-tier eligible).
5. **Instance type:** choose **t2.micro** (or **t3.micro**) — it should say
   *"Free tier eligible."*
6. **Key pair (login):** click **Create new key pair**.
   - Name: `andon-key`
   - Type: RSA, Format: **.pem**
   - Click **Create** — a `andon-key.pem` file downloads. **Keep it safe**; you need it to log in.
7. **Network settings** → click **Edit**:
   - **Allow SSH traffic from** → "My IP" (so only you can log in).
   - Check **Allow HTTP traffic from the internet** (optional; we'll use a custom port anyway).
   - We'll add the app's port next.
8. Leave storage at the default **8 GB**.
9. Click **Launch instance**, then **View all instances**. Wait until
   **Instance state = Running** and status checks pass.

---

## Step 3 — Open the app's port (8900) in the firewall

The app serves on port 8900, so we must allow it.

1. In EC2 → **Instances**, click your `andon-demo` instance.
2. Go to the **Security** tab → click the **security group** link (e.g. `launch-wizard-1`).
3. Click **Edit inbound rules** → **Add rule**:
   - **Type:** Custom TCP
   - **Port range:** `8900`
   - **Source:** for a quick demo, `Anywhere-IPv4 (0.0.0.0/0)`.
     *(If using real data, restrict this to specific IPs instead — ask your managers
     for their IPs, or keep it to your corporate network range.)*
4. Click **Save rules**.

---

## Step 4 — Connect to the instance (no software needed)

Easiest for beginners: use the browser-based connection.

1. EC2 → **Instances** → select `andon-demo` → click **Connect** (top).
2. Choose the **EC2 Instance Connect** tab → click **Connect**.
3. A terminal opens in your browser, logged into the server. (No .pem needed for this method.)

---

## Step 5 — Install Python (usually already there)

In that browser terminal, run:

```bash
python3 --version
```

If it prints a version, you're set. If not:

```bash
sudo dnf install -y python3
```

---

## Step 6 — Get the app files onto the server (direct upload)

Since we're uploading directly (not GitHub), the simplest way is to recreate the files
on the server. But the cleanest beginner method is to **use `nano` to paste each file**,
OR upload via **EC2 Instance Connect is text-only**, so we'll use a small helper.

**Recommended: upload a ZIP using AWS CloudShell / your browser.**

Simplest reliable approach for a beginner:

1. On your PC, put all the Andon files into a single ZIP named `andon.zip`
   (`server.py`, `associate.html`, `sme.html`, `dashboard.html` — the `.db` is not needed).
2. In the AWS Console search bar, open **S3** → **Create bucket** → give it a unique name
   (e.g. `andon-upload-<yourname>`) → Create.
3. Open the bucket → **Upload** → add `andon.zip` → **Upload**.
4. Back in the EC2 browser terminal, download it and unzip:

```bash
mkdir -p ~/andon && cd ~/andon
# replace BUCKET with your bucket name:
aws s3 cp s3://BUCKET/andon.zip .
unzip andon.zip
ls
```

You should see `server.py` and the HTML files.

> If `aws s3 cp` says access denied, the instance needs an IAM role with S3 read.
> Simpler alternative below.

**Even simpler alternative (no S3): paste files with `nano`.**
For each file:
```bash
cd ~/andon
nano server.py
```
Paste the file contents (copy from your local file), then press `Ctrl+O`, `Enter`
to save, and `Ctrl+X` to exit. Repeat for `associate.html`, `sme.html`, `dashboard.html`.
(4 files total.)

---

## Step 7 — Run the server

### 7a — REQUIRED for real data: set a password

The app has a built-in password gate. It is **only active if you set the
`ANDON_PASSWORD` environment variable**. If you skip this, the site is open to
anyone with the link — **do not do that with real data.**

Set a password (and a stable secret so logins survive a restart) before starting.
Replace `ChooseAStrongPassword` with your own:

```bash
export ANDON_PASSWORD='ChooseAStrongPassword'
export ANDON_SECRET='some-long-random-string-you-make-up'
```

- `ANDON_PASSWORD` — everyone who uses the tool enters this on the login page.
- `ANDON_SECRET` — signs the login session cookie. Any long random string. Setting
  it means people stay logged in even if the server restarts. (If you omit it, a new
  random one is used each restart, which just forces users to log in again.)

> These `export` lines only last for the current terminal session. The background
> start command below runs in that same session, so the values carry over. If you
> reconnect later to restart the server, set them again first.

### 7b — Start the server

```bash
cd ~/andon
python3 server.py 8900
```

You should see "Andon server running on port 8900" and, if the password is set,
`Authentication -> ON (password required)`.

To keep it running after you close the browser terminal, use this instead:

```bash
cd ~/andon
nohup python3 server.py 8900 > andon.log 2>&1 &
```

This runs it in the background; logs go to `andon.log`.

**One-liner (set password + run in background together):**

```bash
cd ~/andon
ANDON_PASSWORD='ChooseAStrongPassword' ANDON_SECRET='some-long-random-string' \
  nohup python3 server.py 8900 > andon.log 2>&1 &
```

Confirm auth is on:

```bash
cat andon.log
```

You should see `Authentication -> ON (password required)`. If it says `OFF`, the
password variable wasn't set — stop the server and start again with it set.

---

## Step 8 — Get your shareable link

1. EC2 → **Instances** → select `andon-demo`.
2. Copy the **Public IPv4 address** (e.g. `52.12.34.56`).
3. Your entry link (the login page) is:
   - `http://<PUBLIC-IP>:8900/login.html`
4. After signing in with the password, users reach:
   - `http://<PUBLIC-IP>:8900/associate.html`
   - `http://<PUBLIC-IP>:8900/sme.html`
   - `http://<PUBLIC-IP>:8900/dashboard.html`
5. Test it yourself (you should be redirected to the login page first), then share the
   link **and the password** with your managers — ideally via separate messages.

---

## Step 8b — STRONGLY RECOMMENDED for real data: add HTTPS

The password gate stops "anyone with the link" from getting in, but on plain `http://`
the **password itself travels unencrypted** over the network. For **real data**, you
should add HTTPS so the login and all traffic are encrypted.

Why it matters: without HTTPS, someone on the network path could read the password or
data in transit. With HTTPS, it's encrypted end to end.

Options (pick one; ask me for the exact commands for your choice):

1. **Caddy (easiest, auto-HTTPS)** — a small web server that gets a free certificate
   automatically **if the instance has a domain name** pointing to it. It sits in front
   of the app on port 443. Best option if you can get a hostname.
2. **Self-signed certificate** — works with just the IP (no domain), but browsers show a
   "not secure / proceed anyway" warning. Acceptable for an internal pilot where you tell
   users to click through, not ideal for wider sharing.
3. **Put it behind an internal HTTPS endpoint** — the proper long-term answer, handled
   during real internal hosting (see INTERNAL-HOSTING-REQUEST.md).

> Honest note: HTTPS on a bare IP with no domain always involves a browser warning
> (option 2). A clean, warning-free HTTPS needs a domain name (option 1) or internal
> hosting (option 3). For real associate data, do at least option 2, and restrict the
> port-8900 (or 443) inbound rule to specific manager IPs rather than `0.0.0.0/0`.

Tell me which option you want and I'll write the exact steps.

---

## Step 9 — IMPORTANT: shut it down to avoid any charges

When the demo/pilot is over (and after exporting any CSV you want to keep):

1. **Export data:** open the dashboard, click **Export CSV**, save it locally.
2. EC2 → **Instances** → select `andon-demo` → **Instance state** → **Terminate instance**.
3. If you created an S3 bucket in Step 6, delete it: S3 → select bucket → **Empty**, then **Delete**.
4. That's it — with the instance terminated and no other resources, nothing can charge you.

On a burner account, expiry also wipes everything automatically, but terminating
yourself when done is the clean habit.

---

## Cost summary (how you stay at $0)

| Resource | Free-tier? | Note |
|----------|-----------|------|
| 1 × t2.micro / t3.micro EC2 | Yes (750 hrs/month free) | The only compute you need |
| 8 GB default disk | Yes (30 GB free) | Default size |
| SQLite database | Free | Runs on the instance, no paid DB |
| S3 (optional, for upload) | Yes (small free tier) | Delete the bucket after |
| Data transfer (demo traffic) | Small free allowance | Tiny for a demo |

Keep it to the above, terminate when done, and there are no ongoing charges.

---

## Troubleshooting

- **Can't open the link:** re-check Step 3 (port 8900 inbound rule) and that the
  server is running (Step 7). Use the **Public IPv4**, not the private IP.
- **Server stopped when I closed the terminal:** use the `nohup ... &` command in Step 7.
- **`aws s3 cp` access denied:** use the `nano` paste method instead (Step 6 alternative).
- **Page loads but no data saves:** make sure you're running `server.py` from the folder
  that has the HTML files, and that it didn't error on start (`cat andon.log`).
