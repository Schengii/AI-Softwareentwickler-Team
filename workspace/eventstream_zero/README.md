# EventStream-Zero

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.14](https://img.shields.io/badge/python-3.14-blue.svg)](https://www.python.org/downloads/)
[![Status: Alpha](https://img.shields.io/badge/status-alpha-orange.svg)]()

EventStream-Zero is a high-performance, distributed event-streaming and stream-processing platform built for financial and IoT telemetry data. It combines the reliability of append-only WAL storage with the flexibility of real-time stream processing.

## 🚀 Key Features

*   **Core Storage:** Append-only Write-Ahead-Log (WAL) using `mmap` for zero-copy performance.
*   **Stream Processing:** In-memory engine supporting Tumbling, Sliding, and Session windows.
*   **Consumer Groups:** Automated rebalancing, heartbeat monitoring, and persistent offset tracking.
*   **Resilience:** Built-in DLQ with exponential backoff and circuit-breaker patterns.
*   **API-First:** FastAPI-based REST and WebSocket interfaces for management and real-time monitoring.

## 🛠️ Prerequisites

*   Python 3.14+
*   `pip`

## 📦 Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/your-org/eventstream-zero.git
   cd eventstream-zero
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## 🏃 Usage

Start the EventStream-Zero server:

```bash
python -m app.main
```

The API will be available at `http://localhost:8000`.

## 🏗️ Architecture

EventStream-Zero follows a modular design with a focus on high throughput and low latency.

```mermaid
C4Context
    title Systemarchitektur EventStream-Zero

    Person(producer, "Producer", "Sends Telemetry/Events")
    Person(consumer, "Consumer", "Reads & Processes Events")

    System_Boundary(cluster, "EventStream-Zero Cluster") {
        Container(api_gateway, "API Gateway", "FastAPI / WebSockets", "REST/WS Interface")
        Container(raft_node, "Raft Consensus", "AsyncIO", "Leader Election & Metadata")
        Container(stream_processor, "Stream Processing", "Python", "Windowing & Aggregation")
        Container(cg_coordinator, "Consumer Group Coordinator", "Python", "Rebalancing & Offsets")
        ContainerDb(wal_storage, "WAL Storage", "mmap", "Append-Only Log")
    }
```

## 📝 Changelog

### [0.1.0] - 2025-05-15
*   Initial release of core components.
*   Implemented `mmap`-based WAL storage engine.
*   Implemented Consumer Group coordination and offset tracking.
*   Added basic FastAPI structure and static frontend.

## 📄 License

Distributed under the MIT License. See `LICENSE` for more information.
