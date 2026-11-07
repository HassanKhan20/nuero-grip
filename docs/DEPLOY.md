# Deploy: Vultr + GoDaddy (about 20 minutes)

The server has no webcam or ESP32, so the public site runs in **mock mode**. The live hardware demo still runs on the laptop.

## 1. Vultr instance
1. Vultr → Deploy → **Cloud Compute, Ubuntu 24.04**, the cheapest plan (1 GB RAM is enough). Add your SSH key.
2. Note the public IP.

## 2. Copy the app and install
```bash
# from your laptop, in the repo folder (Git Bash)
ssh root@<IP> mkdir -p /opt/neurogrip
scp -r app.py neurogrip templates static requirements.txt root@<IP>:/opt/neurogrip/

# on the server
ssh root@<IP>
apt update && apt install -y python3-venv libgl1 libglib2.0-0   # opencv needs these on a headless server
cd /opt/neurogrip && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
ufw allow 80/tcp
```

## 3. Run it on port 80
```bash
cat > /opt/neurogrip/.env <<'EOF'
NG_MODE=mock
PORT=80
NVIDIA_API_KEY=...
GEMINI_API_KEY=...
MONGODB_URI=mongodb+srv://...
EOF

cat > /etc/systemd/system/neurogrip.service <<'EOF'
[Unit]
Description=NeuroGrip dashboard
After=network-online.target

[Service]
WorkingDirectory=/opt/neurogrip
EnvironmentFile=/opt/neurogrip/.env
ExecStart=/opt/neurogrip/.venv/bin/python app.py
Restart=always

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload && systemctl enable --now neurogrip
curl -sI http://localhost/login | head -1      # expect HTTP/1.1 200
```
In MongoDB Atlas → Network Access, allow the Vultr IP, or the app falls back to in-memory storage.

## 4. GoDaddy domain
1. Register the domain.
2. DNS → **A record**, host `@`, value `<Vultr IP>`, TTL 600. Add a second A record with host `www`.
3. Wait a few minutes, then open `http://<domain>` and log in with `therapist` / `therapist`.
