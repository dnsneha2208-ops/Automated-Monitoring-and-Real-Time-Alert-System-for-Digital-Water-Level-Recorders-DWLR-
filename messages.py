from twilio.rest import Client
import keys
import app
import time
import threading

client = Client(keys.account_sid, keys.auth_token)


def send_alert(alert, alert_type):
    message = client.messages.create(
        body=alert,  # Directly use the alert string
        from_=keys.twilio_number,  # Twilio phone number
        to=keys.target_number  # Recipient phone number
    )



def monitor_alerts():
    sent_alerts = set()
    while True:
        # Fetch data and alerts
        df, water_level_alerts, battery_level_alerts = app.fetch_paginated_data_and_alerts(100, 0)

        # Check and send water level alerts
        for alert in water_level_alerts:
            if alert not in sent_alerts:
                send_alert(alert, "Water Level")
                sent_alerts.add(alert)

        # Check and send battery level alerts
        for alert in battery_level_alerts:
            if alert not in sent_alerts:
                send_alert(alert, "Battery Level")
                sent_alerts.add(alert)

        # Sleep for a certain period before checking again
        time.sleep(60)  # Adjust the sleep time as needed


# Run the alert monitoring in a separate thread
alert_thread = threading.Thread(target=monitor_alerts)
alert_thread.start()