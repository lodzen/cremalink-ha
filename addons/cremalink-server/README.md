# <img src="icon.png" alt="Cremalink Logo" height="45" style="vertical-align: middle; margin-right: 10px;"> cremalink Server HA Add-on

**Run the local Cremalink server directly within Home Assistant to bridge your coffee machine.**

[![Open your Home Assistant instance and show the add add-on repository dialog with a specific repository URL pre-filled.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Flodzen%2Fcremalink-ha)
[![License](https://img.shields.io/github/license/lodzen/cremalink-ha?style=for-the-badge&color=success)](LICENSE)
[![Source Code](https://img.shields.io/badge/Source-GitHub-black?style=for-the-badge&logo=github)](https://github.com/lodzen/cremalink-ha)

---

> [!WARNING]
> **Deprecated for the Cremalink Home Assistant integration.** As of the
> embedded local server feature, `cremalink_ha` no longer requires, installs,
> or connects to this add-on — local mode now runs entirely in-process. This
> add-on remains available only for non-Home-Assistant/standalone use of the
> `cremalink` library. Existing add-on-based config entries are prompted to
> reconfigure to the embedded server (see the main [README](../../README.md#-upgrading-from-the-add-on)).

## ✨ Overview

This Home Assistant Add-on runs the **Cremalink Server**, which communicates directly with supported coffee machines over the local network. It exposes an API that the **Cremalink Integration** uses to monitor and control the machine.

> [!NOTE] 
> This project was developed with a result-oriented approach, primarily optimized for the **De'Longhi PrimaDonna Soul**. While the architecture is designed to be extensible, some logic may currently be tightly coupled to this specific model.
>
> The goal is to make the library fully generic. If you encounter issues with other machines, contributions are highly encouraged!

> [!NOTE]
> **cremalink-ha** acts solely as a bridge to Home Assistant. Device management (e.g., adding new machines) is handled exclusively via the main **[cremalink](https://github.com/lodzen/cremalink)** project. Please set up your devices there before using this integration.

---

## 🚀 Installation & Configuration

### 1. Installation

1.  Click the badge above or navigate to **Settings** > **Add-ons** > **Add-on Store**.
2.  Add the repository URL: `https://github.com/lodzen/cremalink-ha`
3.  Install **Cremalink for Home-Assistant**.
4.  Start the add-on.

### 2. Configuration

Configure the add-on via the **Configuration** tab.

| Option                  | Description                                              | Default |
|:------------------------|:---------------------------------------------------------|:--------|
| `advertised_ip`         | (Optional) The IP address to advertise for the server.   | Empty   |
| `server_port`           | The port the server will listen on.                      | `10280` |
| `monitor_poll_interval` | Interval (in seconds) to poll the machine status.        | `1.0`   |
| `log_level`             | Logging verbosity (`debug`, `info`, `warning`, `error`). | `info`  |

---

## 🛠 Usage

Once running, this add-on handles the low-level communication with the coffee machine.

To control the machine from Home Assistant, you must also install the **Cremalink Integration**.

👉 **[Go to Integration Documentation](../../README.md)** for next steps.

---

## 📄 License

Distributed under the **AGPL-3.0-or-later** License.

---

*Developed by [Midian Tekle Elfu](mailto:developer@midian.tekleelfu.de). Supported by the community.*
