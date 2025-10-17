# 🏠 Custom Home Assistant Integration — Voltie Charger

A custom integration for [Home Assistant](https://www.home-assistant.io) that lets you montitor and control your Voltie Charger.

---

## ✨ Features
- ⚡ Easy to install via [HACS](https://hacs.xyz)
- 🔧 Simple setup through the Home Assistant UI
- 🧠 Lightweight and local — no cloud required

---

## 📦 Installation via HACS

> 💡 You must have [HACS](https://hacs.xyz) installed first.

1. Open **HACS** in your Home Assistant sidebar  
2. Go to **Integrations**  
3. Click the **⋮ (three dots)** menu in the top-right → **Custom repositories**  
4. Paste this repository URL: https://github.com/voltie-eu/homeassistant-voltie_charger
5. Select **Integration** as the category  
6. Click **Add**, then find **Voltie Charger** in the HACS Integrations list  
7. Click **Download** / **Install**  
8. **Restart Home Assistant** after installation  

---

## ⚙️ Configuration

After restarting:
1. Go to **Settings → Devices & Services → + Add Integration**  
2. Search for **Voltie Charger**
3. Enter the local IP address of your Voltie Charger followed by the port set up in the Voltie App (deafult is **5059**)  
```Example: 192.168.1.121:5059```
4. Enter the username and password set up in the Voltie App
5. Follow the on-screen instructions  



MIT License
Copyright (c) 2025 Voltie
