# Extruder Edge Agent

This is the local "Edge Agent" designed to bridge factory floor Inoex Extruder machines (accessible only via local LAN) with a Cloud-based ERPNext instance. 

It uses a highly resilient **"Store and Forward"** architecture. If the factory loses internet connection to the cloud, the agent will continue polling the machines and securely buffer the data in a local SQLite database. Once the internet is restored, it will forward all backlogged data in chronological order, ensuring zero data loss.

## Features
- **OPC UA Integration**: Connects to Battenfeld-Cincinnati BCtouch UX machines via OPC UA.
- **Zero Data Loss**: Uses a local SQLite database (`buffer.db`) to cache data during network drops.
- **Dynamic Configuration**: The agent queries ERPNext every 15 minutes to ask which machines are currently active, meaning you never have to hardcode machine IP addresses.
- **Stateless Agent**: All complex business logic (session detection, 1-hour log intervals) is handled by the ERPNext backend. This agent acts purely as a "Dumb Forwarder".

## ⚠️ CRITICAL: Network Topology Requirement

For the offline buffering ("Store and Forward") to work correctly, the device running this agent **MUST be physically on the same local network switch as the Extruder machines**. 

- **Correct Setup**: A small local PC or Raspberry Pi plugged directly into the factory LAN. If the factory's outside internet connection drops, the agent can still ping the machine (`192.168.x.x`), collect data, and buffer it locally.
- **Incorrect Setup**: Installing this on a Cloud VPS (AWS, DigitalOcean) or a server that loses routing to the factory floor when the main internet goes down. If the agent cannot ping the machine during an outage, the data will be permanently lost because the machine itself does not store historical data.

## Installation

1. Clone or copy this directory to your local server (e.g., Ubuntu VPS or Raspberry Pi).
2. Initialize and activate a Python virtual environment:

```bash
python3 -m venv venv
source venv/bin/activate
```

3. Install the required Python dependencies:

```bash
pip3 install -r requirements.txt
```

## Configuration

Create or edit the `config.json` file to point to your Cloud ERPNext instance:

```json
{
  "erpnext_url": "https://your-production-site.com",
  "api_key": "YOUR_API_KEY",
  "api_secret": "YOUR_API_SECRET"
}
```

*Note: You do not need to add the extruder IP addresses here. The agent will fetch the IPs of all active `Production Machine` records directly from ERPNext.*

## Running Manually (Testing)

To test the agent and watch the terminal output:

```bash
python3 agent.py
```

## Production Deployment (Systemd Service)

For production, you should run the agent as a background service so it automatically starts when the server reboots.

1. Create a new service file:
```bash
sudo nano /etc/systemd/system/extruder-agent.service
```

2. Paste the following configuration (update `/path/to/extruder_edge_agent` and `User` to match your server setup):

```ini
[Unit]
Description=Extruder Edge Agent (Store and Forward)
After=network.target

[Service]
User=frappe
WorkingDirectory=/path/to/extruder_edge_agent
ExecStart=/path/to/extruder_edge_agent/venv/bin/python3 /path/to/extruder_edge_agent/agent.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

3. Enable and start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable extruder-agent.service
sudo systemctl start extruder-agent.service
```

4. View the live logs:
```bash
sudo journalctl -u extruder-agent.service -f
```

## Troubleshooting
- **No data pushed?** Check `agent.log` in this directory to see if the OPC UA connection to the local machine failed.
- **Machines not found?** Ensure the machines in ERPNext have the `Is Active` checkbox checked and the correct local `Machine IP` entered.
