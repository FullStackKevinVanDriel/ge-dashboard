# GE Appliances Dashboard

Real-time web dashboard for monitoring GE SmartHQ washer and dryer appliances.

![Python](https://img.shields.io/badge/python-3.9+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)

## Features

- **Real-time Updates**: Live status via Server-Sent Events (SSE)
- **Dark Theme UI**: Easy on the eyes, perfect for laundry room displays
- **Comprehensive Data**: All appliance properties, settings, and states
- **Multi-Device Access**: View from any device on your network

### Washer Monitoring
- Machine state (running, paused, idle, end of cycle)
- Current cycle and sub-cycle phase
- Time remaining
- Soil level, water temperature, rinse options
- Smart Dispense tank status and loads remaining
- Door status

### Dryer Monitoring
- Machine state and time remaining
- Temperature and dryness settings
- EcoDry status
- Extended tumble options
- Dryer sheet inventory
- Vent blockage alerts
- WasherLink connection status

## Requirements

- Python 3.9+
- GE SmartHQ account with connected appliances

## Installation

1. Clone the repository:
```bash
git clone https://github.com/FullStackKevinVanDriel/ge-dashboard.git
cd ge-dashboard
```

2. Install dependencies:
```bash
pip install flask gehomesdk
```

3. Edit `app.py` and update your SmartHQ credentials:
```python
SMARTHQ_EMAIL = "your_email@example.com"
SMARTHQ_PASSWORD = "your_password"
SMARTHQ_REGION = "US"  # or "EU"
```

## Usage

Start the dashboard:
```bash
python app.py
```

Open your browser to:
- Local: http://localhost:5000
- Network: http://YOUR_IP:5000

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  GE SmartHQ     │◄───►│  Python Backend  │◄───►│  Web Browser    │
│  (WebSocket)    │     │  (Flask + SSE)   │     │  (HTML/CSS/JS)  │
└─────────────────┘     └──────────────────┘     └─────────────────┘
```

- **Backend**: Flask with Server-Sent Events for real-time updates
- **Frontend**: Single-page HTML with vanilla JavaScript
- **Data Source**: [gehomesdk](https://pypi.org/project/gehomesdk/) WebSocket client

## Project Structure

```
ge-dashboard/
├── app.py              # Flask app + gehomesdk integration
├── templates/
│   └── dashboard.html  # Main dashboard UI
├── static/
│   └── style.css       # Dark theme styling
└── README.md
```

## Security Note

The current implementation stores credentials in `app.py`. For production use, consider:
- Using environment variables
- Implementing a secrets manager
- Adding authentication to the web interface

## License

MIT

## Acknowledgments

- [gehomesdk](https://github.com/simbaja/gehome) - Python SDK for GE SmartHQ appliances
- Built with [Flask](https://flask.palletsprojects.com/)
