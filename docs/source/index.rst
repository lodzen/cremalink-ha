cremalink-ha
=================

**A Home Assistant integration for monitoring and controlling De'Longhi coffee machines — powered by** `cremalink`_.

.. |License| image:: https://img.shields.io/github/license/lodzen/cremalink-ha?style=for-the-badge&color=success
   :target: https://github.com/lodzen/cremalink-ha/blob/main/LICENSE
.. |Source Code| image:: https://img.shields.io/badge/Source-GitHub-black?style=for-the-badge&logo=github
   :target: https://github.com/lodzen/cremalink-ha
.. |HACS| image:: https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge
   :target: https://hacs.xyz/

|License| |Source Code| |HACS|

----

✨ Overview
-------------

The integration connects to a De'Longhi coffee machine over **local LAN**
(preferred — low latency, no cloud dependency) or the **De'Longhi cloud API**,
exposing the machine's live state, profiles, settings, statistics, and brew
actions as Home Assistant entities.

Entities include:

* **Sensors** — machine status, statistics counters
* **Selects** — profile selection and writable machine settings (auto-off,
  water hardness)
* **Switches** — power, beep, energy saving (machine-confirmed writes)
* **Buttons** — brew beverages and machine actions
* **Binary sensors** — accessory/alert states

Local mode runs an embedded cremalink LAN server in-process: session
keep-alives, command queuing, and datapoint republish handling are managed
for you.

🚀 Installation
----------------

Via **HACS** as a custom repository:

1. HACS → ⋯ → *Custom repositories* → add
   ``https://github.com/lodzen/cremalink-ha`` (category: *Integration*)
2. Install **Cremalink for Home-Assistant**
3. Restart Home Assistant
4. Settings → Devices & Services → *Add Integration* → **Cremalink**

The config flow discovers machines on the LAN (or accepts your cloud
credentials for cloud mode).

🛠 Development
---------------

**Testing**

.. code-block:: bash

   pytest tests/

The test suite stubs ``homeassistant`` modules — no full HA install is
needed to run it.

📄 License
----------

Distributed under the **AGPL-3.0-or-later** License. See
`LICENSE <https://github.com/lodzen/cremalink-ha/blob/main/LICENSE>`_.

----

.. toctree::
   :maxdepth: 2
   :caption: Contents:
   :hidden:

   Home <self>
   api/modules

.. toctree::
   :maxdepth: 2
   :caption: API Reference
   :hidden:

   api/cremalink_ha

.. _cremalink: https://github.com/lodzen/cremalink
