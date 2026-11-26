# GameBoy-Cloud 

**Automated, cross-platform cloud save synchronization between an embedded Linux handheld (RetroPie / Raspberry Pi CM4) and Windows (RetroArch) backed by Cloudflare R2.**

---

## Overview

Handheld retro gaming setups lack native cloud save infrastructure, making it tedious to move game progress between a portable device and a desktop PC without manually
transferring `.srm` save files over SFTP or SD cards.

**GameBoy-Cloud** solves this with a lightweight, zero-cost, event-driven synchronization engine written in Python. By hooking directly into emulator
lifecycle events on both Linux and Windows, save states stay synchronized automatically across devices with cryptographic integrity checks, conflict protection, 
and local versioned backups.

---

## System Architecture

```text
┌───────────────────────────────────────┐       ┌───────────────────────────────────────┐
│   RetroFlag GPi Case 2 (RetroPie)     │       │         Windows PC (RetroArch)        │
│   Raspberry Pi CM4 • Debian Linux     │       │         Desktop Wrapper Script        │
└───────────────────┬───────────────────┘       └───────────────────┬───────────────────┘
                    │                                               │
     1. Game Launch │ runcommand-onstart.sh          1. Game Launch │ launch_retroarch.bat
        ► sync.py pull                                  ► sync.py pull
                    │                                               │
                    ▼                                               ▼
          ┌───────────────────────────────────────────────────────────────────┐
          │                    Cloudflare R2 Object Storage                   │
          │               S3-Compatible API • Bucket: retro-saves             │
          │          SHA-256 Content Hashing + Timestamp Conflict Check       │
          └───────────────────────────────────────────────────────────────────┘
                    ▲                                               ▲
                    │                                               │
     2. Game Exit   │ runcommand-onend.sh            2. Game Exit   │ launch_retroarch.bat
        ► sync.py push                                  ► sync.py push
