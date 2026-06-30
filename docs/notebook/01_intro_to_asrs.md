# Chapter 1 — Introduction to the ASRS

> The grounding chapter. Read this first to understand the physical system the
> Predictive Maintenance (PdM) model reasons about. Everything downstream — the
> signals, the per-component scoring, the modules — maps back to the equipment
> described here.

## 1.1 What the system is

The plant runs a **six-aisle Automated Storage and Retrieval System (ASRS)** that
buffers inventory between **inbound QC (IQC)** and **order fulfilment**. The unit of
movement is the **tote**, never loose items. A **Warehouse Execution System (WES)**
is the brain: it coordinates every movement, and barcodes on each tote face and
each partition give end-to-end traceability. The entire sensor/acknowledgement
fabric is visualised in **Grafana**, which is the single source of all PdM data —
this system never talks to the PLCs directly; it learns from what Grafana exposes.

## 1.2 Aisles and geometry

- **6 aisles**, each spanning roughly **70 m** of rack.
- **Levels per aisle:** aisles 1–4 have **19 levels** (grouped 5·5·5·4); aisles 5–6
  have **24 levels** (grouped 5·5·5·5·4). A level-group is called a **ground**.
- Each level has **two racks**, one on either side of a central **shuttle lane**.
- Each rack has **deep 1** (front, shuttle side) and **deep 2** (rear). Reaching
  deep 2 means first relocating the deep-1 tote — a **reshuffle**.

**Capacity.** Per level = 2 racks × 113 locations × 2 deeps = **452** positions.
Aisles 1–4 hold 8,588 each; aisles 5–6 hold 10,848 each; system gross =
**56,048** positions. A vacancy reserve is held by design to allow reshuffles.

**Addressing.** Positions are addressed `Aisle–Level–Location–Deep`, e.g.
`01-12-16-02`.

## 1.3 The shuttle

One **shuttle per aisle** runs the central lane with telescopic forks that reach
both racks. Deep-2 access requires a reshuffle (move the deep-1 tote first). The
shuttle is the only **Wi-Fi** device in the system — everything else is wired.

## 1.4 Lifts and buffers — the focus of Module 1

Each aisle has **two lifts and two buffers — one of each on each face** (an
**inbound** face and an **outbound** face). Each lift and buffer handles **two
totes at a time**.

- **Inbound flow:** a tote enters the inbound lane → is placed on the inbound lift
  → **the lift rises only once it is holding two totes** → moves to a buffer →
  the shuttle stores it on a rack.
- **Retrieval flow:** the path reverses — shuttle → buffer → outbound lift →
  outbound lane → conveyor → **GTP** (goods-to-person) stations.

Crucially, **lifts and buffers sense only presence, not identity.** Identity is
carried by the barcodes scanned along the path. A lift's identifier looks like
`aisle_04_inbound_lift_02`, and its status surfaces as a numeric `lift_status`
plus a textual description (e.g. `ERROR`).

Lifts are **rotating, load-bearing** assets cycling continuously under load — the
classic profile of a component that degrades measurably before it fails. That is
why Lift is an early PdM module: error frequency, fault recurrence, cycle-time
drift, idle behaviour, and load all leave fingerprints in Grafana well before a
hard failure.

## 1.5 Tote types

Totes come in **TS (short)** and **TL (tall)** variants with the same footprint.
They carry **2 / 4 / 8 partitions**, one **PID** per partition. All four faces and
every partition are barcoded.

## 1.6 Inbound, put-away, and retrieval

Decant at IQC → WES assigns an address → conveyor → lift → buffer → shuttle →
store. Retrieval reverses to the GTP for **picking, compaction, and cycle count**.
Any unresolved discrepancy **blocks a tote** until it is verified.

## 1.7 Control and connectivity

The **WES is the brain**. Almost everything is wired (LAN / EtherCAT); **only the
moving shuttle uses Wi-Fi**. Every handoff is acknowledged, and the whole
sensor/ack system is visualised in Grafana. Because communications quality
(latency, packet loss) can precede mechanical symptoms, the Network/Comms module
(built later) doubles as a cross-feature for the rotating-asset modules including
Lift.

## 1.8 Why this matters for PdM

The PdM system has **no maintenance logbook**. It cannot be told "this lift was
serviced on date X." Instead it infers health purely from operational and error
data — per physical unit, on a short data window, accumulating its own
longitudinal history over time. Chapter `methodology.md` explains how. Each module
chapter (starting with Lift) then documents the exact panels, fields, features,
and formulas for one equipment type.
