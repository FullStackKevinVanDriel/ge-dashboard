# ge-dashboard

GE SmartHQ appliance monitoring dashboard - real-time washer/dryer status via Flask and SSE.

## Key Commands

```bash
# Install dependencies
pip install flask gehomesdk

# Run the dashboard
python app.py
```

## Important Files

- `app.py` - Main Flask application with SmartHQ integration
- `templates/dashboard.html` - Dashboard UI
- `static/style.css` - Dark theme styling

## Configuration

Edit credentials in `app.py`:
```python
SMARTHQ_EMAIL = "your_email@example.com"
SMARTHQ_PASSWORD = "your_password"
SMARTHQ_REGION = "US"
```

## Constraints

- Requires Python 3.9+
- Requires GE SmartHQ account with connected appliances
- Credentials currently stored in source (use env vars for production)
- Dashboard accessible at http://localhost:5000
