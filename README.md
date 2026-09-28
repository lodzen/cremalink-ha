# <img src="icon.png" alt="Cremalink Logo" height="45" style="vertical-align: middle; margin-right: 10px;"> cremalink for Home Assistant

**The official Home Assistant integration for monitoring and controlling IoT coffee machines via Cremalink.**

[![Open your Home Assistant instance and show the add add-on repository dialog with a specific repository URL pre-filled.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Flodzen%2Fcremalink-ha)
[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?category=integration&repository=cremalink-ha&owner=lodzen)
[![License](https://img.shields.io/github/license/lodzen/cremalink-ha?style=for-the-badge&color=success)](LICENSE)
[![Source Code](https://img.shields.io/badge/Source-GitHub-black?style=for-the-badge&logo=github)](https://github.com/lodzen/cremalink-ha)

---

## ✨ Overview

This integration connects your Home Assistant instance to the **Cremalink** ecosystem, allowing for real-time state monitoring and control of smart coffee machines. Local (LAN) connectivity is handled by a built-in, embedded server hosted directly by the integration — **no separate add-on is required**.

> [!NOTE] 
> This project was developed with a result-oriented approach, primarily optimized for the **De'Longhi PrimaDonna Soul**. While the architecture is designed to be extensible, some logic may currently be tightly coupled to this specific model.
>
> The goal is to make the library fully generic. If you encounter issues with other machines, contributions are highly encouraged!

> [!NOTE]
> **cremalink-ha** acts solely as a bridge to Home Assistant. Device management (e.g., adding new machines) is handled exclusively via the main **[cremalink](https://github.com/lodzen/cremalink)** project. Please set up your devices there before using this integration.
---

## 🚀 Installation

### 1. Install the Integration

**Via HACS (Recommended):**
1.  Click the "Open your Home Assistant instance" badge above, or manually add this repository to HACS as a custom repository.
2.  Search for "Cremalink" and install.
3.  Restart Home Assistant.

**Manual Installation:**
1.  Copy the `custom_components/cremalink_ha` folder to your `config/custom_components/` directory.
2.  Restart Home Assistant.

> [!NOTE]
> The **Cremalink Server Add-on** is deprecated for this integration — local mode
> now runs entirely in-process, with no Supervisor add-on to install, configure, or
> keep running. If you have an existing add-on-based setup, see
> [Upgrading from the add-on](#-upgrading-from-the-add-on) below.

---

## ⚙️ Configuration

1.  Navigate to **Settings** > **Devices & Services**.
2.  Click **Add Integration**.
3.  Search for **Cremalink**.
4.  Sign in with your Cremalink cloud account email and password. The integration
    automatically discovers your coffee machine(s), detects the correct model, and
    connects locally (via the built-in embedded server) whenever LAN details are
    available, falling back to the cloud connection otherwise — no device map,
    DSN, LAN key, or add-on to set up.
5.  Don't have (or don't want to use) a cloud account? Check **Advanced setup** on
    the first screen to fall back to the previous manual flow: picking a device map
    and entering the DSN/LAN key/IP (local) or a refresh token (cloud) by hand.

---

## ⚙️ Upgrading from the add-on

If you previously set up local mode using the **Cremalink Server Add-on**, that
entry is flagged as needing reconfiguration after upgrading (visible under
**Settings > Repairs**, and via a "Reconfigure" option on the device's config
entry). Your DSN, device name, and device map are reused automatically —
completing the reconfigure step switches the entry to the built-in embedded
server, after which you can uninstall the add-on.

---

## 🛡️ What happens to the embedded server during a reload, restart, or crash?

Since the embedded server runs *inside* Home Assistant's own process, it's
worth being explicit about what's guaranteed in each scenario:

- **Config entry reload / unload / removal** — the embedded server is
  stopped and its port released before the entry finishes unloading. A
  stuck device connection can no longer make this hang: the server's own
  teardown has a short internal bound, and the integration additionally
  wraps every stop with its own bounded timeout, so a reload/removal
  always completes within a few seconds even in the worst case.
- **A full Home Assistant restart** — Home Assistant does not unload
  config entries individually as part of a normal restart; the whole
  process exits and is relaunched by whatever manages it (systemd,
  Docker, the Supervisor, etc.). The operating system reclaims every
  socket and background task on process exit, and the embedded server's
  automatic port-fallback already tolerates binding again immediately
  afterward — no cleanup needs to run for a restart to be safe.
- **A hard crash (power loss, OOM, `SIGKILL`)** — identical outcome to a
  restart: nothing runs, the OS reclaims everything, and the next start
  begins clean.

In short: a problem in the embedded server cannot destabilize Home
Assistant itself in any of these scenarios.

---

## 🤝 Contributing

Contributions are welcome! If you have a machine profile not yet supported, please check the [Project Wiki of the official cremalink repository](https://github.com/lodzen/cremalink/wiki/) on how to add new definitions.

---

## 💫 Star History

[![Star History Chart](https://api.star-history.com/svg?repos=lodzen/cremalink-ha&type=date&logscale&legend=top-left)](https://www.star-history.com/#lodzen/cremalink-ha&type=date&logscale&legend=top-left)

## 📄 License

Distributed under the **AGPL-3.0-or-later** License. See `LICENSE` for more information.

---

*Developed by [Midian Tekle Elfu](mailto:developer@midian.tekleelfu.de). Supported by the community.*
